# Permissions

Three roles take part, plus the infrastructure synthesis role, which needs only
`ecs:DescribeServices` on the service to read the live revision. Scope every resource to one service: a deploy role shared across services
lets one typo reach a sibling's database.

## Audit role, read only

Used by `ecsc drift` and by a plan step on pull requests. It must not be able to deploy.

| Action | Resource | Why |
|---|---|---|
| `ecs:DescribeServices` | the service | find the live revision |
| `ecs:DescribeTaskDefinition` | `*` (the API does not support resource scoping) | read the live revision |
| `ssm:GetParameter` | the pointer parameters and shared parameters the contract names | resolve sources |
| `secretsmanager:DescribeSecret` | the service's config secret | bind vault-sourced keys |

The audit role does not get `secretsmanager:GetSecretValue`. Without it, a `jsonKey` on a pointer
cannot be confirmed: `ecsc` warns that the key is unverified and keeps the binding (see
[secret probe outcomes](#secret-probe-outcomes)).

A role that a `pull_request` workflow can assume is reachable by anyone who can push a branch
to the repository, because that branch can edit the workflow. Roles assumable from
`pull_request`-triggered workflows must not trust unprotected refs for anything beyond the
read-only actions above. The deploy role, and any role that can read a secret value, never
trusts `pull_request` or an unprotected branch.

`drift-audit.yml` runs without a GitHub environment, so its token's `sub` names a ref. Trust the
audit role to the protected default branch and to the `job_workflow_ref` of `drift-audit.yml`.

## Deploy role

Everything the audit role has, plus:

| Action | Resource | Why |
|---|---|---|
| `ecs:RegisterTaskDefinition` | `*` | register the rendered revision |
| `ecs:TagResource` | task definitions of the family | tags are carried from the live revision |
| `ecs:UpdateService` | the service | point it at the new revision |
| `iam:PassRole` | the task role and the execution role, with `iam:PassedToService` = `ecs-tasks.amazonaws.com` | registration passes them |
| `secretsmanager:GetSecretValue`, `secretsmanager:PutSecretValue` | the service's config secret only | `ecsc sync` merges vault values into it |
| `secretsmanager:GetSecretValue` | secrets behind pointers | optional: confirm a `jsonKey` exists; explicit access denial warns and keeps the binding; service, transport and decryption failures stop rendering |

Trust it to the repository, the calling workflow, and the GitHub environment. On production,
the environment's protection rules restrict which branches or tags may deploy. An example trust
policy, with placeholders in angle brackets:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Federated": "<github-oidc-provider-arn>" },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:<owner>/<repository>:environment:production",
          "token.actions.githubusercontent.com:job_workflow_ref": "tanya-ok/ecs-contract/.github/workflows/deploy.yml@<full-commit-sha>"
        }
      }
    }
  ]
}
```

- `<github-oidc-provider-arn>` is the IAM OIDC provider for `token.actions.githubusercontent.com`.
- `sub` is environment scoped: only jobs that run in the `production` GitHub environment match.
- `job_workflow_ref` carries the ref from the caller's `uses:` line, so the role only works with
  the reusable workflow pinned to that commit. Update it together with the pin.
- IAM evaluates `job_workflow_ref` as a condition key for GitHub tokens. Names can be reused
  after a rename, so consider adding `repository_id` and `repository_owner_id` as well.

## Execution role

The role the ECS agent uses to start the task. It resolves every binding the contract produces.

| Action | Resource |
|---|---|
| `secretsmanager:GetSecretValue` | secrets behind pointers, and the config secret |
| `ssm:GetParameters` | the parameters bound directly |
| `kms:Decrypt` | the keys encrypting those, when they are customer managed |

## Secret probe outcomes

Only a successfully decoded JSON object can prove that a key is absent. Missing
secrets and invalid/non-object JSON have distinct blocking diagnostics. Throttling,
decryption errors, other service errors and transport failures are also blocking;
no new task-definition output is written by that invocation. Existing output files
are not deleted, so callers must honor the nonzero exit status.

An explicit AccessDenied response retains the existing least-privilege mode:
warn that the JSON key is unverified and retain the reference. This does not
prove secret availability or value correctness; ECS task startup still needs its
own execution-role permissions. Error messages and secret contents are never
used in the diagnostic. Tests exercise render with mocked AWS, not live services.
