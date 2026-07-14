## What to build

Establish the persisted configuration schema as the enforceable completeness
contract for the Guided editor. Make the packaged schema canonical, keep the
project-root copy identical, classify CLI-maintained metadata explicitly, and
introduce a machine-readable registry that assigns every user-authored schema
field to an editor section with presentation and help metadata.

This is enabling prefactoring. It must leave the existing TUI and generated
infrastructure behavior unchanged while making missing editor coverage
mechanically visible.

## Where to start

- Compare `src/darth_infra/darth-infra.schema.json` with the root
  `darth-infra.schema.json`; the packaged schema currently contains fields the
  root copy lacks.
- Read `ProjectConfig` and its nested dataclasses in
  `src/darth_infra/config/models.py` to distinguish persisted fields from the
  runtime-only active preview.
- Read `src/darth_infra/tui/wizard_export.py` and
  `src/darth_infra/tui/screens/review.py` for examples of fields the current
  bridge loses.
- Read the schema-copy behavior in `src/darth_infra/scaffold/generator.py`.
- Add focused coverage tests near `tests/test_tui_review_build_config.py`, but
  prefer a new registry contract test over extending lossy state tests.

## Contract

- `src/darth_infra/darth-infra.schema.json` is the canonical schema artifact;
  the root schema must be byte-for-byte synchronized from it.
- `project.cli_version_floor` is marked read-only and remains persisted and
  visible. It is the only currently persisted read-only exemption.
- Runtime-only `active_preview` is not added to the persisted schema or editor
  registry.
- Registry paths use one stable wildcard notation for repeated and map values,
  for example `services[].name`, `services[].environment_variables.*`, and
  `environments.*.tags.*`.
- Every editable leaf or editable map/list container has one registry entry.
- Each entry identifies its canonical section, common versus Advanced
  placement, intended control kind, and TUI-specific help/example metadata.
  Core meaning, defaults, ranges, and constraints continue to come from the
  schema.
- The registry describes purpose-built controls; it does not generate a generic
  editor directly from JSON Schema.
- Coverage traversal must handle nested objects, arrays of objects, maps with
  arbitrary keys, nullable values, and read-only fields.
- A new schema field without registry coverage must fail a test in the same
  change that introduces it.

## Out of scope

- Do not build visible editor screens or widgets.
- Do not change configuration defaults, validation semantics, loader behavior,
  template generation, Logical IDs, or deploy behavior.
- Do not add new configuration concepts.
- Do not make the root schema an independently maintained source.

## Acceptance criteria

- [ ] The packaged and root schemas are byte-for-byte identical.
- [ ] `project.cli_version_floor` is explicitly read-only in the canonical schema.
- [ ] A registry entry exists for every user-authored persisted schema field and includes section, placement, control, and help metadata.
- [ ] Coverage fails when a fixture schema gains an uncovered editable field and permits only explicit read-only fields.
- [ ] Runtime-only active preview state is absent from editable coverage.
- [ ] The existing full test suite remains green.

Run:

```bash
cmp src/darth_infra/darth-infra.schema.json darth-infra.schema.json
uv run pytest tests/test_tui_field_registry.py tests/test_config_validation_cloudfront_alb.py
uv run pytest
git diff --check
```

Success means `cmp` emits no output, all tests pass, and `git diff --check`
emits no output.

## Blocked by

None - can start immediately
