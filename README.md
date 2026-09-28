# darth-infra

A CLI that turns one `darth-infra.toml` into a multi-environment AWS ECS deployment:
ECS services, ECR, ALB routing, and optionally RDS PostgreSQL, S3, CloudFront, and
Secrets Manager. It generates CloudFormation YAML into your project and deploys it
through change sets.

**Full field, command, and troubleshooting reference:
[docs/configuration.md](docs/configuration.md).**

## Install

```bash
uv tool install git+https://github.com/artshumrc/darth-infra-cli.git          # latest
uv tool install git+https://github.com/artshumrc/darth-infra-cli.git@vX.Y.Z   # pinned
uv tool upgrade darth-infra
```

Needs Python ≥ 3.12, AWS credentials, AWS CLI v2, Docker `buildx`, and
`session-manager-plugin` for `exec`. Before the first deploy the account must already
have a VPC, a shared ALB (if `alb.mode = "shared"`), and ACM certificates for any HTTPS
domains. DNS outside preview environments is yours to manage.

## Using it

```bash
darth-infra init                             # guided editor, writes on confirm
darth-infra render                           # regenerate templates, no AWS calls
darth-infra deploy --env prod --with-images  # prod first — other envs require it
darth-infra deploy --env dev --with-images
darth-infra deploy --env prod --no-execute   # create change set only, to review
darth-infra status|logs|exec|secret ... --env prod
```

Edit config with `darth-infra tui` (comment-preserving) or let a coding agent do it
after `darth-infra install-skill`. `render` and version-floor bumps rewrite the TOML in
canonical form, dropping comments.

## How it works

```
darth-infra.toml
  → config/loader + models   parse, validate unknown keys (schema) and cross-field rules
  → scaffold/context         derive a typed, frozen RenderContext; all naming lives here
  → scaffold/builders        build troposphere Templates
  → templates/generated/     root.yaml + services/<service>.yaml
  → cli/cfn                  resolve AWS lookups, package, change set, execute
```

One template set serves every environment; differences flow through Parameters and
Conditions, never render-time specialization. User additions go in
`templates/custom/overrides.yaml`, which is written once and deployed as a nested stack.

## Repo map

| Path | What's there |
|---|---|
| `src/darth_infra/cli/` | Click commands (`main.py` registers them). `cfn.py` is the deploy engine: lookups, priority allocation, change sets, recovery |
| `src/darth_infra/config/` | `models.py` dataclasses + validation, `loader.py` TOML I/O, `document.py` comment-preserving edits, `schema.py` unknown-key check |
| `src/darth_infra/scaffold/` | `context.py` config → `RenderContext`, `builders/` troposphere templates, `generator.py` writes files |
| `src/darth_infra/tui/` | Textual editor used by `init` and `tui` |
| `src/darth_infra/skill/` | Agent skill installed by `install-skill` |
| `darth-infra.schema.json` | Field surface. Root copy and `src/darth_infra/` copy must match (tested) |
| `tests/` | pytest. `builders_expected.py` holds frozen structural template snapshots |
| `docs/adr/`, `CONTEXT.md` | Design decisions and domain glossary — read before touching generation |
| `.tracker/` | Specs and tickets for multi-step work |

## Rules that bite

- **No-op deploy contract.** Rendering an unchanged TOML with a new CLI version must
  yield an empty change set on every existing stack. YAML text may change; resources
  may not.
- **Logical IDs are permanent.** Renaming one replaces the resource — data loss for
  RDS and S3.
- **Troposphere spec lag is silent.** A property troposphere doesn't know gets dropped,
  not rejected. Keep `cfn-lint` current; see
  [ADR 0001](docs/adr/0001-troposphere-template-generation.md).
- **Adding a config field** means updating `models.py`, both schema copies, the TUI
  field registry, and the reference docs.
- Tests assert on built template structure, never rendered text.

## Develop

```bash
uv sync
uv run pytest
uv run darth-infra --help    # run from checkout
```

## Release

Uses [changesets](https://github.com/changesets/changesets). Add one with
`npx @changesets/cli` in any PR that should ship. Merging to `main` opens a "Version
Release" PR; merging that tags a GitHub release with the wheel and syncs
`pyproject.toml`.
