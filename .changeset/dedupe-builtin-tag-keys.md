---
"darth-infra": patch
---

Let a configured tag key replace the built-in tag it shadows, instead of emitting both.

`Project`, `Environment`, `Service` and the autoscaling `Name` tag were always rendered alongside every configured tag, so a project tagging its resources `project` or `environment` got both casings. S3, ECR and ECS compare tag keys case-sensitively and accept that; IAM does not, and failed every `TaskRole` and `TaskExecutionRole` in the stack with "Duplicate tag keys found. Please note that Tag keys are case insensitive." A project could not use the lowercase keys AWS cost allocation was already activated on, because cost-allocation keys are themselves case-sensitive and `Project` is a different billing dimension from `project`.

A configured key now suppresses the built-in whose key matches case-insensitively, keeping the configured casing. The substitution is conditional on that tag's own parameter being non-empty, so an environment that does not set the key still gets the built-in rather than no tag at all.
