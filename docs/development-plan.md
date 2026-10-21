# Development plan for ecs-contract

Reviewed on 2026-10-04 against local commit `7adec16`. Prioritize a small demonstration and a safe adoption path. The current code contains the checker, resolver, guard, synchronization, migration planning, and CDK construct. The next milestone should prove their boundaries together rather than add another backend.

## Current evidence and positioning

Lint, formatting, and type checks passed. All 131 tests passed after permitting the local Vault fixtures to bind a loopback server and redirecting the CDK package cache to a temporary writable location. Final validation is recorded below.

The README records one end-to-end development-service verification. This review made no AWS calls and does not broaden that claim to a fleet.

AWS now lists [drift detection for AWS::ECS::TaskDefinition](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/resource-import-supported-resources.html). The older assertion of missing native coverage should be removed. The useful distinction is the source contract: who owns each field, which source supplies it, and whether a declaration is safe before deployment. Native drift support alone does not enforce those rules.

The [Copilot end of support announcement](https://aws.amazon.com/blogs/containers/announcing-the-end-of-support-for-the-aws-copilot-cli/) creates a possible documentation context, not proof of an unoccupied market. Compare this design with the official ECS actions, ecspresso, Terraform's lifecycle controls, ECS Express Mode, and CDK constructs on explicit dimensions. Avoid claims that no alternative can solve the ownership problem.

## Work in priority order

| Priority | Proposed work | Acceptance criterion |
|---|---|---|
| P0 | Document and test the synthesis to deployment race | If the live application revision changes after `ServiceFromLiveRevision` synthesis, the infrastructure deployment procedure stops or re-synthesizes; an old template is never presented as race free |
| P1 | Define coordination for every writer | Application and infrastructure share a lock or agreed serialization procedure; two repository-specific concurrency groups are not assumed to coordinate each other |
| P1 | Publish a bounded offline ownership demo when separately authorized | A synthetic setting is visibly reset by a conflicting writer and preserved by the contract path; a bad declaration fails without credentials |
| P1 | Demonstrate rotation and rollback behavior | Change a synthetic secret, force a fresh task, and verify the running task uses the intended version; test rollback with retained keys and explicit `--prune` behavior |
| P1 | Make adoption diagnosable | Provide a schema and compatibility table, least-privilege role fixtures, and a safe structured summary that emits names and verdicts only |
| P2 | Test a second independent use case | Cover sidecars, more than one environment, cross-repository coordination, and a failed deployment without modifying infrastructure-owned fields |
| P2 | Improve supply chain reproducibility | Bound dependency majors where appropriate and verify the built package with optional extras; preserve credential-free and network-free `check` |

`guard` already detects a revision that changed since render, and the supplied application workflow already serializes its own deployments. Extend those protections to the infrastructure path; do not describe them as absent. An additional read before deployment narrows a race but is not atomic without coordination.

## Demo notes

An earlier design discussion proposed `smallest-board`, a Go game on a 3 by 3 board, with separate service and infrastructure projects. It includes persistence, an optimal-play oracle, and pointer, parameter, and vault sources. It originally depended on the resolver and infrastructure stages; both are now implemented locally. The notes do not establish that the demo has been built.

Keep a minimal visual board and deterministic moves for the first version. Show the two writers through one harmless application setting. Prove the failure, the preservation rule, a stale plan rejection, and offline validation before adding full game rules, Postgres, or an oracle. These additions should follow a demonstrated need, because they create more maintenance than the deployment lesson requires.

Split the demonstration into a credential-free replay and an optional live synthetic AWS run. Keep secret values off the board, screenshots, logs, and artifacts. If a live stage is implemented later, give it cleanup and rollback assertions. No live stage or publication was performed here.

## Validation record

Final validation: lint, formatting, and strict types passed; all 131 tests passed. The first attempts encountered sandbox restrictions on a CDK cache directory and local sockets. A temporary cache and permission for loopback fixtures resolved those environment restrictions. No real AWS access was needed.

Before implementation commits, use the CI checks: ruff, formatting, strict mypy, pytest, package build, and execution of the built artifact. Preserve anonymization checks across the tree and full history. Validate against public AWS behavior and this repository, without copying private implementations or private planning material.

## Task tracking checkpoint

The [2026-10-07 portfolio checkpoint](https://github.com/tanya-ok/mcp-svid-auth/blob/main/docs/portfolio-checkpoint-2026-10-07.md) reconciles this plan with local beads tasks. Use `bd --sandbox ready` before starting work and update task status and validation evidence as work progresses. Public task snapshots are in `.beads/issues.jsonl`; local databases stay untracked. Remote synchronization is disabled.
