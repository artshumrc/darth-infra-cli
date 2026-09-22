---
"darth-infra": minor
---

Let a project that already deploys without `[rds]` adopt its database by snapshot restore.

`initial_snapshot_identifier` and `initial_snapshot_credentials_secret` were honoured only while the `<project>-ecs-prod` stack did not exist. The guard read the deployed `RdsSnapshotIdentifier` parameter and treated any non-`None` result as authoritative, so a project that cut over to this CLI with its database left outside — hand-made, or owned by the tool being migrated away from — could never bring it under management. Adding `[rds]` produced an empty instance instead of a restore, and because preview environments seed from `<project>-prod-db`, that project could not use them at all.

A stack that carries no `RdsSnapshotIdentifier` parameter has no database to protect: the key's absence means `[rds]` was never configured, which is a different case from the empty value a live managed instance records. The guard now distinguishes them, so adding `[rds]` to a deployed project restores prod's data at the storage layer while the original database keeps serving. Nothing repoints the application — the restored instance is created alongside it, to cut over deliberately once verified. A managed database deployed without a snapshot still never acquires one.
