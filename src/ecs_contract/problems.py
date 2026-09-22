"""One problem, one line: the file, the environment, the key, what is wrong."""

from __future__ import annotations

from dataclasses import dataclass

NA = "-"


@dataclass(frozen=True)
class Problem:
    file: str
    environment: str
    key: str
    message: str

    def text(self) -> str:
        return f"{self.file}: {self.environment}: {self.key}: {self.message}"

    def github(self) -> str:
        where = f"{self.environment}: {self.key}: {self.message}"
        return f"::error file={_property(self.file)},title=ecs-contract::{_data(where)}"


def _data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _property(value: str) -> str:
    return _data(value).replace(":", "%3A").replace(",", "%2C")
