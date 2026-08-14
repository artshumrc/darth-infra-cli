---
"darth-infra": minor
---

- Add `[rds]` keys `initial_snapshot_identifier` and `initial_snapshot_credentials_secret`, restoring prod from an existing database's snapshot on its first deploy.
- Read the deployed RDS snapshot identifier and source credentials ARN back from the stack for every environment, not just active previews.
- Reject configuration keys the schema does not define, suggesting the closest valid name.
- Print config-file problems as CLI errors instead of tracebacks.
- Add `darth-infra install-skill`, installing the `darth-infra.toml` authoring skill to `.claude/skills/` and `.agents/skills/`.
- Install that skill from `darth-infra init`; `--no-skill` skips it.
