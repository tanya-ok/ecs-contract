"""Render the next revision from the one the service runs now. Only three fields change."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ecs_contract.aws import Clients
from ecs_contract.sources import Binding

READ_ONLY_FIELDS: tuple[str, ...] = (
    "taskDefinitionArn",
    "revision",
    "status",
    "requiresAttributes",
    "compatibilities",
    "registeredAt",
    "registeredBy",
    "deregisteredAt",
)


class RenderError(Exception):
    """The live service or its task definition does not allow a render."""


@dataclass(frozen=True)
class Live:
    task_definition_arn: str
    task_definition: dict[str, Any]
    tags: list[dict[str, str]]

    @property
    def revision(self) -> str:
        return family_revision(self.task_definition_arn)


def family_revision(arn: str) -> str:
    """`family:revision` from a task definition ARN. No account id, so it may be printed."""
    return arn.rsplit("/", 1)[-1]


def live(aws: Clients, cluster: str, service: str) -> Live:
    described = aws.ecs.describe_services(cluster=cluster, services=[service])
    services = [s for s in described.get("services", []) if s.get("status") != "INACTIVE"]
    if not services:
        raise RenderError(f"service {service} not found in cluster {cluster}")
    arn = services[0].get("taskDefinition")
    if not arn:
        raise RenderError(f"service {service} has no task definition")
    task = aws.ecs.describe_task_definition(taskDefinition=arn, include=["TAGS"])
    tags = [{"key": t["key"], "value": t["value"]} for t in task.get("tags", []) if "key" in t]
    return Live(arn, dict(task["taskDefinition"]), tags)


def pick_container(task_definition: Mapping[str, Any], name: str | None) -> dict[str, Any]:
    containers: list[dict[str, Any]] = list(task_definition.get("containerDefinitions", []))
    names = [str(c.get("name")) for c in containers]
    if name is None:
        if len(containers) == 1:
            return containers[0]
        raise RenderError(
            f"task definition has {len(containers)} containers ({', '.join(names)});"
            " name one with --container"
        )
    for container in containers:
        if container.get("name") == name:
            return container
    raise RenderError(f"no container named {name}; the task definition has {', '.join(names)}")


def replace_tag(image: str, tag: str) -> str:
    """Swap the tag of an image reference, dropping any digest."""
    repository = image.split("@", 1)[0]
    last = repository.rsplit("/", 1)[-1]
    if ":" in last:
        repository = repository[: repository.rfind(":")]
    return f"{repository}:{tag}"


def render(
    current: Live,
    container: str | None,
    parameters: Mapping[str, str],
    bindings: Iterable[Binding],
    image: str | None = None,
) -> dict[str, Any]:
    """Registration input for the next revision. Everything but three fields is copied as is."""
    registration = {
        key: copy.deepcopy(value)
        for key, value in current.task_definition.items()
        if key not in READ_ONLY_FIELDS
    }
    target = pick_container(registration, container)
    target["environment"] = [{"name": k, "value": v} for k, v in sorted(parameters.items())]
    target["secrets"] = [
        {"name": b.name, "valueFrom": b.value_from} for b in sorted(bindings, key=lambda b: b.name)
    ]
    if image:
        target["image"] = image
    if current.tags:
        registration["tags"] = copy.deepcopy(current.tags)
    return registration


def outside_writers(container: Mapping[str, Any]) -> list[str]:
    """Other channels that also set variables in this container, outside the contract."""
    found = []
    if container.get("environmentFiles"):
        found.append("environmentFiles")
    return found
