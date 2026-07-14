# troposphere-migration — Release manager guide

This epic replaces the Jinja2 CloudFormation templates with a troposphere
object pipeline. The cutover (ticket 10) is behaviorally invisible: an
unchanged `darth-infra.toml` must produce a **no-op deploy** (an empty change
set) on every existing stack. Before publishing the minor release, the release
manager runs the no-op verification gate against each real deployed stack.

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

### Expected output — PASS (no changes)

CloudFormation refuses to create an empty change set, and that failure is the
success signal:

```
Verifying no-op deploy for <project> environment <env>...
...
No infrastructure changes detected.
✓ No-op verification passed for <env>: no infrastructure changes.
```

Exit code `0`. The change set is deleted before the command returns.

### Expected output — FAIL (changes would occur)

```
Verifying no-op deploy for <project> environment <env>...
...
Change set: verify-<env>-<timestamp>
- Modify: WebTaskDefinition (AWS::ECS::TaskDefinition)
- Modify: WebService (AWS::ECS::Service)
No-op verification FAILED: 2 infrastructure change(s) detected (listed above).
✗ No-op verification failed for <env>: infrastructure changes detected (see above).
```

Exit code `1` (nonzero). The change set is still deleted before returning.

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
