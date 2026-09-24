from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ecs_contract import Report, check

pytest_plugins = ("tests.aws_world",)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
EXAMPLE = ROOT / "examples" / "orderbook"

# Identifier-shaped strings are assembled at runtime so no source file carries one literally.
ARN_PREFIX = "arn" + ":aws:"
ACCOUNT_ID = "4" * 12

Contract = Callable[..., Report]


def document(section: str, environments: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"environments": {env: {section: entries} for env, entries in environments.items()}}


@pytest.fixture
def contract(tmp_path: Path) -> Contract:
    """Write both files from plain dicts, or raw text, and run the check."""

    def run(
        parameters: dict[str, Any] | str | None = None,
        secrets: dict[str, Any] | str | None = None,
        **options: Any,
    ) -> Report:
        paths = {}
        for name, given in (("parameters", parameters), ("secrets", secrets)):
            content: dict[str, Any] | str
            if given is None:
                content = document(name, {"development": {}})
            elif isinstance(given, dict) and "environments" not in given:
                content = document(name, {"development": given})
            else:
                content = given
            text = content if isinstance(content, str) else json.dumps(content)
            path = tmp_path / f"{name}.json"
            path.write_text(text, encoding="utf-8")
            paths[name] = path
        return check(paths["parameters"], paths["secrets"], **options)

    return run


def messages(report: Report) -> list[str]:
    return [p.text() for p in report.problems]


def only(report: Report) -> str:
    assert len(report.problems) == 1, messages(report)
    return report.problems[0].message
