# The infrastructure side

Infrastructure keeps the service and stops describing a task definition. It reads the revision
the service runs now and sets that exact ARN on the service resource. The template then holds no
task definition, so an infrastructure deploy cannot revert what the application wrote.

## AWS CDK, Python

```bash
pip install 'ecs-contract[cdk]'
```

```python
from ecs_contract.cdk import ServiceFromLiveRevision

ServiceFromLiveRevision(
    self,
    "Orderbook",
    cluster="exchange",
    service_name="orderbook",
    launch_type="FARGATE",
    network_configuration=network,
    load_balancers=[target],
)
```

| Behaviour | Why |
|---|---|
| `DescribeServices` runs at every synthesis, never cached | a cached revision is an old one, and deploying it reverts the application |
| any lookup failure stops synthesis: no credentials, access denied, throttling | a placeholder would be deployed |
| the ARN must be complete and revisioned | `family` or `family:latest` would let ECS pick |
| `task_definition`, `desired_count`, `cluster`, `service_name` are refused as extra props | the construct owns them; a count overrides autoscaling |
| `cluster` and `service_name` must be literal names | the lookup runs before tokens resolve |
| `initial_task_definition` is used only while the service does not exist | the first creation needs a revision; afterwards it is ignored |
| an AWS error is reported as operation and code only | the AWS message can carry ARNs and account ids |

The synthesizing role needs `ecs:DescribeServices` on the service. Other props pass through to
`AWS::ECS::Service` unchanged. The construct records the live `family:revision` as node metadata.

A lookup can be injected with `lookup=`, a function from `(cluster, service)` to an ARN or `None`.
Tests use it to synthesize without AWS. A deploy must use the default.

## Terraform

The provider reads the live revision through the `aws_ecs_service` data source. The data source
fails when the service does not exist, so the first creation takes the revision from a variable.

```hcl
variable "initial_task_definition" {
  type    = string
  default = null
}

data "aws_ecs_service" "live" {
  count        = var.initial_task_definition == null ? 1 : 0
  cluster_arn  = aws_ecs_cluster.exchange.arn
  service_name = "orderbook"
}

resource "aws_ecs_service" "orderbook" {
  name            = "orderbook"
  cluster         = aws_ecs_cluster.exchange.id
  launch_type     = "FARGATE"
  task_definition = coalesce(var.initial_task_definition, one(data.aws_ecs_service.live[*].task_definition))

  lifecycle {
    ignore_changes = [desired_count]
  }
}
```

There is no `aws_ecs_task_definition` resource. If one exists today, follow
[migration.md](migration.md): mark it `lifecycle { prevent_destroy = true }` and remove it from
state with a `removed` block and `destroy = false`, never by deleting it from the configuration
alone.

## Planning a migration

`ecsc migrate --plan` reads the live service and prints the runbook in
[migration.md](migration.md) filled in by name: the revision to record, the pointer each secret
needs, and the keys each contract file will hold. It changes nothing and prints no value or ARN.

```bash
ecsc migrate --plan -e production --cluster exchange --service orderbook --container app
```
