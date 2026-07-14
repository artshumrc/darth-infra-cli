## What to build

Complete Routing with CloudFront configuration, service connections, and cached
behaviors. Users must be able to enable CloudFront, edit every persisted field,
select or manually enter the required certificate, manage nested collections,
and receive complete cross-field validation without navigating a single long
undifferentiated form.

## Where to start

- Read CloudFront controls and behavior validation in
  `src/darth_infra/tui/screens/alb.py`.
- Read `CloudFrontConfig`, `CloudFrontConnection`, and
  `CloudFrontCachedBehavior` plus their model validation and schema definitions.
- Read existing builder and validation coverage in
  `tests/test_builders_cloudfront.py` and
  `tests/test_config_validation_cloudfront_alb.py`.
- Extend the AWS discovery adapter with CloudFront certificate discovery rather
  than adding boto calls to widgets.
- Reuse master-detail, field help, reference impact, and nested collection
  controls from preceding tickets.

## Contract

- CloudFront settings remain hidden behind an enable control when disabled, but
  existing configured values force the relevant panel open and are never
  discarded merely by navigation.
- Cover every persisted CloudFront field: enabled, ALB origin HTTPS-only,
  custom domain, certificate ARN, price class, comment, service connections,
  and all cached-behavior fields.
- Certificate input supports searchable AWS discovery and manual ARN entry.
  Discovery remains optional and does not block locally valid saves.
- Connections use service and environment-variable key fields and participate
  in service reference impact/cascade behavior.
- Cached behaviors use master-detail editing with name, path, compression,
  origin-header caching, TTLs, query-string mode/allowlist, cookie
  mode/allowlist, and Authorization forwarding.
- Conditional allowlists are visible only when their corresponding mode
  requires them; hidden existing values remain preserved until the user
  explicitly changes the mode and confirms any resulting removal.
- TTL ordering, unique names/path constraints, certificate/domain requirements,
  and origin protocol constraints surface next to fields and prevent save.
- Existing CloudFront rendering behavior, logical IDs, policies, and service
  references remain unchanged.
- Ordinary configured environment-variable keys and values are not masked.

## Out of scope

- Do not add new cache modes or CloudFront distribution behavior.
- Do not perform CloudFront deployment or distribution discovery.
- Do not alter ALB routing or priority allocation completed in ticket 08.
- Do not remove legacy Routing code before cutover.

## Acceptance criteria

- [ ] Pilot enables/disables CloudFront and edits every scalar field without losing hidden existing values.
- [ ] Certificate discovery and manual entry both work with fake/offline adapters.
- [ ] Service connections support add, edit, duplicate, delete, and service-reference cascade behavior.
- [ ] Cached behaviors round-trip every registered field and conditionally present allowlists.
- [ ] Invalid TTL ordering, modes, certificates, domains, and duplicate behavior identities prevent save at the responsible field.
- [ ] Existing non-default CloudFront configuration survives a no-op editor save.
- [ ] Existing CloudFront builder and validation tests remain green.

Run:

```bash
uv run pytest tests/test_tui_routing_cloudfront.py
uv run pytest tests/test_builders_cloudfront.py tests/test_config_validation_cloudfront_alb.py
uv run pytest
git diff --check
```

Success means all tests pass and `git diff --check` emits no output.

## Blocked by

- Ticket 05: `05-network-aws-discovery.md`
- Ticket 07: `07-advanced-services-references.md`
- Ticket 08: `08-alb-routing.md`
