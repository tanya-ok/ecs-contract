from __future__ import annotations

import json
import re
import sys
from typing import Any

import pytest

from ecs_contract.cli import main
from tests.aws_world import CONFIG_SECRET, POINTER, World

IDENTIFIERS = re.compile("arn" + r":aws|\b\d{12}\b")


def render(world: World, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, str]:
    code = main(world.args("render", *world.service_args(*extra)))
    return code, capsys.readouterr().out


def written(world: World, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    out = world.root / "task-definition.json"
    code, text = render(
        world,
        capsys,
        "--container",
        "app",
        "--config-secret",
        CONFIG_SECRET,
        "--out",
        str(out),
        *extra,
    )
    assert code == 0, text
    return dict(json.loads(out.read_text()))


def container(task: dict[str, Any], name: str = "app") -> dict[str, Any]:
    return next(c for c in task["containerDefinitions"] if c["name"] == name)


def test_render_replaces_three_fields_and_nothing_else(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    task = written(world, capsys)
    app = container(task)
    assert app["environment"] == [
        {"name": "LOG_LEVEL", "value": "info"},
        {"name": "PORT", "value": "8080"},
    ]
    assert app["secrets"] == [
        {"name": "DB_PASSWORD", "valueFrom": f"{world.db_secret_arn}:password::"},
        {
            "name": "SETTLEMENT_API_TOKEN",
            "valueFrom": f"{world.config_secret_arn}:SETTLEMENT_API_TOKEN::",
        },
        {"name": "TLS_CA_BUNDLE", "valueFrom": world.ca_parameter_arn},
    ]
    assert app["image"] == "registry.example/orderbook:1.0.0"
    assert app["portMappings"][0]["containerPort"] == 8080
    assert container(task, "log-router")["environment"] == [{"name": "OUTPUT", "value": "stdout"}]
    assert task["cpu"] == "256"
    assert task["tags"] == [{"key": "team", "value": "exchange"}]
    for field in ("taskDefinitionArn", "revision", "status", "registeredAt", "compatibilities"):
        assert field not in task


def test_rendered_file_registers(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    task = written(world, capsys)
    world.deploy(task)
    assert world.live_container()["environment"][0] == {"name": "LOG_LEVEL", "value": "info"}


def test_image_tag(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    task = written(world, capsys, "--image-tag", "1.1.0")
    assert container(task)["image"] == "registry.example/orderbook:1.1.0"


def test_full_image(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    task = written(world, capsys, "--image", "registry.example/orderbook@sha256:abc")
    assert container(task)["image"] == "registry.example/orderbook@sha256:abc"


def test_output_names_changes_and_never_identifiers(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = render(
        world, capsys, "--container", "app", "--config-secret", CONFIG_SECRET, "--dry-run"
    )
    assert code == 0
    assert "live revision: orderbook:1" in out
    assert "change: environment: LEGACY_FLAG: only in the live revision" in out
    assert "change: environment: LOG_LEVEL: value differs" in out
    assert "change: secrets: DB_PASSWORD: only in the contract" in out
    assert not IDENTIFIERS.search(out), out
    assert "synthetic" not in out
    assert not (world.root / "task-definition.json").exists()


def test_github_outputs(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = world.root / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    written(world, capsys)
    lines = dict(line.split("=", 1) for line in outputs.read_text().splitlines())
    assert lines["live-task-definition"] == world.task_definition_arn
    assert lines["task-definition"].endswith("task-definition.json")


def test_pointer_missing(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.ssm.delete_parameter(Name=POINTER)
    code, out = render(
        world, capsys, "--container", "app", "--config-secret", CONFIG_SECRET, "--dry-run"
    )
    assert code == 1
    assert f"DB_PASSWORD: pointer parameter {POINTER} does not exist" in out


def test_pointer_not_an_arn(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.ssm.put_parameter(Name=POINTER, Value="orderbook/development/db", Overwrite=True)
    code, out = render(
        world, capsys, "--container", "app", "--config-secret", CONFIG_SECRET, "--dry-run"
    )
    assert code == 1
    assert "does not hold a complete Secrets Manager ARN" in out


def test_pointer_json_key_missing(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    secrets = json.loads(world.secrets.read_text())
    secrets["environments"]["development"]["secrets"]["DB_PASSWORD"]["jsonKey"] = "passphrase"
    world.secrets.write_text(json.dumps(secrets))
    code, out = render(
        world, capsys, "--container", "app", "--config-secret", CONFIG_SECRET, "--dry-run"
    )
    assert code == 1
    assert "DB_PASSWORD: the secret behind this pointer has no key passphrase" in out


def test_parameter_missing(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.write_contract(secrets={"TLS_CA_BUNDLE": {"parameter": "/shared/missing"}})
    code, out = render(world, capsys, "--container", "app", "--dry-run")
    assert code == 1
    assert "TLS_CA_BUNDLE: parameter /shared/missing does not exist" in out


def test_vault_needs_config_secret(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = render(world, capsys, "--container", "app", "--dry-run")
    assert code == 1
    assert "SETTLEMENT_API_TOKEN: vault source needs --config-secret" in out


def test_config_secret_missing(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = render(world, capsys, "--container", "app", "--config-secret", "nope", "--dry-run")
    assert code == 1
    assert "cannot be found" in out


def test_several_containers_need_a_name(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = render(world, capsys, "--config-secret", CONFIG_SECRET, "--dry-run")
    assert code == 1
    assert "2 containers (app, log-router); name one with --container" in out


def test_unknown_container_lists_names(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = render(
        world,
        capsys,
        "--container",
        "app-development",
        "--config-secret",
        CONFIG_SECRET,
        "--dry-run",
    )
    assert code == 1
    assert "no container named app-development; the task definition has app, log-router" in out


def test_unknown_service(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    args = world.args(
        "render",
        "--cluster",
        "orderbook",
        "--service",
        "ghost",
        "--region",
        "eu-west-1",
        "--dry-run",
        "--config-secret",
        CONFIG_SECRET,
    )
    assert main(args) == 1
    assert "service ghost not found" in capsys.readouterr().out


def test_broken_contract_refused_before_aws(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.write_contract(secrets={"DB_PASSWORD": {}})
    code, out = render(world, capsys, "--container", "app", "--dry-run")
    assert code == 1
    assert "names no source" in out


def test_environment_files_warning(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    task = written(world, capsys)
    container(task)["environmentFiles"] = [
        {"type": "s3", "value": "arn" + ":aws:s3:::bucket/orderbook.env"}
    ]
    world.deploy(task)
    code, out = render(
        world, capsys, "--container", "app", "--config-secret", CONFIG_SECRET, "--dry-run"
    )
    assert code == 0
    assert "the container also reads environmentFiles" in out


def test_without_boto3(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "boto3", None)
    code = main(world.args("render", *world.service_args("--dry-run")))
    assert code == 2
    assert "install ecs-contract[aws]" in capsys.readouterr().err
