"""A synthetic ECS service in moto: one cluster, one service, two containers, three sources."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

REGION = "eu-west-1"
CLUSTER = "orderbook"
SERVICE = "orderbook"
POINTER = "/orderbook/development/infra/db-secret-arn"
CA_PARAMETER = "/shared/certs/bundle.pem"
CONFIG_SECRET = "orderbook/development/config"
VAULT_REFERENCE = "orderbook-development/settlement-api/token"


@dataclass
class World:
    root: Path
    ecs: Any
    ssm: Any
    secretsmanager: Any
    db_secret_arn: str
    config_secret_arn: str
    ca_parameter_arn: str
    task_definition_arn: str
    parameters: Path
    secrets: Path

    def args(self, command: str, *extra: str) -> list[str]:
        base = [command, "--parameters", str(self.parameters), "--secrets", str(self.secrets)]
        return [*base, "--environment", "development", *extra]

    def service_args(self, *extra: str) -> list[str]:
        return ["--cluster", CLUSTER, "--service", SERVICE, "--region", REGION, *extra]

    def write_contract(
        self, parameters: dict[str, str] | None = None, secrets: dict[str, Any] | None = None
    ) -> None:
        if parameters is not None:
            self.parameters.write_text(
                json.dumps({"environments": {"development": {"parameters": parameters}}})
            )
        if secrets is not None:
            self.secrets.write_text(
                json.dumps({"environments": {"development": {"secrets": secrets}}})
            )

    def live_container(self, name: str = "app") -> dict[str, Any]:
        service = self.ecs.describe_services(cluster=CLUSTER, services=[SERVICE])["services"][0]
        task = self.ecs.describe_task_definition(taskDefinition=service["taskDefinition"])
        containers = task["taskDefinition"]["containerDefinitions"]
        return next(c for c in containers if c["name"] == name)

    def deploy(self, task_definition: dict[str, Any]) -> str:
        registered = self.ecs.register_task_definition(**task_definition)
        arn = str(registered["taskDefinition"]["taskDefinitionArn"])
        self.ecs.update_service(cluster=CLUSTER, service=SERVICE, taskDefinition=arn)
        return arn


DEFAULT_SECRETS: dict[str, Any] = {
    "DB_PASSWORD": {"pointer": POINTER, "jsonKey": "password"},
    "TLS_CA_BUNDLE": {"parameter": CA_PARAMETER},
    "SETTLEMENT_API_TOKEN": {"vault": VAULT_REFERENCE},
}


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    for name, value in (
        ("AWS_ACCESS_KEY_ID", "testing"),
        ("AWS_SECRET_ACCESS_KEY", "testing"),
        ("AWS_SESSION_TOKEN", "testing"),
        ("AWS_REGION", REGION),
        ("AWS_DEFAULT_REGION", REGION),
    ):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    with mock_aws():
        ecs = boto3.client("ecs", region_name=REGION)
        ssm = boto3.client("ssm", region_name=REGION)
        sm = boto3.client("secretsmanager", region_name=REGION)
        db = sm.create_secret(
            Name="orderbook/development/db",
            SecretString=json.dumps({"username": "orderbook", "password": "synthetic"}),
        )
        config = sm.create_secret(Name=CONFIG_SECRET)
        ssm.put_parameter(Name=POINTER, Value=db["ARN"], Type="String")
        ssm.put_parameter(Name=CA_PARAMETER, Value="synthetic-bundle", Type="String")
        ca_arn = ssm.get_parameter(Name=CA_PARAMETER)["Parameter"]["ARN"]
        ecs.create_cluster(clusterName=CLUSTER)
        registered = ecs.register_task_definition(
            family="orderbook",
            requiresCompatibilities=["FARGATE"],
            networkMode="awsvpc",
            cpu="256",
            memory="512",
            containerDefinitions=[
                {
                    "name": "app",
                    "image": "registry.example/orderbook:1.0.0",
                    "essential": True,
                    "environment": [
                        {"name": "LOG_LEVEL", "value": "warn"},
                        {"name": "LEGACY_FLAG", "value": "on"},
                    ],
                    "portMappings": [{"containerPort": 8080}],
                },
                {
                    "name": "log-router",
                    "image": "registry.example/log-router:2",
                    "essential": False,
                    "environment": [{"name": "OUTPUT", "value": "stdout"}],
                },
            ],
            tags=[{"key": "team", "value": "exchange"}],
        )
        arn = registered["taskDefinition"]["taskDefinitionArn"]
        ecs.create_service(cluster=CLUSTER, serviceName=SERVICE, taskDefinition=arn, desiredCount=1)
        w = World(
            tmp_path,
            ecs,
            ssm,
            sm,
            db["ARN"],
            config["ARN"],
            ca_arn,
            arn,
            tmp_path / "parameters.json",
            tmp_path / "secrets.json",
        )
        w.write_contract({"LOG_LEVEL": "info", "PORT": "8080"}, DEFAULT_SECRETS)
        yield w
