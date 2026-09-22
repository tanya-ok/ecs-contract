# Traps

Each of these was found by hitting it. Most are quiet: nothing fails, something is simply wrong
afterwards.

## Retain has to be deployed before the removal

CloudFormation applies the deletion policy recorded in the previously deployed template. Adding
retain and deleting the resource in one deploy deletes it. The plan shows `destroy` instead of
`orphan`. Make the plan fail on `destroy` for stateful types instead of trusting someone to read
the label.

## Importing a resource records the template, not the resource

Importing an existing role records the template you submit and does not touch the live role. The
stack then claims the new trust policy while the role keeps the old one, and the next deploy
changes nothing because the stored template already agrees. Reconcile after an import: apply
what the template says directly, then read the live resource back.

## A template value overwrites what the application wrote

If a template still describes a resource the application writes, such as a parameter holding the
deployed version, the next deploy resets it. The diff does not show it as intended. While the
resource is still in the template, feed synthesis the live value so the diff is empty, then
remove the resource from the template.

## A desired count in the template overrides autoscaling

A template carrying a count of two resets a service that scaled in to one. Omit the count after
the first creation.

## A guard that needs a permission the deploy role lacks

A pre-deploy guard that resolves resources through a broad API fails under a tightly scoped deploy
role. Resolve from the synthesized template first; fall back to an API only when the template
cannot answer.

## Two spellings during a migration

A hand-written config secret with lower-case keys, and a sync that writes upper-case variable
names, leave a window where the old binding points at keys that no longer exist, and the service
fails to start. Stop describing the task definition in infrastructure before the first sync.

## Environment file precedence

Tools that inject secret references from a file often give the file precedence over the shell. A
variable the workflow sets and the file also defines silently takes the file's value. Keep derived
values such as the environment name and the image tag out of the file, and assert them.

## Duplicate fields collapse silently

Two fields with the same label in a vault item, or the same key twice in a JSON object, collapse
into one when read into a dictionary. Count fields instead of indexing them. `ecsc check` refuses
duplicate keys for this reason.

## A bundled dependency that throws only at runtime

When a dependency of a bundled action became ESM only, the bundler emitted a stub that throws at
runtime, and the check comparing the committed bundle with a clean build passed. Execute the
built artifact in CI, not only the source. This repository's CI runs the built wheel.

## Container names differ per environment

One service had a stage suffix on its container name, another did not. Make the container name an
input with a default, and state it in the contract.
