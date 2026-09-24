from __future__ import annotations

import http.server
import json
import os
import stat
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ecs_contract.cli import main
from ecs_contract.vaults import HashiCorpVault, OnePasswordCli, VaultError
from tests.aws_world import CONFIG_SECRET, REGION, World

FAKE_OP = """#!/bin/sh
case "$3" in
  *missing*) echo "[ERROR] item not found in vault" >&2; exit 1 ;;
  *) printf 'value-of-%s' "${3##*/}" ;;
esac
"""


@pytest.fixture
def fake_op(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    op = bin_dir / "op"
    op.write_text(FAKE_OP)
    op.chmod(op.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return op


def sync(world: World, *extra: str) -> int:
    return main(
        world.args(
            "sync",
            "--config-secret",
            CONFIG_SECRET,
            "--vault-backend",
            "1password",
            "--region",
            REGION,
            *extra,
        )
    )


def secret(world: World) -> dict[str, Any]:
    value = world.secretsmanager.get_secret_value(SecretId=CONFIG_SECRET)["SecretString"]
    return dict(json.loads(value))


def test_sync_writes_then_is_idempotent(
    world: World, fake_op: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sync(world) == 0
    out = capsys.readouterr().out
    assert "sync: SETTLEMENT_API_TOKEN: added" in out
    assert "sync: written" in out
    assert "value-of-token" not in out
    assert secret(world) == {"SETTLEMENT_API_TOKEN": "value-of-token"}

    assert sync(world) == 0
    out = capsys.readouterr().out
    assert "sync: SETTLEMENT_API_TOKEN: unchanged" in out
    assert "already current" in out


def test_sync_keeps_keys_for_rollback_unless_pruned(
    world: World, fake_op: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world.secretsmanager.put_secret_value(
        SecretId=CONFIG_SECRET, SecretString=json.dumps({"settlement_api_token": "old"})
    )
    assert sync(world) == 0
    assert "sync: settlement_api_token: kept" in capsys.readouterr().out
    assert set(secret(world)) == {"settlement_api_token", "SETTLEMENT_API_TOKEN"}

    assert sync(world, "--prune") == 0
    assert "sync: settlement_api_token: removed" in capsys.readouterr().out
    assert set(secret(world)) == {"SETTLEMENT_API_TOKEN"}


def test_sync_dry_run_writes_nothing(
    world: World, fake_op: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sync(world, "--dry-run") == 0
    assert "dry run, nothing written" in capsys.readouterr().out
    with pytest.raises(world.secretsmanager.exceptions.ResourceNotFoundException):
        world.secretsmanager.get_secret_value(SecretId=CONFIG_SECRET)


def test_sync_masks_values_in_actions(
    world: World,
    fake_op: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert sync(world) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "::add-mask::value-of-token"
    assert sum("value-of-token" in line for line in lines) == 1


def test_sync_vault_failure_names_key(
    world: World, fake_op: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world.write_contract(secrets={"SETTLEMENT_API_TOKEN": {"vault": "exchange/missing/token"}})
    assert sync(world) == 1
    out = capsys.readouterr().out
    assert "SETTLEMENT_API_TOKEN: op read failed: [ERROR] item not found in vault" in out


def test_sync_refuses_non_json_secret(
    world: World, fake_op: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world.secretsmanager.put_secret_value(SecretId=CONFIG_SECRET, SecretString="plain text")
    assert sync(world) == 1
    assert "something other than a JSON object" in capsys.readouterr().out


def test_sync_without_vault_keys(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.write_contract(secrets={"TLS_CA_BUNDLE": {"parameter": "/shared/certs/bundle.pem"}})
    assert sync(world) == 0
    assert "nothing to write" in capsys.readouterr().out


def test_op_missing_from_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    with pytest.raises(VaultError, match="not on PATH"):
        OnePasswordCli().read("exchange/item/field")


def test_op_adds_scheme(fake_op: Path) -> None:
    assert OnePasswordCli().read("exchange/settlement/token") == "value-of-token"
    assert (
        OnePasswordCli().read(OnePasswordCli.scheme + "exchange/settlement/key") == "value-of-key"
    )


class _Vault(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.headers.get("X-Vault-Token") != "root":
            self.send_response(403)
            self.end_headers()
            return
        if self.path == "/v1/kv/data/orderbook/settlement":
            body = json.dumps({"data": {"data": {"token": "from-vault"}}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return


@pytest.fixture
def vault_address() -> Iterator[str]:
    server = http.server.HTTPServer(("127.0.0.1", 0), _Vault)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_hashicorp_reads_field(vault_address: str) -> None:
    assert (
        HashiCorpVault(vault_address, "root").read("kv/orderbook/settlement#token") == "from-vault"
    )


def test_hashicorp_missing_field(vault_address: str) -> None:
    with pytest.raises(VaultError, match="no string field 'secret'"):
        HashiCorpVault(vault_address, "root").read("kv/orderbook/settlement#secret")


def test_hashicorp_http_error(vault_address: str) -> None:
    with pytest.raises(VaultError, match="HTTP 403"):
        HashiCorpVault(vault_address, "wrong").read("kv/orderbook/settlement#token")


def test_hashicorp_reference_shape() -> None:
    with pytest.raises(VaultError, match="is not <mount>/<path>#<field>"):
        HashiCorpVault("https://vault.example", "t").read("kv/orderbook/settlement")


def test_hashicorp_refuses_plain_http() -> None:
    with pytest.raises(VaultError, match="must use https"):
        HashiCorpVault("http://vault.example", "t")


def test_hashicorp_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    with pytest.raises(VaultError, match="needs VAULT_ADDR and VAULT_TOKEN"):
        HashiCorpVault.from_environment()


def test_sync_config_secret_missing(
    world: World, fake_op: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        world.args(
            "sync", "--config-secret", "ghost", "--vault-backend", "1password", "--region", REGION
        )
    )
    assert code == 1
    assert "the config secret named by --config-secret cannot be found" in capsys.readouterr().out
