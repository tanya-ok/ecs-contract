"""`ecsc migrate --plan`: the migration runbook, filled in from the live service. Reads only."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ecs_contract.render import Live, pick_container
from ecs_contract.reserved import RESERVED_NAMES, is_secret_shaped

_SECRET = re.compile(r":secretsmanager:[^:]+:[^:]+:secret:[^:]+(?::(?P<json_key>[^:]*))?")
_PARAMETER_ARN = re.compile(r":ssm:[^:]+:[^:]+:parameter(?P<name>/.*)$")


@dataclass(frozen=True)
class SecretPlan:
    name: str
    kind: str
    target: str
    json_key: str | None = None


@dataclass
class Plan:
    service: str
    environment: str
    revision: str
    container: str
    containers: list[str]
    parameters: list[str] = field(default_factory=list)
    secrets: list[SecretPlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def pointer_name(service: str, environment: str, key: str) -> str:
    return f"/{service}/{environment}/infra/{key.lower().replace('_', '-')}-arn"


def classify(service: str, environment: str, name: str, value_from: str) -> SecretPlan:
    """Map one live binding onto a source kind. Never keeps an ARN: account ids stay out."""
    secret = _SECRET.search(value_from)
    if secret:
        return SecretPlan(
            name, "pointer", pointer_name(service, environment, name), secret["json_key"] or None
        )
    parameter = _PARAMETER_ARN.search(value_from)
    if parameter:
        return SecretPlan(name, "parameter", parameter["name"])
    if value_from.startswith("arn:"):
        return SecretPlan(name, "pointer", pointer_name(service, environment, name))
    path = value_from if value_from.startswith("/") else f"/{value_from}"
    return SecretPlan(name, "parameter", path)


def plan(current: Live, service: str, environment: str, container: str | None) -> Plan:
    target: Mapping[str, Any] = pick_container(current.task_definition, container)
    names = [str(c.get("name")) for c in current.task_definition.get("containerDefinitions", [])]
    result = Plan(service, environment, current.revision, str(target.get("name")), names)
    for entry in target.get("environment") or []:
        name = str(entry.get("name"))
        if name in RESERVED_NAMES:
            result.warnings.append(f"{name}: reserved; the deploy sets it, drop it from the files")
        elif is_secret_shaped(name):
            result.warnings.append(
                f"{name}: looks like a secret but sits in environment; move it to secrets"
            )
        else:
            result.parameters.append(name)
    for entry in target.get("secrets") or []:
        result.secrets.append(
            classify(service, environment, str(entry.get("name")), str(entry.get("valueFrom")))
        )
    if target.get("environmentFiles"):
        result.warnings.append(
            "environmentFiles: variables set there bypass the contract; move them into the files"
        )
    result.parameters.sort()
    result.secrets.sort(key=lambda s: s.name)
    return result


def lines(p: Plan) -> list[str]:
    """The runbook as printable lines. Names and paths only, never a value or an ARN."""
    out = [
        f"migrate: plan for {p.service}, environment {p.environment}; nothing is changed",
        f"live revision: {p.revision}",
        f"container: {p.container} (of {', '.join(p.containers)})",
        "",
        "0. Before you start",
        f"   record the live revision {p.revision} and the version map of every secret below",
        "   remove the desired count from the service resource if autoscaling manages it",
        "",
        "1. Publish pointers and widen the deploy role; expect no change to the service",
    ]
    pointers = [s for s in p.secrets if s.kind == "pointer"]
    out += [
        f"   {s.name}: publish {s.target} holding the secret ARN it binds now" for s in pointers
    ]
    if not pointers:
        out.append("   no secret needs a pointer")
    out += [
        "",
        "2. In one commit: retain policy on the task definition resource, and the service set to",
        "   the live revision (ServiceFromLiveRevision). Plan: no replacement. Deploy.",
        "",
        "3. In a second commit: delete the task definition resource. Plan: orphan or retain,",
        "   never destroy; if destroy, stop, step 2 was not deployed. Deploy.",
        f"   verify the service still runs {p.revision}",
        "",
        "4. Write the contract files, then ecsc check",
    ]
    out += [f"   parameters: {name}" for name in p.parameters]
    for s in p.secrets:
        key = f", jsonKey {s.json_key}" if s.json_key else ""
        out.append(f"   secrets: {s.name}: {s.kind} {s.target}{key}")
    out += [f"   warning: {w}" for w in p.warnings]
    out += [
        "",
        "5. Verify: ecsc drift reports none, and an infrastructure deploy changes nothing",
    ]
    return out
