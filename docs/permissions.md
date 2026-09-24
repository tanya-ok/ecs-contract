# Permissions

Three roles take part. Scope every resource to one service: a deploy role shared across services
lets one typo reach a sibling's database.

## Audit role, read only

Used by `ecsc drift` and by a plan step on pull requests. It must not be able to deploy.

| Action | Resource | Why |
|---|---|---|
| `ecs:DescribeServices` | the service | find the live revision |
| `ecs:DescribeTaskDefinition` | `*` (the API does not support resource scoping) | read the live revision |
| `ssm:GetParameter` | the pointer parameters and shared parameters the contract names | resolve sources |
| `secretsmanager:DescribeSecret` | the service's config secret | bind vault-sourced keys |
| `secretsmanager:GetSecretValue` | secrets behind pointers | optional: confirm a `jsonKey` exists; without it `ecsc` warns and keeps the binding |

## Deploy role

Everything the audit role has, plus:

| Action | Resource | Why |
|---|---|---|
| `ecs:RegisterTaskDefinition` | `*` | register the rendered revision |
| `ecs:TagResource` | task definitions of the family | tags are carried from the live revision |
| `ecs:UpdateService` | the service | point it at the new revision |
| `iam:PassRole` | the task role and the execution role, with `iam:PassedToService` = `ecs-tasks.amazonaws.com` | registration passes them |
| `secretsmanager:GetSecretValue`, `secretsmanager:PutSecretValue` | the service's config secret only | `ecsc sync` merges vault values into it |

Trust it to the repository, the calling workflow, and the GitHub environment. On production,
also to the protected branch or tag.

## Execution role

The role the ECS agent uses to start the task. It resolves every binding the contract produces.

| Action | Resource |
|---|---|
| `secretsmanager:GetSecretValue` | secrets behind pointers, and the config secret |
| `ssm:GetParameters` | the parameters bound directly |
| `kms:Decrypt` | the keys encrypting those, when they are customer managed |
