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
- uses: tanya-ok/ecs-contract@v1
  with:
    parameters-file: ecs/parameters.json
    secrets-file: ecs/secrets.json
    reserved: APP_ENV IMAGE_TAG
```

Or as a reusable workflow:

```yaml
jobs:
  contract:
    uses: tanya-ok/ecs-contract/.github/workflows/contract-check.yml@v1
    with:
      parameters-file: ecs/parameters.json
      secrets-file: ecs/secrets.json
```

Problems appear as annotations on the pull request. The action runs the code at the ref you pin,
so pinning a commit SHA pins the checker.

Editors can validate both files against the published JSON schemas in
[`src/ecs_contract/schema/`](src/ecs_contract/schema/) through a `$schema` key.

## Status

| Stage | Contents | State |
|---|---|---|
| 1. The contract | specification, schemas, `ecsc check`, action, reusable workflow | this release |
| 2. The resolver | render from the live revision, pluggable secret sources, drift audit, deploy guards | planned |
| 3. The infrastructure side | a construct that points a service at the live revision, executable migration runbook | planned |

The pattern was designed and then proven end to end once, on one service in one development
environment. It has not yet run across a fleet. Read it as carefully designed and once verified,
not as battle tested.

Further reading:

- [SPEC.md](SPEC.md), the contract
- [docs/traps.md](docs/traps.md), failure modes found by hitting them
- [docs/migration.md](docs/migration.md), moving a service that already has two writers
- [docs/prior-art.md](docs/prior-art.md), what exists and where this fits

## Principles

- Values are never printed, logged or written to an artifact. Names are.
- A missing source is an error. A default source would recreate the quiet failure this project
  exists to remove.
- No telemetry, ever. A tool that reads secret references does not phone home.
- One obvious way. A contract with options is a suggestion.

## License

Apache License 2.0. See [LICENSE](LICENSE).
