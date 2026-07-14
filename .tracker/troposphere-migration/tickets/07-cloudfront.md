# 07 — CloudFront slice

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

Port the CloudFront layer: both distributions (the app CDN fronting the ALB
domain and the S3/static distribution), the `OriginAccessControl`, cached
behaviors (path patterns, header forwarding — including the always-forwarded
`Host` header and the conditional `Authorization` forwarding), custom-domain
certificate handling, and the CloudFront statements in the S3 bucket policy.

## Where to start

- `src/darth_infra/templates/cfn/root.yaml.j2` — first distribution (226),
  `OriginAccessControl` (360), second distribution (369), the CloudFront
  parts of `S3::BucketPolicy` (397).
- `tests/test_generator_cloudfront_alb.py` — the authoritative scenario set
  (custom domain vs none, forward-auth on/off, shared vs dedicated ALB).
  Port every one of its CloudFront assertions to structural form in this
  slice; its text assertions (e.g.
  `"Headers:\n                - Host"`) become dict assertions on the cached
  behavior's forwarded headers.
- Ticket 06's bucket/policy builders (this slice adds the CloudFront
  statements they deliberately left out) and ticket 04's ALB domain wiring.

## Contract

- Distribution logical IDs, origin IDs, cache/origin-request policy
  references, and behavior ordering match Jinja output exactly (behavior
  order is semantically meaningful to CloudFront).
- The forward-auth conditional affects exactly the headers list it affects
  today; `Host` is always present for cached behaviors, matching the current
  test's guarantee.

## Out of scope

- No changes to validation logic in
  `tests/test_cli_cfn_cloudfront_listener_validation.py`'s deploy-layer
  subject — deploy layer untouched.
- No CLI wiring, no `.j2` deletions, no config model changes.

## Acceptance criteria

- [ ] Every scenario in `test_generator_cloudfront_alb.py` has a structural
      counterpart in this slice's tests, asserting on `to_dict()` of the
      built root template.
- [ ] Both distributions, OAC, and bucket-policy statements structurally
      match Jinja output for a full-featured CloudFront fixture.
- [ ] cfn-lint passes over rendered fixture output; full suite green
      (original text-based tests still pass — they are deleted in ticket 10,
      not here).

Commands:

```
uv run pytest
uv run pytest tests/ -k cloudfront
```

## Blocked by

- 04 (`04-dedicated-alb-dns.md`)
- 06 (`06-service-discovery-s3.md`)
