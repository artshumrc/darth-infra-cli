# troposphere-migration — Release manager guide

This epic replaces the Jinja2 CloudFormation templates with a troposphere
object pipeline. The cutover (ticket 10) is behaviorally invisible: an
unchanged `darth-infra.toml` must produce **no real infrastructure changes** on
every existing stack. Before publishing the minor release, the release manager
runs the no-op verification gate against each real deployed stack.

Note on "no-op": the deploy uses nested stacks referenced by content-hashed S3
URLs. Because troposphere serializes YAML differently than the old Jinja
templates, `aws cloudformation package` produces new child-template hashes, so
every nested `AWS::CloudFormation::Stack` resource shows as `Modify` (a new
`TemplateURL`) even when nothing inside actually changes. A strict *empty*
change set is therefore impossible on the cutover. The gate recurses into
nested stacks and grades **leaf** resources instead: nested-stack wrapper churn
is ignored, and the gate passes when no leaf resource is really added, removed,
or modified.

## The no-op verification gate

The gate is a flag on the existing deploy command. It renders and resolves the
templates the same way a real deploy does (`generate_project` →
`resolve_lookup_data` → `build_project_templates`), then does a **read-only
structural comparison** of the deployed stack templates (fetched with
`get-template`, root + nested) against the freshly-built templates. It makes no
changes to infrastructure and creates no change set.

It deliberately does **not** use a CloudFormation change set: change sets over
nested stacks emit conservative false positives (e.g. predicting an ECS service
"replacement" for an unchanged cluster) whenever a nested stack updates — and
the serializer migration updates every nested stack. The structural comparison
resolves parameter references, evaluates conditions (so condition-gated-off
resources like dedicated-ALB listeners on a shared-ALB stack are skipped), and
ignores nested-stack `TemplateURL` content-hash churn, reporting only real
leaf-resource differences.

```bash
# Run from the target project directory (the one with darth-infra.toml).
# Requires AWS credentials with read access to the stack and its lookups.
uv run darth-infra deploy --env <env> --verify-noop
echo $?   # 0 = no infrastructure changes (PASS); nonzero = changes detected (FAIL)

# Preview environments are not declared in darth-infra.toml, so they also need
# --preview-from; without it the command fails with "Environment not found".
uv run darth-infra deploy --env pr-140 --preview-from prod --verify-noop
```

`--verify-noop` cannot be combined with `--cancel`, `--with-images`, or
`--no-execute`.

**The gate is read-only against AWS, but not against your working tree.** It
re-renders `templates/generated/` (and refreshes `darth-infra.schema.json`) in
the target project repo as part of building the comparison templates, so each
project you check will come back with a dirty git status showing the one-time
serializer reformat. That diff is expected and is what you commit as part of
the cutover; `git checkout -- .` discards it if you would rather stage it
deliberately later.

**A stack that has not been deployed in a long time will fail the gate for
reasons unrelated to this migration.** The gate compares against the *deployed*
template, so it also surfaces every config and generator change made since that
stack's last deploy. Before treating a failure as a migration regression,
render the same config from `main` and from this branch and diff them — if they
agree, the drift predates the migration and belongs to a separate catch-up
deploy:

```bash
git worktree add /tmp/main-wt main
cd <project-dir>
uv run --project /tmp/main-wt              darth-infra render -o /tmp/out-main
uv run --project <this-repo>               darth-infra render -o /tmp/out-new
diff -r /tmp/out-main/templates /tmp/out-new/templates
```

### Expected output — PASS (no real changes)

```
Verifying no-op deploy for <project> environment <env>...
Refreshing CloudFormation templates from darth-infra.toml...
Skipped 1 static nested template(s) not built from config: CustomOverrides (../custom/overrides.yaml).
No real infrastructure changes — structural no-op confirmed (nested-stack template churn and deploy-time-resolved values ignored).
✓ No-op verification passed for <env>.
```

Exit code `0`. The static `CustomOverrides` placeholder is a fixed
WaitConditionHandle stack that is not built from config, so it is skipped.

### Expected output — FAIL (real leaf changes would occur)

```
Verifying no-op deploy for <project> environment <env>...
...
No-op verification FAILED: 3 structural change line(s):
  [ServiceWeb] changed resource TaskDefinition (AWS::ECS::TaskDefinition)
      .ContainerDefinitions
  [root] added resource SomeNewBucket (AWS::S3::Bucket)
✗ No-op verification failed for <env>: infrastructure changes detected (see above).
```

Exit code `1` (nonzero). Each `[stack] changed/added/removed resource …` line
names a real resource-level difference, with the changed property paths under
it. Investigate every one before publishing the release.

## Release procedure

1. On branch `jinja-to-troposphere`, for **each** existing real stack/env:
   `uv run darth-infra deploy --env <env> --verify-noop` and confirm exit `0`.
   (The gate creates no change sets, so there is nothing to clean up
   afterward — the older "delete leftover change sets" step no longer applies.)
2. For any stack that fails, run the `main`-vs-branch render diff above before
   concluding it is a regression.
3. Only when **every** stack reports no changes, publish the minor release
   (see `.changeset/troposphere-cfn-generation.md`).

### Fleet inventory and status (2026-08-07)

The darth-infra-managed stacks are exactly these; everything else in account
`407196791491` is CDK or unrelated. Identify them by the
`<project>-ecs-<env>` naming and the `darth-infra root stack for …`
description.

| Stack | Project dir | Gate result |
| --- | --- | --- |
| `iiif-cache-ecs-prod` | `infrastructure/iiif-cache/iiif-cache-infrastructure` | PASS |
| `bta-infrastructure-ecs-prod` | `bta/infrastructure` | PASS |
| `bta-infrastructure-ecs-pr-140` | `bta/infrastructure` (preview) | PASS; deployed + destroyed as the live test, stack no longer exists |
| `elasticsearch-shared-ecs-prod` | `infrastructure/elasticsearch/elasticsearch-shared-infra` | FAIL — pre-existing drift, see below |

`bta-infrastructure-ecs-pr-140` was deployed for real on the new pipeline: the
update touched only nested-stack wrappers, all four ECS task definitions stayed
at revision `:1`, and the RDS instance, S3 bucket, CloudFront distributions,
Cloud Map namespace and secrets kept their physical IDs. CloudFormation
predicted `Modify` on two `AWS::EC2::SecurityGroupIngress` leaves and then
emitted no events for them — the same change-set over-prediction that motivated
the structural gate.

### `elasticsearch-shared` is blocked on a separate problem

That stack was last deployed 2026-02-23 and is ~6 months of generator changes
behind, so its gate failure is drift, not this migration — `main` and this
branch render it identically apart from one intentional fix
(`Ec2InstanceProfile` no longer emits `Tags`, which CloudFormation rejects;
`main`'s template is invalid and cannot deploy at all).

Do **not** deploy it as part of this release. Its pending drift renames both
secrets:

```
deployed: ${ProjectName}-${EnvironmentName}-elastic-password
current:  /darth-infra/${ProjectName}/${EnvironmentName}/ELASTIC_PASSWORD
```

`Name` is a replacement property on `AWS::SecretsManager::Secret`, so the next
deploy replaces and regenerates them despite `generate_once` — and
`bta/infrastructure/darth-infra.toml` references the *old* ARNs directly via
`source = "existing"`, so the blast radius includes bta prod's django, worker
and sveltekit. Needs its own plan: pre-create the new secret names carrying the
existing values, repoint bta, then deploy.

If any stack reports changes, do **not** publish. Investigate the printed diff:
the troposphere output is expected to be byte-for-byte equivalent to the Jinja
output for logical IDs, parameters, and resource properties, so any resource
change indicates a regression to fix before release.
