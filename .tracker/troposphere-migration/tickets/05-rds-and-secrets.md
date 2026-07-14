# 05 — RDS + Secrets Manager slice

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

Port the data layer: the RDS instance with its security group, subnet group,
generated master secret and `SecretTargetAttachment`, the snapshot-restore
condition path, generated app secrets, and the service-side wiring — task
definitions consuming secret ARNs and RDS-derived environment variables
(host/port/dbname/username/password key mapping) across all secret sources
(`generate`, `rds`, external ARNs passed as parameters).

## Where to start

- `src/darth_infra/templates/cfn/root.yaml.j2` — app secret (319), RDS
  master secret (432), `RdsSecurityGroup` (456), `DBSubnetGroup` (468),
  `DBInstance` (480, note `HasRdsSnapshot` condition and DeletionPolicy),
  `SecretTargetAttachment` (509).
- `src/darth_infra/templates/cfn/nested/service.yaml.j2` — task-definition
  `Secrets`/`Environment` blocks (inside 402+), which resolve RDS JSON keys.
- Ticket 01's context: `_derive_rds_master_username`,
  `_normalize_rds_json_key`, secret logical-ID mangling, `rds_expose_to`.
- Existing scenarios in `tests/test_deploy_secret_validation.py` and the RDS
  parts of `tests/test_preview_environments.py` — port the template-facing
  assertions structurally here (deploy-layer assertions stay where they are).

## Contract

- Logical IDs for secrets use the exact mangling
  (`EnvSecretArn` + name stripped of `_`/`-` etc.) from ticket 01's context.
- `RdsSnapshotIdentifier`/`RdsSourceSecretArn`/`RdsInstanceType` parameters
  and `HasRdsSnapshot` condition behavior match Jinja exactly, including
  DeletionPolicy and snapshot-vs-fresh property differences.
- Secret JSON-key references in task definitions
  (`arn:...:secret:...:key::`-style dynamic references or `Fn::Sub` forms)
  are ported semantically — same resolved strings.

## Out of scope

- Deploy-time snapshot/secret resolution (`_resolve_rds_snapshot`,
  `_build_parameters` in `cli/cfn.py`) — deploy layer untouched.
- Structural deploy validation (ticket 09) — this ticket only builds.
- No CLI wiring, no `.j2` deletions, no config model changes.

## Acceptance criteria

- [ ] An RDS-enabled fixture builds root + service templates structurally
      matching Jinja output: DB instance (both snapshot and no-snapshot
      shapes), SG, subnet group, master secret + attachment.
- [ ] A fixture with each secret source (`generate`, `rds`, external)
      produces the correct task-definition `Secrets` entries and parameter
      declarations.
- [ ] RDS env-var key mapping (DATABASE_*/POSTGRES_* → host/port/dbname/
      username/password) is asserted structurally for an exposed service.
- [ ] cfn-lint passes over rendered fixture output; full suite green.

Commands:

```
uv run pytest
uv run pytest tests/ -k "rds or secret"
```

## Blocked by

- 03 (`03-service-stack-core.md`)

## Verification blocker

On 2026-07-14, the RDS and Secrets Manager implementation and focused tests
were completed. `uv run pytest tests/ -k "rds or secret"` passes all 17
selected tests, and the RDS-enabled service template passes `cfn-lint`.

The mandatory full-suite gate cannot pass while ticket 04's partial
implementation remains in the worktree: the minimal root-resource test sees
the new dedicated-ALB resources, and root-template lint rejects the legacy
listener `Tags` with `E3002`. The full run otherwise passes 85 of 87 tests.
Ticket 05 must be rerun, committed, and marked completed after the ticket 04
listener-tag decision is resolved.
