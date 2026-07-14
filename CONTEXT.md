# Domain Glossary

## Configuration

**Guided editor** — An interactive interface for every user-authored field in
the persisted project configuration. Common fields are immediately visible;
rare fields may be grouped into advanced panels, but remain editable and must
round-trip without loss. Navigation is non-linear, with an optional guided
order for creating or reviewing a project.

**Document-preserving save** — An update to an existing project configuration
that retains user-authored comments, ordering, and unrelated formatting while
changing only the settings edited by the user.

## Deployment

**No-op deploy** — A deploy against an already-provisioned stack whose changeset
reports no changes (CloudFormation refuses changeset execution with "the
submitted information didn't contain changes"). The backwards-compatibility
contract for template-generation changes: rendering an unchanged
`darth-infra.toml` with a new generator version must produce a no-op deploy on
every existing stack. Textual differences in rendered YAML are permitted;
resource replacement or modification is not.

**Logical ID** — The CloudFormation resource key (e.g. `EcsCluster`,
`DedicatedAlb`). Changing a logical ID causes CloudFormation to replace the
resource, which for stateful resources (RDS, S3) means data loss. Logical IDs
are therefore a permanent public contract of the generator, independent of how
templates are produced.

**Rendered template** — The YAML written to `templates/generated/` by
`darth-infra render` or regenerated transiently by `darth-infra deploy`. A
build artifact derived entirely from `darth-infra.toml`; never hand-edited.
User-owned customization lives in the `custom/` overrides stack instead.
