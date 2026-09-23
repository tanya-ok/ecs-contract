# The ECS config contract

Version 0.1. Provider neutral: no vendor or organization appears here except the AWS services the
problem is about.

## 1. Problem

A container on Amazon ECS receives three kinds of content through its task definition:

1. plain configuration, in `environment`
2. secrets, in `secrets`, each a `valueFrom` reference resolved by the agent at start
3. the image version, in `image`

Two systems want to write them. Infrastructure as code describes the task definition because the
service, the roles and the log group are defined next to it. The application pipeline registers
task definitions because the image and the configuration change with every release.

Each writes a complete revision, so the last writer wins. An infrastructure deploy reverts what the
application wrote, and no diff shows it as an intended change.

## 2. The rule

**Infrastructure owns everything around the container. The application owns the container's
content.**

| Infrastructure | Application |
|---|---|
| cluster, service, load balancer, target group | image tag |
| task role, execution role | values of `environment` |
| log group, autoscaling, alarms | values of `secrets` |
| secret and parameter resources and their names | the container's cpu and memory request |
| pointer parameters (section 4.3) | |

### 2.1 Consequences

- **A secret resource is created without a value.** The template carries a name and no content.
  Writing a value from code resends it on every property edit, and a placeholder default
  overwrites a live secret.
- **Infrastructure does not describe a task definition.** It reads the revision the service runs
  now and sets that exact revision on the service resource. The synthesized template contains no
  task definition, so an infrastructure deploy cannot change application content.
- **The service resource omits the desired count** after its first creation, so a deploy does not
  override autoscaling.

## 3. Files

The application commits two files, one for configuration and one for secrets. The split exists
so the secrets list gets its own review.

Both have the same outer shape, and both declare the same set of environments:

```json
{
  "$schema": "<optional>",
  "environments": {
    "<environment>": { "<section>": { "<KEY>": "<entry>" } }
  }
}
```

`<section>` is `parameters` in the parameters file and `secrets` in the secrets file. `<KEY>` is
an environment variable name: `[A-Za-z_][A-Za-z0-9_]*`.

### 3.1 Parameters

Each entry is a string, the value as the container will see it. Numbers are written as strings,
because task definition environment values are strings.

### 3.2 Secrets

Each entry is an object naming **exactly one** source. An entry naming none is an error, never a
default.

| Source | Fields | Resolves to |
|---|---|---|
| `pointer` | `pointer`, optional `jsonKey` | the secret whose complete ARN is stored in the named parameter, optionally one key inside it |
| `parameter` | `parameter` | the named parameter, read directly |
| `vault` | `vault` | a value from an external secret store, written into the service's own config secret and bound from there |

## 4. Source kinds

### 4.1 `parameter`

Shared, non-secret or low-sensitivity material that many services read, such as a certificate
bundle.

### 4.2 `vault`

Values only a human or an external store knows. At deploy time they are fetched, written as one
JSON document into the service's own config secret, and each key is bound out of that secret.
The document is written whole, so it must contain every key bound out of it, not only the changed
ones. Keys the contract no longer names are kept by default: a rollback to the previous revision
still binds them. Removing them is an explicit step.

### 4.3 `pointer`

A pointer is a parameter, published by infrastructure, whose value is the complete ARN of a
secret that some stack owns. Recommended name: `/<service>/<environment>/infra/<what>-arn`.

Without it, the application repository must either commit ARNs, which carry an account id and
differ per environment, or the deploy grows a lookup table. A pointer turns the ARN into a
stable, greppable, per-environment name that infrastructure publishes and the application
consumes.

## 5. The deploy

1. Resolve every parameter and every secret source. Fail on the first key with no source.
2. Refuse to continue when a name shaped like a secret appears in `environment`.
3. Read the task definition the service runs now.
4. Replace `environment`, `secrets` and the image of the named container. Change nothing else.
5. Register the revision, update the service, wait until it is stable.
6. Record the deployed version where a human can read it.

Step 3 is what lets fields the contract does not mention, added by someone else for a good
reason, survive a deploy.

## 6. The checks

| Check | Credentials | Catches |
|---|---|---|
| contract check, every pull request | none | the rules in 6.1 |
| drift audit, on demand | read only | any difference between what a deploy would write and what is live, `environment` by name and value, `secrets` by name and `valueFrom` |
| deploy guards | deploy role | a secret-shaped name in `environment`; a stateful resource about to be destroyed rather than orphaned; a live revision that moved since the plan |

### 6.1 Contract check rules

A conforming checker refuses, reporting file, environment and key for each:

1. a key declared in both files for one environment
2. a secret naming no source
3. a secret naming more than one source
4. `jsonKey` without `pointer`
5. a literal ARN in any value
6. a 12-digit number, shaped like an AWS account id, in any value
7. a reserved name: AWS credential and container metadata variables, plus names the deploy
   workflow sets itself
8. a secret-shaped name declared as a parameter, unless explicitly allowed
9. an environment declared in one file and not the other
10. a key, environment or field declared twice in one JSON object
11. a pointer that is not an absolute parameter path
12. a parameter value that is not a string, a key that is not a valid variable name, an unknown
    field

It reports every problem, not only the first, and never prints a value.

## 7. Migrating a service with two writers

Order matters. The wrong order deregisters the running revision. The full runbook is in
[docs/migration.md](docs/migration.md). In short:

1. Publish the pointer parameters and widen the deploy role. Nothing changes yet.
2. Deploy the infrastructure once with a **retain** policy on the task definition, and the service
   pointed at the live revision.
3. Deploy again, removing the task definition from the template. It is orphaned, not deleted.
4. Move the application onto the contract. Deploy once.
5. Run the drift audit. It must report no difference.

Nothing else may deploy the service between steps 2 and 3. Retain must already be deployed
before the removal, because CloudFormation applies the deletion policy from the previously
deployed template.

## 8. Non-goals

This is not a deployment tool. Registering a revision and waiting for it takes four API calls and
every team already has them. The ownership rule, the source kinds and the checks are the product.

## 9. Status

Designed, then proven end to end once: one service, one development environment. The infrastructure
deploy left the running revision and the secret value untouched, and the drift audit after an
application deploy reported no difference. Not yet exercised across many services.
