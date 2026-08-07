# 02 — Pipeline skeleton + root-stack core builder

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

The new pipeline's spine: add the `troposphere` and `cfn-flip` dependencies,
create the `build_project_templates` seam, and implement the root stack's
always-present parts as troposphere builders — Parameters, Conditions,
Outputs, ECS cluster, per-service ECR repositories, nested-stack resources
(service stacks + the custom-overrides stack), and the additional-tags
plumbing. Also build the structural test harness (including a cfn-lint helper)
that every later slice reuses. The pipeline is **inert**: nothing in
`generate_project` or the CLI calls it yet.

## Where to start

- `src/darth_infra/templates/cfn/root.yaml.j2` — the porting source.
  Core sections: Parameters/Conditions (lines 12–101), `EcsCluster` (104),
  ECR repository (417), nested `AWS::CloudFormation::Stack` resources (518,
  618), Outputs (end of file). Skip for now: ALB/listeners (133–225),
  CloudFront (226–416), RDS/secrets (319, 432–517), service discovery (118).
- Ticket 01's `derive_render_context` — the only input to builders besides
  `ProjectConfig`.
- `src/darth_infra/cli/cfn.py:440` (`package_template`) — shows that nested
  stack `TemplateURL` values are **local relative paths** rewritten by
  `aws cloudformation package`; emit them as plain strings.

## Contract

- New package (suggested: `src/darth_infra/scaffold/builders/`) exposing:

  ```python
  def build_project_templates(config: ProjectConfig) -> ProjectTemplates: ...
  # ProjectTemplates: mapping of relative output path -> troposphere Template,
  # e.g. {"templates/generated/root.yaml": <Template>,
  #       "templates/generated/services/web.yaml": <Template>}
  ```

  Pure function, no I/O. This is the single structural seam for all tests and
  (later) deploy-time validation. Service templates may be stubs/absent until
  ticket 03 — but the mapping shape is fixed now.
- Logical IDs, parameter names, condition names, and output names must match
  the Jinja template exactly (permanent public contract). When a name is
  computed, compute it via ticket 01's context — never inline.
- Feature-conditional parameters/conditions (RDS, service discovery, secrets,
  cluster routing, tag parameters) are emitted by the same rules as the Jinja
  `{% if %}`/`{% for %}` blocks — driven by config, in this ticket where the
  block is part of the Parameters/Conditions sections.
- YAML emission: `Template.to_yaml()` (cfn-flip short-form intrinsics). Add a
  test-harness helper that (a) returns `Template.to_dict()` for structural
  assertions and (b) serializes to YAML and runs cfn-lint over it.
- Dropping to raw dicts is allowed only where troposphere cannot model a
  construct, and each use gets a comment naming the gap.
- Add `cfn-lint` as a dev dependency; lint runs inside pytest (hermetic, no
  AWS credentials).

## Out of scope

- Do not modify `generate_project`, any CLI command, or delete any `.j2` file
  — the Jinja pipeline remains the shipping pipeline until ticket 10.
- No ALB, CloudFront, RDS, secrets, or service-discovery resources (tickets
  04–07) beyond their Parameters/Conditions entries.
- No service template internals (ticket 03).
- No changes to `config/models.py` or the TUI.

## Acceptance criteria

- [ ] `uv add troposphere cfn-flip` (runtime) and `cfn-lint` (dev) recorded in
      `pyproject.toml`/`uv.lock`.
- [ ] `build_project_templates(minimal_config)` returns a root Template whose
      `to_dict()` contains the exact Parameters, Conditions, `EcsCluster`,
      ECR, nested-stack resources, and Outputs the Jinja template produces
      for that config (names verified against rendered Jinja output by hand,
      asserted structurally in tests).
- [ ] Structural tests cover at least: minimal shared-ALB config, a config
      with extra tags (tag parameters + conditions), and a config with
      cluster routing (priority parameters present).
- [ ] Root template YAML output passes cfn-lint via the harness helper.
- [ ] Full suite green; Jinja pipeline untouched.

Commands:

```
uv run pytest                          # full suite green
uv run pytest tests/ -k builders      # new structural tests green
```

## Blocked by

- 01 (`01-typed-render-context.md`)
