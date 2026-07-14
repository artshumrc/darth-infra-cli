# 09 — Structural deploy-time validation

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

Reimplement the deploy-time safety checks to assert structurally on built
template objects instead of substring-matching rendered text. The function
keeps its role and its failure mode (raise before any AWS call when a
required template element is missing); only the inspection layer changes.
The new implementation consumes `build_project_templates` output directly —
it must not read or parse the YAML files.

## Where to start

- `src/darth_infra/cli/cfn.py:246` — `validate_rendered_deploy_templates`:
  reads `templates/generated/*.yaml` as text and checks markers like
  `"PolicyName: SesSendEmail"`, `"- ses:SendEmail"`, and the RDS env-key
  mapping table (DATABASE_*/POSTGRES_* → host/port/...). Enumerate every
  marker it checks today; each becomes a structural assertion.
- Call sites: `src/darth_infra/cli/deploy_cmd.py:122` and `:177`.
- Tickets 03/05 built the objects being validated (SES policy, RDS secret
  wiring).

## Contract

- Same public behavior: called from the deploy flow after template
  generation, raises with an actionable message naming the service and the
  missing element. Keep raising `FileNotFoundError`-equivalent errors for
  missing templates only if the file-existence check still makes sense at the
  call site — otherwise validate the built mapping (missing service key =
  same error class of failure).
- Every guarantee the text markers provided is preserved as a structural
  assertion (SES policy presence + action list; RDS secret key wiring per
  exposed env var; any others found during enumeration). None are silently
  dropped.
- Until ticket 10 lands, the old text-based function keeps running in the
  shipping deploy path; the structural version lands inert with unit tests.
  (If wired behind the same name, it must not change deploy behavior for the
  Jinja pipeline — safest is a parallel function that ticket 10 swaps in.)

## Out of scope

- No changes to `_build_parameters`, lookups, changeset logic, or any other
  part of `cli/cfn.py`.
- No deletion of the text-based checks (ticket 10 does that at cutover).

## Acceptance criteria

- [ ] Unit tests prove the structural validator raises on a template mapping
      missing the SES policy (when config enables it) and on missing RDS
      secret wiring — and passes on correct fixtures from tickets 03/05.
- [ ] A checklist in the PR description maps every text marker in the old
      function to its structural assertion.
- [ ] Full suite green; shipping deploy path behavior unchanged.

Commands:

```
uv run pytest
uv run pytest tests/ -k "validation"
```

## Blocked by

- 03 (`03-service-stack-core.md`)
- 05 (`05-rds-and-secrets.md`)
