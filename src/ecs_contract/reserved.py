"""Names the contract may not declare, and names that look like secrets."""

from __future__ import annotations

RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN",
        "ECS_CONTAINER_METADATA_URI",
        "ECS_CONTAINER_METADATA_URI_V4",
    }
)

SECRET_SUFFIXES: tuple[str, ...] = (
    "PASSWORD",
    "PASSWD",
    "SECRET",
    "TOKEN",
    "API_KEY",
    "SECRET_KEY",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "SIGNING_KEY",
    "ENCRYPTION_KEY",
    "CREDENTIALS",
)


def is_secret_shaped(name: str) -> bool:
    upper = name.upper()
    return any(upper == suffix or upper.endswith(f"_{suffix}") for suffix in SECRET_SUFFIXES)
