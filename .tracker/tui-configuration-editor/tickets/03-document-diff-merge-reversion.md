## What to build

Extend the document-editing session with semantic change classification,
field/section/session reversion, and conflict-aware three-way merge. The result
must let later UI slices explain exactly what changed, revert draft work without
reloading, and safely combine disjoint external edits without losing either
author's comments or formatting.

This behavior stays behind the document module's interface and is verified
without Textual so every later screen receives the same semantics.

## Where to start

- Begin with the document session delivered by ticket 02 and its content-based
  revision handling.
- Read the persisted collection models and serializer in
  `src/darth_infra/config/models.py` and `src/darth_infra/config/loader.py`.
- Use semantic identities already present in configuration: service name,
  bucket name, secret name, path-rule name, cached-behavior name, volume name,
  ulimit name, and environment name. Connections may require stable composite
  identities derived from their owning resource and declared keys.
- Add focused scenarios to `tests/test_config_document.py` or a dedicated
  `tests/test_config_document_merge.py` when that keeps failures legible.

## Contract

- Semantic changes have stable paths and one of `added`, `removed`, `changed`,
  or `reset_to_default`, with before/after values where applicable.
- Exact TOML patch generation remains separate from semantic change reporting.
- `revert_field`, `revert_section`, and `revert_all` restore the session
  baseline's values and explicit/omitted presence, including comments attached
  to restored fields.
- A cascading edit later performed by the UI is represented as one draft
  transaction and is fully reversible until save.
- Three-way merge compares the loaded baseline, current disk document, and TUI
  draft at semantic field paths.
- Disjoint semantic changes merge automatically while preserving both
  documents' unrelated syntax.
- Editing the same semantic field differently, or deleting a record modified
  by the other side, produces an explicit conflict containing baseline, disk,
  and draft values.
- Detection or cancellation of conflicts does not mutate the current draft.
- A resolved merge is revalidated before it can be saved.
- Collection ordering changes alone do not cause unrelated records to appear
  changed.
- No persistent undo log or recovery file is introduced.

## Out of scope

- Do not build conflict dialogs, Review widgets, or save notifications.
- Do not predict CloudFormation impact.
- Do not add global cross-session undo/redo.
- Do not silently choose disk or draft values for a true conflict.

## Acceptance criteria

- [ ] Semantic diffs distinguish add, remove, change, and reset-to-default operations.
- [ ] Field, section, and session reversion restore both value and presence state.
- [ ] Reverting a multi-field transaction restores all of its changes together.
- [ ] Disjoint disk and draft edits merge while preserving comments and unrelated formatting from both documents.
- [ ] Same-field and delete-versus-modify conflicts are reported with baseline, disk, and draft values.
- [ ] Cancelling or failing a merge leaves the draft unchanged.
- [ ] Collection reorder does not create false per-record changes.
- [ ] The full test suite remains green.

Run:

```bash
uv run pytest tests/test_config_document.py tests/test_config_document_merge.py
uv run pytest
git diff --check
```

Success means all tests pass and `git diff --check` emits no output.

## Blocked by

- Ticket 02: `02-document-preserving-session.md`
