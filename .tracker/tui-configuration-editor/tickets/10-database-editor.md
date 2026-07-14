## What to build

Deliver a complete Database section for the existing singleton RDS model. Users
must be able to enable or remove RDS, edit common and Advanced fields, control
service exposure, inspect the environment variables provided by existing RDS
semantics, and understand every affected reference before removal.

## Where to start

- Read the current RDS screen and managed-secret synchronization in
  `src/darth_infra/tui/screens/rds.py`.
- Read `RdsConfig`, RDS validation, and environment override behavior in
  `src/darth_infra/config/models.py`.
- Read RDS render-context secret derivation in
  `src/darth_infra/scaffold/context.py`; preserve it exactly.
- Read current loader/serializer coverage for `engine_version` and
  `backup_retention_days`, which the legacy TUI fails to rebuild.
- Reuse Services reference impact and the shared field/help/Advanced controls.

## Contract

- Cover every persisted RDS field: database name, instance type, allocated
  storage, exposed services, engine version, and backup retention days.
- Common fields are visible; engine version and backup retention are Advanced
  and auto-expand when explicitly configured or invalid.
- Enabling RDS preserves existing defaults and established RDS secret/env-var
  behavior. This ticket does not redesign bindings or add new aliases.
- Service exposure uses a multi-service selector and participates in reference
  impact when services are deleted.
- Removing RDS shows the complete configuration impact, including RDS-backed
  secret declarations/bindings managed by existing behavior, and requires one
  explicit confirmation.
- Confirmed removal and cleanup form one reversible document transaction.
- RDS instance-type normalization remains existing model behavior; raw document
  presence and formatting remain preserved by `ProjectDocument`.
- Environment-specific RDS instance override editing remains in ticket 13, but
  Database shows which environments currently override the base value and links
  to Environments when available.
- Actual secret values are never fetched or displayed.

## Out of scope

- Do not change RDS engine, snapshot, secret attachment, or generated template
  semantics.
- Do not add multiple databases.
- Do not move environment override editing into Database.
- Do not redesign the existing `DATABASE_*` or `POSTGRES_*` behavior.

## Acceptance criteria

- [ ] Pilot enables RDS and edits every registered base RDS field.
- [ ] Existing engine version and backup retention survive a no-op editor save.
- [ ] Service exposure updates references without creating duplicate bindings.
- [ ] Removing RDS presents the complete impact and applies cleanup atomically only after confirmation.
- [ ] Revert restores RDS and all cleaned configuration references.
- [ ] Actual secret values are absent from widgets, logs, notifications, and test snapshots.
- [ ] Existing RDS render-context and builder behavior remains green.

Run:

```bash
uv run pytest tests/test_tui_database_section.py
uv run pytest tests/test_render_context.py tests/test_builders.py tests/test_preview_environments.py
uv run pytest
git diff --check
```

Success means all tests pass and `git diff --check` emits no output.

## Blocked by

- Ticket 04: `04-editor-shell-project.md`
- Ticket 07: `07-advanced-services-references.md`
