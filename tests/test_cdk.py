from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION", "1")

from aws_cdk import App, Aws, Stack
from aws_cdk.assertions import Template
from botocore.exceptions import ClientError

from ecs_contract.cdk import (
    LiveRevisionError,
    ServiceFromLiveRevision,
    describe_live_revision,
)
from tests.aws_world import CLUSTER, SERVICE, World
from tests.conftest import ACCOUNT_ID, ARN_PREFIX

INITIAL = f"{ARN_PREFIX}ecs:eu-west-1:{ACCOUNT_ID}:task-definition/orderbook:1"


def synth(**props: Any) -> tuple[ServiceFromLiveRevision, Template]:
    stack = Stack(App(), "Infra")
    construct = ServiceFromLiveRevision(stack, "Orderbook", **props)
    return construct, Template.from_stack(stack)


def test_service_points_at_the_live_revision(world: World) -> None:
    world.deploy(
        {
            "family": "orderbook",
            "containerDefinitions": [
                {"name": "app", "image": "registry.example/orderbook:2", "memory": 512}
            ],
        }
    )
    live = world.ecs.describe_services(cluster=CLUSTER, services=[SERVICE])["services"][0]
    construct, template = synth(
        cluster=CLUSTER,
        service_name=SERVICE,
        lookup=lambda c, s: describe_live_revision(c, s, client=world.ecs),
        launch_type="FARGATE",
    )
    assert construct.task_definition_arn == live["taskDefinition"]
    assert construct.revision == "orderbook:2"
    assert not construct.created_from_initial
    template.resource_count_is("AWS::ECS::TaskDefinition", 0)
    services = template.find_resources("AWS::ECS::Service")
    (properties,) = [r["Properties"] for r in services.values()]
    assert properties["TaskDefinition"] == live["taskDefinition"]
    assert properties["LaunchType"] == "FARGATE"
    assert "DesiredCount" not in properties


def test_initial_task_definition_only_for_first_creation(world: World) -> None:
    def lookup(cluster: str, service: str) -> str | None:
        return describe_live_revision(cluster, service, client=world.ecs)

    construct, template = synth(
        cluster=CLUSTER, service_name="absent", initial_task_definition=INITIAL, lookup=lookup
    )
    assert construct.created_from_initial
    template.has_resource_properties("AWS::ECS::Service", {"TaskDefinition": INITIAL})
    construct, _ = synth(
        cluster=CLUSTER, service_name=SERVICE, initial_task_definition=INITIAL, lookup=lookup
    )
    assert construct.task_definition_arn == world.task_definition_arn


def test_missing_cluster_counts_as_missing_service(world: World) -> None:
    assert describe_live_revision("nowhere", SERVICE, client=world.ecs) is None


def test_missing_service_without_initial_fails_synthesis() -> None:
    with pytest.raises(LiveRevisionError, match="initial_task_definition"):
        synth(cluster=CLUSTER, service_name=SERVICE, lookup=lambda c, s: None)


class _Denied:
    def describe_services(self, **_: Any) -> dict[str, Any]:
        error: Any = {"Error": {"Code": "AccessDeniedException", "Message": INITIAL}}
        raise ClientError(error, "DescribeServices")


def test_lookup_failure_fails_synthesis_without_the_aws_message() -> None:
    client: Any = _Denied()
    with pytest.raises(LiveRevisionError) as caught:
        describe_live_revision(CLUSTER, SERVICE, client=client)
    assert str(caught.value) == "AWS DescribeServices failed: AccessDeniedException"
    assert caught.value.__cause__ is None


def test_no_credentials_fails_synthesis(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", os.devnull)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", os.devnull)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    with pytest.raises(LiveRevisionError, match="DescribeServices failed"):
        synth(cluster=CLUSTER, service_name=SERVICE, region="eu-west-1")


@pytest.mark.parametrize("found", ["orderbook:3", "", INITIAL.rsplit(":", 1)[0]])
def test_placeholder_or_partial_arn_is_refused(found: str) -> None:
    with pytest.raises(LiveRevisionError, match="not a complete"):
        synth(cluster=CLUSTER, service_name=SERVICE, lookup=lambda c, s: found)


@pytest.mark.parametrize("prop", ["task_definition", "desired_count"])
def test_owned_props_are_refused(prop: str) -> None:
    with pytest.raises(LiveRevisionError, match=prop):
        synth(cluster=CLUSTER, service_name=SERVICE, lookup=lambda c, s: INITIAL, **{prop: "1"})


def test_token_names_are_refused() -> None:
    stack = Stack(App(), "Infra")
    with pytest.raises(LiveRevisionError, match="literal"):
        ServiceFromLiveRevision(
            stack,
            "Orderbook",
            cluster=Aws.STACK_NAME,
            service_name=SERVICE,
            lookup=lambda c, s: INITIAL,
        )
