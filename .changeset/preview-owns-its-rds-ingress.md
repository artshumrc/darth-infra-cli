---
"darth-infra": patch
---

Preview environments now create RDS ingress rules inside their service stacks, ensuring database access is available before ECS services start and avoiding CloudFormation dependency deadlocks. They also clear inherited ALB listener priorities so preview rules are allocated from the configured preview range, while named environments retain their existing stack layout and priorities.
