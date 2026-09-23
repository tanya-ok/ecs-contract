# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html). The floating major tag is `v0` until
the 1.0 release.

## Unreleased

### Added

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
