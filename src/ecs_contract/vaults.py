"""External secret stores behind one interface. A backend returns a value and prints nothing."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class VaultError(Exception):
    """A value could not be fetched. The message never contains a value."""


class VaultBackend(Protocol):
    name: str

    def read(self, reference: str) -> str: ...


class OnePasswordCli:
    """Reads through the 1Password CLI. Authentication is the CLI's own, for example a service
    account token in OP_SERVICE_ACCOUNT_TOKEN."""

    name = "1password"
    scheme = "op" + "://"

    def __init__(self, executable: str = "op", timeout: float = 60.0) -> None:
        self.executable = executable
        self.timeout = timeout

    def read(self, reference: str) -> str:
        executable = shutil.which(self.executable)
        if executable is None:
            raise VaultError(f"the 1Password CLI {self.executable!r} is not on PATH")
        target = reference if reference.startswith(self.scheme) else f"{self.scheme}{reference}"
        try:
            result = subprocess.run(  # noqa: S603 - fixed argv, executable from PATH
                [executable, "read", "--no-newline", target],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise VaultError(f"op read timed out after {self.timeout:.0f}s") from error
        if result.returncode != 0:
            detail = (result.stderr.strip().splitlines() or ["no detail"])[0][:200]
            raise VaultError(f"op read failed: {detail}")
        return result.stdout


class HashiCorpVault:
    """Reads a field from a KV version 2 engine. Reference: `<mount>/<path>#<field>`."""

    name = "hashicorp"

    def __init__(
        self, address: str, token: str, namespace: str | None = None, timeout: float = 10.0
    ) -> None:
        parsed = urllib.parse.urlparse(address)
        if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK:
            raise VaultError("VAULT_ADDR must use https; plain http is accepted only on loopback")
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise VaultError("VAULT_ADDR must be an https URL")
        self.address = address.rstrip("/")
        self.token = token
        self.namespace = namespace
        self.timeout = timeout

    @classmethod
    def from_environment(cls) -> HashiCorpVault:
        address = os.environ.get("VAULT_ADDR")
        token = os.environ.get("VAULT_TOKEN")
        if not address or not token:
            raise VaultError("the hashicorp backend needs VAULT_ADDR and VAULT_TOKEN")
        return cls(address, token, os.environ.get("VAULT_NAMESPACE") or None)

    def read(self, reference: str) -> str:
        path, _, field = reference.partition("#")
        mount, _, secret_path = path.strip("/").partition("/")
        if not field or not mount or not secret_path:
            raise VaultError(f"reference {reference!r} is not <mount>/<path>#<field>")
        url = (
            f"{self.address}/v1/{urllib.parse.quote(mount)}/data/{urllib.parse.quote(secret_path)}"
        )
        headers = {"X-Vault-Token": self.token}
        if self.namespace:
            headers["X-Vault-Namespace"] = self.namespace
        request = urllib.request.Request(url, headers=headers)  # noqa: S310 - scheme checked in __init__
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = json.load(response)
        except urllib.error.HTTPError as error:
            raise VaultError(f"vault returned HTTP {error.code} for {path}") from error
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise VaultError(f"cannot read {path} from vault: {type(error).__name__}") from error
        data = (body.get("data") or {}).get("data") or {}
        value = data.get(field)
        if not isinstance(value, str):
            raise VaultError(f"{path} has no string field {field!r}")
        return value


def backend(name: str) -> VaultBackend:
    if name == "1password":
        return OnePasswordCli()
    if name == "hashicorp":
        return HashiCorpVault.from_environment()
    raise VaultError(f"unknown vault backend {name!r}; expected 1password or hashicorp")
