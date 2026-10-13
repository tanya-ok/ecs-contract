# Contributing

Issues and pull requests are welcome. Report security problems privately, as described in
[SECURITY.md](SECURITY.md), never in a public issue.

## Set up

```sh
uv sync --locked
git config core.hooksPath .githooks
```

The pre-push hook runs the anonymization gate in `tests/test_no_identifiers.py`.

## Before opening a pull request

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy
```

All four must pass. Documentation changes also need
`uvx --from zensical==0.0.65 zensical build --strict`.

## Rules

- English only, in code, docs, commits and pull requests.
- Synthetic data only. No real account ids, ARNs, hostnames, secret names or values, in files or
  in commit messages.
- Values are never printed, logged or written to an artifact. Names are.
- Commit messages use `type(scope): Subject`, where type is one of `feat`, `fix`, `docs`, `ci`,
  `chore`, `refactor`, `test`, `security` or `perf`.
- Add a line under `Unreleased` in [CHANGELOG.md](CHANGELOG.md) for user-visible changes.
