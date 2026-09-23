"""AWS access. boto3 is optional: `pip install ecs-contract[aws]`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_ecs import ECSClient
    from mypy_boto3_secretsmanager import SecretsManagerClient
    from mypy_boto3_ssm import SSMClient


class AwsUnavailableError(Exception):
    """boto3 is not installed, so commands that read AWS cannot run."""


@dataclass(frozen=True)
class Clients:
    ecs: ECSClient
    ssm: SSMClient
    secretsmanager: SecretsManagerClient


def clients(region: str | None) -> Clients:
    try:
        import boto3  # noqa: PLC0415
    except ImportError as error:
        raise AwsUnavailableError("this command reads AWS; install ecs-contract[aws]") from error
    session = boto3.session.Session(region_name=region)
    return Clients(
        ecs=session.client("ecs"),
        ssm=session.client("ssm"),
        secretsmanager=session.client("secretsmanager"),
    )


def error_code(error: BaseException) -> str:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code", "")
        return str(code)
    return ""
