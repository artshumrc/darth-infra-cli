## What to build

Deliver the core Services section through a reusable master-detail interaction.
Users must be able to search, add, select, edit, duplicate, and delete
unreferenced services while editing all common container, build, compute,
health, launch, and environment-variable settings directly in the document
session.

This slice establishes the collection-editor interaction that later routing,
storage, and secrets slices reuse. It must eliminate separate Add/Update form
modes in the new editor and prove that ordinary environment-variable values are
visible configuration rather than secrets.

## Where to start

- Read the current service form and merge behavior in
  `src/darth_infra/tui/screens/services.py` and
  `tests/test_tui_review_build_config.py`.
- Read every common service field in `ServiceConfig` and its schema definition.
- Read service validation and launch-type constraints in
  `ProjectConfig.__post_init__`.
- Build on the shell, field wrapper, and document paths from tickets 01, 02,
  and 04.
- Use Textual Pilot to test the visible master-detail workflow rather than
  testing private list-refresh methods.

## Contract

- The service list is searchable and communicates empty, selected, modified,
  and invalid states with text as well as color.
- Selecting a service opens its details without a second explicit Update action;
  valid changes update the in-memory draft.
- Add creates a new draft service and requires a unique valid name.
- Duplicate copies service-owned configuration, requires a new name before it
  is valid, and does not duplicate incoming references from other resources.
- Delete removes an unreferenced service after confirmation. Referenced-service
  impact and cascade are completed in ticket 07; until then, referenced delete
  must be blocked rather than leave dangling references.
- Cover the common persisted fields registered for Services: name, Dockerfile,
  build context, build target, external image, port/worker behavior, all health
  check fields, CPU, memory, desired count, command, launch type, EC2 instance
  type, ECS Exec, SES permission, and environment variables.
- External image versus Docker build fields and worker versus routed-service
  fields use clear conditional presentation without changing schema semantics.
- Environment variables use an inline collection editor. Names and values are
  visible in the editor and later Review; only declared Secrets receive secret
  treatment.
- Field validation follows the touched/on-blur contract and complete service
  model validation runs before save.
- Master-detail behavior is packaged for reuse without exposing document AST or
  service-specific internals in its interface.
- Advanced user data, architecture, ulimits, EBS, and service discovery belong
  to ticket 07.

## Out of scope

- Do not implement cascading cleanup of external references yet.
- Do not add new shared environment-variable semantics.
- Do not edit Routing, Database, Storage, Secrets, or Environments screens.
- Do not hide or mask ordinary environment-variable values.
- Do not remove the legacy Services screen before cutover.

## Acceptance criteria

- [ ] Pilot can add, search, select, edit, duplicate, and delete an unreferenced service.
- [ ] Every common service field listed in the contract saves and reloads through `load_config()`.
- [ ] Existing non-default desired count and ECS Exec values round-trip instead of reverting to defaults.
- [ ] Duplicate copies service-owned fields but no incoming references and remains invalid until given a unique name.
- [ ] Referenced deletion is blocked with an actionable message and never leaves a dangling reference.
- [ ] Environment-variable names and values remain visible and persist exactly.
- [ ] Master-detail controls remain keyboard-operable at 120x35 and 80x24.
- [ ] Existing service and render-context tests remain green.

Run:

```bash
uv run pytest tests/test_tui_services_core.py
uv run pytest tests/test_tui_review_build_config.py tests/test_render_context.py
uv run pytest
git diff --check
```

Success means all tests pass and `git diff --check` emits no output.

## Blocked by

- Ticket 04: `04-editor-shell-project.md`
