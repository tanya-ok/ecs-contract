"""Prove standalone VM isolation, container ownership and secret transport."""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

spec = importlib.util.spec_from_file_location(
    "local_vault", Path(__file__).resolve().parents[1] / "scripts/local_vault.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
IMAGE = module.IMAGE_REPOSITORY + "@sha256:" + "a" * 64


def owned_instance() -> dict[str, Any]:
    return {
        "name": "ecs-contract",
        "status": "Running",
        "config": {
            "param": {"project": "ecs-contract"},
            "mounts": [],
            "containerd": {"system": True, "user": False},
        },
    }


@pytest.mark.parametrize(
    "name,image",
    [
        ("security-lab", IMAGE),
        ("ecsc-smoke-abcdef;bad", IMAGE),
        ("ecsc-smoke-abcdef", "vault:latest"),
    ],
)
def test_refuse_unsafe_name_or_unpinned_image(name: str, image: str) -> None:
    with pytest.raises(module.LocalVaultError):
        module.LocalVault(name, 18200, image)


@pytest.mark.parametrize("change", ["shared-vm", "mount", "wrong-owner", "stopped"])
def test_foreign_or_unsafe_vm_is_refused(change: str) -> None:
    item = owned_instance()
    if change == "shared-vm":
        item["name"] = "security-lab"
    elif change == "mount":
        item["config"]["mounts"] = [{"location": "/example/private"}]
    elif change == "wrong-owner":
        item["config"]["param"]["project"] = "other"
    else:
        item["status"] = "Stopped"
    with pytest.raises(module.LocalVaultError):
        module.verify_instance(item)


def test_foreign_container_is_not_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = module.LocalVault("ecsc-smoke-abcdef", 18200, IMAGE)
    monkeypatch.setattr(module, "instance", owned_instance)
    monkeypatch.setattr(runtime, "exists", lambda: True)
    mutations: list[list[str]] = []

    def nerdctl(args: list[str], **kwargs: Any) -> str:
        if args[0] == "inspect":
            return json.dumps({"app.kubernetes.io/part-of": "other"})
        mutations.append(args)
        return ""

    monkeypatch.setattr(module, "nerdctl", nerdctl)
    with pytest.raises(module.LocalVaultError, match="foreign container"):
        runtime.stop(recover=True)
    assert not mutations


class FreePort:
    def __enter__(self) -> "FreePort":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def bind(self, address: tuple[str, int]) -> None:
        pass


def test_partial_launch_is_cleaned_without_token_in_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = module.LocalVault("ecsc-smoke-abcdef", 18200, IMAGE)
    monkeypatch.setattr(module.socket, "socket", FreePort)
    monkeypatch.setattr(module, "instance", owned_instance)
    exists = False
    commands: list[list[str]] = []
    token = "synthetic-sensitive-value"
    monkeypatch.setattr(runtime, "exists", lambda: exists)

    def nerdctl(args: list[str], *, body: str | None = None) -> str:
        nonlocal exists
        commands.append(args)
        assert all(token not in argument for argument in args)
        if args[0] == "run":
            assert body == "VAULT_DEV_ROOT_TOKEN_ID=" + token + "\n"
            assert args[args.index("--env-file") + 1] == "/dev/stdin"
            exists = True
            raise module.LocalVaultError("Local runtime operation failed")
        if args[0] == "inspect":
            return json.dumps(
                {"app.kubernetes.io/part-of": module.OWNER, "ecs-contract.run": runtime.name}
            )
        if args[0] == "rm":
            exists = False
        return ""

    monkeypatch.setattr(module, "nerdctl", nerdctl)
    with pytest.raises(module.LocalVaultError) as error:
        runtime.start(token)
    assert token not in str(error.value)
    runtime.stop()
    assert not exists
    assert any(args[0] == "rm" for args in commands)


def test_vm_stop_refuses_retained_containers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "instance", owned_instance)
    monkeypatch.setattr(module, "nerdctl", lambda _: "retained-vault\n")
    monkeypatch.setattr(module, "command", lambda *args, **kwargs: pytest.fail("no VM stop"))
    with pytest.raises(module.LocalVaultError, match="retained"):
        module.runtime_stop()


def test_runtime_command_targets_only_standalone_vm(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def collect(args: list[str], **kwargs: Any) -> str:
        commands.append(args)
        return ""

    monkeypatch.setattr(module, "command", collect)
    module.nerdctl(["ps"])
    assert commands == [
        ["limactl", "shell", "ecs-contract", "sudo", "nerdctl", "--namespace", "ecs-contract", "ps"]
    ]


def test_occupied_port_is_refused_before_any_runtime_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = module.LocalVault("ecsc-smoke-abcdef", 18200, IMAGE)

    class Occupied:
        def __enter__(self) -> "Occupied":
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def bind(self, address: tuple[str, int]) -> None:
            raise OSError("occupied")

    monkeypatch.setattr(module.socket, "socket", Occupied)
    monkeypatch.setattr(module, "instance", lambda: pytest.fail("no runtime command"))
    with pytest.raises(module.LocalVaultError, match="occupied"):
        runtime.start("synthetic-sensitive-value")
