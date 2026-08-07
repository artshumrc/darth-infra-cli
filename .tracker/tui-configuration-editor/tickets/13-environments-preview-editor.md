## What to build

Deliver the Environments section as the single editing location for
environment-specific overrides, environment tags, and preview-environment
policy. Users must be able to inspect effective inherited values, set or reset
only the override types supported by the existing schema, and configure every
preview field without changing inheritance or deployment semantics.

## Where to start

- Read the current environment tag and preview screens in
  `src/darth_infra/tui/screens/tags.py` and
  `src/darth_infra/tui/screens/preview.py`.
- Read `EnvironmentOverride`, `PreviewEnvironmentsConfig`, environment
  normalization, tag resolution, and active-preview behavior in
  `src/darth_infra/config/models.py`.
- Read preview loader/serializer behavior and
  `tests/test_preview_environments.py`.
- Use Project's environment list as the source of selectable environments and
  Services/Database for effective base values.
- Reuse field presence, Automatic/Override, reference impact, and Advanced
  controls from preceding tickets.

## Contract

- Environments is the only place that edits environment-specific overrides.
  Owning sections may show override indicators and navigate here, but must not
  expose duplicate override editors.
- Environment selection shows effective values with `INHERITED` or `OVERRIDE`
  badges and uses Reset to inherited to remove persisted override keys.
- Cover every existing environment override field: RDS instance type, per-
  service EC2 instance type, and environment tags.
- Project tags remain in Project. Environment tags remain scoped to the selected
  environment.
- Removing or renaming a service updates or blocks its EC2 instance override
  through the shared reference-impact behavior.
- Cover every persisted preview field: enabled, base environment, name pattern,
  domain template, hosted-zone name, listener-priority start/end, and tags.
- Preview priority bounds remain editable because they reserve allocation space
  for active previews. Pairing, range, and ordering errors surface inline.
- Preview fields are grouped under a clearly optional panel. Existing active
  configuration forces it open.
- Runtime-only `active_preview` data is never editable or persisted by this
  section.
- Existing environment ordering, base environment, tag interpolation, priority
  allocation, and preview deployment semantics remain unchanged.

## Out of scope

- Do not make arbitrary service fields environment-overridable.
- Do not move project tags into Environments.
- Do not edit runtime active-preview metadata.
- Do not perform Route53, listener, or deployment operations.
- Do not change preview naming or priority allocation behavior.

## Acceptance criteria

- [ ] Pilot selects each environment and edits every supported override and environment tag.
- [ ] Effective inherited values are visible without being persisted, and Reset to inherited removes the override key.
- [ ] Service EC2 overrides and RDS overrides link to valid existing resources and participate in reference cleanup.
- [ ] Every preview field saves and reloads, including paired priority bounds and tags.
- [ ] Invalid base environment, patterns, or priority bounds prevent save at the responsible field.
- [ ] Runtime active-preview data has no editable registry control.
- [ ] Existing preview allocation, tag, loader, and model tests remain green.

Run:

```bash
uv run pytest tests/test_tui_environments_section.py
uv run pytest tests/test_preview_environments.py tests/test_config_environment_tags.py tests/test_cli_cfn_environment_tags.py
uv run pytest
git diff --check
```

Success means all tests pass and `git diff --check` emits no output.

## Blocked by

- Ticket 07: `07-advanced-services-references.md`
- Ticket 10: `10-database-editor.md`
