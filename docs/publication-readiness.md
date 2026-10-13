# Publication and demonstration gates

This page defines acceptance criteria, not an approval badge. Publication stays
separate from local preparation. No remote deployment is implied by a successful
local documentation build.

## Reproduce the project

Run from a fresh checkout with the documented runtime and package manager:

```sh
uv sync --locked
uv run pytest
uv run ruff check
uv run mypy
```

Follow the [demonstration guide](demo.md). Capture the source revision, environment,
command, observed positive and negative outcomes and cleanup result. Saved
screenshots or an older report must identify their capture date. Re-run an
applicable integration check after changing the behavior it exercises.

Local checks and modeled AWS responses do not prove a live AWS deployment. The personal-account smoke and teardown passed on 2026-10-13; see the [live run](demo.md#live-run-on-2026-10-13). Re-run it after changing deployment behavior. Every writer must cooperate with the mutex.

## Build the documentation

Documentation tooling is separate from the application runtime:

```sh
python3.12 -m venv .venv-docs
.venv-docs/bin/python -m pip install --require-hashes -r requirements-docs.lock
.venv-docs/bin/zensical build --strict --clean
.venv-docs/bin/zensical serve --dev-addr 127.0.0.1:8000
```

`requirements-docs.txt` holds the direct pin. `requirements-docs.lock` holds every transitive
dependency with hashes, and the docs workflow refuses a lock that does not match the direct pin.
After changing `requirements-docs.txt`, regenerate the lock:

```sh
uv pip compile requirements-docs.txt --universal --python-version 3.12 --generate-hashes -o requirements-docs.lock
```

The pinned generator produces `site/`. Check navigation, code blocks, diagrams,
search and project-subpath asset URLs in a browser. Never add private overlays,
state databases, credentials or private vaults to documentation sources.

## Protect release tags

Callers that follow the `v0` default run whatever commit the tag points at, inside jobs that hold
OIDC and vault tokens. Anyone who can create or move a `v*` tag can change that code. Before
the next release, add a repository ruleset:

| Setting | Value |
|---|---|
| Target | tags |
| Include pattern | `refs/tags/v*` |
| Rules | restrict creations, restrict updates, restrict deletions, block force pushes |
| Bypass list | the maintainer only |
| Enforcement | active |

The release workflow moves the major tag with the workflow token. If the ruleset blocks that
update, move `v0` by hand after the release is verified, or add a narrowly scoped bypass for the
actor that runs it. Callers should still pin a full commit SHA in both the `uses:` line and
`ecs-contract-ref`, as the README describes.

## GitHub Pages handoff

The prepared workflow builds on pull requests and publishes only from `main`
after an authorized push or explicit workflow dispatch. It uploads the static
`site/` directory and uses the GitHub Pages environment with job-scoped
`pages: write` and `id-token: write`; no long-lived deploy key is required.
The repository owner must select GitHub Actions as the Pages source before the
first deployment. Preparing this file does not enable Pages or execute a deploy.

Before publication, inspect the exact staged diff and distributable contents,
run the repository privacy/secret gates, reproduce the demo from a clean checkout,
verify the strict docs build and retain its evidence. Remote CI and the resulting
Pages URL still need verification after publication is explicitly authorized.

Generator behavior and configuration follow the
[official Zensical guide](https://zensical.org/docs/create-your-site/).

## Revision references

Revision hashes in dated records that do not resolve in this repository identify
development commits. They were squashed into the 2026-10-13 release commit and are
archived locally. The release tree was checked again after the squash.
