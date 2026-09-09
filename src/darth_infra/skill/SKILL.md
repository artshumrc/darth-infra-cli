---
name: darth-infra-toml
description: Write or edit a darth-infra.toml file.
disable-model-invocation: true
---

# Writing darth-infra.toml

`darth-infra.toml` is the single source of truth for a project's AWS deployment.
Everything else — CloudFormation templates under `templates/generated/`, resource
names, env vars — is derived from it and is never hand-edited.

Two things this file needs that you cannot invent: **real AWS resource identifiers**
(VPC, subnets, ALB, certificates, secrets) and **valid field names and combinations**.
Look the first up with the AWS CLI. Verify the second with `darth-infra render`, and
take field names from the bundled schema rather than from memory.

## Procedure

1. **Read the current state.** If `darth-infra.toml` exists, read it first and make the
   smallest edit that does the job. Preserve existing keys and ordering.
2. **Look up the AWS facts you need** (table below). Never guess an ID, ARN, or name.
3. **Write the TOML.** Consult `reference/darth-infra.schema.json` in this skill
   directory for the exact field list, types, defaults, and enums — it is the
   authoritative surface and lists every valid key.
4. **Verify with `darth-infra render`.** This runs the real validator and writes
   nothing if the config is wrong. It rejects any key the schema does not define —
   with a "did you mean" suggestion — so a plausible-sounding but invented key name
   fails loudly rather than being ignored. Re-run until clean.
5. **Preview the AWS impact** with `darth-infra deploy --env <env> --no-execute`, which
   creates a change set without executing it. Read the change set before deploying.

Never run `darth-infra deploy` without `--no-execute`.

## AWS lookups

Run these to fill in fields that reference existing infrastructure. Add
`--region <region>` to match `project.aws_region`.

| Field | Command |
|---|---|
| `project.vpc_name` / `vpc_id` | `aws ec2 describe-vpcs --query 'Vpcs[].{id:VpcId,name:Tags[?Key==\`Name\`]\|[0].Value,cidr:CidrBlock}'` |
| `project.private_subnet_ids` | `aws ec2 describe-subnets --filters Name=vpc-id,Values=<vpc-id> --query 'Subnets[].{id:SubnetId,az:AvailabilityZone,public:MapPublicIpOnLaunch,name:Tags[?Key==\`Name\`]\|[0].Value}'` |
| `project.public_subnet_ids` | same as above; public subnets are the ones that route to an internet gateway |
| `alb.shared_alb_name` | `aws elbv2 describe-load-balancers --query 'LoadBalancers[].{name:LoadBalancerName,arn:LoadBalancerArn,vpc:VpcId,dns:DNSName}'` |
| `alb.shared_listener_arn` | `aws elbv2 describe-listeners --load-balancer-arn <arn> --query 'Listeners[].{arn:ListenerArn,port:Port,protocol:Protocol}'` |
| `alb.shared_alb_security_group_id` | `aws elbv2 describe-load-balancers --load-balancer-arns <arn> --query 'LoadBalancers[].SecurityGroups'` |
| `alb.certificate_arn` | `aws acm list-certificates --query 'CertificateSummaryList[].{arn:CertificateArn,domain:DomainName}'` |
| `cloudfront.certificate_arn` | same, but **must be `--region us-east-1`** |
| `preview_environments.hosted_zone_name` | `aws route53 list-hosted-zones --query 'HostedZones[].Name'` |
| `[[secrets]] existing_secret_name` | `aws secretsmanager list-secrets --query 'SecretList[].{name:Name,arn:ARN}'` |
| `s3_buckets[].existing_bucket_name` | `aws s3api list-buckets --query 'Buckets[].Name'` |
| `rds.initial_snapshot_identifier` | `aws rds describe-db-snapshots --db-instance-identifier <db> --query 'DBSnapshots[].{id:DBSnapshotIdentifier,created:SnapshotCreateTime}'` |

Two checks worth running before writing routing config:

- **Listener priorities in use** (they must be unique across everything on a shared
  listener, not just this project):
  `aws elbv2 describe-rules --listener-arn <arn> --query 'Rules[].Priority'`
- **Whether a stack already exists** (this changes what is safe to edit):
  `aws cloudformation describe-stacks --stack-name <project>-ecs-<env>`

## Minimal valid config

```toml
[project]
name = "myapp"                 # lowercase; prefixes every AWS resource name
aws_region = "us-east-1"
vpc_name = "main-vpc"          # or vpc_id = "vpc-…"
environments = ["prod"]        # "prod" is required and is always first

[[services]]
name = "web"
port = 8000                    # omit for a worker with no inbound traffic
health_check_path = "/health"

[alb]
mode = "shared"                # or "dedicated"
shared_alb_name = "global-prod"
domain = "myapp.example.com"
default_target_service = "web"
```

Add `[rds]`, `[[s3_buckets]]`, `[[secrets]]`, `[cloudfront]`, `[service_discovery]`,
and `[preview_environments]` as needed — see the schema for their fields.

## Rules that bite

`darth-infra render` enforces all of these; these are the ones that most often make a
hand-written config invalid.

- `"prod"` must be in `project.environments` and is reordered first automatically.
- A service referenced by `alb.default_target_service` or `alb.path_rules[].target_service`
  must have a `port`.
- Setting `alb.domain` requires `alb.default_target_service`, and vice versa.
- `cloudfront.enabled = true` requires `alb.domain` **and** at least one
  `cloudfront.cached_behaviors` entry. Its certificate must be in `us-east-1`.
- `cloudfront.cached_behaviors[].origin_request_headers` forwards viewer headers to the
  origin without adding them to the cache key. It rejects `Host` and `Authorization`
  (use `forward_authorization_header`), and `Accept-Encoding` while `compress = true`.
  The rendered cache policy keeps the behavior's existing cache key, so adding it to a
  live behavior does not discard what that path has already cached.
- `[[secrets]]` with `source = "existing"` or `"rds"` requires `existing_secret_name`;
  `source = "generate"` or `"env"` forbids it. For `source = "rds"` the value is a JSON
  key (`host`, `port`, `dbname`, `username`, `password`), not a secret name.
- Every name in `services[].secrets` must exist in `[[secrets]]`.
- `launch_type = "ec2"` requires `ec2_instance_type`; `ebs_volumes` are EC2-only.
- Listener priorities are 1–50000 and unique within the config.
- **Prod must be deployed before any other environment.**

## Names are derived, not configured

Do not add fields trying to set these — they come from `<project>` and `<env>`:

| Resource | Name |
|---|---|
| CloudFormation stack | `<project>-ecs-<env>` |
| ECS cluster / service | `<project>-<env>` / `<project>-<env>-<service>` |
| ECR repository | `<project>/<env>/<service>` |
| S3 bucket (managed) | `<project>-<env>-<bucket name>` |
| RDS instance | `<project>-<env>-db` |
| RDS credentials secret | `<project>-<env>-rds-credentials` |
| Generated secret | `/darth-infra/<project>/<env>/<SECRET_NAME>` |

Non-prod hostnames are prefixed automatically: `alb.domain = "myapp.example.com"`
gives prod `myapp.example.com` and dev `dev.myapp.example.com`.

## What containers receive

Beyond `environment_variables`: every secret in `services[].secrets`; `POSTGRES_DB`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` for services in
`rds.expose_to`; each bucket connection's `env_key`. To rename the database variables,
declare explicit `rds`-sourced secrets instead of using `expose_to`.

## Adopting infrastructure that already exists

Migrating a project onto darth-infra usually means reusing resources it did not create.

**An existing S3 bucket** — set `mode = "existing"` and `existing_bucket_name`. Use
`mode = "seed-copy"` with `seed_source_bucket_name` to copy from it instead.

**An existing database** — restore prod from a snapshot of it on prod's first deploy.
The result is an ordinary managed instance with no link to the original:

```toml
[rds]
database_name = "myapp"        # set to the source database's own name
expose_to = ["web"]
initial_snapshot_identifier = "legacy-prod-final-2026-08-14"
initial_snapshot_credentials_secret = "legacy-prod-credentials"
```

`initial_snapshot_credentials_secret` is a Secrets Manager name or ARN holding the
source database's `username` and `password` — required, because a restored instance
keeps the master credentials of the database it came from. Create one if needed:

```bash
aws secretsmanager create-secret --name legacy-prod-credentials \
  --secret-string '{"username":"myapp","password":"…"}'
```

Constraints that matter:

- Both keys apply **only to prod's first deploy**, while `<project>-ecs-prod` does not
  yet exist. Check with `aws cloudformation describe-stacks` before suggesting them.
- Adding them to an already-deployed project does nothing. It will not migrate a live
  database, and it will not replace one.
- **Leave both keys in the file permanently.** RDS requires the snapshot identifier on
  every later update; removing the credentials key is a hard error on the next deploy.
- Take a fresh final snapshot of the source database immediately before cutover, or the
  restored database will be missing recent writes.
- Decommissioning the original instance is manual — darth-infra never touches it.

An existing RDS instance cannot be adopted *in place*; a snapshot restore is the
supported path.

## Editing an already-deployed project

Some edits force AWS to replace a resource and lose its data. Before changing any of
these on a deployed environment, say so plainly and confirm with the user:

- `project.name`, `project.aws_region`, `project.vpc_name`/`vpc_id`, or the subnet lists
- `rds.database_name`, or removing `[rds]`
- an `s3_buckets[].name` or `mode`, or removing a bucket
- a `services[].name`
- removing an environment from `project.environments`

Adding a service, changing an env var, a health-check path, a CPU/memory value, a tag,
or a listener priority is ordinarily safe.
