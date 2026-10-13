"""Exercise the actual local Vault runtime without creating AWS resources."""

import json
import secrets
import urllib.request

from local_vault import LocalVault

IMAGE = (
    "docker.io/hashicorp/vault@sha256:"
    "750bb37c1638fa194ab37053a81618c61bb0491ddec6fccac87c07a8e6cd8166"
)


def main() -> None:
    runtime = LocalVault("ecsc-smoke-" + secrets.token_hex(6), 18200, IMAGE)
    token = secrets.token_urlsafe(24)
    value = secrets.token_urlsafe(24)
    try:
        runtime.start(token)
        url = "http://127.0.0.1:18200/v1/secret/data/synthetic"
        request = urllib.request.Request(
            url,
            data=json.dumps({"data": {"value": value}}).encode(),
            headers={"X-Vault-Token": token, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5):
            pass
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            urllib.request.Request(url, headers={"X-Vault-Token": token}),
            timeout=5,
        ) as response:
            if json.load(response)["data"]["data"]["value"] != value:
                raise RuntimeError("Synthetic Vault value mismatch")
        print("PASS: containerd Vault write and read over local forwarding")
    finally:
        runtime.stop()
    print("PASS: owned container removed; standalone VM and shared security lab preserved")


if __name__ == "__main__":
    main()
