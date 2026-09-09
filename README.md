# darth-infra

A CLI that turns a single `darth-infra.toml` file into a complete, multi-environment
AWS ECS deployment: CloudFormation templates, ECR repositories, an ALB routing setup,
optional RDS PostgreSQL, S3 buckets, CloudFront, and Secrets Manager wiring.

You describe *what* you want in TOML. `darth-infra` generates CloudFormation YAML into
your project, then deploys it through change sets.

---

## Table of contents

- [Installation](#installation)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [The configuration file](#the-configuration-file)
  - [`[project]`](#project)
  - [`[[services]]`](#services)
  - [`[rds]`](#rds)
    - [Adopting an existing database](#adopting-an-existing-database)
  - [`[[s3_buckets]]`](#s3_buckets)
  - [`[alb]`](#alb)
  - [`[cloudfront]`](#cloudfront)
  - [`[[secrets]]`](#secrets)
  - [`[environments.<name>]`](#environmentsname)
  - [`[service_discovery]`](#service_discovery)
  - [`[preview_environments]`](#preview_environments)
- [Editing the config with an agent](#editing-the-config-with-an-agent)
- [Cross-field rules](#cross-field-rules)
- [What your containers receive](#what-your-containers-receive)
- [Complete worked examples](#complete-worked-examples)
- [Commands](#commands)
- [Naming conventions](#naming-conventions)
- [How environments work](#how-environments-work)
- [Generated project layout](#generated-project-layout)
- [AWS permissions](#aws-permissions)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Installation

Install as a standalone tool with [uv](https://docs.astral.sh/uv/):

```bash
# Latest from the default branch
uv tool install git+https://github.com/artshumrc/darth-infra-cli.git

# Pin to a released tag (recommended for teams and CI)
uv tool install git+https://github.com/artshumrc/darth-infra-cli.git@v0.8.0
```

Verify:

```bash
darth-infra --version
darth-infra --help
```

Upgrade or reinstall a different version:

```bash
uv tool upgrade darth-infra
# or, to move to a specific tag:
uv tool install --force git+https://github.com/artshumrc/darth-infra-cli.git@v0.8.0
```

Run once without installing:

```bash
uvx --from git+https://github.com/artshumrc/darth-infra-cli.git darth-infra --help
```

Alternatives:

```bash
# From a local checkout
uv tool install .

# From a GitHub Release wheel
pip install https://github.com/artshumrc/darth-infra-cli/releases/download/v0.8.0/darth_infra-0.8.0-py3-none-any.whl
```

## Prerequisites

| Requirement | Needed for | Notes |
|---|---|---|
| Python ≥ 3.12 | everything | uv provisions this automatically for `uv tool install` |
| AWS credentials | every AWS-touching command | Standard boto3 resolution: `AWS_PROFILE`, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, SSO, instance role |
| **AWS CLI v2** | `deploy`, `push`, `logs`, `exec` | Shelled out to for `cloudformation package`, `ecr get-login-password`, `logs tail`, `ecs execute-command` |
| Docker with `buildx` | `build`, `push`, `deploy --with-images` | See <https://docs.docker.com/go/buildx/> |
| `session-manager-plugin` | `darth-infra exec` | Required by `aws ecs execute-command` |

Existing AWS resources you must have **before** the first deploy:

- A **VPC**, discoverable either by its `Name` tag (`project.vpc_name`) or by explicit
  `project.vpc_id`. It must contain private subnets (and public subnets if you use a
  dedicated ALB).
- If `alb.mode = "shared"`: an **existing Application Load Balancer**, referenced by
  name (`alb.shared_alb_name`) or by listener ARN (`alb.shared_listener_arn` +
  `alb.shared_alb_security_group_id`).
- If `alb.mode = "dedicated"` and you want HTTPS: an **ACM certificate** in the
  project region.
- If `cloudfront.custom_domain` is set: an **ACM certificate in `us-east-1`**.
- DNS records pointing at the ALB (or CloudFront) are **not** created for you outside of
  preview environments — configure them externally (e.g. a Route 53 alias).

`darth-infra` creates a per-account/per-region CloudFormation artifact bucket on first
deploy: `darth-infra-artifacts-<account-id>-<region>`.

## Quick start

```bash
mkdir my-webapp-infra && cd my-webapp-infra

# 1. Create the project interactively (guided editor, writes files on confirm)
darth-infra init

# ...or write darth-infra.toml by hand and scaffold non-interactively:
darth-infra init --non-interactive --config darth-infra.toml

# 2. Regenerate templates any time the TOML changes (no AWS calls)
darth-infra render

# 3. Deploy production first — every other environment requires it
darth-infra deploy --env prod --with-images

# 4. Deploy additional environments
darth-infra deploy --env dev --with-images

# 5. Operate
darth-infra status --env prod
darth-infra logs web --env prod -f
darth-infra exec web --env prod
darth-infra secret DJANGO_SECRET_KEY --env prod
```

`darth-infra` locates `darth-infra.toml` by walking up from the current directory, so
you can run commands from anywhere inside the project.

## The configuration file

`darth-infra.toml` is the single source of truth. Everything under
`templates/generated/` is derived from it and is overwritten on every `render` and
`deploy` — never hand-edit those files.

The file is validated against `darth-infra.schema.json`, which is copied into your
project directory. Keep the first line for editor autocompletion:

```toml
#:schema ./darth-infra.schema.json
```

Only `[project]` (with `name`) and at least one `[[services]]` entry are strictly
required. Everything else is optional, and every field below shows its default.

The blocks in this section are **field references**: they show every available key at
once, including mutually exclusive ones. Don't paste them wholesale — start from
[Complete worked examples](#complete-worked-examples), which are validated end to end.

### `[project]`

```toml
[project]
name = "my-webapp"                       # required; ^[a-z][a-z0-9-]*$
aws_region = "us-east-1"
vpc_name = "artshumrc-prod-standard"     # VPC discovered by Name tag
environments = ["prod", "dev"]           # "prod" is required and is always sorted first

# Optional explicit network pinning (skips discovery)
vpc_id = "vpc-0123456789abcdef0"
private_subnet_ids = ["subnet-aaa", "subnet-bbb"]
public_subnet_ids  = ["subnet-ccc", "subnet-ddd"]

# Minimum CLI version this project requires. Managed automatically — see below.
cli_version_floor = "0.8.0"

[project.tags]                           # extra tags applied to all resources
owner = "web-team"
```

Notes:

- If `private_subnet_ids` / `public_subnet_ids` are omitted, subnets are discovered from
  the VPC: those with `MapPublicIpOnLaunch = false` are treated as private, the rest as
  public. Deploy fails if more than 16 private subnets resolve — pin an explicit list of
  2–6 subnets across AZs in that case.
- `cli_version_floor` is written and bumped automatically after successful commands. A
  CLI older than the floor refuses to run against the project, so teams stay in sync.

### `[[services]]`

One table array entry per container. Repeat for each service.

```toml
[[services]]
name = "web"                             # required; used in resource names
dockerfile = "Dockerfile"
build_context = "."
docker_build_target = "production"       # optional docker build --target
image = "docker.elastic.co/…:8.12.0"     # optional: use an external image instead of
                                         #   building. Skips ECR + build/push entirely.
port = 8000                              # omit entirely for background workers
health_check_path = "/health"
health_check_http_codes = "200-399"
health_check_timeout_seconds = 5
health_check_interval_seconds = 30
healthy_threshold_count = 5
unhealthy_threshold_count = 2
health_check_grace_period_seconds = 60   # optional ECS grace period
cpu = 256                                # Fargate: 256/512/1024/2048/4096
memory_mib = 512
desired_count = 1
command = "gunicorn app.wsgi"            # optional container command override
entrypoint = "/opt/app/worker.sh"        # optional image ENTRYPOINT override
secrets = ["DJANGO_SECRET_KEY"]          # names from [[secrets]]
environment_variables = { DEBUG = "0", SITE_URL = "{domain}" }
enable_exec = true                       # ECS Exec (needed by `darth-infra exec`)
enable_ses_send_email = false            # grants ses:SendEmail/SendRawEmail/GetSendQuota
enable_service_discovery = false         # register in Cloud Map
launch_type = "fargate"                  # or "ec2"

# EC2 launch type only
ec2_instance_type = "t4g.medium"         # required when launch_type = "ec2"
architecture = "arm64"                   # auto-detected from ec2_instance_type
user_data_script = "scripts/userdata.sh" # path relative to project root
user_data_script_content = """#!/bin/bash
echo hello
"""

[[services.ulimits]]
name = "nofile"                          # core|cpu|data|fsize|locks|memlock|msgqueue|
soft_limit = 65535                       #   nice|nofile|nproc|rss|rtprio|rttime|
hard_limit = 65535                       #   sigpending|stack

[[services.ebs_volumes]]                 # EC2 launch type only
name = "data"
size_gb = 100
mount_path = "/data"
device_name = "/dev/xvdf"
volume_type = "gp3"                      # gp2|gp3|io1|io2|st1|sc1
filesystem_type = "ext4"                 # ext4|xfs
```

`environment_variables` values support these placeholders, substituted at deploy time:

| Placeholder | Value |
|---|---|
| `{project}` | project name |
| `{env}` | environment name |
| `{domain}` | `https://<cluster domain>` (empty when no `alb.domain`) |
| `{hostname}` | cluster domain without scheme |
| `{number}` | preview environment number (empty otherwise) |
| `{base_environment}` | `preview_environments.base_environment` |
| `{service_discovery_namespace}` | resolved Cloud Map namespace |

`command` is run through a shell (`sh -c`), so it takes a whole command line.
`entrypoint` is emitted in **exec form** — split on shell words, no shell — so an
entrypoint script's `$0` is its own path and signals reach it directly. Reach for
`entrypoint` when the image's own `ENTRYPOINT` ignores its arguments, which makes a
`command` override silently do nothing.

> **`s3_access` is not template-generating.** `services[].s3_access` exists in the
> schema and the editor, but S3 environment variables and IAM grants are produced
> **only** by `[[s3_buckets.connections]]`. Use connections to wire buckets to services.

### `[rds]`

Optional. A single PostgreSQL instance per environment.

```toml
[rds]
database_name = "myapp"        # required; ^[A-Za-z][A-Za-z0-9_]*$, ≤ 63 chars
instance_type = "db.t4g.micro" # a bare "t4g.micro" is normalized to "db.t4g.micro"
allocated_storage_gb = 20      # must be ≥ 20
expose_to = ["web"]            # services that receive POSTGRES_* env vars
engine_version = "15"
backup_retention_days = 7

# Adopting a database this CLI did not create — see below. Both or neither.
initial_snapshot_identifier = "legacy-prod-final-2026-08-14"
initial_snapshot_credentials_secret = "legacy-prod-credentials"
```

The master username is derived from `database_name`. Credentials are stored in a
generated Secrets Manager secret named `<project>-<env>-rds-credentials`.

#### Adopting an existing database

To migrate a project whose database was created by something else, restore prod's
database from a snapshot of the existing one. The result is an ordinary managed
instance — there is no permanent link to the original, and the whole stack stays
under this CLI's management.

```toml
[rds]
database_name = "myapp"        # set to the source database's own name
initial_snapshot_identifier = "legacy-prod-final-2026-08-14"
initial_snapshot_credentials_secret = "legacy-prod-credentials"
```

`initial_snapshot_credentials_secret` is a Secrets Manager name or ARN whose value
holds the source database's `username` and `password`. It is required, because a
restored instance keeps the master credentials of the database it came from — the
generated credentials secret is seeded from it so containers can connect. Create one
first if the legacy credentials do not already live in Secrets Manager:

```bash
aws secretsmanager create-secret \
  --name legacy-prod-credentials \
  --secret-string '{"username":"myapp","password":"…"}'
```

Both keys apply **only to prod's first deploy**, while the `<project>-ecs-prod` stack
does not yet exist:

- Once prod is deployed, the snapshot identifier recorded on the stack is
  authoritative and the config keys are ignored. RDS requires that identifier on
  every subsequent update, so **leave both keys in the file** — removing
  `initial_snapshot_credentials_secret` is a hard error on the next deploy.
- A prod stack deployed *without* a snapshot never acquires one. Adding these keys to
  an already-deployed project does nothing, rather than replacing a live database.
- Non-prod environments ignore these keys entirely; they keep seeding from the latest
  automated snapshot of `<project>-prod-db`.

The deploy fails before touching CloudFormation if the snapshot or the secret cannot
be found. A restored instance keeps the source database's internal name, master
username, and password, so `database_name` should be set to match the source.

Deleting the original instance is left to you — this CLI never touches it.

### `[[s3_buckets]]`

Optional. Repeat per bucket.

```toml
[[s3_buckets]]
name = "media"                 # required; actual bucket: <project>-<env>-<name>
mode = "managed"               # managed | existing | seed-copy
existing_bucket_name = "…"     # required for mode="existing", forbidden otherwise
seed_source_bucket_name = "…"  # required for mode="seed-copy", forbidden otherwise
seed_non_prod_only = true      # run the one-time seed copy only for non-prod envs
public_read = false
cloudfront = false             # provision a CloudFront distribution for this bucket
cors = false                   # permissive CORS
preview_fallback_bucket_name = "…"   # bucket previews may read from as a fallback
preview_fallback_env_key = "MEDIA_FALLBACK_BUCKET"

[[s3_buckets.connections]]     # this is what actually wires the bucket to a service
service = "web"                # must name a service
env_key = "MEDIA_BUCKET"       # ^[A-Z][A-Z0-9_]*$ — receives the bucket name
cloudfront_env_key = "MEDIA_CDN_URL"   # requires cloudfront = true on the bucket
read_only = false              # false grants read/write, true grants read-only
```

Bucket modes:

| Mode | Behavior |
|---|---|
| `managed` | Creates a fresh `<project>-<env>-<name>` bucket per environment |
| `existing` | Reuses a pre-existing bucket you name. No CloudFront support |
| `seed-copy` | Creates a managed bucket and runs a one-time copy from a source bucket |

### `[alb]`

Routing configuration. Both a shared cluster ALB and a project-dedicated ALB are
supported.

```toml
[alb]
mode = "shared"                          # shared | dedicated

# --- shared mode ---
shared_alb_name = "artshumrc-prod-alb"   # required in shared mode unless the two
                                         #   fields below are both provided
shared_listener_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:listener/…"
shared_alb_security_group_id = "sg-0123456789abcdef0"

# --- dedicated mode ---
certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/…"  # for HTTPS

# --- routing (both modes) ---
domain = "myapp.example.com"             # prod host; other envs get <env>.<domain>
default_target_service = "web"           # required when domain is set
default_listener_priority = 100          # optional; allocated automatically if omitted

[[alb.path_rules]]                       # optional host+path rules
name = "api"
path_pattern = "/api/*"
target_service = "api"
priority = 110                           # optional; allocated automatically if omitted
```

In shared mode without an explicit `shared_listener_arn`, the ALB's `HTTPS:443` listener
is preferred, falling back to any listener on port 80 or 443.

Listener priorities you omit are allocated automatically at deploy time against the live
listener, so parallel environments don't collide, and an allocated priority is then
reused on every later deploy rather than churning.

A priority you set explicitly is authoritative: changing `default_listener_priority` and
redeploying moves the live rule. That is an in-place listener-rule update, not a
replacement — which is what makes it usable to cut traffic over between two stacks
sharing one ALB.

An explicit priority is never silently moved. If it is already used by another rule on
that listener, the deploy fails and names it, rather than allocating a different one:
auto-allocation searches from the bottom of the range, so a silent fallback could place
your rule *above* another stack's rule for the same host and take its traffic.

### `[cloudfront]`

Optional CloudFront distribution **in front of the ALB** (distinct from the per-bucket
`s3_buckets[].cloudfront` flag).

```toml
[cloudfront]
enabled = true
origin_https_only = true
custom_domain = "cdn.myapp.example.com"  # hostname only, no scheme or path
certificate_arn = "arn:aws:acm:us-east-1:…"   # must be issued in us-east-1
price_class = "PriceClass_100"           # PriceClass_100 | PriceClass_200 | PriceClass_All
comment = "myapp CDN"

[[cloudfront.connections]]               # inject the distribution URL into a service
service = "web"
env_key = "APP_CDN_URL"

[[cloudfront.cached_behaviors]]          # at least one is REQUIRED when enabled = true
name = "images"
path_pattern = "/images/*"
compress = true
cache_by_origin_headers = true
min_ttl_seconds = 0
default_ttl_seconds = 3600
max_ttl_seconds = 31536000
query_strings = "all"                    # all | none | allowlist
query_string_allowlist = []              # required iff query_strings = "allowlist"
cookies = "none"                         # none | all | allowlist
cookie_allowlist = []                    # required iff cookies = "allowlist"
forward_authorization_header = false
origin_request_headers = []              # sent to the origin, kept out of the cache key
```

The default behavior is uncached; only the paths you list in `cached_behaviors` are
cached. Cached-behavior names and path patterns must each be unique.

`origin_request_headers` lists viewer headers your origin needs to see but must not
cache on — `Referer` to attribute a request to the site that made it, for example.
Everything else a behavior forwards is part of the cache key, so a header listed there
would split the cache one entry per distinct value.

Setting it renders that behavior with a CloudFront cache policy and origin request
policy in place of legacy forwarded values. The cache key is deliberately unchanged:
the policy keys on the same `Host`, query strings, and cookies the forwarded values did,
carries the same TTLs, and leaves Brotli off, because legacy settings cannot express
Brotli and enabling it would add a dimension that re-splits everything already cached
under that path. Behaviors that leave the list empty are unchanged.

`Host` and `Authorization` are rejected: `Host` is always forwarded, and `Authorization`
has its own `forward_authorization_header` flag, which keeps it in the cache key where it
belongs. `Accept-Encoding` is rejected while `compress = true`, because CloudFront
normalizes that header itself and ignores an origin request policy's copy of it.

### `[[secrets]]`

```toml
[[secrets]]
name = "DJANGO_SECRET_KEY"     # the container env var name
source = "generate"            # generate | env | existing | rds
length = 50                    # generated value length
generate_once = true           # must be true for source="generate"
existing_secret_name = "…"     # required for source="existing" and "rds";
                               #   forbidden for "generate" and "env"
```

| Source | Meaning |
|---|---|
| `generate` | Creates a random value per environment at `/darth-infra/<project>/<env>/<name>` |
| `env` | Reads a **local shell environment variable named the same as the secret** at deploy time; its value is a Secrets Manager secret name or ARN |
| `existing` | References an existing Secrets Manager secret name or ARN given in `existing_secret_name` |
| `rds` | Pulls a JSON key out of the generated RDS credentials secret; `existing_secret_name` is the key (`host`, `port`, `dbname`, `username`, `password`) |

Every name in `services[].secrets` must exist in `[[secrets]]`.

For `source = "existing"`, `existing_secret_name` accepts the `{project}` and `{env}`
placeholders, resolved per deploy — so one entry names a per-environment secret:

```toml
[[secrets]]
name = "DATABASE_URL"
source = "existing"
existing_secret_name = "myapp/{env}/DATABASE_URL"
```

A preview environment resolves `{env}` to its **base** environment, since it has no
external secrets of its own. An ARN, or a name with no placeholder, passes through
unchanged.

### `[environments.<name>]`

Per-environment overrides. The table key is the environment name.

```toml
[environments.dev]
instance_type_override = "db.t3.micro"        # RDS instance class for this env

[environments.dev.tags]
cost-center = "sandbox"

[environments.dev.ec2_instance_type_override]
worker = "t4g.small"                          # service name -> EC2 instance type

[environments.dev.alb]                        # shared ALB targeting for this env
shared_alb_name = "global-dev"
shared_listener_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:listener/…"
shared_alb_security_group_id = "sg-0123456789abcdef0"
default_listener_priority = 49997               # this env's listener rule priority

[environments.dev.services.web]               # per-service runtime settings
cpu = 512
memory_mib = 1024
desired_count = 1
environment_variables = { SITE_ID = "1", DEBUG = "1" }
```

Environment tags override project tags of the same key for that environment only.

`[environments.<env>.services.<service>]` applies over that service's own values:
`cpu`, `memory_mib`, and `desired_count` replace the service default, and
`environment_variables` is merged key by key, so an environment only restates the
variables that actually differ. Use it for values the `{env}` / `{domain}` placeholders
cannot derive. The service name must exist in `[[services]]`.

`[environments.<env>.alb]` retargets the shared ALB for one environment — the case where
prod and non-prod live behind different load balancers. These three fields are resolved
at deploy time and never appear in a rendered template, so all environments still share
one set of templates. Fields you leave unset inherit `[alb]`. `alb.domain` needs no
override: non-prod hostnames are already derived as `<env>.<domain>`.

`default_listener_priority` is overridable per environment because priorities are unique
*per listener*, not per project. When environments sit on different shared listeners that
already carry other projects' rules, there may be no single priority free on all of them
— and picking one that is taken is a hard error, not something to discover at deploy
time.

### `[service_discovery]`

Optional Cloud Map namespace configuration, used by services with
`enable_service_discovery = true`.

```toml
[service_discovery]
namespace_template = "{project}-{env}.local"
```

If the table is omitted entirely, the namespace is the literal `local`. If you *do*
declare the table, the template must contain `{project}` or `{env}`, or be exactly
`"local"`. Supported placeholders: `{project}`, `{env}`, `{number}`,
`{base_environment}`.

### `[preview_environments]`

Optional per-pull-request ephemeral environments, deployed with
`darth-infra deploy --env pr-123 --preview-from prod`.

```toml
[preview_environments]
enabled = true
base_environment = "prod"                # must be a configured environment
name_pattern = "pr-{number}"             # must contain {number}
domain_template = "pr-{number}.myapp.example.com"   # must contain {number}
hosted_zone_name = "example.com"         # enables Route 53 alias creation for previews
listener_priority_start = 40000          # set together with the end bound
listener_priority_end = 40999

[preview_environments.tags]
team = "web"
```

Preview environments automatically receive the tags `environment-type=preview`,
`preview-base-environment`, `pull-request`, and `ephemeral-cleanup-id`. Their database
is restored from the latest **automated** snapshot of the prod instance, so prod must
have at least one automated snapshot before the first preview deploy.

## Editing the config with an agent

The guided TUI (`darth-infra tui`) exists because the option surface is large and some
fields need AWS lookups. A coding agent can do the same job directly against the TOML:

```bash
darth-infra install-skill
```

This installs a skill into both `.claude/skills/darth-infra-toml/` and
`.agents/skills/darth-infra-toml/`, so Claude Code and other agent runtimes pick it up
from the project with no further setup. `--target claude|agents` installs just one.

`darth-infra init` does this automatically for a new project — pass `--no-skill` to
skip it. Nothing is installed if you cancel creation in the guided editor.

The skill covers the AWS CLI lookups each reference field needs, the cross-field rules,
the derived naming conventions, which edits risk replacing a deployed resource, and how
to adopt existing buckets and databases. It ships a copy of `darth-infra.schema.json` as
its field reference, so an installed skill matches the CLI version that installed it —
**re-run `install-skill` after upgrading darth-infra**.

Agents are instructed to verify their work with `darth-infra render`, which runs the
real validator, and to never deploy unless you ask.

## Cross-field rules

These are validated when the config is loaded — a violation is a hard error before any
AWS call:

- Every key must be defined by `darth-infra.schema.json`. An unrecognized key is
  rejected with the closest valid name suggested, rather than being ignored and its
  default deployed. Free-form tables (`project.tags`, `environment_variables`,
  `[environments.<name>]`) still accept any key, as their schemas allow.
- `"prod"` must appear in `project.environments` (it is reordered to first if needed).
- Service names must be unique; S3 bucket names must be unique.
- Every name in `services[].secrets` must exist in `[[secrets]]`.
- Every service named by an `[environments.<env>.services.<service>]` table must exist.
- Every service named by `rds.expose_to`, `s3_buckets[].connections[].service`,
  `cloudfront.connections[].service`, `alb.default_target_service`, and
  `alb.path_rules[].target_service` must exist.
- `alb.default_target_service` and `alb.path_rules[].target_service` must reference
  services that **have a `port`**.
- Setting `alb.default_target_service`, `alb.default_listener_priority`, or any
  `alb.path_rules` requires `alb.domain`; setting `alb.domain` requires
  `alb.default_target_service`.
- `rds.initial_snapshot_identifier` and `rds.initial_snapshot_credentials_secret` must
  be set together.
- `launch_type = "ec2"` requires `ec2_instance_type`; `ebs_volumes` are EC2-only.
- `cloudfront.enabled = true` requires `alb.domain` **and** at least one
  `cloudfront.cached_behaviors` entry.
- `cloudfront.custom_domain` and `cloudfront.certificate_arn` must be set together, and
  the certificate must be in `us-east-1`.
- `cloudfront.origin_https_only = true` requires an HTTPS ALB origin: in shared mode the
  resolved listener must be `HTTPS:443`; in dedicated mode `alb.certificate_arn` must be
  set.
- Any `cloudfront.*` field other than `price_class` requires `cloudfront.enabled = true`.
- `cloudfront_env_key` on a bucket connection requires `cloudfront = true` on that
  bucket. A service may not reuse the same `env_key` (or `cloudfront_env_key`) across
  two bucket connections.
- Listener priorities must be 1–50000 and unique within the config, including any
  set under `[environments.<env>.alb]`. At deploy time an explicitly configured
  priority must also be free on the resolved listener.
- TTLs must satisfy `min ≤ default ≤ max`.
- `alb.shared_alb_name` is required in shared mode (unless both
  `shared_listener_arn` and `shared_alb_security_group_id` are given). This is enforced
  at **deploy** time, not at render time.

## What your containers receive

Beyond your own `environment_variables`, `darth-infra` injects:

| Variable | Condition |
|---|---|
| The name in each `[[secrets]]` entry listed in `services[].secrets` | always |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | service is in `rds.expose_to` |
| `DB_SECRET_ARN` | service has any RDS-backed secret |
| Each bucket connection's `env_key` (bucket name) | per `[[s3_buckets.connections]]` |
| Each connection's `cloudfront_env_key` (bucket CDN URL) | bucket has `cloudfront = true` |
| Each `cloudfront.connections[].env_key` (ALB CDN URL) | `cloudfront.enabled = true` |
| A bucket's `preview_fallback_env_key` | preview environments with a fallback bucket |

You can rename the database variables by declaring explicit `rds`-sourced secrets, e.g.:

```toml
[[secrets]]
name = "DATABASE_HOST"
source = "rds"
existing_secret_name = "host"
```

## Complete worked examples

### Minimal: one web service behind a shared ALB

This is the smallest config that deploys successfully.

```toml
#:schema ./darth-infra.schema.json

[project]
name = "my-webapp"
aws_region = "us-east-1"
vpc_name = "artshumrc-prod-standard"
environments = ["prod"]

[[services]]
name = "web"
dockerfile = "Dockerfile"
port = 8000
health_check_path = "/healthz"

[alb]
mode = "shared"
shared_alb_name = "artshumrc-prod-alb"
domain = "myapp.example.com"
default_target_service = "web"
```

```bash
darth-infra init --non-interactive --config darth-infra.toml
darth-infra deploy --env prod --with-images
```

### Full: web + worker, RDS, S3 + CloudFront, secrets, two environments

```toml
#:schema ./darth-infra.schema.json

[project]
name = "my-webapp"
aws_region = "us-east-1"
vpc_name = "artshumrc-prod-standard"
environments = ["prod", "dev"]

[project.tags]
owner = "web-team"

[[services]]
name = "django"
dockerfile = "Dockerfile"
build_context = "."
port = 8000
health_check_path = "/health"
cpu = 512
memory_mib = 1024
desired_count = 2
secrets = ["DJANGO_SECRET_KEY"]
environment_variables = { DJANGO_ALLOWED_HOSTS = "{hostname}", SITE_URL = "{domain}" }

[[services]]
name = "worker"
dockerfile = "Dockerfile"
command = "celery -A app worker -l info"
secrets = ["DJANGO_SECRET_KEY"]
# no `port` — background worker, not attached to the ALB

[rds]
database_name = "myapp"
instance_type = "db.t4g.micro"
allocated_storage_gb = 20
expose_to = ["django", "worker"]
engine_version = "15"

[[s3_buckets]]
name = "media"
mode = "seed-copy"
seed_source_bucket_name = "legacy-media-bucket"
seed_non_prod_only = true
cloudfront = true
cors = true

[[s3_buckets.connections]]
service = "django"
env_key = "MEDIA_BUCKET"
cloudfront_env_key = "MEDIA_CDN_URL"

[[s3_buckets.connections]]
service = "worker"
env_key = "MEDIA_BUCKET"
read_only = true

[alb]
mode = "shared"
shared_alb_name = "artshumrc-prod-alb"
domain = "myapp.example.com"
default_target_service = "django"

[cloudfront]
enabled = true
origin_https_only = true
custom_domain = "cdn.myapp.example.com"
certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555"
price_class = "PriceClass_100"

[[cloudfront.connections]]
service = "django"
env_key = "APP_CDN_URL"

[[cloudfront.cached_behaviors]]
name = "static"
path_pattern = "/static/*"
compress = true
default_ttl_seconds = 86400
query_strings = "none"
cookies = "none"

[[secrets]]
name = "DJANGO_SECRET_KEY"
source = "generate"
length = 50

[environments.dev]
instance_type_override = "db.t4g.micro"

[environments.dev.tags]
cost-center = "sandbox"
```

Deploy it:

```bash
darth-infra render                        # sanity-check that templates build
darth-infra deploy --env prod --with-images
darth-infra deploy --env dev  --with-images
```

## Commands

| Command | What it does |
|---|---|
| `darth-infra init` | First-run project creation. Opens the guided editor; writes files only after you confirm in Review. `--non-interactive --config <path>` scaffolds directly from an existing TOML. `-o/--output <dir>` sets the output directory. `--no-skill` skips installing the agent authoring skill. |
| `darth-infra tui` | Document-preserving editor for an existing `darth-infra.toml`. Save with Ctrl+S. Preserves your comments, ordering, and formatting. Never renders or deploys. |
| `darth-infra render` | Regenerates `templates/` from the TOML. No AWS calls. `-o/--output <dir>` renders elsewhere. |
| `darth-infra install-skill` | Installs the config-authoring skill so a coding agent can edit `darth-infra.toml` directly. See [Editing the config with an agent](#editing-the-config-with-an-agent). |
| `darth-infra deploy --env <name>` | Regenerates templates, resolves AWS lookups, validates, then deploys via a CloudFormation change set. |
| `darth-infra build` | Builds Docker images for all services (`--service <name>` for one). |
| `darth-infra push --env <name>` | Tags and pushes images to ECR as `:latest` plus an immutable `build-<timestamp>` tag. |
| `darth-infra status --env <name>` | Shows running/desired/pending task counts per service. |
| `darth-infra logs <service> --env <name>` | Tails CloudWatch logs. `-f` to follow, `--since 30m` to change the window. |
| `darth-infra exec <service> --env <name>` | Interactive shell in a running task via ECS Exec. `--command` to change the shell. |
| `darth-infra secret <NAME> --env <name>` | Prints a secret value to stdout. `--json-key <key>` extracts a field from a JSON secret. |
| `darth-infra env --env <name>` | Appends all configured secrets to a `.env` file (`--file` to change the path). |
| `darth-infra destroy --env <name>` | Deletes the environment's stack. `--force` skips the prompt. Prod can only be destroyed after all other environments. |

Useful `deploy` flags:

```bash
darth-infra deploy --env prod --with-images    # build + push images, then deploy
darth-infra deploy --env prod --no-execute     # create the change set but don't run it
darth-infra deploy --env prod --cancel         # cancel an in-flight stack update
darth-infra deploy --env prod --verify-noop    # release gate: exit 0 only if nothing
                                               #   would change (read-only)
darth-infra deploy --env pr-123 --preview-from prod   # dynamic preview environment
```

`--cancel`, `--verify-noop`, `--with-images`, and `--no-execute` are mutually exclusive
in most combinations; the CLI tells you when a combination is rejected.

For a brand-new environment, `--with-images` first runs a bootstrap deploy with
`desired_count = 0` so the ECR repositories exist before the image push, then builds,
pushes, and deploys for real.

> **The TOML gets rewritten.** `darth-infra render` rewrites `darth-infra.toml` in
> canonical form — defaults are expanded and hand-written comments are dropped.
> `deploy`, `build`, `push`, `exec`, `env`, and `destroy` rewrite it too whenever they
> bump `cli_version_floor`. Use `darth-infra tui` when you want comment-preserving
> edits, and keep the file in version control.

## Naming conventions

Every AWS resource name is derived from the project and environment names:

| Resource | Name |
|---|---|
| CloudFormation stack | `<project>-ecs-<env>` |
| ECS cluster | `<project>-<env>` |
| ECS service | `<project>-<env>-<service>` |
| CloudWatch log group | `/ecs/<project>-<env>-<service>` |
| ECR repository | `<project>/<env>/<service>` |
| Local Docker image tag | `<project>-<service>:latest` |
| S3 bucket (managed) | `<project>-<env>-<bucket name>` |
| RDS instance | `<project>-<env>-db` |
| RDS credentials secret | `<project>-<env>-rds-credentials` |
| Generated secret | `/darth-infra/<project>/<env>/<SECRET_NAME>` |
| Dedicated ALB | `<project>-<env>-alb` |
| CFN artifact bucket | `darth-infra-artifacts-<account>-<region>` |

## How environments work

Adding an environment is one line:

```toml
[project]
environments = ["prod", "dev", "feature-xyz"]
```

```bash
darth-infra deploy --env feature-xyz
```

Compared to prod, non-prod environments automatically:

- Restore RDS from the latest automated prod snapshot instead of starting empty. (Prod
  itself starts empty unless it was adopted from a snapshot on its first deploy — see
  [Adopting an existing database](#adopting-an-existing-database).)
- Get environment-prefixed hostnames — `dev.myapp.example.com` for `alb.domain = "myapp.example.com"`.
- Generate their own secrets.
- Apply the per-bucket S3 mode: `managed` creates a fresh bucket, `existing` reuses one,
  `seed-copy` creates a fresh bucket and runs a one-time seed copy from the source.
- Use `Delete` rather than `Snapshot` deletion policies for stateful resources.

**Prod must be deployed first.** Any other environment refuses to deploy until the
`<project>-ecs-prod` stack exists.

## Generated project layout

```
my-webapp-infra/
  darth-infra.toml               # config — source of truth
  darth-infra.schema.json        # copied in for editor autocompletion
  README.md                      # generated project readme
  templates/
    generated/                   # OVERWRITTEN on every render/deploy — do not edit
      root.yaml
      services/
        <service>.yaml
    custom/
      overrides.yaml             # yours; created once and never overwritten
  .darth-infra/build/<env>/      # packaged templates (build artifacts)
```

Put manual CloudFormation additions in `templates/custom/overrides.yaml`. It is deployed
as a nested stack and is never regenerated.

## AWS permissions

The deploying principal needs, at minimum, permission to:

- **CloudFormation**: create/update/delete stacks and change sets, describe stacks,
  events, and resources.
- **EC2**: `DescribeVpcs`, `DescribeSubnets`, `DescribeSecurityGroups`, plus security
  group and (for EC2 launch type) instance/ASG/EBS management.
- **ELBv2**: describe load balancers, listeners, and rules; create target groups and
  listener rules.
- **ECS / ECR**: full management of clusters, services, task definitions, and
  repositories; `ecr:GetAuthorizationToken` for image pushes.
- **IAM**: create and pass the task and execution roles.
- **Secrets Manager**: create, describe, and read the project's secrets.
- **S3**: manage project buckets and the `darth-infra-artifacts-*` bucket.
- **RDS**: manage instances and read snapshots (if `[rds]` is configured).
- **CloudFront**, **Route 53**, **Cloud Map**, **CloudWatch Logs**, **STS
  GetCallerIdentity** as your configuration requires.

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `Could not find darth-infra.toml …` | Run from inside the project, or run `darth-infra init` first. |
| `This project requires darth-infra CLI >= X` | Upgrade: `uv tool upgrade darth-infra`. |
| `'prod' must be in the environments list` | Add `"prod"` to `project.environments`. |
| `Prod stack '<project>-ecs-prod' must be deployed before …` | `darth-infra deploy --env prod` first. |
| `alb.shared_alb_name is required in shared mode` | Set it, or give both `shared_listener_arn` and `shared_alb_security_group_id`. |
| `Expected exactly one VPC with Name=…` | The `vpc_name` tag matches zero or multiple VPCs — pin `project.vpc_id`. |
| `Resolved N private subnets … at most 16` | Pin an explicit `project.private_subnet_ids` list. |
| `Secret 'X' source is 'env' but environment variable is not set` | Export `X=<secret-name-or-arn>` in your shell before deploying. |
| `cloudfront.origin_https_only requires shared ALB listener HTTPS:443` | Point at an HTTPS:443 listener or set `origin_https_only = false`. |
| `Docker buildx is required for image builds` | Install/enable buildx: <https://docs.docker.com/go/buildx/>. |
| `cloudformation package failed` | The AWS CLI v2 is missing or credentials are unset. |

To inspect what a deploy *would* do without touching AWS state:

```bash
darth-infra render                       # generate templates locally
darth-infra deploy --env prod --no-execute   # create the change set only
```

## Contributing

This project uses [changesets](https://github.com/changesets/changesets) for version
management and releases.

When you make a change that should be released, add a changeset before opening your PR:

```bash
npx @changesets/cli
```

You'll be prompted to select a version bump type (major, minor, or patch) and write a
summary of your change. Commit the generated changeset file alongside your code.

When changesets are merged to `main`, a "Version Release" PR is automatically opened.
Merging that PR triggers a GitHub release with the built Python wheel attached.

Run the test suite with:

```bash
uv sync
uv run pytest
```
