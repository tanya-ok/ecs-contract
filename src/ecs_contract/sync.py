"""Write vault-sourced values into the service's own config secret, as one JSON document."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from botocore.exceptions import ClientError

from ecs_contract.aws import Clients, error_code


class SyncError(Exception):
    """The config secret cannot be written safely. The message never contains a value."""


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    written: bool = False


def current_document(aws: Clients, secret_arn: str) -> dict[str, str]:
    try:
        response = aws.secretsmanager.get_secret_value(SecretId=secret_arn)
    except ClientError as error:
        if error_code(error) == "ResourceNotFoundException":
            return {}
        raise
    text = response.get("SecretString")
    if not text:
        return {}
    try:
        document = json.loads(text)
    except ValueError as error:
        raise SyncError("the config secret holds something other than a JSON object") from error
    if not isinstance(document, dict):
        raise SyncError("the config secret holds something other than a JSON object")
    return {str(k): str(v) for k, v in document.items()}


def sync(
    aws: Clients,
    secret_arn: str,
    values: Mapping[str, str],
    *,
    prune: bool = False,
    dry_run: bool = False,
) -> SyncReport:
    """Merge the contract's vault values into the secret. Keys outside the contract are kept
    unless prune is set, so a rollback to the previous revision still resolves its bindings."""
    existing = current_document(aws, secret_arn)
    report = SyncReport()
    document: dict[str, str] = {}
    for key in sorted(existing):
        if key in values:
            continue
        if prune:
            report.removed.append(key)
        else:
            report.kept.append(key)
            document[key] = existing[key]
    for key in sorted(values):
        document[key] = values[key]
        if key not in existing:
            report.added.append(key)
        elif existing[key] != values[key]:
            report.updated.append(key)
        else:
            report.unchanged.append(key)
    changed = bool(report.added or report.updated or report.removed)
    if changed and not dry_run:
        aws.secretsmanager.put_secret_value(SecretId=secret_arn, SecretString=json.dumps(document))
        report.written = True
    return report
