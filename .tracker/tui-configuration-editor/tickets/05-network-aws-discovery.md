## What to build

Add a complete Network section to the new editor and place optional AWS
discovery/verification behind an injected adapter. Users must be able to edit
offline, select discovered resources when credentials are available, retain
manual values, and understand which values are Automatic, explicit, verified,
unverified, or failed verification.

The section covers VPC lookup/override, private and public subnet discovery and
selection, shared versus dedicated ALB mode, shared ALB identity, listener and
security-group overrides, and dedicated certificate configuration. It must
round-trip both shared and dedicated existing projects without changing mode.

## Where to start

- Read current direct boto calls and state updates in
  `src/darth_infra/tui/screens/existing_resources.py`.
- Read shared ALB and network resolution in `src/darth_infra/cli/cfn.py`,
  especially `_resolve_network()` and `_resolve_shared_alb()`, to describe
  Automatic behavior accurately without duplicating deploy logic.
- Read ALB fields and validation in `src/darth_infra/config/models.py` and the
  canonical schema.
- Extend the new shell and field controls from ticket 04.
- Add deterministic fake-adapter Pilot tests rather than mocking boto clients
  inside widgets.

## Contract

- The editor depends on an AWS discovery interface supplied at application
  startup. Production uses a boto-backed adapter; tests use a fake adapter.
- The adapter returns domain records and typed failures. Widgets do not create
  boto clients or interpret raw boto response dictionaries.
- Local editing and saving never require AWS credentials.
- Verification is user-triggered and has visible `Not checked`, `Verified`, or
  `Check failed` state. Failure does not block a locally valid save.
- AWS-backed references support both Select from AWS and Enter manually.
- VPC selection filters subnet discovery. ALB selection filters listener
  discovery. Discovery never silently replaces an existing value.
- Empty results are distinct from loading, success with results, and failure.
- `vpc_id`, subnet lists, listener ARN, ALB security-group ID, and architecture-
  independent ALB identity fields use Automatic/Override semantics where the
  schema permits omission.
- Returning an existing explicit value to Automatic requires confirmation and
  removes the persisted key.
- Shared ALB name remains the common shared-mode selector. Listener ARN and
  security-group ID are advanced overrides.
- Public subnet controls explain their dedicated-ALB relevance. Private subnet
  overrides remain available because placement and ECS subnet limits are user
  intent.
- Dedicated mode exposes its persisted certificate setting and does not require
  shared-only fields.
- No TUI listener-priority lookup or allocation is introduced; priorities are
  owned by Routing and deploy-time resolution.
- The adapter interface may be extended by CloudFront and Secrets tickets, but
  this slice implements only network capabilities needed now.

## Out of scope

- Do not modify deploy-time VPC, ALB, or listener resolution.
- Do not add SSM Parameter Store operations.
- Do not make AWS verification a save prerequisite.
- Do not remove the legacy screens before ticket 16.
- Do not build routing rules or CloudFront configuration.

## Acceptance criteria

- [ ] Shared and dedicated ALB configurations load, edit, save, and reload without mode conversion or field loss.
- [ ] An existing project can be edited and saved with an adapter that has no AWS credentials.
- [ ] Fake discovery drives loading, results, empty, and failure states through Textual Pilot.
- [ ] Manual IDs/ARNs remain editable and are not replaced when discovery runs.
- [ ] VPC and ALB parent choices filter dependent fake-adapter requests.
- [ ] Automatic/Override controls preserve existing explicit values and remove keys only after confirmed reset.
- [ ] Verification status is visible and a failed check does not block a locally valid save.
- [ ] No new listener-priority allocation code exists in the new editor.

Run:

```bash
uv run pytest tests/test_tui_network_section.py tests/test_tui_aws_discovery.py
uv run pytest tests/test_cli_cfn_environment_tags.py tests/test_preview_environments.py
uv run pytest
git diff --check
```

Success means all tests pass, including offline and fake-AWS Pilot scenarios,
and `git diff --check` emits no output.

## Blocked by

- Ticket 04: `04-editor-shell-project.md`
