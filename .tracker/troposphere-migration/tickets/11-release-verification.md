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
      **(Deferred to release manager — needs AWS.)**
- [ ] Running it against a deliberately modified config (e.g. bump a
      container port on a sandbox stack) exits nonzero and names the changed
      resources — proving the check can actually fail.
      **(Deferred to release manager — needs AWS.)**
- [ ] Any changesets created by the check are deleted afterward
      (verify via `aws cloudformation list-change-sets`).
      **(Deferred to release manager — needs AWS.)**
- [x] The release manager's procedure (command + expected output) is
      written down (epic README section or the changeset entry).
      See `.tracker/troposphere-migration/README.md`.

## Implementation notes

- Packaged as a `--verify-noop` flag on `darth-infra deploy`
  (`src/darth_infra/cli/deploy_cmd.py`). It reuses the same code path a real
  deploy runs and threads a new `verify_noop` keyword into `deploy_changeset`
  (`src/darth_infra/cli/cfn.py`). Normal deploy behavior is unchanged when the
  flag is absent (default `False`).
- Semantics: never executes a change set; empty change set (CloudFormation
  "didn't contain changes" failure) → exit 0 / "no changes"; created change set
  with resource changes → nonzero + printed resource list; no resource changes
  → exit 0. The change set is always deleted (new `_delete_change_set` helper,
  called from a `finally` block so every return path cleans up).
- `--verify-noop` rejects combination with `--cancel`, `--with-images`, and
  `--no-execute`.
- Unit tests with mocked boto3 (hand-rolled fakes, matching the repo's existing
  `test_cli_cfn_deploy_changeset.py` style):
  `tests/test_cli_cfn_verify_noop.py` — proves the empty-change-set → exit 0
  path, the resource-changes → nonzero + named resources path, and that created
  change sets are deleted in every path. Full suite: 103 passed.

## Handoff to release manager

The three real-stack acceptance criteria above cannot be satisfied without AWS
credentials and existing deployed stacks, so they are left for a human. The
tooling, unit tests, and documentation are complete and committed.

Procedure (full version in `.tracker/troposphere-migration/README.md`):

1. Real deployed stack, unchanged config → exit 0 / no changes:

   ```bash
   uv run darth-infra deploy --env <env> --verify-noop
   echo $?   # expect 0
   ```

2. Deliberately modified sandbox config (e.g. bump a container port) → nonzero
   and names the changed resources:

   ```bash
   # edit darth-infra.toml on a sandbox env, then:
   uv run darth-infra deploy --env <sandbox-env> --verify-noop
   echo $?   # expect nonzero; output lists the changed resources
   ```

3. Verify no change sets were left behind:

   ```bash
   aws cloudformation list-change-sets --region <region> \
     --stack-name <project>-ecs-<env>
   # expect no verify-<env>-* change sets remaining
   ```

Run step 1 against every real stack; publish the minor release only when all
report no changes.

Commands (illustrative; exact form depends on chosen packaging):

```
uv run darth-infra deploy <env> --verify-noop   # or: uv run python scripts/verify_noop.py <project-dir> <env>
echo $?                                          # 0 = no changes
```

## Blocked by

- 10 (`10-cutover.md`)
