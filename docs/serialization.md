# Deployment serialization

A live-revision lookup at synthesis is a snapshot. If infrastructure synthesizes
revision A, the application deploys B, and infrastructure then deploys its saved
template, it can restore A. `ecsc guard --expect-task-definition` catches a change
before its check; it cannot make a later ECS update conditional. The existing
GitHub concurrency group covers cooperating jobs in that repository only.

## One cooperative writer boundary

`ecsc serialize` runs an explicit foreground command under a shared DynamoDB
mutex. Both application and infrastructure pipelines must use the same regional
table and exact long-form ECS service ARN. This canonical key includes account,
region, cluster and service; name aliases and old short-form ARNs are refused.
The table has a string partition key `pk`, no sort key, and no TTL. Provision it
separately. This project does not create AWS resources or change deployed roles.

```sh
# The script checks, renders/synthesizes, deploys and waits in the foreground.
ecsc serialize --lock-table "$DEPLOY_LOCK_TABLE" --service-arn "$SERVICE_ARN" \
  -- ./deploy-and-wait.sh

# A previously generated plan must name the exact revision captured in that plan.
ecsc serialize --lock-table "$DEPLOY_LOCK_TABLE" --service-arn "$SERVICE_ARN" \
  --expect-task-definition "$PLAN_BASE_REVISION" -- ./apply-saved-plan-and-wait.sh
```

Acquisition is a conditional insert, before reading the live revision. A busy or
unknown lock state refuses the command. A stale saved plan is refused without
executing it. The lock remains held through the command and ECS stability wait;
release checks the unique owner value. Synthesis/plan and apply should normally
run in the same command. A saved plan's expected revision must come from that
plan, not a newly read revision substituted by the caller. Other services in a
multi-service stack require their own locks in a fixed ordering; this wrapper is
for one service and does not infer every resource a command may change.

The command must wait for all its asynchronous writers, including CloudFormation,
CodeDeploy and background jobs. Returning zero after submitting a job violates
this contract: the additional ECS stability wait cannot establish whether an
unrelated CloudFormation operation has finished. This is a cooperative deployment
protocol, not an AWS permission boundary or an ECS compare-and-swap primitive.
Every principal capable of changing this service must follow it. Unwrapped jobs,
manual console updates and other pipelines can still race. The existing reusable
GitHub deploy workflow is not automatically wrapped; use a foreground deployment
script for this mode or keep every writer in the same verified CI concurrency
boundary. Do not claim serialization merely because one workflow has a lock.

## Failure and recovery

The mutex deliberately does not expire. ECS UpdateService has no fencing token
that could reject an abandoned writer after a lease expires. A nonzero command,
uncertain stability result, interruption, lost process or ambiguous AWS response
keeps the lock. This trades availability for avoiding an automatic second writer.
There is no force-unlock command and no time-based takeover. Failure before the
command starts can release this owner's lock safely.

An operator must verify that the original runner and its descendants have stopped,
all CloudFormation/CodeDeploy/ECS operations have reached a terminal state, and no
other writer can continue. Then remove only that service's lock with an
owner-conditional delete and regenerate stale plans. Never delete the table or
clear unrelated service locks. Do not configure automated lock cleanup. A release
failure is reported as failure even if the deployment itself completed.

The runner needs `dynamodb:PutItem` and `dynamodb:DeleteItem` on the chosen table,
`ecs:DescribeServices` for the target and its existing deploy permissions. Restrict
DynamoDB leading keys to the canonical target where practical. No static key is
required. The child inherits its operator's environment and owns its output;
`ecsc` never prints the lock owner or service/task-definition ARN in diagnostics.

## Evidence and limits

Synthetic moto and injected-client tests cover competing owners, refusal to
release another owner's lock, no expiry attribute, stale-plan refusal, lock
coverage through lookup/deploy/wait, crash retention, safe preflight release,
fixed diagnostics, canonical target matching and literal command arguments.
No live AWS write or actual concurrent CloudFormation deployment was executed.

This design follows [DynamoDB conditional writes](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutItem.html).
The lack of an ECS fencing parameter is based on the documented
[UpdateService request](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_UpdateService.html);
the cooperative protocol and its failure policy are project design decisions.

## Follow-up quorum, 2026-10-07

Run `20261007T160024574521Z` completed Claude research, Codex challenge, Claude
rebuttal and independent Moonshot Kimi review on this document and the serializer.
All supported F1: a nonzero exit diagnostic was being replaced by the generic
completion-unknown handler. The implementation now preserves separate fixed
execution-fault, nonzero-exit and stability-wait diagnostics; every uncertain
path still retains the lock. Underlying exception text remains suppressed
deliberately because AWS and child errors may contain identifiers. A nonzero
exit does not prove that no asynchronous AWS work began. The first research
attempt failed exact-quote validation; a retry passed without relaxing the gate.
Kimi used 7216 tokens. Model agreement is a proposal, not execution evidence.
