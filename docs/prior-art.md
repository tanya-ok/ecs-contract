# Prior art

Surveyed September 2026. What exists, and the part each one leaves open.

| Project | Covers | Leaves open |
|---|---|---|
| `aws-actions/amazon-ecs-render-task-definition` and `amazon-ecs-deploy-task-definition` | inserting an image and literal secret ARNs into a task definition file; registering and waiting | where values come from, who owns which field; ARNs are committed in the application repository |
| `fabfuel/ecs-deploy` (Python) | cloning the live task definition, setting environment and secrets from flags or files | no contract, no drift audit, no indirection for ARNs |
| `kayac/ecspresso` (Go) | task and service definitions as code, `diff`, `verify`, `render`, lookups from parameters and state files | assumes it is the single writer of the task definition and the service |
| `Selleo/amazon-ecs-render-task-definition-secrets` | expanding parameter paths into `secrets` before rendering | no validation, no ownership |
| `bugcrowd/ecs-task-definition-validator` | JSON Schema validation of a finished task definition (archived) | validates the output, never the source of the values |
| `terraform-aws-modules/terraform-aws-ecs` | `ignore_task_definition_changes` so the pipeline can own revisions | the two-writer conflict is worked around per module; issues on the topic recur |
| External Secrets Operator | declarative sync from external stores into Kubernetes secrets | Kubernetes only; nothing equivalent for ECS |
| AWS Copilot | a manifest with `secrets:` referencing parameters and secrets | reached end of support in June 2026 |
| CloudFormation drift detection | many resource types | task definitions are not covered, so drift has to be audited from outside |

## Where this fits

The mechanics are solved several times over. The rule that says which system writes which field,
and a check that enforces it before a deploy, are not. `ecs-contract` is deliberately small at
the mechanics layer and composes with the official actions instead of replacing them: its
resolver will produce a task definition file that `amazon-ecs-deploy-task-definition` registers.
