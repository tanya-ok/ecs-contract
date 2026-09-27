"""Live smoke for ecs-contract Stage 2 on a personal AWS account. Synthetic names only.

Run from the repository root against an account you own, never a shared or company one:

    AWS_PROFILE=<personal> uv run python scripts/smoke.py [--keep]

Needs docker for a local HashiCorp dev vault. Creates resources named ecsc-smoke-<run> in
eu-west-1 and deletes them at the end. With --keep they stay; remove them later with
ECSC_SMOKE_NAME=ecsc-smoke-<run> and --teardown. Cost is a few cents. Each run gets its own
names: deleted secrets and log groups keep their names busy, or their old events, for a while.
Values are generated here, never printed, and asserted absent from every ecsc output.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

import boto3

REGION = "eu-west-1"
NAME = os.environ.get("ECSC_SMOKE_NAME") or f"ecsc-smoke-{secrets.token_hex(3)}"
ENV = "development"
CLUSTER = NAME
SERVICE = "app"
CONTAINER = "app"
IMAGE = "public.ecr.aws/docker/library/busybox"
VAULT_PORT = 18200
VAULT_IMAGE = "hashicorp/vault:1.18"
VAULT_CONTAINER = f"{NAME}-vault"
TAGS = [{"Key": "purpose", "Value": NAME}]

DB_SECRET = f"{NAME}/{ENV}/db"
CONFIG_SECRET = f"{NAME}/{ENV}/config"
POINTER = f"/{NAME}/{ENV}/infra/db-secret-arn"
BUNDLE = f"/{NAME}/shared/bundle"
ROLE = f"{NAME}-execution"
LOG_GROUP = f"/{NAME}/app"

VARS = [
    "LOG_LEVEL",
    "PORT",
    "MATCHING_MODE",
    "DB_PASSWORD",
    "TLS_CA_BUNDLE",
    "SETTLEMENT_API_TOKEN",
]
PROBE = (
    "for v in " + " ".join(VARS) + '; do eval "x=\\${$v}"; '
    'if [ -n "$x" ]; then echo "present: $v"; else echo "missing: $v"; fi; done; sleep 3600'
)

session = boto3.session.Session(region_name=REGION)
ecs = session.client("ecs")
sm = session.client("secretsmanager")
ssm = session.client("ssm")
iam = session.client("iam")
logs = session.client("logs")
ec2 = session.client("ec2")

values = {
    "db": secrets.token_urlsafe(24),
    "vault_token": secrets.token_urlsafe(24),
    "settlement": secrets.token_urlsafe(24),
    "stale": secrets.token_urlsafe(24),
}
results: list[tuple[str, bool]] = []
work = Path(tempfile.mkdtemp(prefix=f"{NAME}-"))


def step(label: str, ok: bool) -> None:
    results.append((label, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}", flush=True)


def leaked(text: str) -> list[str]:
    return [k for k, v in values.items() if v in text]


def ecsc(*args: str, expect: int) -> str:
    env = {
        **os.environ,
        "AWS_REGION": REGION,
        "VAULT_ADDR": f"http://127.0.0.1:{VAULT_PORT}",
        "VAULT_TOKEN": values["vault_token"],
        "GITHUB_OUTPUT": str(work / "github-output"),
    }
    env.pop("GITHUB_ACTIONS", None)
    done = subprocess.run(["ecsc", *args], capture_output=True, text=True, env=env, check=False)
    out = done.stdout + done.stderr
    print(f"  $ ecsc {args[0]} ... -> exit {done.returncode}")
    for line in out.splitlines():
        print(f"    {line}")
    hits = leaked(out)
    step(f"ecsc {args[0]}: exit {expect} (got {done.returncode})", done.returncode == expect)
    step(f"ecsc {args[0]}: no value in output", not hits)
    step(f"ecsc {args[0]}: no traceback", "Traceback" not in out)
    return out


def contract_args() -> list[str]:
    return ["--parameters", str(work / "parameters.json"), "--secrets", str(work / "secrets.json")]


def service_args() -> list[str]:
    return ["-e", ENV, "--cluster", CLUSTER, "--service", SERVICE, "--container", CONTAINER]


def write_contract(log_level: str) -> None:
    (work / "parameters.json").write_text(
        json.dumps(
            {
                "environments": {
                    ENV: {
                        "parameters": {
                            "LOG_LEVEL": log_level,
                            "PORT": "8080",
                            "MATCHING_MODE": "price-time",
                        }
                    }
                }
            }
        )
    )
    (work / "secrets.json").write_text(
        json.dumps(
            {
                "environments": {
                    ENV: {
                        "secrets": {
                            "DB_PASSWORD": {"pointer": POINTER, "jsonKey": "password"},
                            "TLS_CA_BUNDLE": {"parameter": BUNDLE},
                            "SETTLEMENT_API_TOKEN": {"vault": f"secret/{NAME}/settlement#token"},
                        }
                    }
                }
            }
        )
    )


def vault_up() -> None:
    subprocess.run(["docker", "rm", "-f", VAULT_CONTAINER], capture_output=True, check=False)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            VAULT_CONTAINER,
            "--cap-add=IPC_LOCK",
            "-e",
            f"VAULT_DEV_ROOT_TOKEN_ID={values['vault_token']}",
            "-p",
            f"127.0.0.1:{VAULT_PORT}:8200",
            VAULT_IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{VAULT_PORT}/v1/sys/health", timeout=2)
            break
        except OSError:
            time.sleep(1)
    body = json.dumps({"data": {"token": values["settlement"]}}).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{VAULT_PORT}/v1/secret/data/{NAME}/settlement",
        data=body,
        headers={"X-Vault-Token": values["vault_token"], "Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(request, timeout=5)
    print("vault: dev server up, synthetic field written")


def infra_up() -> dict[str, str]:
    """What the infrastructure side owns: resources and names, the config secret without a value."""
    logs.create_log_group(logGroupName=LOG_GROUP, tags={"purpose": NAME})
    logs.put_retention_policy(logGroupName=LOG_GROUP, retentionInDays=1)
    db = sm.create_secret(
        Name=DB_SECRET, SecretString=json.dumps({"password": values["db"]}), Tags=TAGS
    )["ARN"]
    config = sm.create_secret(Name=CONFIG_SECRET, Tags=TAGS)["ARN"]
    ssm.put_parameter(Name=POINTER, Value=db, Type="String", Tags=TAGS)
    ssm.put_parameter(Name=BUNDLE, Value="synthetic-bundle-not-secret", Type="String", Tags=TAGS)
    bundle_arn = ssm.get_parameter(Name=BUNDLE)["Parameter"]["ARN"]
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    role = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust), Tags=TAGS)
    log_arn = logs.describe_log_groups(logGroupNamePrefix=LOG_GROUP)["logGroups"][0]["arn"]
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": [db, config],
            },
            {"Effect": "Allow", "Action": "ssm:GetParameters", "Resource": bundle_arn},
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": log_arn,
            },
        ],
    }
    iam.put_role_policy(RoleName=ROLE, PolicyName="bindings", PolicyDocument=json.dumps(policy))
    time.sleep(12)
    ecs.create_cluster(clusterName=CLUSTER, tags=[{"key": "purpose", "value": NAME}])
    # Revision 1 as a previous writer left it: stale environment, fields outside the contract.
    first = ecs.register_task_definition(
        family=NAME,
        requiresCompatibilities=["FARGATE"],
        networkMode="awsvpc",
        cpu="256",
        memory="512",
        executionRoleArn=role["Role"]["Arn"],
        containerDefinitions=[
            {
                "name": CONTAINER,
                "image": f"{IMAGE}:1.36",
                "essential": True,
                "command": ["sh", "-c", PROBE],
                "environment": [{"name": "LOG_LEVEL", "value": "warn"}],
                "stopTimeout": 7,
                "dockerLabels": {"owner": "infrastructure"},
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": LOG_GROUP,
                        "awslogs-region": REGION,
                        "awslogs-stream-prefix": "app",
                    },
                },
            }
        ],
        tags=[{"key": "purpose", "value": NAME}],
    )["taskDefinition"]["taskDefinitionArn"]
    vpc = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"][0]
    subnets = ec2.describe_subnets(
        Filters=[
            {"Name": "vpc-id", "Values": [vpc["VpcId"]]},
            {"Name": "default-for-az", "Values": ["true"]},
        ]
    )["Subnets"]
    # A fresh account gets the ECS service-linked role on first use; it propagates with a delay.
    for attempt in range(12):
        try:
            ecs.create_service(
                cluster=CLUSTER,
                serviceName=SERVICE,
                taskDefinition=first,
                desiredCount=0,
                launchType="FARGATE",
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": [s["SubnetId"] for s in subnets],
                        "assignPublicIp": "ENABLED",
                    }
                },
            )
            break
        except ecs.exceptions.InvalidParameterException as error:
            if "service linked role" not in str(error) or attempt == 11:
                raise
            time.sleep(10)
    print("infra: log group, two secrets (config without value), two parameters, role,")
    print("       cluster, task definition revision 1, service at desired 0")
    return {"first": first}


def live_arn() -> str:
    return ecs.describe_services(cluster=CLUSTER, services=[SERVICE])["services"][0][
        "taskDefinition"
    ]


def config_document() -> dict[str, str] | None:
    try:
        return json.loads(sm.get_secret_value(SecretId=CONFIG_SECRET)["SecretString"])
    except sm.exceptions.ResourceNotFoundException:
        return None


def settled(condition: Callable[[], bool], seconds: int = 30) -> bool:
    """Poll until true. Secrets Manager reads and CloudWatch Logs are eventually consistent."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(2)
    return condition()


def github_output(key: str) -> str:
    lines = (work / "github-output").read_text().splitlines()
    return [line.split("=", 1)[1] for line in lines if line.startswith(f"{key}=")][-1]


def run() -> None:
    write_contract("info")
    vault_up()
    infra = infra_up()

    ecsc("check", *contract_args(), expect=0)
    ecsc("drift", *contract_args(), *service_args(), "--config-secret", CONFIG_SECRET, expect=1)

    sync = ["sync", *contract_args(), "-e", ENV, "--config-secret", CONFIG_SECRET]
    sync += ["--vault-backend", "hashicorp"]
    ecsc(*sync, "--dry-run", expect=0)
    step("sync --dry-run left the config secret without a value", config_document() is None)
    out = ecsc(*sync, expect=0)
    step("sync added SETTLEMENT_API_TOKEN", "SETTLEMENT_API_TOKEN: added" in out)
    wanted = {"SETTLEMENT_API_TOKEN": values["settlement"]}
    step("config secret holds the vault value", settled(lambda: config_document() == wanted))
    out = ecsc(*sync, expect=0)
    step("second sync wrote nothing", "already current" in out)
    sm.put_secret_value(
        SecretId=CONFIG_SECRET,
        SecretString=json.dumps(
            {"SETTLEMENT_API_TOKEN": values["settlement"], "RETIRED_KEY": values["stale"]}
        ),
    )
    settled(lambda: "RETIRED_KEY" in (config_document() or {}))
    out = ecsc(*sync, expect=0)
    step("sync kept a key outside the contract", "RETIRED_KEY: kept" in out)
    out = ecsc(*sync, "--prune", "--dry-run", expect=0)
    step("prune dry run names the key it would drop", "RETIRED_KEY: removed" in out)
    step("prune dry run wrote nothing", "RETIRED_KEY" in (config_document() or {}))

    rendered = work / "task-definition.json"
    render = ["render", *contract_args(), *service_args(), "--config-secret", CONFIG_SECRET]
    ecsc(*render, "--image-tag", "1.37", "--out", str(rendered), expect=0)
    text = rendered.read_text()
    step("rendered file holds no value", not leaked(text))
    td = json.loads(text)
    live = ecs.describe_task_definition(taskDefinition=infra["first"], include=["TAGS"])
    before = live["taskDefinition"]["containerDefinitions"][0]
    after = td["containerDefinitions"][0]
    untouched = {k: v for k, v in before.items() if k not in ("environment", "secrets", "image")}
    step(
        "render changed only environment, secrets and image",
        {k: v for k, v in after.items() if k not in ("environment", "secrets", "image")}
        == untouched,
    )
    step("render kept task definition tags", td.get("tags") == [{"key": "purpose", "value": NAME}])
    step("render set the new image tag", after["image"] == f"{IMAGE}:1.37")
    expected_live = github_output("live-task-definition")
    step("render reported the live revision it read", expected_live == infra["first"])

    ecsc(
        "guard",
        "--task-definition",
        str(rendered),
        "--container",
        CONTAINER,
        "--expect-task-definition",
        expected_live,
        "--cluster",
        CLUSTER,
        "--service",
        SERVICE,
        expect=0,
    )

    second = ecs.register_task_definition(**td)["taskDefinition"]["taskDefinitionArn"]
    ecs.update_service(cluster=CLUSTER, service=SERVICE, taskDefinition=second, desiredCount=1)
    print(f"deploy: {second.rsplit('/', 1)[-1]} registered, service at desired 1, waiting")
    ecs.get_waiter("services_stable").wait(
        cluster=CLUSTER, services=[SERVICE], WaiterConfig={"Delay": 15, "MaxAttempts": 40}
    )
    service = ecs.describe_services(cluster=CLUSTER, services=[SERVICE])["services"][0]
    step(
        "service stable with one running task on the rendered revision",
        service["runningCount"] == 1 and service["taskDefinition"] == second,
    )
    # Read only the stream of the task on the rendered revision: a log group recreated under the
    # same name can show a previous run's events, and ECS may briefly start the old revision.
    task_arns = ecs.list_tasks(cluster=CLUSTER, serviceName=SERVICE)["taskArns"]
    tasks = ecs.describe_tasks(cluster=CLUSTER, tasks=task_arns)["tasks"] if task_arns else []
    ours = [t["taskArn"].rsplit("/", 1)[-1] for t in tasks if t["taskDefinitionArn"] == second]
    others = len(tasks) - len(ours)
    if others:
        print(f"  note: {others} task(s) on another revision")
    stream = f"app/{CONTAINER}/{ours[0]}" if ours else ""
    lines: set[str] = set()

    def probed() -> bool:
        if not stream:
            return False
        try:
            events = logs.get_log_events(
                logGroupName=LOG_GROUP, logStreamName=stream, startFromHead=True
            )["events"]
        except logs.exceptions.ResourceNotFoundException:
            return False
        lines.update(e["message"].strip() for e in events)
        return all(f"present: {v}" in lines or f"missing: {v}" in lines for v in VARS)

    settled(probed, seconds=120)
    # Probe lines carry names only, so they are safe to print.
    print(f"  container probe: {sorted(m for m in lines if m.startswith(('present', 'missing')))}")
    step(
        "container saw every contract variable",
        all(f"present: {v}" in lines for v in VARS)
        and not any(m.startswith("missing") for m in lines),
    )
    step("container log holds no value", not leaked("\n".join(lines)))

    ecsc(
        "drift",
        *contract_args(),
        *service_args(),
        "--config-secret",
        CONFIG_SECRET,
        "--image-tag",
        "1.37",
        expect=0,
    )

    # Another writer registers a full revision: the two-writer problem drift exists to catch.
    foreign = dict(td)
    foreign["containerDefinitions"] = [dict(after)]
    foreign["containerDefinitions"][0]["environment"] = [
        {"name": "LOG_LEVEL", "value": "warn"},
        {"name": "PORT", "value": "8080"},
        {"name": "MATCHING_MODE", "value": "price-time"},
        {"name": "EXTRA_FLAG", "value": "on"},
    ]
    third = ecs.register_task_definition(**foreign)["taskDefinition"]["taskDefinitionArn"]
    ecs.update_service(cluster=CLUSTER, service=SERVICE, taskDefinition=third, desiredCount=0)
    out = ecsc(
        "drift", *contract_args(), *service_args(), "--config-secret", CONFIG_SECRET, expect=1
    )
    step(
        "drift names LOG_LEVEL and EXTRA_FLAG",
        "environment: LOG_LEVEL: value differs" in out
        and "environment: EXTRA_FLAG: only in the live revision" in out,
    )
    step(
        "drift printed neither foreign value",
        "warn" not in out.replace("warning", "") and "=on" not in out,
    )

    ecsc(
        "guard",
        "--task-definition",
        str(rendered),
        "--container",
        CONTAINER,
        "--expect-task-definition",
        expected_live,
        "--cluster",
        CLUSTER,
        "--service",
        SERVICE,
        expect=1,
    )

    shaped = json.loads(text)
    shaped["containerDefinitions"][0]["environment"].append({"name": "API_TOKEN", "value": "x"})
    shaped_path = work / "shaped.json"
    shaped_path.write_text(json.dumps(shaped))
    ecsc("guard", "--task-definition", str(shaped_path), "--container", CONTAINER, expect=1)

    out = ecsc(
        "render",
        *contract_args(),
        *service_args(),
        "--config-secret",
        f"{NAME}/missing",
        "--dry-run",
        expect=1,
    )
    step(
        "missing config secret is refused by key, without its name",
        "SETTLEMENT_API_TOKEN: the config secret named by --config-secret cannot be found" in out
        and f"{NAME}/missing" not in out,
    )


def teardown() -> None:
    print("teardown")
    quiet = (Exception,)
    try:
        ecs.update_service(cluster=CLUSTER, service=SERVICE, desiredCount=0)
        ecs.delete_service(cluster=CLUSTER, service=SERVICE, force=True)
        ecs.get_waiter("services_inactive").wait(cluster=CLUSTER, services=[SERVICE])
    except quiet as e:
        print(f"  service: {type(e).__name__}")
    try:
        arns = ecs.list_task_definitions(familyPrefix=NAME)["taskDefinitionArns"]
        for arn in arns:
            ecs.deregister_task_definition(taskDefinition=arn)
        if arns:
            ecs.delete_task_definitions(taskDefinitions=arns)
    except quiet as e:
        print(f"  task definitions: {type(e).__name__}")
    for label, call in (
        ("cluster", lambda: ecs.delete_cluster(cluster=CLUSTER)),
        (
            "db secret",
            lambda: sm.delete_secret(SecretId=DB_SECRET, ForceDeleteWithoutRecovery=True),
        ),
        (
            "config secret",
            lambda: sm.delete_secret(SecretId=CONFIG_SECRET, ForceDeleteWithoutRecovery=True),
        ),
        ("parameters", lambda: ssm.delete_parameters(Names=[POINTER, BUNDLE])),
        ("role policy", lambda: iam.delete_role_policy(RoleName=ROLE, PolicyName="bindings")),
        ("role", lambda: iam.delete_role(RoleName=ROLE)),
        ("log group", lambda: logs.delete_log_group(logGroupName=LOG_GROUP)),
    ):
        try:
            call()
        except quiet as e:
            print(f"  {label}: {type(e).__name__}")
    subprocess.run(["docker", "rm", "-f", VAULT_CONTAINER], capture_output=True, check=False)
    print("teardown: done")


if __name__ == "__main__":
    if "--teardown" in sys.argv:
        teardown()
        sys.exit(0)
    print(f"run: {NAME}")
    try:
        run()
    except Exception as error:
        step(f"smoke aborted: {type(error).__name__}: {str(error)[:200]}", False)
    finally:
        if "--keep" not in sys.argv:
            teardown()
    failed = [label for label, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    for label in failed:
        print(f"  FAIL {label}")
    sys.exit(1 if failed else 0)
