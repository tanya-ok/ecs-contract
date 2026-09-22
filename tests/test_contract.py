"""One test per failure the specification names, plus the structural ones."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecs_contract import ContractFileError, check
from tests.conftest import (
    ACCOUNT_ID,
    ARN_PREFIX,
    EXAMPLE,
    FIXTURES,
    Contract,
    document,
    messages,
    only,
)

POINTER = {"pointer": "/orderbook/development/infra/db-secret-arn", "jsonKey": "password"}


def test_example_holds() -> None:
    report = check(EXAMPLE / "parameters.json", EXAMPLE / "secrets.json")
    assert report.ok, messages(report)
    assert {env: (c.parameters, c.secrets) for env, c in report.counts.items()} == {
        "development": (4, 3),
        "production": (4, 3),
    }


def test_key_in_both_files(contract: Contract) -> None:
    report = contract({"CACHE_URL": "redis://x"}, {"CACHE_URL": {"parameter": "/c/url"}})
    assert "declared in both files" in only(report)
    assert report.problems[0].key == "CACHE_URL"


def test_secret_with_no_source(contract: Contract) -> None:
    assert "names no source" in only(contract(secrets={"DB_PASSWORD": {}}))


def test_secret_with_two_sources(contract: Contract) -> None:
    source = {"pointer": "/a/b-arn", "vault": "a/b"}
    assert "names 2 sources (pointer, vault)" in only(contract(secrets={"T": source}))


def test_json_key_without_pointer(contract: Contract) -> None:
    source = {"parameter": "/shared/ca.pem", "jsonKey": "pem"}
    assert "jsonKey is only valid" in only(contract(secrets={"TLS_CA": source}))


@pytest.mark.parametrize("field", ["pointer", "parameter", "vault"])
def test_literal_arn_in_secret_source(contract: Contract, field: str) -> None:
    value = f"{ARN_PREFIX}secretsmanager:eu-west-1:{ACCOUNT_ID}:secret:db"
    assert "literal ARN" in only(contract(secrets={"DB_PASSWORD": {field: value}}))


def test_literal_arn_in_partition_variant(contract: Contract) -> None:
    value = "arn" + ":aws-us-gov:ssm:us-gov-west-1:" + ACCOUNT_ID + ":parameter/x"
    assert "literal ARN" in only(contract({"UPSTREAM": value}))


def test_literal_arn_in_parameter(contract: Contract) -> None:
    value = f"{ARN_PREFIX}sqs:eu-west-1:{ACCOUNT_ID}:orders"
    assert "value is a literal ARN" in only(contract({"QUEUE": value}))


def test_account_id_in_parameter(contract: Contract) -> None:
    assert "12-digit" in only(contract({"UPSTREAM_ACCOUNT": ACCOUNT_ID}))


def test_thirteen_digits_are_not_an_account_id(contract: Contract) -> None:
    assert contract({"BIG": ACCOUNT_ID + "4"}).ok


@pytest.mark.parametrize("name", ["AWS_ACCESS_KEY_ID", "AWS_PROFILE", "ECS_CONTAINER_METADATA_URI"])
def test_reserved_name(contract: Contract, name: str) -> None:
    assert "reserved name" in only(contract({name: "x"}))


def test_reserved_name_in_secrets(contract: Contract) -> None:
    report = contract(secrets={"AWS_SECRET_ACCESS_KEY": POINTER})
    assert "reserved name" in only(report)


def test_extra_reserved_name(contract: Contract) -> None:
    assert contract({"IMAGE_TAG": "x"}).ok
    assert "reserved name" in only(contract({"IMAGE_TAG": "x"}, reserved=["IMAGE_TAG"]))


@pytest.mark.parametrize("name", ["DB_PASSWORD", "GITHUB_TOKEN", "STRIPE_API_KEY", "SECRET"])
def test_secret_shaped_parameter(contract: Contract, name: str) -> None:
    assert "looks like a secret" in only(contract({name: "x"}))


@pytest.mark.parametrize("name", ["SORT_KEY", "TOKENIZER_MODE", "PASSWORD_MIN_LENGTH"])
def test_ordinary_names_are_not_secret_shaped(contract: Contract, name: str) -> None:
    assert contract({name: "x"}).ok


def test_allow_secret_shaped(contract: Contract) -> None:
    assert contract({"CSRF_TOKEN": "header"}, allow_secret_shaped=["CSRF_TOKEN"]).ok


def test_environment_missing_from_one_file(contract: Contract) -> None:
    parameters = document("parameters", {"development": {}})
    secrets = document("secrets", {"development": {}, "production": {}})
    report = contract(parameters, secrets)
    problem = report.problems[0]
    assert (problem.environment, problem.message) == (
        "production",
        "environment not declared in this file",
    )
    assert problem.file.endswith("parameters.json")


def test_requested_environment_missing_from_both(contract: Contract) -> None:
    report = contract(environments=["staging"])
    assert [p.environment for p in report.problems] == ["staging", "staging"]


def test_duplicate_key(contract: Contract) -> None:
    raw = '{"environments": {"development": {"parameters": {"PORT": "1", "PORT": "2"}}}}'
    report = contract(raw)
    assert "declared twice" in only(report)
    assert report.problems[0].key == "PORT"


def test_duplicate_environment(contract: Contract) -> None:
    raw = '{"environments": {"development": {"secrets": {}}, "development": {"secrets": {}}}}'
    assert "environment declared twice" in only(contract(secrets=raw))


def test_duplicate_field_in_source(contract: Contract) -> None:
    raw = '{"environments": {"development": {"secrets": {"T": {"vault": "a/b", "vault": "a/c"}}}}}'
    assert "field 'vault' declared twice" in only(contract(secrets=raw))


def test_pointer_must_be_absolute(contract: Contract) -> None:
    report = contract(secrets={"DB_PASSWORD": {"pointer": "orderbook/infra/db-arn"}})
    assert "not an absolute parameter path" in only(report)


def test_parameter_name_charset(contract: Contract) -> None:
    report = contract(secrets={"CA": {"parameter": "/shared/certs bundle"}})
    assert "not a valid parameter name" in only(report)


def test_unknown_source_field(contract: Contract) -> None:
    report = contract(secrets={"SMTP_PASSWORD": {"pionter": "/a/b-arn"}})
    assert len(report.problems) == 2
    assert "unknown field 'pionter'" in messages(report)[0]
    assert "names no source" in messages(report)[1]


def test_empty_source_value(contract: Contract) -> None:
    assert "vault must be a non-empty string" in only(contract(secrets={"T": {"vault": " "}}))


def test_source_not_an_object(contract: Contract) -> None:
    assert "must be an object naming" in only(contract(secrets={"T": "/a/b"}))


def test_parameter_value_must_be_string(contract: Contract) -> None:
    assert "value must be a string, got number" in only(contract({"PORT": 8080}))


def test_invalid_variable_name(contract: Contract) -> None:
    assert "not a valid environment variable name" in only(contract({"LOG-LEVEL": "x"}))


def test_invalid_json_names_line(contract: Contract) -> None:
    report = contract('{"environments": {\n  "development": }')
    assert "invalid JSON at line 2" in only(report)


def test_missing_environments(contract: Contract) -> None:
    report = contract('{"$schema": "x"}')
    assert "missing the 'environments' object" in only(report)


def test_unknown_top_level_field(contract: Contract) -> None:
    report = contract('{"environments": {"development": {"parameters": {}}}, "extra": 1}')
    assert "unknown top-level field 'extra'" in only(report)


def test_no_environments(contract: Contract) -> None:
    report = contract('{"environments": {}}', '{"environments": {}}')
    assert "no environments declared" in only(report)


def test_all_problems_reported_not_only_first() -> None:
    report = check(FIXTURES / "broken" / "parameters.json", FIXTURES / "broken" / "secrets.json")
    found = "\n".join(messages(report))
    for expected in (
        "declared in both files",
        "names no source",
        "names 2 sources",
        "jsonKey is only valid",
        "reserved name",
        "looks like a secret",
        "environment not declared in this file",
        "declared twice",
        "not an absolute parameter path",
        "unknown field 'pionter'",
        "value must be a string",
    ):
        assert expected in found, expected
    assert len(report.problems) == 12


def test_unreadable_file_is_misuse(tmp_path: Path) -> None:
    with pytest.raises(ContractFileError, match="cannot read"):
        check(tmp_path / "missing.json", tmp_path / "missing.json")
