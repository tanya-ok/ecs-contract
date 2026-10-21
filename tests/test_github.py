from __future__ import annotations

import re
from pathlib import Path

import pytest

from ecs_contract.github import set_output

BLOCK = re.compile(r"([^\n<=]+)<<(ghadelimiter_[0-9a-f]{32})\n(.*?)\n\2\n", re.DOTALL)


def outputs(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    blocks = list(BLOCK.finditer(text))
    assert sum(len(m.group(0)) for m in blocks) == len(text), text
    return {m.group(1): m.group(3) for m in blocks}


@pytest.fixture
def target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(path))
    return path


def test_value_cannot_inject_an_output(target: Path) -> None:
    set_output("changes", "1\ninjected=yes\nEOF")
    set_output("task-definition", "out.json")
    assert outputs(target) == {"changes": "1\ninjected=yes\nEOF", "task-definition": "out.json"}


def test_delimiter_is_random(target: Path) -> None:
    set_output("a", "x")
    set_output("a", "x")
    delimiters = re.findall(r"<<(\S+)", target.read_text(encoding="utf-8"))
    assert len(set(delimiters)) == 2


@pytest.mark.parametrize("name", ["", "a\nb", "a=b", "a<<b"])
def test_invalid_name_is_refused(target: Path, name: str) -> None:
    with pytest.raises(ValueError, match="invalid step output name"):
        set_output(name, "x")


def test_without_runner_nothing_is_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    set_output("a", "x")
    assert not list(tmp_path.iterdir())
