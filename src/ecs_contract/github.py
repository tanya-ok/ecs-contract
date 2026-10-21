"""GitHub Actions runner protocol: masks, step outputs, the job summary."""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def in_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def mask(value: str) -> None:
    """Register a value with the runner so it never appears in a log. Each line is masked."""
    if not in_actions():
        return
    for line in value.splitlines() or [value]:
        if line.strip():
            print(f"::add-mask::{line}", flush=True)


def set_output(name: str, value: str) -> None:
    """Multiline form with a random delimiter: a value cannot end the block or add outputs."""
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    if not name or any(c in name for c in "\r\n<="):
        raise ValueError("invalid step output name")
    delimiter = f"ghadelimiter_{secrets.token_hex(16)}"
    if delimiter in value:
        raise ValueError("step output value contains the delimiter")
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def summary(markdown: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(markdown.rstrip() + "\n")
