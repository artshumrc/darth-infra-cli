---
"darth-infra": minor
---

Generate CloudFormation templates from a troposphere object pipeline instead of Jinja text templates. On the next render, files under `templates/generated/` will change formatting (key ordering, quoting, whitespace) — this is a one-time cosmetic diff. Deployed stacks are unaffected: an unchanged `darth-infra.toml` changes no real infrastructure, because every logical ID, parameter, and resource property is preserved exactly. Hand-edited `templates/custom/overrides.yaml` is still never overwritten.

Note that the deploy's change set is *not* empty on the cutover. Nested child templates are referenced by content-hashed S3 URLs, and troposphere serializes YAML differently, so every nested `AWS::CloudFormation::Stack` shows as `Modify` with a new `TemplateURL` even when nothing inside it changed. Verify with `darth-infra deploy --env <env> --verify-noop`, which compares leaf resources structurally and ignores that wrapper churn.

Also fixes a tag regression: dedicated-ALB HTTP/HTTPS listeners are tagged again. troposphere 4.10.2 omits `Tags` from its `Listener` spec, which silently dropped them. Only affects projects using `alb.mode = "dedicated"`.
