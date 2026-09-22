from __future__ import annotations

import socket
from pathlib import Path

import pytest

from ecs_contract import __version__
from ecs_contract.cli import main
from tests.conftest import EXAMPLE, FIXTURES

EXAMPLE_ARGS = [
    "check",
    "--parameters",
    str(EXAMPLE / "parameters.json"),
    "--secrets",
    str(EXAMPLE / "secrets.json"),
]
BROKEN_ARGS = [
    "check",
    "--parameters",
    str(FIXTURES / "broken" / "parameters.json"),
    "--secrets",
    str(FIXTURES / "broken" / "secrets.json"),
]


@pytest.fixture(autouse=True)
def _outside_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def test_success_prints_counts(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(EXAMPLE_ARGS) == 0
    assert capsys.readouterr().out.splitlines() == [
        "development: parameters=4 secrets=3",
        "production: parameters=4 secrets=3",
    ]


def test_single_environment(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*EXAMPLE_ARGS, "-e", "production"]) == 0
    assert capsys.readouterr().out.splitlines() == ["production: parameters=4 secrets=3"]


def test_failure_lists_every_problem(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(BROKEN_ARGS) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "ecsc: 12 problems"
    assert all(line.count(": ") >= 3 for line in lines[:-1])
    assert any("secrets.json: development: DB_PASSWORD: names no source" in x for x in lines)


def test_values_are_never_printed(capsys: pytest.CaptureFixture[str]) -> None:
    main(BROKEN_ARGS)
    out = capsys.readouterr().out
    assert "change-me" not in out
    assert "redis://" not in out


def test_github_format(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BROKEN_ARGS, "--format", "github"]) == 1
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("::error file=")
    assert ",title=ecs-contract::" in first


def test_auto_format_inside_actions(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    main(BROKEN_ARGS)
    assert capsys.readouterr().out.startswith("::error ")


def test_missing_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = str(tmp_path / "nope.json")
    assert main(["check", "--parameters", missing, "--secrets", missing]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_usage_error_exits_2() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["check"])
    assert exit_info.value.code == 2


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.strip() == f"ecsc {__version__}"


def test_check_never_touches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("check opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    assert main(EXAMPLE_ARGS) == 0
    assert main(BROKEN_ARGS) == 1
