# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html). The floating major tag is `v0` until
the 1.0 release.

## Unreleased

## 0.2.0 - 2026-09-27

Stage 2, the resolver. Verified end to end once on a synthetic Fargate service in a personal
account.

### Added

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
