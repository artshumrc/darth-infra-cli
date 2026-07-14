## What to build

Deliver the first end-to-end Guided editor tracer: a new Textual application
shell backed by `ProjectDocument`, with non-linear section navigation and a
complete Project section. A maintainer must be able to launch the new app in a
test harness, edit project identity, region, environments, and project tags,
inspect CLI-maintained metadata, validate fields, and save an existing document
without losing unrelated TOML content.

Build the shared visual and interaction foundation needed by later slices:
control-room theme tokens, section state, Advanced panels, adjacent errors,
focus-aware help, keyboard bindings, responsive navigation, and a contextual
footer. Keep the new shell internal until ticket 16 performs the atomic CLI
cutover.

## Where to start

- Read the current lifecycle and CSS in `src/darth_infra/tui/app.py`, but do not
  carry forward its mutable wizard-state interface.
- Read `src/darth_infra/tui/step_rail.py` and `src/darth_infra/tui/steps.py` for
  behavior to replace, not patterns to preserve.
- Read `src/darth_infra/tui/screens/welcome.py` and
  `src/darth_infra/tui/screens/tags.py` for current Project and tag behavior.
- Use the registry from ticket 01 and document session from ticket 02.
- Introduce the repository's first Textual Pilot tests with `App.run_test()`;
  current TUI tests only exercise state helpers.

## Contract

- The new application accepts a `ProjectDocument` dependency. It does not
  construct configuration through `wizard_export` or `build_config_from_state`.
- Nine canonical navigation destinations exist: Project, Network, Services,
  Routing, Database, Storage, Secrets, Environments, and Review.
- The Project destination is functional in this slice. Unimplemented
  destinations may be clearly marked unavailable in the internal app, but the
  navigation interface must not need replacement later.
- Navigation is non-linear. Project creation can expose a suggested
  Save & Continue action without locking direct navigation.
- Project covers project name, AWS region, environment list, and project tags.
  Network fields belong to ticket 05.
- `cli_version_floor` is displayed read-only from the effective configuration.
- Common fields are visible. Advanced panels expose registered advanced fields,
  auto-expand for explicit non-default values or errors, and show configured
  counts when collapsed.
- Every field wrapper can display schema-backed help, effective default,
  constraints, touched state, adjacent error text, and explicit/default status.
- Validation first appears on blur. Once shown, an error clears live when fixed.
- Existing-project Ctrl+S validates and performs a document-preserving save.
  Full conflict, risk, and quit workflows arrive in tickets 14 and 15.
- Required bindings are Ctrl+S, Ctrl+K, F1, and Escape. Bare `n`, `p`, and `q`
  are not global bindings in the new app.
- Styling uses named semantic tokens: slate surfaces, cyan focus/automatic,
  green valid/verified, amber modified/unverified, and red invalid/destructive.
  Text or symbols accompany every semantic color.
- The shell is usable through keyboard and mouse at 120x35 and 80x24. Below
  80x24 it renders a minimum-size message instead of a broken form.
- Environment-variable handling, AWS access, deployment operations, and legacy
  CLI wiring are not involved in this slice.

## Out of scope

- Do not switch `darth-infra tui` or register `darth-infra init` yet.
- Do not delete legacy screens or state bridges.
- Do not build AWS discovery, repeatable resource editors, Review, topology, or
  conflict dialogs.
- Do not introduce a second field registry or screen-specific config model.

## Acceptance criteria

- [ ] A Textual Pilot test launches the new shell with an existing hand-formatted project document.
- [ ] Project fields and tags can be edited and saved through visible controls, and `load_config()` observes the changes.
- [ ] Unedited comments, ordering, formatting, and explicit/default presence survive the save.
- [ ] `cli_version_floor` is visible and cannot receive edit focus.
- [ ] Advanced panels expand for configured values and errors and report configured counts when collapsed.
- [ ] Touched-field validation, live error clearing, contextual help, and F1 expanded help are observable through Pilot.
- [ ] Ctrl+S works; printable `n`, `p`, and `q` remain ordinary input text.
- [ ] Required Project actions remain reachable at 120x35 and 80x24; smaller terminals show the minimum-size state.
- [ ] The legacy CLI still launches the legacy app until atomic cutover.

Run:

```bash
uv run pytest tests/test_tui_editor_shell.py tests/test_tui_project_section.py
uv run pytest tests/test_config_document.py tests/test_tui_field_registry.py
uv run pytest
git diff --check
```

Success means all Pilot and unit tests pass, the full suite passes, and
`git diff --check` emits no output.

## Blocked by

- Ticket 01: `01-schema-field-registry.md`
- Ticket 02: `02-document-preserving-session.md`
