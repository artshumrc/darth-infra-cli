# 06 — Service discovery + S3 slice

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

Port Cloud Map service discovery (the private DNS namespace in the root
stack with its create-vs-existing conditions, and the per-service
`ServiceDiscovery::Service` + ECS service registry wiring) and the S3 layer
(buckets, bucket policy, and the bucket-connection env vars/IAM statements
services receive).

## Where to start

- `src/darth_infra/templates/cfn/root.yaml.j2` — `ServiceNamespace` (118,
  conditions `CreateServiceNamespace`/`HasExistingCloudMapNamespace`,
  parameter `ExistingCloudMapNamespaceId`), `S3::Bucket` (337),
  `S3::BucketPolicy` (397).
- `src/darth_infra/templates/cfn/nested/service.yaml.j2` —
  `ServiceDiscovery::Service` (509) and the `ServiceRegistries` block on the
  ECS service (603+); S3-related IAM statements in the task role and bucket
  env vars in the task definition.
- Service-discovery fixtures in `tests/test_preview_environments.py`
  (`ServiceDiscoveryConfig`) and S3 fixtures (`S3BucketConfig`,
  `S3BucketConnection`, `S3BucketMode`).

## Contract

- Namespace name comes through ticket 01's context
  (`service_discovery_namespace_cfn`) — same `Fn::Sub` string as Jinja.
- `Fn::If` selection between created and existing namespace IDs matches the
  Jinja shape wherever the namespace is referenced.
- S3 bucket logical IDs, bucket modes (create vs existing), and
  policy/OAC-related statements match Jinja exactly — except OAC/CloudFront
  statements, which belong to ticket 07 (leave the same seams the Jinja
  template has).

## Out of scope

- CloudFront distributions and OriginAccessControl (ticket 07), even where
  the bucket policy references them — port only what exists without
  CloudFront enabled, matching Jinja's conditional blocks.
- No CLI wiring, no `.j2` deletions, no config model changes.

## Acceptance criteria

- [ ] A service-discovery fixture builds root + service templates
      structurally matching Jinja: namespace with conditions, per-service
      discovery service, ECS `ServiceRegistries` wiring.
- [ ] An S3 fixture (create-mode and existing-mode buckets) matches Jinja for
      bucket resources, task-role IAM statements, and injected env vars.
- [ ] cfn-lint passes over rendered fixture output; full suite green.

Commands:

```
uv run pytest
uv run pytest tests/ -k "discovery or s3"
```

## Blocked by

- 03 (`03-service-stack-core.md`)

## Implementation note

The Cloud Map and non-CloudFront S3 slices are implemented and their structural
Jinja-parity tests pass. `uv run pytest tests/ -k "discovery or s3"` passes all
14 selected tests, including cfn-lint for the S3-enabled service template.

The full suite is blocked by two failures introduced by the concurrent,
uncommitted ticket 04 work: the minimal-root test does not expect the newly
unconditional dedicated-ALB/DNS resources, and cfn-lint rejects `Tags` on the
two ALB listener resources. Ticket 06 does not modify those out-of-scope
resources, so human resolution of ticket 04 is required before this ticket can
meet the full-suite acceptance criterion and be marked completed.

## Resolution (2026-07-14)

The ticket-04 blocker is gone: tickets 04 and 05 have since landed. Verified the
current tree against every acceptance criterion — the Cloud Map service-discovery
and non-CloudFront S3 slices were already implemented in
`src/darth_infra/scaffold/builders/__init__.py` (folded into commit f286653), so
no builder code needed to be written for this ticket.

- Full suite: `uv run pytest` -> 93 passed.
- Scoped suite: `uv run pytest tests/ -k "discovery or s3"` -> 14 passed,
  including structural Jinja-parity for the service-discovery namespace/service +
  ECS `ServiceRegistries` wiring and for create-mode (`Bucketmediafiles`) and
  existing-mode (`shared-assets`, no bucket resource) S3 connections.
- cfn-lint: rendered the `_s3_config` and `_service_discovery_config` root and
  service templates and ran `cfn-lint --non-zero-exit-code error` over all four —
  exit 0 (W-level warnings only). Confirms create-mode + existing-mode S3 and
  service-discovery output are valid.

Only tracker/ticket files changed for this ticket.
