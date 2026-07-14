---
"darth-infra": minor
---

Generate CloudFormation templates from a troposphere object pipeline instead of Jinja text templates. On the next render, files under `templates/generated/` will change formatting (key ordering, quoting, whitespace) — this is a one-time cosmetic diff. Deployed stacks are unaffected: an unchanged `darth-infra.toml` produces a no-op deploy (empty changeset), because every logical ID, parameter, and resource property is preserved exactly. Hand-edited `templates/custom/overrides.yaml` is still never overwritten.
