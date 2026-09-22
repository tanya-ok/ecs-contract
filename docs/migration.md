# Migrating a service that already has two writers

Use this when infrastructure code and an application pipeline both register task definitions for
the same service today. Every step is reversible until step 3.

Nothing else may deploy this service's infrastructure stack between step 2 and step 3.

## 0. Before you start

- [ ] Record the task definition ARN the service runs now.
- [ ] Record the version map of every secret the service reads.
- [ ] Confirm which container name the task definition uses in each environment. Do not assume
      it is the same everywhere.
- [ ] Remove the desired count from the service resource if autoscaling manages it.

## 1. Publish pointers and widen the deploy role

- [ ] Create one pointer parameter per secret the application will reference:
      `/<service>/<environment>/infra/<what>-arn`, value the complete secret ARN.
- [ ] Grant the application deploy role read on those parameters and their target secrets, and
      write on the service's own config secret.
- [ ] Deploy. Expect no change to the service.

## 2. Retain, and point at the live revision

- [ ] In one commit: add a retain deletion policy to the task definition resource, and set the
      service's task definition to the ARN it runs now, looked up at synthesis time.
- [ ] If the lookup fails, synthesis must fail. Never substitute a placeholder: it would be deployed.
- [ ] Plan. The service must show no replacement and no new deployment.
- [ ] Deploy this commit.

## 3. Remove the task definition from the template

- [ ] In a second commit: delete the task definition resource.
- [ ] Plan. The task definition must be labelled orphan or retain, **never destroy**. If it says
      destroy, stop: step 2 was not deployed.
- [ ] Deploy.
- [ ] Verify: the service runs the same revision as in step 0, and that revision is still active.

## 4. Move the application onto the contract

- [ ] Write the parameters and secrets files from the live revision's `environment` and `secrets`.
- [ ] `ecsc check` passes.
- [ ] If an existing config secret uses different key casing from the variable names, write both
      spellings until the first contract deploy has run.
- [ ] Deploy the application once.

## 5. Verify

- [ ] The drift audit reports no difference.
- [ ] Every secret's version map matches step 0, except the service's own config secret.
- [ ] An infrastructure deploy now changes nothing on the service.
