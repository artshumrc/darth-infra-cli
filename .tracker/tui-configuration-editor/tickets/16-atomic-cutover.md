## What to build

Perform the atomic user-facing cutover to the complete Guided editor. Wire
`darth-infra tui` to ongoing document-preserving editing, expose
`darth-infra init` for first-run interactive or non-interactive scaffolding,
remove the legacy wizard/state bridges and duplicate ALB behavior, and verify
the entire accepted editor, schema, terminal-size, generator, Logical ID, and
no-op deploy contracts as one release gate.

No partial new editor may remain hidden or optional after this ticket. The
repository must contain one TUI architecture and one configuration editing
path.

## Where to start

- Read command registration in `src/darth_infra/cli/main.py`. The implementation
  named `init_cmd` is currently registered only as `tui`; there is no public
  `init` command.
- Read current mixed edit/scaffold behavior and options in
  `src/darth_infra/cli/init_cmd.py`.
- Inventory legacy files under `src/darth_infra/tui/`, especially `app.py`,
  `wizard_export.py`, `steps.py`, `step_rail.py`, legacy screens, and
  `build_config_from_state()`.
- Find all imports and tests that still use mutable wizard state before deleting
  it.
- Run the complete Textual Pilot suite delivered by tickets 04-15 and the
  existing builder/generator/no-op suites before and after removal.
- Update user documentation and CLI help to distinguish editing from
  initialization.

## Contract

- `darth-infra tui` opens an existing project through `ProjectDocument` and the
  new editor. It performs document-preserving saves and does not scaffold,
  render, deploy, or mutate live infrastructure.
- If `tui` cannot find an existing configuration, it exits with an actionable
  instruction to run `darth-infra init`; it does not silently enter a different
  mode.
- `darth-infra init` is registered as the first-run command. Interactive init
  opens creation mode and requires Review confirmation before invoking existing
  project generation.
- Existing first-run `--output`, `--non-interactive`, and `--config` behavior is
  preserved on `init`. Non-interactive init continues to require `--config` and
  generate the project without launching Textual.
- CLI version-floor enforcement and ratcheting retain current semantics.
- All nine editor sections are reachable and complete. The schema coverage
  contract has no editable omissions.
- The released editor is usable at 120x35 and 80x24, is keyboard complete, and
  shows the minimum-size state below 80x24.
- Remove the legacy mutable wizard state, lossy config reconstruction, old step
  rail, old screen implementations, duplicate Services ALB methods, TUI
  priority lookup/allocation, and tests that assert only those obsolete
  internals.
- Do not retain compatibility wrappers for internal legacy TUI interfaces;
  external persisted configuration and CLI workflows are the compatibility
  contract.
- The canonical config loader/serializer remain available to non-editor callers
  and first-run generation.
- Existing generated template behavior and Logical IDs are unchanged. An
  unchanged `darth-infra.toml` continues to produce a no-op deploy.
- Generated templates remain build artifacts and are not edited by the TUI.
- The full suite is green at cutover; there is no knowingly incomplete section
  deferred behind a feature flag.

## Out of scope

- Do not add deployment, render, destroy, changeset, SSM, or secret-value
  operations to the editor.
- Do not add new configuration semantics while removing the legacy TUI.
- Do not preserve internal `wizard_export` or `build_config_from_state`
  interfaces after all callers are migrated.
- Do not retain two public TUI implementations or a fallback flag.
- Do not claim live no-op verification unless AWS credentials and an existing
  stack are available; the required automated gate is the structural no-op
  suite.

## Acceptance criteria

- [ ] `darth-infra --help` lists distinct `tui` and `init` commands with editing and first-run descriptions.
- [ ] `darth-infra tui` opens and document-preservingly edits an existing config and gives an actionable error when no config exists.
- [ ] Interactive `darth-infra init` requires Review before generating a new project.
- [ ] Non-interactive `darth-infra init --non-interactive --config <path> --output <dir>` preserves existing scaffold behavior.
- [ ] The schema coverage test reports no missing editable fields and only the accepted read-only exemption.
- [ ] Full Pilot scenarios pass at 120x35 and 80x24 with keyboard-only operation.
- [ ] Legacy screens, wizard state conversion, step rail, duplicate ALB methods, and TUI priority lookup code have no remaining imports or files.
- [ ] Existing shared and dedicated ALB, RDS, S3, Secrets, CloudFront, environments, and preview fixtures survive no-op editor saves.
- [ ] Generator, structural validation, and no-op verification suites pass without Logical ID or infrastructure semantic changes.
- [ ] The complete repository test suite passes.

Run:

```bash
uv run darth-infra --help
uv run pytest tests/test_cli_tui_init.py tests/test_tui_editor_acceptance.py tests/test_tui_field_registry.py
uv run pytest tests/test_builders.py tests/test_builders_cloudfront.py tests/test_generator_smoke.py tests/test_render_context.py tests/test_structural_deploy_validation.py
uv run pytest tests/test_cli_cfn_verify_noop.py tests/test_preview_environments.py
uv run pytest
git diff --check
```

Success means CLI help shows both commands with the agreed roles, every listed
test passes, the full suite passes, and `git diff --check` emits no output.

Optional live release verification, when a configured AWS project and deployed
environment are available:

```bash
uv run darth-infra deploy --env <env> --verify-noop
```

Success means the deployed stack reports no infrastructure changes. This live
command is not required for local ticket completion when AWS access is absent.

## Blocked by

- Ticket 01: `01-schema-field-registry.md`
- Ticket 02: `02-document-preserving-session.md`
- Ticket 03: `03-document-diff-merge-reversion.md`
- Ticket 04: `04-editor-shell-project.md`
- Ticket 05: `05-network-aws-discovery.md`
- Ticket 06: `06-core-services-editor.md`
- Ticket 07: `07-advanced-services-references.md`
- Ticket 08: `08-alb-routing.md`
- Ticket 09: `09-cloudfront-routing.md`
- Ticket 10: `10-database-editor.md`
- Ticket 11: `11-storage-editor.md`
- Ticket 12: `12-secrets-editor.md`
- Ticket 13: `13-environments-preview-editor.md`
- Ticket 14: `14-review-topology-risk.md`
- Ticket 15: `15-session-safety-workflows.md`
