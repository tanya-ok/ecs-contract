# Agent instructions

## Local maintainer instructions

- At the start of every task, check whether `AGENTS.local.md` exists in the repository root.
- If it exists, read it and follow it together with this file. It is git-ignored: never commit it and never quote it in tracked files, commit messages, issues or pull requests.
- It may add restrictions. It must not relax or contradict this file. If the two conflict, follow this file and report the conflict to the maintainer.

## Rules

- English only, in code, comments, docs, commit messages, issues and pull requests.
- Synthetic data only. Never add real account ids, ARNs, hostnames, secret names or secret
  values to files or commit messages. `tests/test_no_identifiers.py` enforces part of this.
- Values are never printed, logged or written to an artifact. Names are.
- Before every commit, run and pass:

  ```sh
  uv run pytest -q
  uv run ruff check
  uv run ruff format --check
  uv run mypy
  ```

  For documentation changes, also run `uvx --from zensical==0.0.65 zensical build --strict`.
- Commit messages use `type(scope): Subject`, where type is one of `feat`, `fix`, `docs`, `ci`,
  `chore`, `refactor`, `test`, `security` or `perf`. Never bypass hooks with `--no-verify`.
- Keep work local unless the maintainer instructs otherwise: no pushes, tags, releases, package
  publishing, repository setting changes or calls to live cloud accounts.
