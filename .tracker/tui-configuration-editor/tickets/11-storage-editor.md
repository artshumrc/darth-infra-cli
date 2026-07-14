## What to build

Deliver the complete Storage section using master-detail bucket editing. Users
must be able to manage all S3 bucket modes, seed and preview behavior, access
flags, CloudFront integration, and service connections without losing advanced
fields the legacy TUI does not expose reliably.

## Where to start

- Read current bucket and connection forms in
  `src/darth_infra/tui/screens/s3.py`.
- Read `S3BucketConfig`, `S3BucketConnection`, their validation, schema, and
  serializer behavior.
- Pay particular attention to preview fallback fields, seed-copy fields,
  connection service lists, and `cloudfront_env_key`.
- Read existing S3 render-context derivation and builder coverage before
  changing editor behavior.
- Reuse Services master-detail and reference-impact interfaces.

## Contract

- Buckets use searchable master-detail behavior with add, duplicate, select,
  edit, and confirmed delete.
- Cover every persisted bucket field: name, mode, existing bucket name, seed
  source, preview fallback bucket and env key, non-prod seed scope, public read,
  CloudFront, CORS, and all connection fields.
- Mode-specific fields use conditional panels. Hidden existing values are
  preserved until an explicit mode change confirms their removal or reset.
- Bucket connections support all persisted service, env key, CloudFront env
  key, and read-only fields and participate in service reference impact.
- Public-read changes display an amber deployment-sensitive warning and remain
  ordinary saveable configuration after explicit risk confirmation.
- Deleting a bucket lists affected service connections and configuration
  relationships and applies cleanup as one reversible transaction.
- Duplicate copies bucket-owned fields and connections but requires a unique
  bucket logical name.
- Existing managed/existing/seed-copy semantics, bucket naming, policies, and
  preview fallback behavior remain unchanged.

## Out of scope

- Do not create, inspect, or mutate live S3 objects.
- Do not add bucket modes or change IAM policy semantics.
- Do not move preview policy editing out of Environments; only bucket-specific
  preview fallback fields belong here.
- Do not infer or display deployed bucket names beyond existing configuration.

## Acceptance criteria

- [ ] Pilot can add, search, edit, duplicate, and delete buckets through master-detail controls.
- [ ] Every registered bucket and connection field saves and reloads, including preview fallback and CloudFront env keys.
- [ ] Existing hidden mode-specific values survive navigation and a no-op save.
- [ ] Explicit mode changes handle incompatible values only after confirmation.
- [ ] Service deletion impact includes bucket connections, and bucket deletion cleanup is atomic and reversible.
- [ ] Public-read changes appear as deployment-sensitive without being blocked after confirmation.
- [ ] Existing S3 render-context, builder, and preview tests remain green.

Run:

```bash
uv run pytest tests/test_tui_storage_section.py
uv run pytest tests/test_render_context.py tests/test_builders.py tests/test_preview_environments.py
uv run pytest
git diff --check
```

Success means all tests pass and `git diff --check` emits no output.

## Blocked by

- Ticket 04: `04-editor-shell-project.md`
- Ticket 07: `07-advanced-services-references.md`
