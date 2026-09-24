"""GitHub Actions runner protocol: masks, step outputs, the job summary."""

from __future__ import annotations

import os
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
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def summary(markdown: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(markdown.rstrip() + "\n")
