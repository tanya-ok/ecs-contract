"""Resolve secret sources into task definition `secrets` bindings. Values are never returned."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from ecs_contract.aws import Clients, error_code
from ecs_contract.problems import Problem

SECRET_ARN = re.compile(
    r"arn:aws(?:-[a-z]+)*:secretsmanager:[a-z0-9-]+:\d{12}:secret:[A-Za-z0-9/_+=.@-]+-[A-Za-z0-9]{6}"
)
_DENIED = {"AccessDeniedException", "AccessDenied", "UnauthorizedOperation"}


@dataclass(frozen=True)
class Binding:
    name: str
    value_from: str
    kind: str


@dataclass
class Resolution:
    bindings: list[Binding] = field(default_factory=list)
    vault: dict[str, str] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)
    warnings: list[Problem] = field(default_factory=list)


def resolve(
    path: str,
    environment: str,
    entries: Mapping[str, Mapping[str, Any]],
    aws: Clients,
    config_secret: str | None,
) -> Resolution:
    """Turn every secret entry of one environment into a binding, or a problem naming its key."""
    return _Resolver(path, environment, aws).run(entries, config_secret)


def config_secret_arn(aws: Clients, name_or_arn: str) -> str | None:
    try:
        return aws.secretsmanager.describe_secret(SecretId=name_or_arn)["ARN"]
    except ClientError as error:
        if error_code(error) == "ResourceNotFoundException":
            return None
        raise


@dataclass
class _Resolver:
    path: str
    environment: str
    aws: Clients
    result: Resolution = field(default_factory=Resolution)

    def problem(self, key: str, message: str) -> None:
        self.result.problems.append(Problem(self.path, self.environment, key, message))

    def warning(self, key: str, message: str) -> None:
        self.result.warnings.append(Problem(self.path, self.environment, key, message))

    def run(
        self, entries: Mapping[str, Mapping[str, Any]], config_secret: str | None
    ) -> Resolution:
        config_arn = self.config_arn(entries, config_secret)
        for key, source in sorted(entries.items()):
            if "pointer" in source:
                self.pointer(key, str(source["pointer"]), source.get("jsonKey"))
            elif "parameter" in source:
                self.parameter(key, str(source["parameter"]))
            elif "vault" in source:
                self.result.vault[key] = str(source["vault"])
                if config_arn:
                    self.result.bindings.append(Binding(key, f"{config_arn}:{key}::", "vault"))
        return self.result

    def config_arn(
        self, entries: Mapping[str, Mapping[str, Any]], config_secret: str | None
    ) -> str | None:
        vault_keys = [key for key, source in entries.items() if "vault" in source]
        if not vault_keys:
            return None
        arn = config_secret_arn(self.aws, config_secret) if config_secret else None
        if arn is None:
            message = (
                "the config secret named by --config-secret cannot be found"
                if config_secret
                else "vault source needs --config-secret, the service's own config secret"
            )
            for key in vault_keys:
                self.problem(key, message)
        return arn

    def read_parameter(self, key: str, name: str, what: str) -> dict[str, Any] | None:
        try:
            return dict(self.aws.ssm.get_parameter(Name=name)["Parameter"])
        except ClientError as error:
            code = error_code(error)
            if code == "ParameterNotFound":
                self.problem(key, f"{what} {name} does not exist")
            else:
                self.problem(key, f"cannot read {what} {name}: {code or 'error'}")
            return None

    def pointer(self, key: str, pointer: str, json_key: object) -> None:
        parameter = self.read_parameter(key, pointer, "pointer parameter")
        if parameter is None:
            return
        arn = str(parameter.get("Value", "")).strip()
        if not SECRET_ARN.fullmatch(arn):
            self.problem(
                key, f"pointer parameter {pointer} does not hold a complete Secrets Manager ARN"
            )
            return
        if json_key is None:
            self.result.bindings.append(Binding(key, arn, "pointer"))
            return
        verdict = _has_json_key(self.aws, arn, str(json_key))
        if verdict is False:
            self.problem(key, f"the secret behind this pointer has no key {json_key}")
            return
        if verdict is None:
            self.warning(
                key,
                f"cannot read the secret behind this pointer to confirm key {json_key};"
                " binding kept",
            )
        self.result.bindings.append(Binding(key, f"{arn}:{json_key}::", "pointer"))

    def parameter(self, key: str, name: str) -> None:
        parameter = self.read_parameter(key, name, "parameter")
        if parameter is not None:
            self.result.bindings.append(Binding(key, str(parameter["ARN"]), "parameter"))


def _has_json_key(aws: Clients, arn: str, json_key: str) -> bool | None:
    """True or False when the secret is readable, None when the caller may not read it."""
    try:
        response = aws.secretsmanager.get_secret_value(SecretId=arn)
    except ClientError as error:
        if error_code(error) in _DENIED:
            return None
        return False
    except BotoCoreError:
        return None
    try:
        document = json.loads(response.get("SecretString") or "")
    except ValueError:
        return False
    return isinstance(document, dict) and json_key in document
