---
"darth-infra": patch
---

Allow `[rds].engine_version` to be raised across a PostgreSQL major version.

The RDS instance now renders `AllowMajorVersionUpgrade: true`. Without it CloudFormation rejects any `EngineVersion` change that crosses a major version, so bumping `engine_version` from e.g. `"15"` to `"16"` failed the stack update. The property is inert unless the rendered `EngineVersion` actually changes.
