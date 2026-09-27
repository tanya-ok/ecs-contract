from __future__ import annotations

import json
from typing import Any

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

import ecs_contract.aws
from ecs_contract.cli import main
from tests.aws_world import CLUSTER, CONFIG_SECRET, REGION, SERVICE, World
from tests.conftest import ACCOUNT_ID, ARN_PREFIX


def rendered(world: World, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    out = world.root / "task-definition.json"
    args = world.args(
        "render",
        *world.service_args(
            "--container", "app", "--config-secret", CONFIG_SECRET, "--out", str(out)
        ),
    )
    assert main(args) == 0
    capsys.readouterr()
    return dict(json.loads(out.read_text()))


def drift(world: World, *extra: str) -> int:
    return main(
        world.args(
            "drift",
            *world.service_args("--container", "app", "--config-secret", CONFIG_SECRET, *extra),
        )
    )


def test_drift_before_and_after_deploy(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    assert drift(world) == 1
    out = capsys.readouterr().out
    assert "drift: environment: LEGACY_FLAG: only in the live revision" in out
    assert "drift: environment: PORT: only in the contract" in out
    assert "ecsc: 6 differences" in out

    world.deploy(rendered(world, capsys))
    assert drift(world) == 0
    assert capsys.readouterr().out.strip().endswith("drift: none")


def test_drift_sees_a_hand_edit(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    task = rendered(world, capsys)
    world.deploy(task)
    app = next(c for c in task["containerDefinitions"] if c["name"] == "app")
    app["environment"] = [
        {"name": "LOG_LEVEL", "value": "debug"},
        {"name": "PORT", "value": "8080"},
    ]
    world.deploy(task)
    assert drift(world) == 1
    out = capsys.readouterr().out
    assert "drift: environment: LOG_LEVEL: value differs" in out
    assert "debug" not in out


def test_drift_image(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.deploy(rendered(world, capsys))
    assert drift(world, "--image-tag", "2.0.0") == 1
    assert "drift: image: -: image differs" in capsys.readouterr().out


def guard(path: str, *extra: str) -> int:
    return main(["guard", "--task-definition", path, "--container", "app", *extra])


def test_guard_passes_and_refuses_secret_shaped(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    task = rendered(world, capsys)
    path = world.root / "task-definition.json"
    assert guard(str(path)) == 0
    app = next(c for c in task["containerDefinitions"] if c["name"] == "app")
    app["environment"].append({"name": "SIGNING_SECRET", "value": "x"})
    path.write_text(json.dumps(task))
    capsys.readouterr()
    assert guard(str(path)) == 1
    assert "SIGNING_SECRET: looks like a secret but sits in environment" in capsys.readouterr().out
    assert guard(str(path), "--allow-secret-shaped", "SIGNING_SECRET") == 0


def test_guard_live_revision_moved(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    task = rendered(world, capsys)
    path = str(world.root / "task-definition.json")
    service = ["--cluster", CLUSTER, "--service", SERVICE, "--region", REGION]
    assert guard(path, "--expect-task-definition", world.task_definition_arn, *service) == 0
    world.deploy(task)
    capsys.readouterr()
    assert guard(path, "--expect-task-definition", world.task_definition_arn, *service) == 1
    out = capsys.readouterr().out
    assert "the service moved from orderbook:1 to orderbook:2 since render" in out


def test_guard_expect_needs_service(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    rendered(world, capsys)
    path = str(world.root / "task-definition.json")
    assert guard(path, "--expect-task-definition", world.task_definition_arn) == 2


def test_guard_unreadable(tmp_path: Any) -> None:
    assert guard(str(tmp_path / "missing.json")) == 2


def _refusing(monkeypatch: pytest.MonkeyPatch, client: str, method: str, error: Exception) -> None:
    real = ecs_contract.aws.clients

    def patched(region: str | None) -> Any:
        aws = real(region)

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise error

        monkeypatch.setattr(getattr(aws, client), method, refuse)
        return aws

    monkeypatch.setattr(ecs_contract.aws, "clients", patched)


@pytest.mark.parametrize("command", ["render", "drift"])
def test_aws_error_is_one_line_without_identifiers(
    world: World,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    message = f"User: {ARN_PREFIX}iam::{ACCOUNT_ID}:user/ci is not authorized"
    denied = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": message}}, "DescribeSecret"
    )
    _refusing(monkeypatch, "secretsmanager", "describe_secret", denied)
    extra = ["--dry-run"] if command == "render" else []
    args = world.args(
        command,
        *world.service_args("--container", "app", "--config-secret", CONFIG_SECRET, *extra),
    )
    assert main(args) == 2
    captured = capsys.readouterr()
    assert captured.err == "ecsc: AWS DescribeSecret failed: AccessDeniedException\n"
    assert ACCOUNT_ID not in captured.out + captured.err


def test_botocore_error_without_operation(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _refusing(monkeypatch, "ecs", "describe_services", NoCredentialsError())
    assert drift(world) == 2
    assert capsys.readouterr().err == "ecsc: AWS call failed: NoCredentialsError\n"


def test_other_errors_still_raise(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    _refusing(monkeypatch, "ecs", "describe_services", RuntimeError("bug"))
    with pytest.raises(RuntimeError):
        drift(world)
