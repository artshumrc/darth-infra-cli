## What to build

Deliver the ALB portion of Routing: cluster domain, default target service,
shared/dedicated mode context, default host-header rule, and additional path
rules. Listener priorities remain editable only as Advanced preferred overrides;
the editor must not query or allocate a "next" priority.

The slice must round-trip shared and dedicated routing, use the common
master-detail and reference-impact behavior, and prove that deploy-time
allocation and stack-owned priority preservation remain authoritative.

## Where to start

- Read current routing controls, validation, and priority workers in
  `src/darth_infra/tui/screens/alb.py`.
- Read the unreachable duplicate ALB methods in
  `src/darth_infra/tui/screens/services.py`; they are removed at cutover, not a
  source for the new editor.
- Read ALB validation in `ProjectConfig.__post_init__` and priority resolution in
  `_resolve_listener_priorities()` in `src/darth_infra/cli/cfn.py`.
- Reuse Network's Automatic/Override controls and Services' master-detail and
  reference-impact interfaces.
- Read existing optional-priority and preview allocation tests before adding
  Pilot coverage.

## Contract

- Routing owns cluster domain, default target, default preferred priority, and
  path rules. Network owns ALB mode and resource identity; Routing displays that
  context and links to Network rather than duplicating controls.
- Default and path-rule priorities use Automatic/Override. Automatic omits the
  value; Override persists an integer from 1 through 50000.
- Help text states that explicit priorities are preferences and existing
  stack-owned values are preserved during deploy.
- There is no `Get Next Available Priority` action, boto rule lookup, or local
  allocator in the new editor.
- Path rules use master-detail behavior with unique name, path pattern, target
  service, and optional preferred priority.
- Target controls list only eligible services according to existing model
  rules. Removing or changing a service uses the reference-impact contract.
- Duplicate priority validation and normalized rule-name collision validation
  surface adjacent to the responsible fields and prevent save.
- Shared and dedicated ALB configurations both retain their persisted fields.
- Changing routing configuration does not change logical-ID derivation,
  priority parameter names, or deploy allocation order.
- Priority reset to Automatic is a semantic `reset_to_default`/omission change
  and requires confirmation when replacing an existing explicit value.

## Out of scope

- Do not implement CloudFront; ticket 09 owns it.
- Do not modify deploy-time listener-priority allocation.
- Do not remove preview priority bounds.
- Do not remove legacy files until ticket 16.
- Do not introduce route-order semantics beyond the existing list order and
  preferred-priority model.

## Acceptance criteria

- [ ] Pilot edits and round-trips domain, default target, default priority override, and complete path rules.
- [ ] Automatic priority omits the TOML key; Override persists a validated value.
- [ ] Returning an existing explicit priority to Automatic requires confirmation and produces a reset semantic diff.
- [ ] No priority fetch button or TUI allocation call is visible or reachable in the new editor.
- [ ] Shared and dedicated configurations survive a no-op editor save unchanged.
- [ ] Invalid service targets, duplicate priorities, and colliding rule identities prevent save and focus the relevant field.
- [ ] Existing deploy allocation and no-op priority tests remain green.

Run:

```bash
uv run pytest tests/test_tui_routing_alb.py
uv run pytest tests/test_config_validation_cloudfront_alb.py tests/test_preview_environments.py tests/test_cli_cfn_verify_noop.py
uv run pytest
git diff --check
```

Success means all tests pass, no new editor priority allocator exists, and
`git diff --check` emits no output.

## Blocked by

- Ticket 05: `05-network-aws-discovery.md`
- Ticket 07: `07-advanced-services-references.md`
