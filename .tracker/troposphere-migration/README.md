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
```

`--verify-noop` cannot be combined with `--cancel`, `--with-images`, or
`--no-execute`.

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
2. Confirm no change sets were left behind (the gate deletes its own, but
   verify per stack):
   `aws cloudformation list-change-sets --region <region> --stack-name <project>-ecs-<env>`
   should show no `verify-<env>-*` change sets.
3. Only when **every** stack reports no changes, publish the minor release
   (see `.changeset/troposphere-cfn-generation.md`).

If any stack reports changes, do **not** publish. Investigate the printed diff:
the troposphere output is expected to be byte-for-byte equivalent to the Jinja
output for logical IDs, parameters, and resource properties, so any resource
change indicates a regression to fix before release.
