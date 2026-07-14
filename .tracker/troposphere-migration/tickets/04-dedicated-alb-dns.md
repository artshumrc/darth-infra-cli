# 04 — Dedicated ALB, certificate, and Route53 slice

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

Port dedicated-ALB mode: the load balancer, its security group, the HTTP and
HTTPS listeners (with the certificate/no-certificate condition variants), the
Route53 record set, and the security-group-ingress cross-wiring between ALB
and services. Shared-ALB mode (parameters passed in from outside) already
works from tickets 02–03; this slice makes `AlbMode.DEDICATED` configs build
completely.

## Where to start

- `src/darth_infra/templates/cfn/root.yaml.j2` — `DedicatedAlb` (134),
  `DedicatedAlbSecurityGroup` (151), listeners (176, 203),
  `SecurityGroupIngress` (595), `Route53::RecordSet` (607). Note the
  condition set: `UseDedicatedAlb`, `HasCertificate`,
  `UseDedicatedAlbWithCert`, `UseDedicatedAlbNoCert`, `HasHostedZone` —
  already emitted by ticket 02; this ticket attaches resources to them.
- Existing dedicated-ALB test scenarios in
  `tests/test_generator_cloudfront_alb.py` (the `dedicated=True` fixtures) —
  port their assertions structurally into this slice's tests (CloudFront
  assertions stay with ticket 07).

## Contract

- Logical IDs, `Condition:` attachments, and listener default-action shapes
  match the Jinja output exactly.
- Listener-rule priority parameters and per-rule wiring follow ticket 01's
  context values (cluster routing).
- One template still serves all environments: no render-time branching on
  environment name — dedicated vs shared stays a CFN Parameter/Condition
  concern exactly as today.

## Out of scope

- CloudFront distributions (ticket 07), even though they reference the ALB
  domain.
- Any change to how `_build_parameters`/lookups resolve shared-ALB values in
  `cli/cfn.py` — deploy layer untouched.
- No CLI wiring, no `.j2` deletions.

## Acceptance criteria

- [ ] A dedicated-ALB fixture (with certificate) builds a root template whose
      `to_dict()` structurally matches Jinja output for ALB, SG, both
      listeners, ingress wiring, and Route53 record — including `Condition:`
      attachments.
- [ ] A dedicated-ALB fixture without certificate exercises the
      `UseDedicatedAlbNoCert` listener variant.
- [ ] cfn-lint passes over the rendered fixture output.
- [ ] Full suite green.

Commands:

```
uv run pytest
uv run pytest tests/ -k "alb"
```

## Blocked by

- 03 (`03-service-stack-core.md`)
