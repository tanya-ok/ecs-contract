"""Standalone ECS Contract Lima/containerd runtime and ephemeral local Vault."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

VM = "ecs-contract"
OWNER = "ecs-contract-smoke"
NAMESPACE = "ecs-contract"
IMAGE_REPOSITORY = "docker.io/hashicorp/vault"
PROFILE = Path(__file__).resolve().parents[1] / "deploy/lima.yaml"


class LocalVaultError(Exception):
    """Fixed messages only; no captured output or secret material."""


def command(args: list[str], *, body: str | None = None, timeout: int = 120) -> str:
    try:
        done = subprocess.run(
            args,
            input=body,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise LocalVaultError("Local runtime operation unavailable") from None
    if done.returncode:
        raise LocalVaultError("Local runtime operation failed")
    return done.stdout


def instance() -> dict[str, Any] | None:
    if not shutil.which("limactl"):
        raise LocalVaultError("Lima is required")
    return next(
        (
            json.loads(line)
            for line in command(["limactl", "list", "--json"]).splitlines()
            if line and json.loads(line).get("name") == VM
        ),
        None,
    )


def verify_instance(item: dict[str, Any] | None, *, running: bool = True) -> None:
    config = item.get("config", {}) if item else {}
    if (
        not item
        or item.get("name") != VM
        or config.get("param", {}).get("project") != "ecs-contract"
        or config.get("mounts")
        or config.get("containerd", {}).get("system") is not True
        or config.get("containerd", {}).get("user") is not False
    ):
        raise LocalVaultError("Refusing a foreign or unsafe ECS runtime VM")
    if running and item.get("status") != "Running":
        raise LocalVaultError("Start the standalone ECS runtime before the demo")


def nerdctl(args: list[str], *, body: str | None = None) -> str:
    return command(
        ["limactl", "shell", VM, "sudo", "nerdctl", "--namespace", NAMESPACE, *args], body=body
    )


def runtime_up() -> None:
    current = instance()
    if current:
        verify_instance(current, running=False)
        command(["limactl", "start", "--tty=false", VM], timeout=600)
    else:
        command(["limactl", "start", "--tty=false", "--name=" + VM, str(PROFILE)], timeout=600)
    verify_instance(instance())
    print("Standalone ECS Contract Lima/containerd runtime ready")


def runtime_stop() -> None:
    verify_instance(instance())
    if nerdctl(["ps", "--all", "--format", "{{.Names}}"]).strip():
        raise LocalVaultError("Refusing to stop a VM with retained ECS containers")
    command(["limactl", "stop", VM])
    print("Standalone ECS runtime stopped; shared security lab untouched")


class LocalVault:
    def __init__(self, name: str, port: int, image: str) -> None:
        if not re.fullmatch(r"ecsc-smoke-[a-z0-9]{6,32}", name):
            raise LocalVaultError("Invalid smoke name")
        if port != 18200:
            raise LocalVaultError("The standalone profile forwards only port 18200")
        if not re.fullmatch(re.escape(IMAGE_REPOSITORY) + r"@sha256:[a-f0-9]{64}", image):
            raise LocalVaultError("Vault requires a pinned image digest")
        self.name = name
        self.container = name + "-vault"
        self.port = port
        self.image = image
        self.created = False

    def exists(self) -> bool:
        return self.container in nerdctl(["ps", "--all", "--format", "{{.Names}}"]).splitlines()

    def start(self, token: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,}", token):
            raise LocalVaultError("Invalid runtime token format")
        try:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", self.port))
        except OSError:
            raise LocalVaultError("Local forwarding port is already occupied") from None
        verify_instance(instance())
        if self.exists():
            raise LocalVaultError("Smoke container already exists")
        # Mark this attempt before launch so a partial creation can be cleaned up.
        self.created = True
        nerdctl(
            [
                "run",
                "--detach",
                "--name",
                self.container,
                "--label",
                "app.kubernetes.io/part-of=" + OWNER,
                "--label",
                "ecs-contract.run=" + self.name,
                "--user",
                "100:1000",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--memory=256m",
                "--cpus=0.25",
                "--env-file",
                "/dev/stdin",
                "--publish",
                f"127.0.0.1:{self.port}:8200",
                "--entrypoint",
                "vault",
                self.image,
                "server",
                "-dev",
                "-dev-listen-address=0.0.0.0:8200",
            ],
            body="VAULT_DEV_ROOT_TOKEN_ID=" + token + "\n",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(60):
            if not self.exists():
                raise LocalVaultError("Local Vault exited before readiness")
            try:
                with opener.open(
                    f"http://127.0.0.1:{self.port}/v1/sys/health", timeout=2
                ) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(1)
        raise LocalVaultError("Local Vault readiness timed out")

    def stop(self, *, recover: bool = False) -> None:
        if not self.created and not recover:
            return
        verify_instance(instance())
        if not self.exists():
            self.created = False
            return
        labels = json.loads(
            nerdctl(["inspect", "--format", "{{json .Config.Labels}}", self.container])
        )
        if (
            labels.get("app.kubernetes.io/part-of") != OWNER
            or labels.get("ecs-contract.run") != self.name
        ):
            raise LocalVaultError("Refusing to delete a foreign container")
        nerdctl(["rm", "--force", self.container])
        if self.exists():
            raise LocalVaultError("Local container cleanup is incomplete")
        self.created = False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["up", "stop"])
    args = parser.parse_args()
    try:
        if args.operation == "up":
            runtime_up()
        else:
            runtime_stop()
    except LocalVaultError as error:
        print(str(error))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
