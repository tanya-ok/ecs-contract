from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from ecs_contract import serialization
from ecs_contract.cli import main
from ecs_contract.serialization import (
    DeploymentMutex,
    SerializationError,
    run_serialized,
)
from tests.aws_world import REGION
from tests.conftest import ACCOUNT_ID, ARN_PREFIX

SERVICE_ARN = f"{ARN_PREFIX}ecs:{REGION}:{ACCOUNT_ID}:service/orderbook/orderbook"
REVISION = f"{ARN_PREFIX}ecs:{REGION}:{ACCOUNT_ID}:task-definition/orderbook:1"


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name=REGION)
        table = resource.create_table(
            TableName="deployment-locks",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield table


def item(table: Any) -> dict[str, Any] | None:
    return table.get_item(Key={"pk": SERVICE_ARN}, ConsistentRead=True).get("Item")  # type: ignore[no-any-return]


def test_shared_mutex_refuses_competing_writer_and_releases_only_its_owner(table: Any) -> None:
    app, infra = DeploymentMutex(table, SERVICE_ARN), DeploymentMutex(table, SERVICE_ARN)
    app.acquire()
    assert set(item(table) or {}) == {"pk", "owner"}  # No TTL or expiry takeover.
    with pytest.raises(SerializationError, match="busy"):
        infra.acquire()
    with pytest.raises(SerializationError, match="release failed"):
        infra.release()
    assert item(table)["owner"] == app.owner  # type: ignore[index]
    app.release()
    infra.acquire()
    infra.release()
    assert item(table) is None


def test_stale_saved_infrastructure_plan_never_executes(table: Any) -> None:
    calls: list[Sequence[str]] = []

    def execute(command: Sequence[str]) -> int:
        calls.append(command)
        return 0

    mutex = DeploymentMutex(table, SERVICE_ARN)
    with pytest.raises(SerializationError, match="stale"):
        run_serialized(
            mutex,
            ["synthetic"],
            revision=lambda: REVISION[:-1] + "2",
            settle=lambda: None,
            expected=REVISION,
            execute=execute,
        )
    assert calls == []
    assert item(table) is None


def test_lock_covers_lookup_command_and_stability_wait(table: Any) -> None:
    mutex = DeploymentMutex(table, SERVICE_ARN)
    competitor = DeploymentMutex(table, SERVICE_ARN)
    order = []

    def assert_locked(stage: str) -> None:
        with pytest.raises(SerializationError, match="busy"):
            competitor.acquire()
        order.append(stage)

    def revision() -> str:
        assert_locked("read")
        return REVISION

    def execute(command: Sequence[str]) -> int:
        assert command == ["synthetic", "literal argument"]
        assert_locked("deploy")
        return 0

    assert (
        run_serialized(
            mutex,
            ["synthetic", "literal argument"],
            revision=revision,
            settle=lambda: assert_locked("stable"),
            expected=REVISION,
            execute=execute,
        )
        == 0
    )
    assert order == ["read", "deploy", "stable"]
    assert item(table) is None


@pytest.mark.parametrize("stage", ["command", "wait", "interrupt"])
def test_unknown_completion_keeps_lock_without_time_based_takeover(table: Any, stage: str) -> None:
    mutex = DeploymentMutex(table, SERVICE_ARN)

    def execute(_command: Sequence[str]) -> int:
        if stage == "interrupt":
            raise KeyboardInterrupt
        return 1 if stage == "command" else 0

    def settle() -> None:
        raise RuntimeError("synthetic-private-diagnostic")

    with pytest.raises(KeyboardInterrupt if stage == "interrupt" else SerializationError) as caught:
        run_serialized(
            mutex, ["synthetic"], revision=lambda: REVISION, settle=settle, execute=execute
        )
    if stage != "interrupt":
        label = "command failed" if stage == "command" else "completion unknown"
        assert label in str(caught.value)
        assert "synthetic-private-diagnostic" not in str(caught.value)
    with pytest.raises(SerializationError, match="busy"):
        DeploymentMutex(table, SERVICE_ARN).acquire()
    assert item(table)["owner"] == mutex.owner  # type: ignore[index]


def test_preflight_failure_releases_without_executing(table: Any) -> None:
    def fail() -> str:
        raise RuntimeError("synthetic-read-failure")

    with pytest.raises(RuntimeError, match="read-failure"):
        run_serialized(
            DeploymentMutex(table, SERVICE_ARN), ["synthetic"], revision=fail, settle=lambda: None
        )
    assert item(table) is None


def test_acquire_error_is_fixed_and_does_not_start_command(
    table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(**_kwargs: Any) -> None:
        raise ClientError(
            {"Error": {"Code": "InternalServerError", "Message": REVISION}}, "PutItem"
        )

    monkeypatch.setattr(table, "put_item", fail)
    with pytest.raises(SerializationError) as caught:
        DeploymentMutex(table, SERVICE_ARN).acquire()
    assert str(caught.value) == "deployment lock acquisition failed; no command was started"
    assert REVISION not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("service", ["orderbook", SERVICE_ARN.rsplit("/", 2)[0] + "/orderbook"])
def test_aliases_and_old_service_arn_format_are_refused(table: Any, service: str) -> None:
    with pytest.raises(SerializationError, match="complete long-form"):
        DeploymentMutex(table, service)


def test_cli_passes_literal_command_and_refuses_a_busy_lock(
    table: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen = []

    def fake(table_name: str, service: str, command: Sequence[str], **kwargs: Any) -> int:
        seen.append((table_name, service, command, kwargs))
        raise SerializationError("deployment lock busy; no command was started")

    monkeypatch.setattr(serialization, "serialized_from_aws", fake)
    assert (
        main(
            [
                "serialize",
                "--lock-table",
                "deployment-locks",
                "--service-arn",
                SERVICE_ARN,
                "--expect-task-definition",
                REVISION,
                "--region",
                REGION,
                "--",
                "deploy-script",
                "literal;argument",
            ]
        )
        == 1
    )
    assert seen == [
        (
            "deployment-locks",
            SERVICE_ARN,
            ["deploy-script", "literal;argument"],
            {"region": REGION, "expected": REVISION},
        )
    ]
    output = capsys.readouterr()
    assert SERVICE_ARN not in output.out + output.err
    assert REVISION not in output.out + output.err


@pytest.mark.parametrize("state", ["ok", "wrong-target", "missing", "not-active", "wait-failed"])
def test_aws_adapter_uses_one_canonical_target_and_retains_uncertain_completion(
    table: Any,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    from types import SimpleNamespace  # noqa: PLC0415

    calls: list[str] = []

    class Ecs:
        def describe_services(self, *, cluster: str, services: list[str]) -> dict[str, Any]:
            assert (cluster, services) == ("orderbook", ["orderbook"])
            live = {
                "serviceArn": SERVICE_ARN if state != "wrong-target" else "different",
                "taskDefinition": REVISION,
                "status": "ACTIVE" if state != "not-active" else "INACTIVE",
            }
            return {"services": [] if state == "missing" else [live]}

        def get_waiter(self, name: str) -> Any:
            assert name == "services_stable"

            def wait(**_kwargs: Any) -> None:
                calls.append("wait")
                if state == "wait-failed":
                    raise RuntimeError("synthetic uncertainty")

            return SimpleNamespace(wait=wait)

    session = SimpleNamespace(
        client=lambda name: Ecs(),
        resource=lambda name: SimpleNamespace(Table=lambda name: table),
    )

    def create_session(*, region_name: str) -> Any:
        assert region_name == REGION
        return session

    monkeypatch.setattr(boto3.session, "Session", create_session)

    def execute(_command: Sequence[str]) -> int:
        calls.append("command")
        return 0

    monkeypatch.setattr(serialization, "_execute", execute)
    if state == "ok":
        assert (
            serialization.serialized_from_aws(
                "deployment-locks", SERVICE_ARN, ["synthetic"], expected=REVISION
            )
            == 0
        )
        assert calls == ["command", "wait"]
        assert item(table) is None
    else:
        with pytest.raises(SerializationError):
            serialization.serialized_from_aws(
                "deployment-locks", SERVICE_ARN, ["synthetic"], expected=REVISION
            )
        assert calls == (["command", "wait"] if state == "wait-failed" else [])
        assert (item(table) is not None) == (state == "wait-failed")
