# 08 — EC2 launch-type slice

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

Port the EC2 launch-type path in the service template: the instance IAM role
and instance profile, launch template (including user-data script content),
auto-scaling group, capacity wiring on the ECS service, and the launch-type
conditional differences in the task definition (network mode, memory/cpu
placement).

## Where to start

- `src/darth_infra/templates/cfn/nested/service.yaml.j2` — instance role
  (271), `InstanceProfile` (292), `LaunchTemplate` (305, note the user-data
  `Fn::Base64`/`Fn::Sub` block), `AutoScalingGroup` (376), and the
  `LaunchType`-conditional branches inside `TaskDefinition` (402) and
  `ECS::Service` (603).
- `src/darth_infra/scaffold/generator.py` —
  `_resolve_user_data_script_content` (line 25): user-provided script content
  gets `${` → `$${` escaped before landing in the `Fn::Sub` body. Ticket 01
  carried this into the context; consume it, don't reimplement.
- `LaunchType` enum in `src/darth_infra/config/models.py`.

## Contract

- The user-data escaping contract holds: user script content is inert inside
  `Fn::Sub` (no accidental interpolation), byte-for-byte equivalent to
  today's escaping behavior.
- Launch-type branching is config-driven (mirrors Jinja `{% if %}` blocks) —
  not a CFN Condition — exactly as today. Logical IDs and ASG/launch-template
  property shapes match Jinja output.

## Out of scope

- The user-data script file **copying** into the project dir (a
  `generate_project` I/O concern — stays where it is, cutover ticket keeps
  it).
- No CLI wiring, no `.j2` deletions, no config model changes.

## Acceptance criteria

- [ ] An EC2 launch-type fixture (with an inline user-data script containing
      `${literal}`) builds a service template structurally matching Jinja:
      role, instance profile, launch template with correctly-escaped
      user data, ASG, and ECS service capacity wiring.
- [ ] A Fargate fixture is unchanged by this slice (no EC2 resources leak
      in).
- [ ] cfn-lint passes over rendered fixture output; full suite green.

Commands:

```
uv run pytest
uv run pytest tests/ -k "ec2 or launch"
```

## Blocked by

- 03 (`03-service-stack-core.md`)

## Implementation blocker

On 2026-07-14, the EC2 builder path and structural Jinja-parity tests were
completed. The parity test passes, including the legacy `$${literal}` user-data
escaping, EC2 role/profile, launch template, EBS mappings, auto-scaling group,
task-definition branches, and ECS service launch type. The Fargate isolation
test also passes.

The mandatory `cfn-lint` gate conflicts with exact legacy parity in two places:

- The Jinja template adds `Tags` to `AWS::IAM::InstanceProfile`, but
  `cfn-lint 1.53.0` rejects that property with `E3002`.
- The required legacy `${` to `$${` user-data escaping is preserved exactly,
  but `cfn-lint` interprets the remaining `${literal}` portion as an unresolved
  `Fn::Sub` variable and rejects it with `E1021`.

Decision (2026-07-14): remove the unsupported instance-profile `Tags` and use
CloudFormation's launch-template-safe literal escaping (`\${!literal}`).
Exact structural parity is explicitly waived for those invalid legacy shapes;
all logical IDs and supported properties remain unchanged. Partial
implementation and tests are left uncommitted in the worktree.

## Completion note (2026-07-14)

The EC2 launch-type builder path and its tests were already committed in
`f286653` ("require valid cloudflormation"). Verified the current tree against
every acceptance criterion; no new builder/test code was needed.

- `_ec2_config` fixture carries an inline `${literal}` user-data script; the
  EC2 service template builds `Ec2InstanceRole`, `Ec2InstanceProfile` (no
  `Tags`, per the decision), `LaunchTemplate` (with EBS mappings + ASG tag
  specs), `AutoScalingGroup`, and wires `EcsService` capacity with
  `LaunchType: EC2`.
- User-data escaping is `\${!literal}` (CloudFormation launch-template-safe),
  applied upstream in `context._resolve_user_data_script_content`
  (`content.replace("${", r"\${!")`) — reflects the recorded decision, not the
  legacy `$${literal}`.
- Fargate fixture leaks no EC2 resources (`LaunchType: FARGATE`).
- `cfn-lint 1.53.0` passes (exit 0, warnings only) over both rendered EC2 and
  Fargate service templates; full suite green (93 passed).
