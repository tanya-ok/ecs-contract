from __future__ import annotations

import re

import pytest

from ecs_contract.cli import main
from ecs_contract.migrate import classify
from tests.aws_world import CLUSTER, SERVICE, World
from tests.conftest import ACCOUNT_ID, ARN_PREFIX

SUFFIX = "Ab" + "CdEf"
IDENTIFIERS = re.compile("arn" + r":aws|\b\d{12}\b")


def migrate(capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, str]:
    args = ["migrate", "--plan", "-e", "development", "--cluster", CLUSTER, "--region", "eu-west-1"]
    code = main([*args, *extra])
    return code, capsys.readouterr().out


def test_plan_names_every_key_and_never_a_value(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.deploy(
        {
            "family": "orderbook",
            "containerDefinitions": [
                {
                    "name": "app",
                    "image": "registry.example/orderbook:1.0.0",
                    "memory": 512,
                    "environment": [
                        {"name": "LOG_LEVEL", "value": "verbose"},
                        {"name": "API_TOKEN", "value": "synthetic-value"},
                    ],
                    "secrets": [
                        {"name": "DB_PASSWORD", "valueFrom": f"{world.db_secret_arn}:password::"},
                        {"name": "TLS_CA_BUNDLE", "valueFrom": world.ca_parameter_arn},
                    ],
                    "environmentFiles": [{"value": "registry.example/env", "type": "s3"}],
                },
            ],
        }
    )
    code, out = migrate(capsys, "--service", SERVICE)
    assert code == 0, out
    assert "live revision: orderbook:2" in out
    assert "DB_PASSWORD: publish /orderbook/development/infra/db-password-arn" in out
    assert "secrets: DB_PASSWORD: pointer /orderbook/development/infra/db-password-arn" in out
    assert "jsonKey password" in out
    assert "secrets: TLS_CA_BUNDLE: parameter /shared/certs/bundle.pem" in out
    assert "parameters: LOG_LEVEL" in out
    assert "API_TOKEN: looks like a secret" in out
    assert "environmentFiles" in out
    assert "synthetic" not in out
    assert "verbose" not in out
    assert not IDENTIFIERS.search(out)


def test_several_containers_need_a_name(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = migrate(capsys, "--service", SERVICE)
    assert code == 1
    assert "name one with --container" in out
    code, out = migrate(capsys, "--service", SERVICE, "--container", "app")
    assert code == 0, out
    assert "container: app (of app, log-router)" in out


def test_missing_service_is_refused(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = migrate(capsys, "--service", "absent")
    assert code == 1
    assert "not found" in out


def test_plan_is_required() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["migrate", "-e", "development", "--cluster", CLUSTER, "--service", SERVICE])
    assert caught.value.code == 2


@pytest.mark.parametrize(
    ("value_from", "kind", "target"),
    [
        (f"{ARN_PREFIX}ssm:eu-west-1:{ACCOUNT_ID}:parameter/shared/x", "parameter", "/shared/x"),
        ("shared/x", "parameter", "/shared/x"),
        ("/shared/x", "parameter", "/shared/x"),
        (
            f"{ARN_PREFIX}secretsmanager:eu-west-1:{ACCOUNT_ID}:secret:db-{SUFFIX}",
            "pointer",
            "/svc/dev/infra/db-url-arn",
        ),
    ],
)
def test_classify(value_from: str, kind: str, target: str) -> None:
    found = classify("svc", "dev", "DB_URL", value_from)
    assert (found.kind, found.target, found.json_key) == (kind, target, None)
