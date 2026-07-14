## What to build

Deliver the complete Secrets section using master-detail editing and the AWS
discovery adapter. Users must be able to configure every existing secret source,
bind one declaration to multiple services, inspect source metadata, and safely
remove references without ever viewing secret values.

## Where to start

- Read current secret source controls and Secrets Manager listing in
  `src/darth_infra/tui/screens/secrets.py`.
- Read `SecretSource`, `SecretConfig`, secret validation, loader, and serializer.
- Read secret resolution in `src/darth_infra/cli/secret_cmd.py` and deploy lookup
  behavior only to describe source semantics; do not move retrieval into the
  editor.
- Extend the AWS discovery adapter from ticket 05 for secret metadata listing.
- Reuse Services master-detail and reference-impact interfaces.

## Contract

- Secrets use searchable master-detail behavior with add, duplicate, select,
  edit, and confirmed delete.
- Cover every persisted field: environment-variable name, source, existing
  secret name/ARN or RDS JSON key, generated length, `generate_once`, and all
  service bindings represented by current configuration semantics.
- Supported sources remain `generate`, `env`, `existing`, and `rds`; their
  deploy behavior does not change.
- Existing-secret discovery lists identifiers and metadata only. Manual
  name/ARN entry remains available offline.
- The editor never calls `get_secret_value`, displays secret values, writes them
  to logs, or includes them in errors/test snapshots.
- `env` source describes the deployer's local environment reference without
  collecting or persisting the value in the TUI.
- RDS-backed declarations preserve existing RDS binding behavior and JSON-key
  validation.
- Service binding changes use existing service references. Deleting a secret
  lists and atomically removes its service references after confirmation.
- Duplicate copies source settings but requires a unique environment-variable
  name and does not silently replace an existing declaration.
- Ordinary service environment variables remain outside this screen and are not
  masked or reclassified as secrets.

## Out of scope

- Do not view, reveal, rotate, or update live secret values.
- Do not add SSM Parameter Store support.
- Do not change generated-secret lifecycle or Secrets Manager naming.
- Do not redesign RDS-provided aliases or add a shared environment-variable
  model.

## Acceptance criteria

- [ ] Pilot can add, search, edit, duplicate, and delete all four secret source types.
- [ ] Every registered secret field and service binding saves and reloads.
- [ ] Fake AWS discovery supports results, empty, and failure states while manual entry remains usable offline.
- [ ] No test or production path in the new editor retrieves or renders secret values.
- [ ] Deleting a bound secret lists affected services and performs atomic reversible cleanup only after confirmation.
- [ ] Duplicate requires a unique name and preserves source metadata without changing live AWS state.
- [ ] Existing secret deployment and render-context tests remain green.

Run:

```bash
uv run pytest tests/test_tui_secrets_section.py tests/test_tui_aws_discovery.py
uv run pytest tests/test_render_context.py tests/test_cli_cfn_deploy_changeset.py
uv run pytest
git diff --check
```

Success means all tests pass, no secret-value retrieval is introduced, and
`git diff --check` emits no output.

## Blocked by

- Ticket 05: `05-network-aws-discovery.md`
- Ticket 07: `07-advanced-services-references.md`
