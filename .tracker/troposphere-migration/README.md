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

The gate is packaged as a flag on the existing deploy command, so it exercises
the exact rendering + packaging + change-set code path that a real deploy runs
(`generate_project` → `build_project_templates` → `validate_built_deploy_templates`
→ `resolve_lookup_data` → `package_template` → `deploy_changeset`). It is
read-only with respect to infrastructure: it creates a CloudFormation change
set **without executing it**, inspects it, and always deletes it afterward.

```bash
# Run from the target project directory (the one with darth-infra.toml).
# Requires AWS credentials with read access to the stack and its lookups.
uv run darth-infra deploy --env <env> --verify-noop
echo $?   # 0 = no infrastructure changes (PASS); nonzero = changes detected (FAIL)
```

`--verify-noop` cannot be combined with `--cancel`, `--with-images`, or
`--no-execute`.

### Expected output — PASS (no real changes)

Two shapes both pass with exit code `0`. If the generated templates happen to
match what is deployed byte-for-byte, CloudFormation refuses to create an empty
change set and that failure is the success signal (`No infrastructure changes
detected.`). On the cutover the usual shape is nested-stack template churn only:

```
Verifying no-op deploy for <project> environment <env>...
...
Change set: verify-<env>-<timestamp>
Ignoring 5 nested-stack wrapper change(s) (TemplateURL/parameter reformatting; leaf contents inspected below).
No real infrastructure changes detected (nested-stack template churn only).
✓ No-op verification passed for <env>.
```

The change set is deleted before the command returns. If any resources are
listed as `~ attribute-driven (unresolved statically)`, those are ripples
CloudFormation could not resolve (typically a `SecurityGroupIngress` that
references a nested-stack output). They do **not** fail the gate, but glance at
them — they should be resources that legitimately depend on an updated stack.

### Expected output — FAIL (real leaf changes would occur)

```
Verifying no-op deploy for <project> environment <env>...
...
Change set: verify-<env>-<timestamp>
No-op verification FAILED: 2 real leaf infrastructure change(s):
  - Modify: TaskDefinition (AWS::ECS::TaskDefinition)
  - Add: SomeNewBucket (AWS::S3::Bucket)
✗ No-op verification failed for <env>: infrastructure changes detected (see above).
```

Exit code `1` (nonzero). The change set is still deleted before returning.
Investigate every listed resource before publishing the release.

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
