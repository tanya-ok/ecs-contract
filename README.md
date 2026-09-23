# ecs-contract

**Who owns what in an ECS task definition.**

## The outage you have already had

Your ECS service gets its configuration from two places. The infrastructure code describes a task
definition, because that is where the roles, the log group and the service live. The application
pipeline registers task definitions too, because the image tag and the configuration change on
every release.

Both write a complete revision. Whoever ran last wins. An infrastructure deploy on a quiet Tuesday
quietly reverts sixteen environment variables the application set last week. Nothing alerts. The
only symptom is behaviour that used to be configured and is not any more.

Tools exist for the mechanics of registering a revision and waiting for it. None of them says who
owns which field. That missing rule is what this project provides.

## The rule

> Infrastructure owns everything around the container. The application owns what goes inside it.

| Infrastructure owns | The application owns |
|---|---|
| cluster, service, load balancer, target group | the image tag |
| task role and execution role | the values in `environment` |
| log group, autoscaling, alarms | the values in `secrets` |
| secret and parameter resources, and their names, never their values | the container's own cpu and memory |
| pointer parameters that publish ARNs to the application | nothing else |

Two consequences carry the whole design:

1. Infrastructure creates secret resources without values. The value belongs to the application.
2. Infrastructure stops describing a task definition. It points the service at the revision that is
   already running, unchanged, so an infrastructure deploy can never revert application content.

Read [SPEC.md](SPEC.md) for the full contract.

## What the application commits

Two files. Splitting them is deliberate: the secrets file is the one that deserves a careful review.

`ecs/parameters.json`

```json
{
  "environments": {
    "production": {
      "parameters": { "LOG_LEVEL": "info", "PORT": "8080" }
    }
  }
}
```

`ecs/secrets.json`. Every key names exactly one source. There is no default source.

```json
{
  "environments": {
    "production": {
      "secrets": {
        "DB_PASSWORD": { "pointer": "/orderbook/production/infra/db-secret-arn", "jsonKey": "password" },
        "TLS_CA_BUNDLE": { "parameter": "/shared/certs/bundle.pem" },
        "SETTLEMENT_API_TOKEN": { "vault": "orderbook-production/settlement-api/token" }
      }
    }
  }
}
```

A `pointer` is a parameter whose value is the complete ARN of a secret that another stack owns.
The application repository therefore commits no ARNs and no account ids, and the same file shape
works in every account.

## The check

`ecsc check` runs with no credentials and no network, in well under a second. It fails the pull
request instead of the deploy.

```bash
uvx --from ecs-contract ecsc check --parameters ecs/parameters.json --secrets ecs/secrets.json
```

Every problem is one line naming the file, the environment and the key. All problems are listed,
not only the first. Values are never printed.

```text
ecs/parameters.json: production: SOME_API_KEY: looks like a secret but is declared as a parameter; move it to the secrets file, or allow it explicitly with --allow-secret-shaped
ecs/secrets.json: production: DB_PASSWORD: names no source; expected exactly one of pointer, parameter, vault (no default)
ecsc: 2 problems
```

What it refuses:

- a key declared as both a parameter and a secret
- a secret naming no source, or more than one
- `jsonKey` on anything but a pointer
- a literal ARN, or a 12-digit number shaped like an account id, anywhere in either file
- a reserved name such as `AWS_ACCESS_KEY_ID`, plus any names your deploy sets itself (`--reserved`)
- a secret-shaped name such as `*_PASSWORD` or `*_TOKEN` declared as a plain parameter
- an environment present in one file and missing from the other
- a key declared twice in one object, which JSON parsers otherwise resolve silently
- a pointer that is not an absolute parameter path

Exit codes: `0` the contract holds, `1` it does not, `2` a file cannot be read.

## In GitHub Actions

As a step:

```yaml
- uses: tanya-ok/ecs-contract@v0
  with:
    parameters-file: ecs/parameters.json
    secrets-file: ecs/secrets.json
    reserved: APP_ENV IMAGE_TAG
```

Or as a reusable workflow:

```yaml
jobs:
  contract:
    uses: tanya-ok/ecs-contract/.github/workflows/contract-check.yml@v0
    with:
      parameters-file: ecs/parameters.json
      secrets-file: ecs/secrets.json
```

Problems appear as annotations on the pull request. The action runs the code at the ref you pin,
so pinning a commit SHA pins the checker.

The floating major tag is `v0` while the package is below 1.0, and becomes `v1` at the 1.0
release. Production callers pin a commit SHA.

## Deploying

`ecsc` does not register task definitions itself. It renders the next revision from the one the
service runs now, and the official `aws-actions/amazon-ecs-deploy-task-definition` registers it.

```bash
pip install 'ecs-contract[aws]'
ecsc render --parameters ecs/parameters.json --secrets ecs/secrets.json -e production \
  --cluster exchange --service orderbook --container app \
  --config-secret orderbook/production/config --image-tag 1.4.0 --out task-definition.json
```

| Command | Reads | Writes | Does |
|---|---|---|---|
| `ecsc render` | ECS, SSM, Secrets Manager metadata | a JSON file | copies the live revision, replaces `environment`, `secrets` and the image of one container |
| `ecsc guard` | the rendered file, optionally ECS | nothing | refuses a secret-shaped name in `environment`, or a service that moved since render |
| `ecsc sync` | a vault | the service's config secret | merges vault-sourced values in; keys outside the contract are kept for rollbacks unless `--prune` |
| `ecsc drift` | as render | nothing | exits 1 when a deploy would change anything, naming each key, never a value |

Every command prints names and verdicts only. Vault values are masked in the runner before
anything else happens.

As a reusable workflow, in the spec's order: check, render, guard, sync, register and wait.

```yaml
jobs:
  deploy:
    uses: tanya-ok/ecs-contract/.github/workflows/deploy.yml@v0
    permissions:
      contents: read
      id-token: write
    with:
      parameters-file: ecs/parameters.json
      secrets-file: ecs/secrets.json
      environment: production
      github-environment: production
      cluster: exchange
      service: orderbook
      container: app
      image-tag: ${{ github.sha }}
      config-secret: orderbook/production/config
      vault-backend: 1password
      aws-region: eu-west-1
      role-to-assume: ${{ vars.DEPLOY_ROLE }}
    secrets:
      op-service-account-token: ${{ secrets.OP_SERVICE_ACCOUNT_TOKEN }}
```

`drift-audit.yml` runs the audit on a schedule or on demand with a read-only role. The roles
each step needs are listed in [docs/permissions.md](docs/permissions.md).

Vault backends: `1password` reads through the `op` CLI, `hashicorp` reads a KV version 2 field
given as `<mount>/<path>#<field>` over HTTPS.

Editors can validate both files against the published JSON schemas in
[`src/ecs_contract/schema/`](src/ecs_contract/schema/) through a `$schema` key.

## Status

| Stage | Contents | State |
|---|---|---|
| 1. The contract | specification, schemas, `ecsc check`, action, reusable workflow | 0.1 |
| 2. The resolver | render from the live revision, pluggable secret sources, drift audit, deploy guards | 0.2 |
| 3. The infrastructure side | a construct that points a service at the live revision, executable migration runbook | planned |

The pattern was designed and then proven end to end once, on one service in one development
environment. It has not yet run across a fleet. Read it as carefully designed and once verified,
not as battle tested.

Further reading:

- [SPEC.md](SPEC.md), the contract
- [docs/traps.md](docs/traps.md), failure modes found by hitting them
- [docs/migration.md](docs/migration.md), moving a service that already has two writers
- [docs/permissions.md](docs/permissions.md), the roles each step needs
- [docs/prior-art.md](docs/prior-art.md), what exists and where this fits

## Principles

- Values are never printed, logged or written to an artifact. Names are.
- A missing source is an error. A default source would recreate the quiet failure this project
  exists to remove.
- No telemetry, ever. A tool that reads secret references does not phone home.
- One obvious way. A contract with options is a suggestion.

## License

Apache License 2.0. See [LICENSE](LICENSE).
