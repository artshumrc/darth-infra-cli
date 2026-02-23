# darth-infra

A CLI tool for deploying websites to AWS ECS with multi-environment support.

## Installation

```bash
uv tool install .
```

## Quick Start

```bash
# Interactive project setup
darth-infra init

# Resume a previously cancelled/incomplete wizard session
darth-infra init --seed wizard-export.json

# Deploy production
darth-infra deploy --env prod

# Regenerate CloudFormation templates from darth-infra.toml (no deploy)
darth-infra render

# Deploy a feature environment
darth-infra deploy --env feature-xyz

# Build & push Docker images
darth-infra build
darth-infra push --env prod

# Operations
darth-infra logs django --env prod -f
darth-infra exec django --env prod
darth-infra secret DJANGO_SECRET_KEY --env prod
darth-infra status --env prod
darth-infra destroy --env dev
```

## How It Works

1. **`darth-infra init`** — Interactive Textual TUI that walks you through project setup:
   - Project name, region, VPC
   - ECS services (name, Dockerfile, port)
   - Optional RDS PostgreSQL database
   - Optional S3 buckets (with optional CloudFront)
   - ALB mode and cluster routing (shared or dedicated)
   - Secrets management (auto-generated or from env vars)

2. The TUI scaffolds a **complete CloudFormation YAML project** that you own and can customize.

3. **`darth-infra deploy --env <name>`** deploys via CloudFormation change sets. Prod must be deployed first.

4. Adding a new environment is as simple as editing `darth-infra.toml`:
   ```toml
   [project]
   environments = ["prod", "dev", "feature-xyz"]
   ```
   Then: `darth-infra deploy --env feature-xyz`

5. Non-prod environments automatically:
   - Clone RDS from the latest prod snapshot
   - Create fresh S3 buckets with the same config
   - Generate new secrets
   - Get environment-prefixed subdomains (e.g., `dev.myapp.example.com`)

The interactive wizard always writes a raw draft/export file (`wizard-export.json` by default),
including incomplete values, so sessions can be resumed later.
Full wizard answers (including incomplete draft values) live in `wizard-export.json`.

## Configuration

The `darth-infra.toml` file is the source of truth. Example:

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
instance_type = "t4g.micro"
expose_to = ["django"]

[[s3_buckets]]
name = "media"
cloudfront = true

[alb]
mode = "shared"
domain = "myapp.example.com"
default_target_service = "django"
default_listener_priority = 100

[[secrets]]
name = "DJANGO_SECRET_KEY"
source = "generate"
```

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
