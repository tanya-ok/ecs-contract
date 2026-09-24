"""What a deploy would write against what is live. Names and verdicts only, never values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Difference:
    section: str
    key: str
    message: str

    def text(self) -> str:
        return f"{self.section}: {self.key}: {self.message}"


def _by_name(entries: Any, field: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in entries or []:
        if isinstance(entry, Mapping) and "name" in entry:
            result[str(entry["name"])] = str(entry.get(field, ""))
    return result


def compare(
    rendered: Mapping[str, Any], live: Mapping[str, Any], *, image: bool = False
) -> list[Difference]:
    found: list[Difference] = []
    for section, field, verb in (
        ("environment", "value", "value differs"),
        ("secrets", "valueFrom", "valueFrom differs"),
    ):
        wanted = _by_name(rendered.get(section), field)
        actual = _by_name(live.get(section), field)
        for key in sorted(wanted.keys() | actual.keys()):
            if key not in actual:
                found.append(Difference(section, key, "only in the contract"))
            elif key not in wanted:
                found.append(Difference(section, key, "only in the live revision"))
            elif wanted[key] != actual[key]:
                found.append(Difference(section, key, verb))
    if image and rendered.get("image") != live.get("image"):
        found.append(Difference("image", "-", "image differs"))
    return found
