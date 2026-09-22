# Security policy

## Supported versions

The latest release on the `v0` line is supported. There are no backports below it.

## Reporting a vulnerability

Report privately through GitHub: open the Security tab of this repository and use
**Report a vulnerability**. Please do not open a public issue for a security report.

Expect an acknowledgement within seven days. If a fix is needed, the advisory stays private
until a release carrying it is published.

## Scope notes

`ecsc check` reads two JSON files. It makes no network calls, needs no credentials, and has no
runtime dependencies. Later stages read AWS APIs and external secret stores; values are never
printed, logged or written to an artifact, only names.

This project has no telemetry.
