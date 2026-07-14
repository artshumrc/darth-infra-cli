## What to build

Deliver Review as an actionable representation of the current draft. It must
show a section-grouped semantic change list, the exact document-preserving TOML
patch, a compact topology of declared configuration relationships, validation
problems linked to owning fields, and deployment-sensitive warnings based only
on the unsaved diff.

Review remains available for existing-project inspection and is mandatory
before first-time creation. It does not claim to show deployed AWS topology or
an authoritative CloudFormation plan.

## Where to start

- Read the current long static summary in
  `src/darth_infra/tui/screens/review.py`; replace its state-dictionary
  formatting rather than extending it.
- Use semantic changes and exact patch output from ticket 03.
- Read relationships already derived in `src/darth_infra/scaffold/context.py`
  for vocabulary, but derive Review topology from the draft configuration, not
  rendered templates.
- Read resource validation in `ProjectConfig.__post_init__` and the reference
  impact module from ticket 07.
- Use every completed editor section's registry ownership to make changes and
  errors navigable.

## Contract

- Review has at least `Changes` and `TOML` views.
- Changes groups semantic operations by canonical editor section and labels
  `added`, `removed`, `changed`, and `reset to default` distinctly.
- Environment-variable values remain visible ordinary configuration in both
  views. Actual secret values are never available to Review.
- TOML displays the exact patch that the current save would apply, preserving
  document formatting outside changed regions.
- Unchanged fields are omitted from Changes.
- Topology visualizes only declared relationships among CloudFront, ALB routes,
  services, RDS, buckets, and secret declarations.
- Topology clearly identifies itself as configuration, not deployed AWS state.
  Large topologies can collapse, and invalid/dangling relationships link to the
  owning editor where practical.
- Deployment-sensitive classification includes at minimum removal or identity
  change of managed RDS, managed buckets, ALB mode, environment identity,
  service identity, and network identity.
- Warnings say what a future deploy may do; they never assert replacement or
  deletion without a CloudFormation changeset.
- Warnings compare only the loaded/saved document with the current draft and
  disappear when that diff is saved or reverted.
- One confirmation per save covers all current deployment-sensitive changes.
  Save orchestration and conflict UX are completed in ticket 15.
- Validation errors appear before topology/diff confirmation and navigate to the
  first responsible control.

## Out of scope

- Do not render templates or create a CloudFormation changeset.
- Do not query AWS for topology or deployment status.
- Do not track the last deployed configuration.
- Do not mask environment-variable values.
- Do not write a new independent risk model outside semantic changes.

## Acceptance criteria

- [ ] Pilot shows semantic and exact TOML views for representative edits in every canonical section.
- [ ] Added, removed, changed, and reset-to-default operations have distinct visible labels.
- [ ] The exact TOML view matches the patch applied by the document session.
- [ ] Topology shows configured routes and dependencies, identifies itself as configuration, and collapses for a large fixture.
- [ ] Invalid topology relationships navigate to their owning editor control.
- [ ] Deployment-sensitive changes produce one future-deploy warning and confirmation; ordinary changes do not.
- [ ] Warnings clear after revert and do not claim persisted deployment state.
- [ ] Environment variables are visible and actual secret values are absent.

Run:

```bash
uv run pytest tests/test_tui_review.py tests/test_tui_topology.py tests/test_tui_risk_changes.py
uv run pytest tests/test_config_document.py tests/test_config_document_merge.py
uv run pytest
git diff --check
```

Success means all tests pass and `git diff --check` emits no output.

## Blocked by

- Ticket 03: `03-document-diff-merge-reversion.md`
- Ticket 08: `08-alb-routing.md`
- Ticket 09: `09-cloudfront-routing.md`
- Ticket 10: `10-database-editor.md`
- Ticket 11: `11-storage-editor.md`
- Ticket 12: `12-secrets-editor.md`
- Ticket 13: `13-environments-preview-editor.md`
