# darth-infra

A CLI tool for deploying websites to AWS ECS with multi-environment support.

## Installation

```bash
uv tool install .
```

## Docker Build Prerequisite

`darth-infra build` uses Docker BuildKit via `docker buildx`. If `buildx` is not available, install/enable it:

https://docs.docker.com/go/buildx/

## Quick Start

```bash
# Interactive project setup
darth-infra tui

# Re-run TUI (it auto-rehydrates from darth-infra.toml when present)
darth-infra tui

# Deploy production
darth-infra deploy --env prod

# Cancel an in-flight deploy/update
darth-infra deploy --env prod --cancel

# Regenerate CloudFormation templates from darth-infra.toml (no deploy)
darth-infra render

# Deploy a feature environment
darth-infra deploy --env feature-xyz

# Build & push Docker images
darth-infra build
darth-infra push --env prod

# Deploy and include build/push in one flow
darth-infra deploy --env prod --with-images

# Operations
darth-infra logs django --env prod -f
darth-infra exec django --env prod
darth-infra secret DJANGO_SECRET_KEY --env prod
darth-infra status --env prod
darth-infra destroy --env dev
```

## How It Works

1. **`darth-infra tui`** — Interactive Textual editor with validation for `darth-infra.toml`:
   - Project name, region, VPC
   - ECS services (name, Dockerfile, port)
   - Optional RDS PostgreSQL database
   - Optional S3 buckets (with optional CloudFront)
  - Shared ALB and cluster routing
  - Optional CloudFront distribution in front of ALB with allowlisted cached paths
   - Secrets management (auto-generated or from env vars)

2. The TUI scaffolds a **complete CloudFormation YAML project** that you own and can customize.

3. **`darth-infra deploy --env <name>`** deploys via CloudFormation change sets. Prod must be deployed first.

  If you need to stop an in-progress update, run:
  `darth-infra deploy --env <name> --cancel`

  Use **`--with-images`** to include Docker build/push before the deploy. For first-time environments,
  `darth-infra` runs a bootstrap pass to provision ECR repositories before image push.

4. Adding a new environment is as simple as editing `darth-infra.toml`:
   ```toml
   [project]
   environments = ["prod", "dev", "feature-xyz"]
   ```
   Then: `darth-infra deploy --env feature-xyz`

5. Non-prod environments automatically:
   - Clone RDS from the latest prod snapshot
   - Apply S3 behavior per bucket mode:
     - `managed`: create fresh env bucket (`{project}-{env}-{name}`)
     - `existing`: reuse a pre-existing bucket
     - `seed-copy`: create fresh env bucket and run one-time seed copy from source
   - Generate new secrets
   - Get environment-prefixed subdomains (e.g., `dev.myapp.example.com`)

The interactive wizard rehydrates from `darth-infra.toml` when present.
On quit/cancel, if confirmed wizard values differ from an existing `darth-infra.toml`,
you are prompted to save or disregard those changes.

## Configuration

The `darth-infra.toml` file is the source of truth and seed source for the wizard. Example:

```toml
[project]
name = "my-webapp"
aws_region = "us-east-1"
vpc_name = "artshumrc-prod-standard"
environments = ["prod", "dev"]

[[services]]
name = "django"
dockerfile = "Dockerfile"
port = 8000
secrets = ["DJANGO_SECRET_KEY"]
s3_access = ["media"]

[rds]
database_name = "myapp"
instance_type = "db.t4g.micro"
expose_to = ["django"]

[[s3_buckets]]
name = "media"
mode = "seed-copy"
seed_source_bucket_name = "legacy-media-bucket"
seed_non_prod_only = true
cloudfront = true

[alb]
mode = "shared"
domain = "myapp.example.com"
default_target_service = "django"
default_listener_priority = 100

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
name = "images"
path_pattern = "/images/*"
query_strings = "all"
cookies = "none"
forward_authorization_header = false

[[secrets]]
name = "DJANGO_SECRET_KEY"
source = "generate"
```

Notes:
- `cloudfront.custom_domain` and `cloudfront.certificate_arn` must be set together.
- CloudFront certificates must be issued in `us-east-1`.
- `cloudfront.origin_https_only = true` requires ALB origin HTTPS compatibility:
  - shared mode: selected shared listener must be `HTTPS:443`
  - dedicated mode: `alb.certificate_arn` must be set
- Configure DNS for CloudFront custom domains externally (for example, Route53 alias to distribution).

Generated secrets are named using:

`/darth-infra/<project name>/<env>/<secret name>`

## Architecture

Each scaffolded project contains:

```
my-webapp-infra/
  darth-infra.toml        # Config (source of truth)
  templates/
    generated/
      root.yaml            # Regenerated from TOML
      services/
        <service>.yaml     # Regenerated service templates
    custom/
      overrides.yaml       # User-owned CFN overrides (not overwritten)
```

## Contributing

This project uses [changesets](https://github.com/changesets/changesets) for version management and releases.

When you make a change that should be released, add a changeset before opening your PR:

```bash
npx @changesets/cli init 
npx @changesets/cli
```

You'll be prompted to select a version bump type (major, minor, or patch) and write a summary of your change. Commit the generated changeset file alongside your code.

When changesets are merged to `main`, a "Version Release" PR is automatically opened. Merging that PR triggers a GitHub release with the built Python wheel attached.

### Installing from a GitHub Release

```bash
pip install https://github.com/artshumrc/darth-infra-cli/releases/download/v0.1.0/darth_infra-0.1.0-py3-none-any.whl
```
