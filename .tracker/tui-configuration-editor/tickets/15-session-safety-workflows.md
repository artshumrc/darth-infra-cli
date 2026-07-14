## What to build

Complete the editor's save, quit, reversion, and concurrent-file workflows.
Existing projects must save from any section; new projects must pass through
Review before canonical project files are created. Invalid state must never be
silently discarded, external file changes must never be overwritten, and every
draft action must remain recoverable through the agreed baseline-based
reversion controls until save.

## Where to start

- Integrate the document revision, merge, conflict, and reversion behavior from
  ticket 03 with the editor shell and Review.
- Replace, in the new app only, the legacy quit path in
  `src/darth_infra/tui/app.py` that catches config-build failures and exits.
- Read project creation/scaffolding flow in
  `src/darth_infra/cli/init_cmd.py` and
  `src/darth_infra/scaffold/generator.py`; CLI cutover remains ticket 16.
- Use Review's risk classification and confirmation from ticket 14.
- Add full Textual Pilot flows rather than unit testing modal callback methods.

## Contract

- Existing-project Ctrl+S validates and saves from any editor section.
- First-time creation cannot write project files until the user visits Review
  and confirms creation. New files use canonical formatting and existing
  scaffold behavior.
- Quitting a valid dirty draft offers Save, Discard, or Cancel.
- Quitting an invalid dirty draft offers Return to fix or Discard. Save is not
  offered, and validation/conversion errors never cause an automatic exit.
- A successful save reports the config path and semantic changed-field count.
- Deployment-sensitive changes require the one Review/risk confirmation before
  write. Ordinary changes do not.
- Reset field restores its baseline value and presence. Revert section affects
  only that registry section. Revert all restores the loaded/saved baseline.
- Cascading deletions are one transaction and fully restored by reversion.
- Before write, compare the current disk content revision with the session
  baseline.
- Disjoint external changes merge automatically, revalidate, and show the exact
  merged patch before write.
- True conflicts open a resolver showing baseline, disk, and draft values.
  Users may choose per conflict or cancel. Cancellation preserves the draft and
  disk file.
- Failed merged validation prevents write and preserves the draft.
- No hidden autosave or persistent recovery file is created.
- Focus returns to the initiating control after dialogs; Escape cancels without
  mutation.
- Save updates the session baseline so the semantic diff and risk warnings
  clear.

## Out of scope

- Do not wire public CLI commands or delete legacy code; ticket 16 owns cutover.
- Do not add persistent deployment tracking, autosave, crash recovery, or global
  undo/redo history.
- Do not bypass Review for first-time project creation.
- Do not force AWS verification before save.

## Acceptance criteria

- [ ] Existing projects save from Project and at least one non-Project section without visiting Review.
- [ ] First-time creation cannot write before Review confirmation and then produces canonical project output.
- [ ] Valid dirty quit offers Save/Discard/Cancel; invalid dirty quit offers Return/Discard and preserves the draft on Return.
- [ ] Model or conversion errors never exit the application silently.
- [ ] Field, section, and all reversion restore values, presence, comments, and cascading transactions as scoped.
- [ ] Disjoint external edits merge and save without losing either document's unrelated formatting.
- [ ] Same-field conflicts require resolution; cancellation and failed validation leave disk and draft unchanged.
- [ ] Successful save reports path/count and clears diff, modified state, and risk warnings.
- [ ] No recovery/autosave file is created.

Run:

```bash
uv run pytest tests/test_tui_save_quit.py tests/test_tui_revert.py tests/test_tui_conflicts.py
uv run pytest tests/test_config_document.py tests/test_config_document_merge.py tests/test_tui_review.py
uv run pytest
git diff --check
```

Success means all tests pass and `git diff --check` emits no output.

## Blocked by

- Ticket 03: `03-document-diff-merge-reversion.md`
- Ticket 04: `04-editor-shell-project.md`
- Ticket 14: `14-review-topology-risk.md`
