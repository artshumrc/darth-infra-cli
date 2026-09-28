---
"darth-infra": minor
---

Back up prod's database to S3 every month with `pg_dump`, keep the files indefinitely, and email `backup_alert_email` when a run fails. Automated backups now default to 35 days, and the monthly backup is on by default, so existing prod stacks gain these resources on their next deploy.
