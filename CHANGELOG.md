# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html). The floating major tag is `v0` until
the 1.0 release.

## Unreleased

Everything below this heading and above 0.1.0 is unreleased. The package version in
`pyproject.toml` is 0.3.0, but no 0.3.0 tag or PyPI release exists yet: PyPI and the `v0` tag
still carry 0.1.0.

### Security

- The HashiCorp Vault backend no longer follows redirects. Any 3xx answer is an error, so
  `X-Vault-Token` is never sent to a redirect target.
- Vault references with an empty, `.` or `..` path segment are refused before any request.
- Step outputs use the multiline `name<<DELIMITER` form with a random delimiter, so a value
  cannot add or end an output. `ecsc drift` escapes its GitHub annotations.
- The reusable deploy and drift audit workflows install `ecsc` from `uv.lock` instead of
  resolving dependencies afresh, and every `setup-uv` step pins the uv version.
- The release workflow runs the full CI suite before building and publishing.
- Documentation tooling installs from a hashed lock, `requirements-docs.lock`.

### Fixed

- `ecsc sync` refuses a config secret holding non-string JSON values, naming the key and never
  the value, instead of rewriting them as Python reprs.
- `python -m ecs_contract.cli` defined `_serialize` after the main guard and failed.
- A local Vault test no longer binds the real forwarding port.

### Changed

- The audit role in `docs/permissions.md` no longer reads secret values. The docs add an OIDC
  trust policy example and guidance for pinning `ecs-contract-ref` and protecting `v*` tags.
- Light and dark documentation themes.

## 0.3.0 - Unreleased

Stage 2, the resolver, and Stage 3, the infrastructure side. 0.2.0 was prepared but never
released; its scope ships here. The resolver was verified end to end on a synthetic Fargate
service in a personal account; see [the demo guide](docs/demo.md).

### Added

- `ServiceFromLiveRevision` in the `cdk` extra, which sets an ECS service to the revision it runs
  now, read with `DescribeServices` at every synthesis. Any lookup failure stops synthesis. The
  template holds no task definition and no desired count.
- `ecsc migrate --plan`, which prints the migration runbook filled in from the live service, by
  name only.
- `docs/infrastructure.md`, the construct and its Terraform equivalent.

- `ecsc render`, which copies the revision the service runs now and replaces only `environment`,
  `secrets` and the image of one container. Tags and every other field are kept.
- `ecsc drift`, which exits 1 when a deploy would change anything and names each key, never a
  value.
- `ecsc guard`, which refuses a secret-shaped name in `environment` and a service that moved since
  render.
- `ecsc sync`, which merges vault-sourced values into the service's config secret. Keys outside
  the contract are kept for rollbacks unless `--prune`.
- Secret sources `pointer`, `parameter` and `vault`, with 1Password and HashiCorp Vault KV v2
  backends.
- Reusable `deploy.yml` and `drift-audit.yml` workflows, and `docs/permissions.md`.
- The `aws` extra, which installs boto3 for the commands that read AWS.
- A failed AWS call is reported as one line naming the operation and the error code, exit 2,
  never a traceback or the AWS message.
- `scripts/smoke.py`, a live smoke of every command against a synthetic Fargate service.
- `CHANGELOG.md`, `CODEOWNERS` and a security policy.

### Changed

- Callers are pointed at the `v0` tag, which is the major tag below 1.0.

## 0.1.0 - 2026-09-22

Stage 1, the contract.

### Added

- `SPEC.md`, the ownership rule, the two-file model, three secret source kinds and the check rules.
- JSON schemas for the parameters and secrets files.
- `ecsc check`, which runs with no credentials, no network and no runtime dependencies. It reports
  every problem as one line naming the file, the environment and the key, and never prints a value.
- A composite action and a reusable workflow for GitHub Actions.
- Documentation: prior art, the migration runbook, and the traps behind the design.
