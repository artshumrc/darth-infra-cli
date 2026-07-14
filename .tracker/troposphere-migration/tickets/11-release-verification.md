# 11 — Pre-release no-op verification against real stacks

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

The release gate: a small scripted check that, for a given project directory
and environment, renders templates with the new pipeline and creates a
CloudFormation changeset **without executing it**, then reports whether any
infrastructure changes would occur. Run it against the team's existing real
stacks before publishing the cutover release; the release ships only when
every stack reports no changes.

## Where to start

- `src/darth_infra/cli/cfn.py` — `deploy_changeset` already supports
  `no_execute`; `package_template` handles nested-template upload. The
  script/command should reuse this path rather than reimplementing it, so
  the verification exercises the same code users run.
- CloudFormation semantics: an empty changeset fails creation with
  "The submitted information didn't contain changes" — that outcome is the
  **success** signal here. A created changeset must be inspected
  (`describe_change_set`) and reported: resource changes = FAIL (print the
  changes), no resource changes = PASS. Clean up created changesets.
- Simplest packaging: a `--verify-noop`-style flag on deploy or a small
  script in `scripts/` — implementer's choice, but it must be documented in
  the epic's README/changelog notes so the release manager can run it.

## Contract

- Read-only with respect to infrastructure: never executes a changeset,
  always deletes the changesets it creates.
- Exit code 0 only when the changeset outcome is "no changes"; nonzero with
  a human-readable diff summary otherwise.
- The check runs against **existing real stacks** (per the ADR's accepted
  trade-off); it does not create stacks or fixtures.

## Out of scope

- No CI integration — this is a manually-run release gate requiring AWS
  credentials.
- No purpose-built verification stack matrix (considered and declined in the
  ADR).
- No changes to deploy behavior.

## Acceptance criteria

- [ ] Running the check against a real deployed stack with an unchanged
      config exits 0 and reports no infrastructure changes.
- [ ] Running it against a deliberately modified config (e.g. bump a
      container port on a sandbox stack) exits nonzero and names the changed
      resources — proving the check can actually fail.
- [ ] Any changesets created by the check are deleted afterward
      (verify via `aws cloudformation list-change-sets`).
- [ ] The release manager's procedure (command + expected output) is
      written down (epic README section or the changeset entry).

Commands (illustrative; exact form depends on chosen packaging):

```
uv run darth-infra deploy <env> --verify-noop   # or: uv run python scripts/verify_noop.py <project-dir> <env>
echo $?                                          # 0 = no changes
```

## Blocked by

- 10 (`10-cutover.md`)
