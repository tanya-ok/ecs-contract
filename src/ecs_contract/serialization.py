"""Cooperative serialization across application and infrastructure deployment writers.

Locks deliberately have no TTL: ECS does not accept a fencing token, so expiring
an abandoned lock could let a still-running writer race its replacement.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from mypy_boto3_ecs import ECSClient

SERVICE_ARN = re.compile(
    r"^arn:"
    r"aws[a-z-]*:ecs:(?P<region>[a-z0-9-]+):\d{12}:service/"
    r"(?P<cluster>[A-Za-z0-9_-]+)/(?P<service>[A-Za-z0-9_-]+)$"
)
TASK_ARN = re.compile(r"^arn:" r"aws[a-z-]*:ecs:[a-z0-9-]+:\d{12}:task-definition/[^:]+:\d+$")


class SerializationError(Exception):
    """A fixed public diagnostic; deployment must not continue."""


class DeploymentMutex:
    """A non-expiring, owner-bound mutex in one regional DynamoDB table.

    The table must have exactly one string partition key named `pk`, no sort key
    and TTL disabled. All writers must use this same table and canonical service
    ARN. Provisioning and abandoned-lock recovery are operator responsibilities.
    """

    def __init__(self, table: Any, service_arn: str) -> None:
        if not SERVICE_ARN.fullmatch(service_arn):
            raise SerializationError("a complete long-form ECS service ARN is required")
        self.table = table
        self.service_arn = service_arn
        self.owner = uuid4().hex

    def acquire(self) -> None:
        from boto3.dynamodb.conditions import Attr  # noqa: PLC0415

        try:
            self.table.put_item(
                Item={"pk": self.service_arn, "owner": self.owner},
                ConditionExpression=Attr("pk").not_exists(),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            raise SerializationError("deployment lock busy; no command was started") from None
        except Exception:
            raise SerializationError(
                "deployment lock acquisition failed; no command was started"
            ) from None

    def release(self) -> None:
        from boto3.dynamodb.conditions import Attr  # noqa: PLC0415

        try:
            self.table.delete_item(
                Key={"pk": self.service_arn},
                ConditionExpression=Attr("owner").eq(self.owner),
            )
        except Exception:
            raise SerializationError(
                "deployment lock release failed; operator recovery required"
            ) from None


def run_serialized(  # noqa: PLR0913 - injectable deployment boundaries
    mutex: DeploymentMutex,
    command: Sequence[str],
    *,
    revision: Callable[[], str | None],
    settle: Callable[[], None],
    expected: str | None = None,
    execute: Callable[[Sequence[str]], int] | None = None,
) -> int:
    """Lock before reading live state; keep the lock through the completed deployment.

    If `expected` is supplied, it must be the exact revision in the saved plan.
    The executable must stay in the foreground and wait for all asynchronous
    writers (including CloudFormation/CodeDeploy) before returning success.
    """
    if not command:
        raise SerializationError("a deployment command is required")
    if expected is not None and not TASK_ARN.fullmatch(expected):
        raise SerializationError("expected revision must be a complete task definition ARN")
    mutex.acquire()
    try:
        current = revision()
        if expected is not None and current != expected:
            raise SerializationError("stale deployment plan refused; regenerate under the lock")
    except Exception:
        # No deployment command has run, so this owner can release safely.
        mutex.release()
        raise
    try:
        result = (execute or _execute)(command)
    except Exception:
        raise SerializationError(
            "deployment execution failed; lock retained for operator recovery"
        ) from None
    if result != 0:
        raise SerializationError("deployment command failed; lock retained for operator recovery")
    try:
        settle()
    except Exception:
        # A failed wait may leave an asynchronous AWS writer running.
        raise SerializationError(
            "deployment completion unknown; lock retained for operator recovery"
        ) from None
    mutex.release()
    return 0


def _execute(command: Sequence[str]) -> int:
    return subprocess.run(command, check=False).returncode  # noqa: S603 - explicit operator command, no shell


def serialized_from_aws(
    table_name: str,
    service_arn: str,
    command: Sequence[str],
    *,
    region: str | None = None,
    expected: str | None = None,
) -> int:
    import boto3  # noqa: PLC0415

    match = SERVICE_ARN.fullmatch(service_arn)
    if match is None or (region is not None and region != match["region"]):
        raise SerializationError("service ARN and region must identify one canonical target")
    session = boto3.session.Session(region_name=match["region"])
    table = session.resource("dynamodb").Table(table_name)
    ecs: ECSClient = session.client("ecs")
    cluster, service = match["cluster"], match["service"]

    def revision() -> str | None:
        response = ecs.describe_services(cluster=cluster, services=[service])
        services = response.get("services", [])
        if response.get("failures") or len(services) != 1:
            raise SerializationError("live deployment target cannot be established")
        live = services[0]
        if live.get("serviceArn") != service_arn or live.get("status") != "ACTIVE":
            raise SerializationError("live deployment target does not match the lock")
        return live.get("taskDefinition")

    def settle() -> None:
        ecs.get_waiter("services_stable").wait(cluster=cluster, services=[service])

    return run_serialized(
        DeploymentMutex(table, service_arn),
        command,
        revision=revision,
        settle=settle,
        expected=expected,
    )
