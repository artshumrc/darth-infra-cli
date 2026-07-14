## What to build

Create the deep document-editing module that allows the Guided editor to load an
existing TOML document, inspect effective and explicit values, apply semantic
field edits, reset fields to omission, validate the resulting `ProjectConfig`,
preview the exact patch, and save without rewriting unrelated document content.

The completed slice must demonstrate a one-field edit against hand-formatted
TOML while preserving comments, ordering, unrelated formatting, omitted fields,
and explicit values equal to defaults. Existing canonical load/dump behavior
remains available for non-editor callers and new-project output.

## Where to start

- Read `load_config()` and `dump_config()` in
  `src/darth_infra/config/loader.py`; they are semantic/canonical interfaces and
  cannot preserve source syntax.
- Read normalization in `ProjectConfig.__post_init__` and related model helpers
  before deciding where raw document intent must remain separate from the
  effective validated model.
- Use the field paths established by ticket 01 rather than inventing a second
  addressing scheme.
- Add a comment-preserving TOML AST dependency suitable for Python 3.12+; keep
  syntax-preservation details inside the new module.
- Add focused tests in a new `tests/test_config_document.py`.

## Contract

The module interface must remain small and own the preservation complexity. It
must provide equivalent capabilities to:

```python
document = ProjectDocument.load(path)
document.config                 # effective validated ProjectConfig
document.value(field_path)      # effective value
document.is_explicit(field_path)
document.set(field_path, value)
document.reset(field_path)      # remove persisted key, restore effective default
document.validate()
document.toml_patch()
document.save(expected_revision=document.revision)
```

- The exact names may follow repository conventions, but callers must not
  manipulate the TOML AST or maintain a parallel state dictionary.
- The document retains a content-based revision captured at load time.
- Raw field presence is independent of model normalization. Reading an omitted
  default and reading an explicit value equal to that default return the same
  effective value but different `is_explicit` results.
- Setting a field persists it explicitly. Resetting removes it and restores
  omission semantics.
- Saving changes only edited document regions and uses an atomic file replace.
- A save against a different disk revision returns a typed conflict result or
  error; it never overwrites the newer file. Three-way merge is ticket 03.
- Validation is performed through the existing loader/model semantics. Invalid
  drafts remain inspectable and are not written.
- New-project canonical formatting continues to use the existing serializer;
  this ticket is for existing-project document preservation.

## Out of scope

- Do not build Textual controls or screens.
- Do not implement semantic change classification, reversion history, or
  three-way merge; ticket 03 owns those behaviors.
- Do not modify model defaults or normalize the source document to match the
  effective dataclass.
- Do not replace `dump_config()` for existing non-editor callers.

## Acceptance criteria

- [ ] Loading hand-formatted TOML preserves comments, ordering, quoting, and unrelated whitespace after one semantic field edit.
- [ ] Omitted and explicit-default fields have equal effective values but distinct presence state.
- [ ] Reset removes a persisted key rather than writing its current default.
- [ ] Invalid edits return model validation errors and cannot be saved.
- [ ] Saving against a changed disk revision refuses to overwrite it.
- [ ] A successful save is atomic and reloads through `load_config()` with the edited semantic value.
- [ ] Existing loader, serializer, and model tests remain green.

Run:

```bash
uv run pytest tests/test_config_document.py
uv run pytest tests/test_config_environment_tags.py tests/test_config_validation_cloudfront_alb.py tests/test_cli_version_floor.py
uv run pytest
git diff --check
```

Success means all tests pass and `git diff --check` emits no output.

## Blocked by

- Ticket 01: `01-schema-field-registry.md`
