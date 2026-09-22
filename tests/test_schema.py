"""The published schemas agree with the checker on the files the checker accepts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.conftest import EXAMPLE, FIXTURES, ROOT

SCHEMAS = ROOT / "src" / "ecs_contract" / "schema"


def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("folder", [EXAMPLE, FIXTURES / "valid"])
@pytest.mark.parametrize("name", ["parameters", "secrets"])
def test_valid_files_match_schema(folder: Path, name: str) -> None:
    validator(name).validate(load(folder / f"{name}.json"))


@pytest.mark.parametrize(
    "source",
    [
        {},
        {"pointer": "/a/b-arn", "vault": "a/b"},
        {"parameter": "/a/b", "jsonKey": "k"},
        {"pointer": "relative/path"},
        {"pionter": "/a/b"},
    ],
)
def test_broken_sources_fail_schema(source: dict[str, str]) -> None:
    document = {"environments": {"development": {"secrets": {"KEY": source}}}}
    assert not validator("secrets").is_valid(document)


def test_non_string_parameter_fails_schema() -> None:
    document = {"environments": {"development": {"parameters": {"PORT": 8080}}}}
    assert not validator("parameters").is_valid(document)
