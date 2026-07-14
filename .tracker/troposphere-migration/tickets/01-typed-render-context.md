# 01 — Typed RenderContext derivation layer

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

Port the generator's derivation logic — today one ~390-line function returning
a loose `dict` — into frozen dataclasses produced by a single derivation
function from `ProjectConfig`. This is a 1:1 port: same computations, same
derived values, typed containers. It is the foundation every builder ticket
consumes; nothing user-visible changes.

## Where to start

- `src/darth_infra/scaffold/generator.py` — `_build_context()` (around line
  159) is the source of truth; also the module-level helpers it uses:
  `_pascalize`, `_enum_value`, `_resolve_user_data_script_content`,
  `_derive_rds_master_username`, `_normalize_rds_json_key`.
- `src/darth_infra/config/models.py` — `ProjectConfig` and friends (input
  types; do not modify).
- The Jinja templates show how each ctx key is consumed:
  `src/darth_infra/templates/cfn/root.yaml.j2`,
  `src/darth_infra/templates/cfn/nested/service.yaml.j2`.

## Contract

- New module (suggested: `src/darth_infra/scaffold/context.py`) exposing
  frozen dataclasses — `RenderContext`, `ServiceRenderContext`,
  `TagParameter`, path-rule/secret contexts as needed — and one entry point:

  ```python
  def derive_render_context(config: ProjectConfig) -> RenderContext: ...
  ```

- Every key currently produced by `_build_context` (including per-service
  `services_ctx` entries) has a typed home. Field names may be cleaned up;
  computed **values** may not change.
- All naming rules live only here: logical-ID pascalization, secret-name
  mangling (the `replace('_','')`/`replace('-','')` quirks), tag
  parameter/condition names. These feed logical IDs, which are a permanent
  public contract — reproduce them exactly, quirks included.
- `_build_context` and the Jinja pipeline keep working unchanged. Either leave
  `_build_context` as-is for now, or reimplement it as a thin adapter over
  `derive_render_context` — in both cases rendered Jinja output must be
  byte-identical to before.

## Out of scope

- No troposphere, no builders, no YAML emission — this ticket is derivation
  only.
- No changes to `config/models.py`, the TUI, or any CLI command.
- No "improving" derived values (e.g. fixing a mangling quirk) — 1:1 port.

## Acceptance criteria

- [ ] `derive_render_context` returns typed objects covering every ctx key
      consumed by the two CFN Jinja templates.
- [ ] Unit tests construct representative `ProjectConfig` fixtures (reuse the
      fixture style of `tests/test_generator_cloudfront_alb.py` and
      `tests/test_preview_environments.py`) and assert derived values: tag
      parameter/condition names, secret logical-ID fragments, listener-rule
      priority parameter names, RDS master username derivation.
- [ ] Existing test suite still passes; Jinja output unchanged.

Commands:

```
uv run pytest                      # full suite green
uv run pytest tests/ -k context   # new derivation tests green
```

## Blocked by

None - can start immediately.
