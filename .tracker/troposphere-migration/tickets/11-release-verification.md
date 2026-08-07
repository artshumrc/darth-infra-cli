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

- [x] Running the check against a real deployed stack with an unchanged
      config exits 0 and reports no infrastructure changes.
      Confirmed 2026-08-07 on `iiif-cache-ecs-prod`,
      `bta-infrastructure-ecs-prod` and `bta-infrastructure-ecs-pr-140`
      (re-run after the listener-tags fix; all exit 0).
- [x] Running it against a deliberately modified config (e.g. bump a
      container port on a sandbox stack) exits nonzero and names the changed
      resources — proving the check can actually fail.
      Confirmed 2026-08-07: bumping `caddy.cpu` 256→512 gave exit 1 and
      exactly `[ServiceCaddy] changed resource TaskDefinition … .Cpu`, with
      no collateral findings. Config reverted.
- [x] ~~Any changesets created by the check are deleted afterward~~ — no
      longer applicable; the gate is a structural comparison and creates no
      change sets (see finding 3).
- [x] The gate's prediction verified against reality. The real deploy of
      `bta-infrastructure-ecs-pr-140` on the new pipeline produced zero
      CloudFormation events for any leaf resource; all four task definitions
      stayed at revision `:1` and every physical ID was unchanged. This is
      what makes the passes on the other stacks meaningful rather than
      merely unfalsified.
- [x] The release manager's procedure (command + expected output) is
      written down (epic README section or the changeset entry).
      See `.tracker/troposphere-migration/README.md`.

## Implementation notes

- Packaged as a `--verify-noop` flag on `darth-infra deploy`
  (`src/darth_infra/cli/deploy_cmd.py`). Normal deploy behavior is unchanged
  when the flag is absent.
- The flag runs `verify_noop_structural` (`src/darth_infra/cli/cfn.py`): a
  read-only structural comparison of the deployed stack templates against the
  freshly-built ones (see finding 3 below for the semantics and why it replaced
  the original change-set approach). No packaging and no change set. Exit 0 =
  no real leaf-resource change; nonzero + named resources otherwise.
- `--verify-noop` rejects combination with `--cancel`, `--with-images`, and
  `--no-execute`.
- Unit tests with mocked boto3 (`tests/test_cli_cfn_verify_noop.py`): identical
  templates pass; a literal-vs-resolved-ref value (priority) is a no-op; a
  condition-gated-off resource is ignored; a real property change fails; a
  nested-stack GetAtt param does not false-positive; a real change inside a
  nested stack fails.

## Handoff to release manager

The gate now runs read-only against AWS (no change sets to clean up), so the
original "delete leftover change sets" criterion no longer applies. It does
rewrite `templates/generated/` in the target project repo, so expect a dirty
working tree there.

**Fleet status as of 2026-08-07** — see the README's inventory table for the
full picture. Three of the four managed stacks gate clean (`iiif-cache` prod,
`bta` prod, `bta` pr-140); `elasticsearch-shared` fails on pre-existing drift
and is deliberately excluded from this release because its pending secret
rename would break bta prod as well. `bta` pr-140 was additionally deployed for
real and then destroyed, exercising both the update and teardown paths.

Two caveats the original procedure missed:

- Preview environments need `--preview-from <base>`; without it the command
  exits 1 with "Environment not found in darth-infra.toml".
- A long-unmaintained stack fails the gate for drift reasons unrelated to this
  migration. Diff a `main` render against a branch render before concluding a
  failure is a regression.

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

Run step 1 against every real stack; publish the minor release only when all
report no changes.

Commands (illustrative; exact form depends on chosen packaging):

```
uv run darth-infra deploy <env> --verify-noop   # or: uv run python scripts/verify_noop.py <project-dir> <env>
echo $?                                          # 0 = no changes
```

## Real-stack verification run — findings (2026-07-14)

First real run against the `bta-infrastructure` prod stack
(`darth-infra deploy --env prod --verify-noop`) reported 7 changes — the gate
did its job. Diagnosis of the changeset (semantic diff of generated templates
old-Jinja vs new-troposphere, plus the deployed stack) found:

1. **Real regression (FIXED, commit `bcdc8ce`).** The service-template builder
   never declared the CloudFront-URL parameters the root stack passes it
   (`cf_param_name` for cloudfront-enabled S3 buckets; `cloudfront_vars` for
   ALB CloudFront) and never injected the matching env vars
   (`cloudfront_env_key`, e.g. `DJANGO_MEDIA_URL`). The generated child
   template received undeclared parameters (nested stack rejected at execution)
   and dropped CDN env vars. A ticket-06/07 service-side gap that the
   root-side-only parameter tests missed; now covered by
   `test_full_featured_cloudfront_service_declares_params_and_env`. After the
   fix, the semantic diff of every bta service template is empty.

2. **Partly benign — the listener half was a real regression (CORRECTED
   2026-08-07, fixed in `0edc5a3`).** `DefaultListenerPriority` moving from a
   hardcoded `49991` to a `Ref` parameter that `_build_parameters` supplies as
   `49991` is genuinely benign (resolves to the same leaf value — no infra
   change, only nested-stack churn).

   The `DedicatedAlb*Listener` `Tags` removal was **not** benign, and calling it
   a "ticket 04 cfn-lint fix" was wrong. CloudFormation *does* accept `Tags` on
   `AWS::ElasticLoadBalancingV2::Listener`; the removal was forced by
   troposphere 4.10.2 omitting `Tags` from `Listener.props`, and the original
   cfn-lint E3002 that appeared to justify it came from this repo's pinned
   cfn-lint 1.53.0, whose bundled schema predates AWS adding listener tagging.
   cfn-lint 1.54.0 accepts it. Both listeners were therefore silently losing
   `Project`, `Environment` and every configured extra tag — invisible on all
   four current stacks only because every project uses `alb.mode = "shared"`,
   which condition-gates the listeners off. Fixed via a `_TaggableListener`
   subclass; cfn-lint floor raised to `>=1.54.0` (otherwise the repo's own lint
   test enforces the bug); regression test
   `test_builders_dedicated_alb_listeners_carry_project_tags`.

   The related `Ec2InstanceProfile` `Tags` removal *is* a real fix and was
   previously undocumented: `AWS::IAM::InstanceProfile` genuinely does not
   accept `Tags`, so `main` renders an invalid elasticsearch service template
   (E3002) and cannot deploy that stack at all.

   Generalization worth carrying forward: troposphere's spec lag fails **closed
   and silent** for properties, not just resource types — see the ADR
   consequences section.

3. **Gate rebuilt as a structural comparison (commit `62932a9`; validated on
   real prod, exit 0).** A change-set-based gate cannot verify this cutover:
   `aws cloudformation package` content-hashes each nested template, so
   troposphere's different bytes give every nested stack a new `TemplateURL`,
   and change sets over nested stacks emit conservative false positives (they
   predicted an `EcsService` *replacement* for an unchanged `Cluster`). The gate
   is now `verify_noop_structural`: it fetches each deployed stack template
   (root + nested) and compares against the freshly-built templates, resolving
   parameter refs (a deploy-time-looked-up priority that is a literal in the
   deployed template but a `Ref` in the new one reads as unchanged), falling
   back to the deployed value for `GetAtt`-valued nested params (stable
   cross-references like `ClusterArn` don't false-positive), evaluating
   `Conditions` (condition-gated-off resources are skipped), and ignoring
   nested-stack `TemplateURL` churn (child contents compared by recursion). The
   superseded change-set gate (`_classify_noop_changes`) was removed.

4. **Priority churn (pre-existing bug, fixed `2153adc`).** While verifying, the
   deployed listener rule showed priority `49991`→`1`. Root cause was in the
   deploy layer (present on `main`): `_resolve_stack_owned_listener_rule_priorities_by_label`
   filtered rules on `rule["ListenerArn"]`, but `describe_rules(RuleArns=…)`
   doesn't return that field, so stack-owned priorities were never preserved and
   got reassigned on every deploy. Now derives the listener from the rule ARN.

Net: with commits `bcdc8ce`, `2153adc`, and `62932a9`, `darth-infra deploy
--env prod --verify-noop` reports a clean no-op against the real bta prod stack.

## Blocked by

- 10 (`10-cutover.md`)
