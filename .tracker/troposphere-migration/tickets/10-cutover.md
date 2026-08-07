# 10 — Cutover: wire the pipeline, delete Jinja CFN templates

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

The contract step of the expand–contract migration, shipped as one **minor**
release. `generate_project` switches to build → serialize → write via
`build_project_templates`; the deploy flow switches to the structural
validator; the CFN `.j2` templates and every text-based template assertion
are deleted. After this ticket, rendering an unchanged `darth-infra.toml`
must be a **no-op deploy** on existing stacks (verified for real in ticket
11).

## Where to start

- `src/darth_infra/scaffold/generator.py` — `generate_project` keeps its
  signature and every I/O behavior: output paths
  (`templates/generated/root.yaml`, `templates/generated/services/{name}.yaml`),
  write-once `templates/custom/overrides.yaml` (lines 138–140), user-data
  script copying, README rendering (stays Jinja — prose is not part of this
  migration), `darth-infra.toml` + JSON-schema emission.
- The overrides placeholder currently comes from
  `templates/cfn/custom/overrides.yaml.j2` — replace with a static string or
  tiny troposphere template producing the same content (WaitConditionHandle
  placeholder + project-name description). Write-once semantics unchanged.
- `src/darth_infra/cli/deploy_cmd.py:122,177` — swap in ticket 09's
  structural validator.
- Delete: `templates/cfn/root.yaml.j2`, `templates/cfn/nested/service.yaml.j2`,
  `templates/cfn/custom/overrides.yaml.j2`, the Jinja env setup for CFN
  rendering in `generator.py`, `_build_context` (fully superseded by ticket
  01's derivation), and the old text-based validator in `cli/cfn.py`.
- Port or delete remaining text-grepping tests: each scenario in
  `test_generator_cloudfront_alb.py` etc. must already have a structural
  counterpart (tickets 04–08); delete the text assertions, keep any scenario
  not yet covered by porting it structurally.

## Contract

- Public CLI surface, config schema, TUI, and deploy-layer behavior are
  unchanged. `jinja2` stays a dependency (README rendering).
- No text-based assertion on rendered CFN YAML survives anywhere in `src/`
  or `tests/` (grep for `read_text` + template paths in tests to confirm).
- Smoke tests at the `generate_project` seam: files land at the frozen paths,
  output parses as YAML, cfn-lint passes, `custom/overrides.yaml` is not
  overwritten when present.
- Release: add a changeset entry at **minor** level whose text warns that
  `templates/generated/` formatting changes on next render while deployed
  stacks are unaffected (no-op deploy contract). Do not publish the release —
  ticket 11 gates it.

## Out of scope

- Property-level template overrides, TUI changes, per-environment render
  specialization — all explicitly fenced by the ADR.
- No "cleanup" of logical IDs, parameter names, or naming quirks —
  permanent public contract.
- Do not run or automate anything against AWS (ticket 11).

## Acceptance criteria

- [ ] `darth-infra render` on the existing fixtures produces templates at the
      frozen paths via the new pipeline; smoke tests pass.
- [ ] `grep -rn "yaml.j2" src/ tests/` returns nothing; the three CFN `.j2`
      files are gone; README.md.j2 remains.
- [ ] No test asserts on rendered CFN template text (structural or smoke
      only).
- [ ] `uv run pytest` fully green; cfn-lint green over all fixtures.
- [ ] A `.changeset/` entry exists at minor level with the migration notice.

Commands:

```
uv run pytest
grep -rn "root.yaml.j2\|service.yaml.j2\|overrides.yaml.j2" src/ tests/  # expect no hits
```

## Blocked by

- 04 (`04-dedicated-alb-dns.md`)
- 05 (`05-rds-and-secrets.md`)
- 06 (`06-service-discovery-s3.md`)
- 07 (`07-cloudfront.md`)
- 08 (`08-ec2-launch-type.md`)
- 09 (`09-structural-deploy-validation.md`)
