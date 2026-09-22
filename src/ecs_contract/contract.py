"""Load and check an ECS config contract. No credentials, no network."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ecs_contract.problems import NA, Problem
from ecs_contract.reserved import RESERVED_NAMES, is_secret_shaped

SOURCE_KINDS: tuple[str, ...] = ("pointer", "parameter", "vault")
SOURCE_FIELDS: frozenset[str] = frozenset((*SOURCE_KINDS, "jsonKey"))

_VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ARN = re.compile(r"arn:aws(?:-[a-z]+)*:", re.IGNORECASE)
_ACCOUNT_ID = re.compile(r"\b\d{12}\b")
_SEGMENT = r"[A-Za-z0-9_.\-]+"
_POINTER = re.compile(rf"(?:/{_SEGMENT})+")
_PARAMETER = re.compile(rf"/?{_SEGMENT}(?:/{_SEGMENT})*")


class ContractFileError(Exception):
    """A contract file cannot be read at all. Misuse of the tool, not a broken contract."""


class _Object(dict[str, Any]):
    """A JSON object that remembers keys it saw twice. Plain dicts silently keep the last."""

    def __init__(self, pairs: list[tuple[str, Any]]) -> None:
        super().__init__()
        self.duplicates: list[str] = []
        for key, value in pairs:
            if key in self and key not in self.duplicates:
                self.duplicates.append(key)
            self[key] = value


def _duplicates(value: object) -> list[str]:
    return list(value.duplicates) if isinstance(value, _Object) else []


def _json_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


@dataclass
class ContractFile:
    path: str
    section: str
    environments: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)
    readable: bool = False

    def problem(self, environment: str, key: str, message: str) -> None:
        self.problems.append(Problem(self.path, environment, key, message))


@dataclass(frozen=True)
class Counts:
    parameters: int
    secrets: int


@dataclass
class Report:
    problems: list[Problem]
    counts: dict[str, Counts]

    @property
    def ok(self) -> bool:
        return not self.problems


def load(path: str | Path, section: str) -> ContractFile:
    """Read one contract file. Structural problems are collected, never raised."""
    display = str(path)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ContractFileError(f"{display}: cannot read: {error.strerror or error}") from error

    contract = ContractFile(display, section)
    try:
        data = json.loads(text, object_pairs_hook=_Object)
    except json.JSONDecodeError as error:
        contract.problem(
            NA, NA, f"invalid JSON at line {error.lineno} column {error.colno}: {error.msg}"
        )
        return contract
    if not isinstance(data, dict):
        contract.problem(NA, NA, "top level must be a JSON object")
        return contract

    for name in _duplicates(data):
        contract.problem(NA, NA, f"top-level field {name!r} declared twice")
    for name in data:
        if name not in ("environments", "$schema"):
            contract.problem(NA, NA, f"unknown top-level field {name!r}; expected 'environments'")

    environments = data.get("environments")
    if environments is None:
        contract.problem(NA, NA, "missing the 'environments' object")
        return contract
    if not isinstance(environments, dict):
        contract.problem(NA, NA, "'environments' must be an object")
        return contract
    contract.readable = True

    for name in _duplicates(environments):
        contract.problem(name, NA, "environment declared twice; the second replaces the first")
    for environment, body in environments.items():
        contract.environments[environment] = _entries(contract, environment, body)
    return contract


def _entries(contract: ContractFile, environment: str, body: object) -> Mapping[str, Any]:
    section = contract.section
    if not isinstance(body, dict):
        contract.problem(environment, NA, f"environment must be an object holding {section!r}")
        return {}
    for name in _duplicates(body):
        contract.problem(environment, NA, f"field {name!r} declared twice")
    for name in body:
        if name != section:
            contract.problem(environment, NA, f"unknown field {name!r}; expected {section!r}")
    entries = body.get(section)
    if entries is None:
        contract.problem(environment, NA, f"missing the {section!r} object")
        return {}
    if not isinstance(entries, dict):
        contract.problem(environment, NA, f"{section!r} must be an object")
        return {}
    for key in _duplicates(entries):
        contract.problem(environment, key, "declared twice; the second replaces the first")
    return entries


def check(
    parameters: str | Path,
    secrets: str | Path,
    environments: Iterable[str] | None = None,
    *,
    reserved: Iterable[str] = (),
    allow_secret_shaped: Iterable[str] = (),
) -> Report:
    """Check both contract files. With no environments given, check every declared one."""
    parameters_file = load(parameters, "parameters")
    secrets_file = load(secrets, "secrets")
    reserved_names = RESERVED_NAMES | frozenset(reserved)
    allowed = frozenset(allow_secret_shaped)
    problems = [*parameters_file.problems, *secrets_file.problems]

    if environments is None:
        names = list(dict.fromkeys([*parameters_file.environments, *secrets_file.environments]))
        if not names and parameters_file.readable and secrets_file.readable:
            problems.append(Problem(parameters_file.path, NA, NA, "no environments declared"))
    else:
        names = list(dict.fromkeys(environments))

    counts: dict[str, Counts] = {}
    for environment in names:
        for contract in (parameters_file, secrets_file):
            if contract.readable and environment not in contract.environments:
                problems.append(
                    Problem(contract.path, environment, NA, "environment not declared in this file")
                )
        declared_parameters = parameters_file.environments.get(environment, {})
        declared_secrets = secrets_file.environments.get(environment, {})

        for key, value in declared_parameters.items():
            at = _At(parameters_file.path, environment, key)
            problems.extend(_check_parameter(at, value, reserved_names, allowed))
        for key, source in declared_secrets.items():
            at = _At(secrets_file.path, environment, key)
            problems.extend(_check_secret(at, source, reserved_names))
        for key in declared_parameters:
            if key in declared_secrets:
                problems.append(
                    Problem(
                        secrets_file.path,
                        environment,
                        key,
                        f"declared in both files, also as a parameter in {parameters_file.path};"
                        " a key has exactly one owner",
                    )
                )
        counts[environment] = Counts(len(declared_parameters), len(declared_secrets))
    return Report(problems, counts)


@dataclass(frozen=True)
class _At:
    """Where a problem sits: the file, the environment, the key."""

    path: str
    environment: str
    key: str

    def problem(self, message: str) -> Problem:
        return Problem(self.path, self.environment, self.key, message)


def _check_name(at: _At, reserved: frozenset[str]) -> list[Problem]:
    if not _VARIABLE_NAME.fullmatch(at.key):
        return [at.problem("not a valid environment variable name")]
    if at.key in reserved:
        return [
            at.problem(
                "reserved name; the platform or the deploy workflow sets it, not the contract"
            )
        ]
    return []


def _check_literal(at: _At, where: str, value: str) -> list[Problem]:
    if _ARN.search(value):
        return [
            at.problem(
                f"{where} is a literal ARN; publish it as a pointer parameter and reference that"
            )
        ]
    if _ACCOUNT_ID.search(value):
        return [at.problem(f"{where} contains a 12-digit number shaped like an AWS account id")]
    return []


def _check_parameter(
    at: _At, value: object, reserved: frozenset[str], allowed: frozenset[str]
) -> list[Problem]:
    found = _check_name(at, reserved)
    if is_secret_shaped(at.key) and at.key not in allowed:
        found.append(
            at.problem(
                "looks like a secret but is declared as a parameter; move it to the secrets"
                " file, or allow it explicitly with --allow-secret-shaped"
            )
        )
    if not isinstance(value, str):
        found.append(at.problem(f"value must be a string, got {_json_type(value)}"))
    else:
        found.extend(_check_literal(at, "value", value))
    return found


def _check_secret(at: _At, source: object, reserved: frozenset[str]) -> list[Problem]:
    found = _check_name(at, reserved)
    if not isinstance(source, dict):
        found.append(
            at.problem("must be an object naming exactly one source: pointer, parameter or vault")
        )
        return found
    found += [at.problem(f"field {name!r} declared twice") for name in _duplicates(source)]
    found += [
        at.problem(f"unknown field {name!r}; expected pointer, parameter, vault or jsonKey")
        for name in source
        if name not in SOURCE_FIELDS
    ]
    kinds = [kind for kind in SOURCE_KINDS if kind in source]
    if not kinds:
        found.append(
            at.problem(
                "names no source; expected exactly one of pointer, parameter, vault (no default)"
            )
        )
    elif len(kinds) > 1:
        found.append(
            at.problem(f"names {len(kinds)} sources ({', '.join(kinds)}); expected exactly one")
        )
    if "jsonKey" in source and "pointer" not in source:
        found.append(at.problem("jsonKey is only valid together with a pointer source"))
    for name in (*SOURCE_KINDS, "jsonKey"):
        if name in source:
            found.extend(_check_source_value(at, name, source[name]))
    return found


def _check_source_value(at: _At, name: str, value: object) -> list[Problem]:
    if not isinstance(value, str) or not value.strip():
        return [at.problem(f"{name} must be a non-empty string")]
    literal = _check_literal(at, name, value)
    if literal:
        return literal
    if name == "pointer" and not _POINTER.fullmatch(value):
        return [
            at.problem(
                f"pointer {value!r} is not an absolute parameter path such as /svc/env/infra/x-arn"
            )
        ]
    if name == "parameter" and not _PARAMETER.fullmatch(value):
        return [at.problem(f"parameter {value!r} is not a valid parameter name")]
    return []
