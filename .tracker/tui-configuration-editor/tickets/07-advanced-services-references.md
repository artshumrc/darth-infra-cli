## What to build

Complete the Services section and introduce reusable configuration-reference
impact handling. Add every remaining persisted service setting, nested ulimit
and EBS editors, service discovery configuration, and explicit
Automatic/Override architecture behavior. A service deletion must show all
incoming references and offer one atomic, reversible cleanup transaction.

The reference mechanism delivered here is shared by later Routing, Database,
Storage, Secrets, and Environments slices; it must reason over the effective
configuration even when those new screens do not yet exist.

## Where to start

- Extend the core Services master-detail editor from ticket 06.
- Read advanced fields in `ServiceConfig`, `EbsVolumeConfig`, `UlimitConfig`,
  and `ServiceDiscoveryConfig`.
- Read renderer architecture derivation in `src/darth_infra/config/models.py`
  and `src/darth_infra/scaffold/context.py` so Automatic reflects existing
  behavior.
- Inventory service references in ALB default/path targets, CloudFront
  connections, RDS `expose_to`, S3 connections, secret bindings, and
  environment EC2 instance overrides.
- Use the document transaction/reversion capability from ticket 03 for atomic
  cleanup.

## Contract

- Complete all remaining schema-registered service fields, including explicit
  architecture, user-data script path, inline user-data content, service
  discovery enablement, ulimits, and every EBS field including volume type,
  device, mount path, size, and filesystem.
- Architecture uses Automatic/Override. Automatic omits the field and preserves
  existing instance-type inference; Override persists `x86_64` or `arm64`.
- EC2-only panels are hidden or clearly unavailable for Fargate and auto-expand
  when an existing EC2 service has configured values.
- Ulimits and EBS volumes use nested master-detail controls with stable names,
  visible selection state, validation, duplicate, and confirmed delete.
- Global service-discovery namespace configuration is owned by Services; the
  per-service toggle remains on each service.
- A reference-impact module returns all semantic references to a selected
  resource without knowing about Textual widgets.
- Deleting a referenced service presents the complete impact list and offers
  Cancel or `Delete service and remove N references`.
- Confirmed deletion and cleanup are one document-session transaction. Revert
  restores the service and all references until save.
- Cleanup removes only references to the deleted service; it does not delete
  otherwise valid secrets, buckets, databases, rules, or environments.
- Duplicate continues to copy all service-owned advanced/nested fields but no
  incoming external references.
- Existing deployment semantics and render context remain unchanged.

## Out of scope

- Do not implement the owning screens for references; later tickets do that.
- Do not alter architecture inference, RDS exposure semantics, or service
  discovery rendering.
- Do not cascade-delete referenced resources themselves.
- Do not add global undo/redo or persist draft transactions.

## Acceptance criteria

- [ ] Every remaining service schema field is editable and round-trips, including explicit defaults and omitted Automatic architecture.
- [ ] Existing architecture, user-data path/content, ECS Exec, ulimit, EBS volume type, and service-discovery values survive a no-op editor save.
- [ ] Nested ulimit and EBS collections support add, edit, duplicate, validation, and confirmed delete through Pilot.
- [ ] Reference impact lists ALB, CloudFront, RDS, S3, secret, and environment references to a service.
- [ ] Confirmed service deletion removes all listed references atomically and leaves no dangling references.
- [ ] Revert restores the deleted service and every cleaned reference.
- [ ] Duplicate copies nested service-owned settings but no incoming references.
- [ ] Render-context and builder tests show no infrastructure semantic changes.

Run:

```bash
uv run pytest tests/test_tui_services_advanced.py tests/test_config_reference_impact.py
uv run pytest tests/test_render_context.py tests/test_builders.py
uv run pytest
git diff --check
```

Success means all tests pass and `git diff --check` emits no output.

## Blocked by

- Ticket 05: `05-network-aws-discovery.md`
- Ticket 06: `06-core-services-editor.md`
