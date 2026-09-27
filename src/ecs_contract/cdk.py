"""The infrastructure side: point an ECS service at the revision it runs now.

`pip install ecs-contract[cdk]`. The lookup runs at synthesis and is never cached, because a
cached revision is an old revision, and deploying it reverts the application.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from aws_cdk import Token
from aws_cdk import aws_ecs as ecs
from constructs import Construct

from ecs_contract.aws import error_code

if TYPE_CHECKING:
    from mypy_boto3_ecs import ECSClient

Lookup = Callable[[str, str], "str | None"]
"""`(cluster, service)` to the live task definition ARN, or None when the service does not exist."""

TASK_DEFINITION_ARN = re.compile(
    r"^arn:aws[a-z-]*:ecs:[a-z0-9-]+:\d{12}:task-definition/[^:]+:\d+$"
)
REFUSED_PROPS = {"task_definition", "desired_count", "cluster", "service_name"}


class LiveRevisionError(Exception):
    """The live revision cannot be established. Synthesis must stop, never guess."""


def describe_live_revision(
    cluster: str, service: str, *, region: str | None = None, client: ECSClient | None = None
) -> str | None:
    """The task definition ARN the service runs now, read with DescribeServices.

    None only when the service does not exist, or its cluster does not. Every other failure
    raises: missing credentials, access denied, throttling. The AWS message is dropped, since it
    can carry account ids.
    """
    if client is None:
        try:
            import boto3  # noqa: PLC0415
        except ImportError as error:
            raise LiveRevisionError("the lookup reads AWS; install ecs-contract[cdk]") from error
        client = boto3.session.Session(region_name=region).client("ecs")
    try:
        described = client.describe_services(cluster=cluster, services=[service])
    except Exception as error:
        code = error_code(error) or type(error).__name__
        if code == "ClusterNotFoundException":
            return None
        raise LiveRevisionError(f"AWS DescribeServices failed: {code}") from None
    failures = [f for f in described.get("failures", []) if f.get("reason") != "MISSING"]
    if failures:
        reason = failures[0].get("reason", "unknown")
        raise LiveRevisionError(f"AWS DescribeServices failed for {service}: {reason}")
    active = [s for s in described.get("services", []) if s.get("status") != "INACTIVE"]
    if not active:
        return None
    arn = active[0].get("taskDefinition")
    if not arn:
        raise LiveRevisionError(f"service {service} in cluster {cluster} has no task definition")
    return str(arn)


class ServiceFromLiveRevision(Construct):
    """An `AWS::ECS::Service` set to the revision it runs now, with no task definition resource.

    The template carries the live ARN as a literal, so an infrastructure deploy leaves the
    application's content alone. The desired count is never set, so autoscaling keeps control.

    `initial_task_definition` is used only when the service does not exist yet, for its first
    creation. Once the service exists it is ignored.
    """

    def __init__(  # noqa: PLR0913
        self,
        scope: Construct,
        construct_id: str,
        *,
        cluster: str,
        service_name: str,
        initial_task_definition: str | None = None,
        lookup: Lookup | None = None,
        region: str | None = None,
        **service_props: Any,
    ) -> None:
        super().__init__(scope, construct_id)
        for name, value in (("cluster", cluster), ("service_name", service_name)):
            if Token.is_unresolved(value):
                raise LiveRevisionError(
                    f"{name} must be a literal name; the lookup runs at synthesis, before any"
                    " token resolves"
                )
        refused = sorted(REFUSED_PROPS & service_props.keys())
        if refused:
            raise LiveRevisionError(
                f"{', '.join(refused)}: set by ServiceFromLiveRevision, not by the caller"
            )
        find = lookup or (lambda c, s: describe_live_revision(c, s, region=region))
        found = find(cluster, service_name)
        if found is None:
            if initial_task_definition is None:
                raise LiveRevisionError(
                    f"service {service_name} not found in cluster {cluster}; pass"
                    " initial_task_definition for its first creation"
                )
            found = initial_task_definition
            self.created_from_initial = True
        else:
            self.created_from_initial = False
        if not TASK_DEFINITION_ARN.match(found):
            raise LiveRevisionError(
                f"service {service_name}: the task definition is not a complete, revisioned"
                " task definition ARN"
            )
        self.task_definition_arn: str = found
        self.revision: str = found.rsplit("/", 1)[-1]
        self.service = ecs.CfnService(
            self,
            "Service",
            cluster=cluster,
            service_name=service_name,
            task_definition=found,
            **service_props,
        )
        self.node.add_metadata("ecs-contract:live-revision", self.revision)
