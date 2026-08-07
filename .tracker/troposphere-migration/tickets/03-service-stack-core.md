# 03 — Service-stack core builder (completes the tracer path)

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

The nested service template's always-present parts as troposphere builders,
completing the minimal end-to-end path: a bare shared-ALB Fargate config now
produces a complete root **and** service template through
`build_project_templates`. Covers: template Parameters, log group, the three
security-group resources, the IAM roles (execution, task — including the
conditional SES send-email policy — and their statements), the task
definition, target group, the two listener rules, and the ECS service.

## Where to start

- `src/darth_infra/templates/cfn/nested/service.yaml.j2` — porting source.
  Core sections: Parameters (top), `AWS::Logs::LogGroup` (94), security
  groups (108–149), IAM roles (150–304 — the SES policy block is inside the
  task role), `AWS::ECS::TaskDefinition` (402), `ServiceDiscovery::Service`
  (509 — SKIP, ticket 06), `TargetGroup` (529), `ListenerRule`s (555, 577),
  `AWS::ECS::Service` (603). Skip EC2/ASG resources (305–401, ticket 08).
- Ticket 02's `ProjectTemplates` mapping and test harness.
- Env-var/secret wiring in the task definition: port only what the minimal and
  SES fixtures exercise; RDS/external-secret wiring deepens in ticket 05.

## Contract

- `build_project_templates` now returns one service Template per configured
  service at `templates/generated/services/{name}.yaml`, alongside root.
- Logical IDs and parameter names exactly match the Jinja output, including
  per-service computed names via ticket 01's context.
- `Fn::Sub` bodies (e.g. container definitions interpolating parameters) are
  ported semantically — the `${` escaping helper behavior for user-data
  content stays equivalent where it applies to core sections.
- The conditional SES policy (when `enable_ses_send_email` is set) emits the
  same PolicyName and action list as today — ticket 09's structural
  validation will assert on it.

## Out of scope

- EC2 launch type resources (launch template, ASG, instance profile,
  user-data) — ticket 08. Fargate-only here.
- Service discovery service resource — ticket 06.
- RDS-sourced env vars/secrets beyond what compiles for the minimal fixture —
  ticket 05.
- No CLI/generate_project wiring, no `.j2` deletions, no config model changes.

## Acceptance criteria

- [ ] For the minimal shared-ALB Fargate fixture, `build_project_templates`
      returns root + service templates; the service template's `to_dict()`
      matches the Jinja-rendered equivalent structurally (logical IDs,
      properties) for all core resources.
- [ ] A fixture with `enable_ses_send_email=True` produces the SES policy
      object with actions `ses:SendEmail`, `ses:SendRawEmail`,
      `ses:GetSendQuota` in the task role.
- [ ] Service template YAML passes cfn-lint via the harness.
- [ ] Full suite green; Jinja pipeline untouched.

Commands:

```
uv run pytest
uv run pytest tests/ -k "builders or service"
```

## Blocked by

- 02 (`02-pipeline-and-root-core.md`)
