# Complete TUI Configuration Editor

## Problem Statement

The current terminal interface behaves as a partially linear setup wizard rather
than a complete configuration editor. It exposes only part of the persisted
project configuration, mixes user intent with deploy-derived values, and can
silently replace unsupported values with defaults when an existing project is
saved. Some controls, such as ALB listener-priority lookup, duplicate deployment
logic and can produce different choices from the deploy-time allocator.

The interface is also difficult to use for focused maintenance. Navigation is
crowded and progression-oriented, long forms provide weak visual hierarchy,
validation relies heavily on transient notifications, AWS lookups lack clear
loading and empty states, and an operator cannot confidently change one field
and exit. Rebuilding the TOML document on save also risks erasing comments,
ordering, explicit-default intent, and unrelated formatting.

The editor must become a complete, non-linear guided editor for every
user-authored persisted setting while preserving the no-op deploy and Logical ID
contracts. It should remain approachable for first-time project creation,
efficient for one-field edits, and visually appropriate for an infrastructure
operations tool.

## Solution

Replace the existing wizard with a complete, purpose-built Textual editor. The
editor presents common fields immediately and places rare settings in Advanced
panels, but every user-authored field in the persisted schema remains editable.
Schema coverage is enforced automatically so future configuration additions
cannot silently bypass the TUI. CLI-maintained metadata is shown read-only and
must be explicitly identified as such in the schema.

Use non-linear section navigation with guided progression for first-time setup.
Existing projects open directly into an editor where any section can be reached,
changed, validated, and saved without visiting Review. Repeatable resources use
a consistent master-detail interaction. Deploy-derived optional settings use an
Automatic/Override control rather than blank or misleading manual inputs.

Introduce document-preserving save behavior for existing projects. The editor
retains comments, ordering, unrelated formatting, and the distinction between
omitted fields and explicit values. It shows semantic and exact TOML diffs,
detects external file changes, and performs conflict-aware three-way merging.
The in-memory draft supports field, section, and session reversion, while saves
remain explicit.

Use a restrained infrastructure-control-room visual language: deep slate
surfaces, cyan focus and automatic states, green valid states, amber modified or
unverified states, and red only for invalid or destructive actions. The editor
must remain keyboard-complete and usable at 80x24. Review includes a compact
configuration topology, risk summary, semantic diff, and exact TOML patch.

AWS discovery remains optional and non-blocking. Resource references support
both searchable AWS selection and manual entry. The editor does not render,
deploy, destroy, mutate SSM Parameter Store, or claim to predict CloudFormation
changes.

## User Stories

1. As a project creator, I want guided progression through project configuration, so that I can create a valid project without knowing the TOML schema.
2. As a project maintainer, I want to open any configuration section directly, so that I can change one value without traversing a wizard.
3. As a project maintainer, I want every user-authored persisted field to be editable, so that the TUI never forces me to switch to a text editor for supported configuration.
4. As a project maintainer, I want rare settings grouped under Advanced panels, so that complete field coverage does not make common workflows overwhelming.
5. As a project maintainer, I want active Advanced panels to open automatically, so that existing non-default configuration is not concealed.
6. As a project maintainer, I want collapsed Advanced headings to show how many values are configured, so that I can recognize meaningful hidden state.
7. As a project maintainer, I want validation errors to expand the relevant Advanced panel, so that I can immediately find the failing field.
8. As a project maintainer, I want persisted CLI-maintained metadata displayed read-only, so that I can inspect it without attempting edits the CLI will overwrite.
9. As a project maintainer, I want schema additions to require matching TUI support, so that editor completeness does not regress over time.
10. As a project maintainer, I want common fields visible without opening Advanced panels, so that routine edits remain fast.
11. As a project maintainer, I want deploy-derived settings to default to Automatic, so that the deploy workflow remains authoritative.
12. As a project maintainer, I want to override an automatically derived value explicitly, so that unusual infrastructure configurations remain supported.
13. As a project maintainer, I want existing explicit overrides to load in Override mode, so that opening the TUI does not change their meaning.
14. As a project maintainer, I want a warning before returning an explicit override to Automatic, so that removing a preference is intentional.
15. As a project maintainer, I want listener priorities described as preferred overrides, so that I understand stack-owned priorities are preserved during deployment.
16. As a project maintainer, I want listener priorities allocated only by deployment, so that a stale TUI lookup cannot pin a conflicting value.
17. As a shared-ALB user, I want the listener ARN and security group to default to Automatic, so that selecting the ALB name is normally sufficient.
18. As an advanced shared-ALB user, I want to override listener and security-group identities, so that non-standard listener arrangements remain representable.
19. As a network administrator, I want subnet selection to default to discovery while allowing explicit choices, so that I can constrain placement and avoid service limits.
20. As a dedicated-ALB user, I want all dedicated mode settings to round-trip, so that the editor never converts my project to shared mode.
21. As an operator, I want section navigation to show complete, modified, and invalid states, so that I can understand the draft at a glance.
22. As a new user, I want Save & Continue actions to suggest an order, so that non-linear navigation does not remove guidance.
23. As an experienced user, I want all valid sections immediately reachable, so that guided progression does not become enforced progression.
24. As an operator, I want Project, Network, Services, Routing, Database, Storage, Secrets, Environments, and Review sections, so that settings are grouped by infrastructure intent.
25. As an operator, I want project tags edited with project identity, so that tag scope is clear.
26. As an operator, I want environment tags and overrides edited under Environments, so that inherited and environment-specific values are not confused.
27. As an operator, I want preview-environment policy grouped with environments, so that ephemeral environment settings have a clear owner.
28. As a service owner, I want a searchable list of services beside the selected service editor, so that I can move quickly among services.
29. As a service owner, I want to duplicate a service, so that similar compute, health, and environment settings do not require repetitive entry.
30. As a service owner, I want service details grouped into focused panels or tabs, so that the complete service model remains manageable.
31. As a storage owner, I want buckets edited through the same master-detail interaction as services, so that collection editing is predictable.
32. As a security owner, I want secrets edited through the same master-detail interaction, so that collection editing is predictable.
33. As a routing owner, I want path rules and CloudFront behaviors edited through the same master-detail interaction, so that nested collections remain understandable.
34. As an operator, I want list actions to reflect the selected resource, so that Add, Duplicate, and Delete are never ambiguous.
35. As an operator, I want deletion to list every affected reference, so that cascading configuration changes are visible before confirmation.
36. As an operator, I want referenced-resource deletion and reference cleanup applied atomically, so that the draft cannot contain dangling references.
37. As an operator, I want deployment-sensitive edits highlighted before save, so that a later deploy does not surprise me.
38. As an operator, I want deployment-sensitive warnings described as possible future deploy effects, so that the editor does not overstate CloudFormation impact.
39. As an operator, I want one risk confirmation per save, so that safety does not become repetitive modal noise.
40. As an operator, I want risk warnings limited to the current unsaved diff, so that the editor does not pretend to know the last deployed state.
41. As an operator, I want to save an existing project from any section, so that a one-field edit is quick.
42. As a project creator, I want first-time creation to pass through Review, so that generated project files are not created without confirmation.
43. As an operator, I want Ctrl+S to validate and save, so that the editor follows familiar keyboard conventions.
44. As an operator, I want quitting with valid changes to offer Save, Discard, or Cancel, so that accidental loss is prevented.
45. As an operator, I want quitting with invalid changes to offer Return to fix or Discard, so that invalid configuration is never written.
46. As an operator, I want invalid quit-time state to remain available, so that a conversion or validation error cannot silently discard my draft.
47. As an operator, I want a save confirmation showing the file path and changed-field count, so that I know what was written.
48. As an operator, I want local validation to work without AWS credentials, so that offline editing remains possible.
49. As an operator, I want AWS verification to be optional, so that unavailable credentials or networks do not block locally valid saves.
50. As an operator, I want AWS verification status to distinguish Verified, Not checked, and Check failed, so that I understand the confidence level.
51. As an operator, I want deploy to remain authoritative for live AWS state, so that a prior TUI verification is not mistaken for a deployment guarantee.
52. As an operator, I want AWS resource references selectable through searchable pickers, so that I do not need to copy long identifiers manually.
53. As an operator, I want AWS resource references enterable manually, so that offline, cross-account, and restricted-permission workflows remain supported.
54. As an operator, I want parent resource choices to filter dependent pickers, so that subnet and listener selection remains relevant.
55. As an operator, I want AWS fetching to show loading, success, empty, and failure states, so that disabled controls are not mistaken for a frozen interface.
56. As an operator, I want fetching never to replace an existing value silently, so that discovery cannot mutate configuration unexpectedly.
57. As an operator, I want field errors shown beside their fields, so that transient notifications are not required to diagnose invalid input.
58. As an operator, I want untouched fields to avoid premature errors, so that the editor does not appear broken while I type.
59. As an operator, I want visible errors to clear as soon as they are fixed, so that feedback feels responsive.
60. As an operator, I want complete model validation on save and Review, so that cross-section errors cannot bypass field validation.
61. As an operator, I want the first invalid field focused and scrolled into view, so that correcting a failed save is direct.
62. As an operator, I want every focused field to show contextual help, so that all supported settings are discoverable.
63. As an operator, I want field help to include defaults and constraints, so that I can make valid choices without consulting source code.
64. As an operator, I want F1 to show expanded examples and consequences, so that rare settings remain understandable.
65. As a maintainer, I want TUI help grounded in schema descriptions, so that field meaning does not drift across documentation surfaces.
66. As a project maintainer, I want comments preserved when changing one field, so that user-authored operational context survives.
67. As a project maintainer, I want TOML ordering and unrelated formatting preserved, so that a small edit produces a small reviewable diff.
68. As a project maintainer, I want omitted fields to remain distinguishable from explicit defaults, so that future default changes do not alter deliberate intent.
69. As a project maintainer, I want inherited values marked DEFAULT, so that effective values are visible without implying they are persisted.
70. As a project maintainer, I want Reset to default to remove a field, so that omission semantics are restored.
71. As a project maintainer, I want existing explicit values preserved even when equal to defaults, so that the editor does not normalize away intent.
72. As a project maintainer, I want an external file change detected before save, so that concurrent work is not overwritten.
73. As a project maintainer, I want unrelated external and TUI edits merged automatically, so that concurrent work does not create unnecessary conflicts.
74. As a project maintainer, I want true field conflicts presented explicitly, so that I choose the correct value.
75. As a project maintainer, I want a failed merge to leave my draft intact, so that conflict resolution cannot destroy work.
76. As an operator, I want Reset field, Revert section, and Revert all actions, so that I can recover from draft changes before saving.
77. As an operator, I want cascading deletions reversible until save, so that a confirmed draft action is not irreversible.
78. As an operator, I want native text-input undo behavior, so that ordinary typing mistakes remain easy to correct.
79. As an operator, I want Review to show a semantic change list, so that I understand configuration intent rather than parsing TOML syntax.
80. As an operator, I want Review to show the exact TOML patch, so that I know precisely what document-preserving save will write.
81. As an operator, I want added, removed, changed, and reset-to-default values distinguished, so that the nature of each change is clear.
82. As an operator, I want environment-variable values treated as ordinary configuration, so that Review and diffs do not conceal them.
83. As a security owner, I want actual secret values never displayed, so that the editor does not expose managed secret material.
84. As an operator, I want a compact topology of configured relationships, so that I can understand routing and dependencies visually.
85. As an operator, I want the topology described as configuration rather than deployed infrastructure, so that its limits are clear.
86. As an operator, I want invalid relationships highlighted in the topology, so that structural errors are easy to locate.
87. As an operator, I want large topologies collapsible, so that Review remains usable for large projects.
88. As an operator, I want topology nodes to navigate to their owning editor where practical, so that review findings are actionable.
89. As an operator, I want a restrained control-room visual theme, so that the editor feels polished without becoming distracting.
90. As an operator, I want consistent semantic colors, so that focus, validity, modification, and danger are immediately recognizable.
91. As an operator, I want state represented by text and symbols as well as color, so that color perception is not required.
92. As an operator, I want automatic values and resource status shown as compact badges, so that dense forms remain scannable.
93. As an operator, I want meaningful empty states, so that blank resource lists explain the next action.
94. As an operator, I want AWS operations to use subtle progress animation, so that asynchronous work is visible without visual noise.
95. As an operator, I want the editor optimized for wide terminals, so that navigation, resources, and details can appear together.
96. As an operator, I want the editor fully usable at 80x24, so that ordinary terminal sessions are supported.
97. As an operator, I want narrow terminals to use single-pane or stacked layouts, so that horizontal scrolling is unnecessary.
98. As an operator, I want a clear minimum-size message below 80x24, so that an unusable layout is not rendered.
99. As a keyboard user, I want every action reachable without a mouse, so that the editor works in remote terminal workflows.
100. As a keyboard user, I want Ctrl+K to open a command palette, so that navigation and actions are quickly discoverable.
101. As a keyboard user, I want Escape to close overlays or cancel editing, so that modal interactions are predictable.
102. As a keyboard user, I want a contextual shortcut footer, so that available actions remain visible.
103. As a keyboard user, I want focus restored after dialogs and section navigation, so that I do not lose my place.
104. As a maintainer, I want the visual editor to preserve existing configuration semantics, so that a UI redesign does not change rendered infrastructure.
105. As a maintainer, I want existing RDS, secrets, environment, storage, and routing behavior unchanged, so that compatibility analysis remains bounded.
106. As a maintainer, I want the no-op deploy suite to remain green, so that the Troposphere cutover contract is preserved.
107. As a maintainer, I want Logical IDs unchanged, so that the TUI redesign cannot replace managed resources.
108. As a maintainer, I want the released editor to have complete schema coverage, so that users never encounter a half-migrated interface.
109. As a maintainer, I want the old screens removed at cutover, so that two competing editing patterns do not remain.
110. As a maintainer, I want dead legacy ALB code removed, so that future routing changes have one implementation location.
111. As a maintainer, I want full-editor behavior tested through the same interface users operate, so that tests do not merely verify internal state transformations.
112. As a maintainer, I want AWS discovery replaceable with a fake adapter in tests, so that full editor scenarios are deterministic.
113. As a maintainer, I want document editing hidden behind a small interface, so that preservation and merge complexity remains localized.
114. As a maintainer, I want the `tui` command to remain the ongoing editing entry point, so that existing workflows continue to work.
115. As a project creator, I want `init` to remain the first-run entry point, so that project creation remains intuitive.

## Implementation Decisions

- The Guided editor covers every user-authored field in the persisted project configuration schema. Advanced placement changes visibility, not editability.
- The schema is the completeness boundary. Persisted fields explicitly marked read-only and runtime-only values are excluded from editable coverage.
- `cli_version_floor` is CLI-maintained metadata. It is marked read-only, displayed for inspection, and omitted from editable-control coverage.
- Active preview metadata remains runtime-only and is not part of the persisted editor.
- Purpose-built Textual screens are retained instead of generating generic forms directly from JSON Schema.
- A machine-readable field registry maps every editable schema path to its owning section, control, grouping, help metadata, and serialization behavior.
- A coverage contract fails whenever a user-authored schema field lacks a registered editor control or help metadata.
- The editor uses nine canonical sections: Project, Network, Services, Routing, Database, Storage, Secrets, Environments, and Review.
- Navigation is non-linear. Guided Save & Continue actions are available for project creation and review, but direct section access is the normal editing model.
- Existing projects can save from any section. First-time project creation requires Review before files are generated.
- The existing `darth-infra tui` command remains the ongoing editing entry point. `darth-infra init` remains the first-run project creation entry point.
- Repeatable resources use a shared master-detail interaction with search, Add, Duplicate, and Delete actions.
- Resource forms update the in-memory draft directly; there is no ambiguous separate Add-versus-Update persistence mode.
- Referenced-resource deletion offers Cancel or an explicit atomic cascade. The confirmation names every affected reference.
- Common fields are immediately visible. Rare fields are placed in Advanced panels.
- Advanced panels default collapsed only when all contained fields are inherited or defaulted. Existing non-default values and validation errors force them open.
- Collapsed Advanced headings show the number of configured fields.
- Optional deploy-derived persisted settings use an Automatic/Override interaction.
- Automatic omits the field from TOML. Override persists and validates an explicit value. Returning to Automatic warns before removing an existing override.
- ALB listener-priority lookup actions are removed. Priority values remain editable as advanced preferred overrides, while deploy-time allocation stays authoritative.
- Shared listener ARN, ALB security-group ID, VPC ID, subnet IDs, and architecture remain editable advanced overrides rather than being removed.
- Preview listener-priority bounds remain editable because they reserve an allocation range for active preview environments.
- The configuration schema and generated infrastructure semantics do not change as part of this redesign, except for marking CLI-maintained metadata read-only.
- Existing RDS variable bindings, secret behavior, environment inheritance, resource naming, routing, and storage behavior remain unchanged.
- The document-editing module is a deep module responsible for loaded document state, effective configuration, field presence, draft changes, semantic diff, exact TOML patch, reversion, external revision detection, three-way merge, validation, and document-preserving save.
- The document-editing module presents a small interface equivalent in responsibility to loading a project document, applying semantic edits, inspecting status/diffs, reverting scope, and saving against an expected revision.
- Existing project saves preserve comments, ordering, unrelated formatting, and unedited values.
- The editor preserves omitted-versus-explicit presence. An explicit value equal to the current default remains explicit.
- Inherited values display a DEFAULT badge. Reset to default removes the persisted key and restores omission semantics.
- New project files use canonical formatting.
- External changes are detected by document content revision rather than modification time alone.
- Saving after an external change performs a three-way merge of session baseline, current disk document, and draft.
- Disjoint changes merge automatically. True semantic conflicts require explicit user resolution. Cancelling conflict resolution preserves the draft.
- Drafts remain in memory. Persistent crash-recovery files are out of scope.
- Baseline-based Reset field, Revert section, and Revert all actions are provided. Cross-section global undo/redo history is out of scope.
- Ctrl+S validates and saves existing projects from any section.
- Quitting with valid dirty state offers Save, Discard, or Cancel. Quitting with invalid dirty state offers Return to fix or Discard.
- Invalid state or conversion errors never cause a silent exit.
- Local validation is mandatory and includes field constraints, cross-field relationships, references, and complete project-model validation.
- Untouched fields are not marked invalid while the user is typing. Validation runs on blur; once visible, errors revalidate live and clear immediately when corrected.
- Save and Review validate the complete configuration, open the relevant panel, focus the first invalid control, and mark the owning navigation section invalid.
- Operation failures such as AWS lookup errors use notifications. Field errors remain adjacent to fields.
- AWS discovery and verification sit behind an injected adapter with real and deterministic fake implementations.
- AWS verification is optional and non-blocking for locally valid saves. Status is represented as Verified, Not checked, or Check failed.
- AWS-backed references support both searchable selection and manual entry. Parent choices filter dependent discovery where applicable.
- AWS fetching displays loading, empty, success, and failure states and never silently replaces an existing value.
- Every focused field shows concise contextual help containing meaning, effective default, and constraints. F1 shows expanded examples and consequences.
- Core field descriptions and constraints come from schema metadata; TUI metadata provides presentation, examples, grouping, and control selection.
- Environment overrides are edited only in Environments. Owning sections show override indicators and navigation links.
- Environment views show effective values with INHERITED or OVERRIDE badges. Reset to inherited removes the override.
- Existing-project Review provides a semantic Changes view and an exact TOML view.
- Semantic changes distinguish add, remove, change, and reset-to-default operations and group them by configuration section.
- Environment-variable values remain ordinary visible configuration. They are not masked or treated as secrets.
- Actual secret values are never displayed. Secret names, sources, and bindings remain visible.
- Review includes a compact configuration topology derived only from declared relationships. It is not an AWS topology or deployment plan.
- Topology errors link to their owning editor where practical, and large topologies can collapse.
- Deployment-sensitive edits require one explicit confirmation per save. Warnings describe what a future deploy may do and never claim exact CloudFormation impact.
- Risk warnings compare only the current unsaved draft to the loaded/saved document. No last-deployed baseline is introduced.
- The visual language is a restrained infrastructure control room: deep slate surfaces, cyan focus/automatic states, green valid/verified states, amber modified/unverified states, and red invalid/destructive states.
- Status is never conveyed through color alone. Text badges and symbols accompany semantic color.
- Motion is limited to loading and state transitions.
- The editor is optimized for terminals at least 120x35 and fully usable at 80x24.
- Narrow layouts use a navigation drawer and single-pane or stacked master-detail presentation. Below 80x24, the editor shows a minimum-size message.
- All workflows support keyboard and mouse. Required keyboard actions include Ctrl+S for save, Ctrl+K for the command palette, F1 for field help, and Escape for closing or cancelling overlays.
- Printable global shortcuts such as bare `n`, `p`, and `q` are removed.
- A contextual footer advertises relevant shortcuts, and focus is restored after navigation and dialogs.
- The redesign does not write exhaustive commented-out TOML options. Complete TUI coverage and the schema provide discoverability; TOML remains focused on active configuration.
- The user-facing cutover is atomic. Development may be incremental, but the released editor must satisfy complete coverage and preservation contracts.
- The legacy TUI screens, lossy wizard-state rebuild path, duplicate ALB behavior, and unreachable legacy ALB code are removed at cutover.

## Testing Decisions

- Good tests exercise externally visible behavior through the same interface a user operates. They should interact with controls, observe rendered states and messages, save documents, and then assert persisted TOML and loaded project semantics. Tests should not depend on private widget methods or internal state dictionaries.
- The primary test seam is the complete Textual application launched against a temporary project document through Textual Pilot.
- The application test seam accepts an AWS discovery adapter. Tests use a deterministic fake adapter; production uses the real AWS adapter.
- Full-application tests cover creation mode, existing-project mode, direct section navigation, guided progression, field editing, Advanced behavior, Automatic/Override behavior, keyboard commands, save, quit, Review, and responsive layouts.
- Full-application tests cover shared and dedicated ALB configurations so mode, certificate, listener, security-group, and priority fields cannot regress.
- Full-application tests cover every repeatable-resource editor, including add, duplicate, delete, explicit cascading cleanup, and dangling-reference prevention.
- Full-application tests cover touched-field validation, live error clearing, cross-field errors, hidden Advanced errors, focus movement, and complete save-time validation.
- Full-application tests cover offline editing, successful AWS discovery, empty discovery, failed verification, manual entry, dependent filtering, and preservation of unresolved existing values.
- Full-application tests cover semantic Review changes, exact TOML patches, topology rendering, topology errors, risk confirmation, and ordinary visible environment-variable values.
- Full-application tests run representative workflows at 120x35 and 80x24 and verify that required actions remain reachable without horizontal scrolling.
- Full-application keyboard tests cover save, command palette, help, overlay cancellation, section navigation, focus restoration, and absence of printable global shortcuts.
- Document-preservation scenarios begin with hand-formatted TOML containing comments, deliberate ordering, omitted defaults, and explicit defaults. After a UI edit, tests assert that only intended document regions change.
- External-file scenarios mutate the temporary TOML after editor launch. Tests cover disjoint automatic merge, true conflicts, cancelled conflict resolution, merged validation failure, and preserved draft state.
- Reversion scenarios cover field, section, and whole-session restoration, including restoration after a cascading deletion.
- First-time project tests assert canonical output and mandatory Review. Existing-project tests assert save from any section.
- A narrow schema coverage contract compares every persisted schema path with the field registry. It permits only explicit read-only exemptions and requires help metadata.
- The existing project-model validation tests remain the contract for semantic constraints and should not be duplicated widget by widget when the full-app seam already proves error presentation.
- The existing builder, generator smoke, preview allocation, and no-op verification suites remain the infrastructure compatibility seam.
- No-op tests must continue proving that unchanged configuration produces no CloudFormation resource changes, including literal-versus-resolved listener-priority equivalence.
- Existing TUI round-trip tests provide prior art for loaded-model reconstruction, but are replaced or elevated where they assert lossy internal state rather than full editor behavior.
- Existing configuration validation tests provide prior art for optional ALB priorities, CloudFront/ALB relationships, environment tags, and service references.
- Existing generator smoke tests provide prior art for validating complete generated projects without asserting YAML formatting.

## Out of Scope

- Adding new user-authored configuration concepts or changing the persisted configuration schema beyond read-only metadata classification.
- Linking environment variables through a new shared declaration model.
- Changing RDS variable bindings, secret semantics, environment inheritance, storage behavior, routing behavior, or resource naming.
- Rendering templates, deploying stacks, destroying stacks, creating CloudFormation changesets, or displaying deployment progress from the editor.
- Predicting exact CloudFormation replacement or deletion behavior without a real changeset.
- Tracking a last-deployed configuration or retaining risk warnings after the current draft is saved.
- Viewing or editing AWS Systems Manager Parameter Store values.
- Displaying actual secret values.
- Treating ordinary environment-variable values as secrets or masking them in Review.
- Exhaustive commented-out field catalogues in generated TOML.
- Persistent crash-recovery drafts.
- Cross-section global undo/redo history.
- Generated or discovered AWS architecture diagrams; Review topology is limited to declared configuration relationships.
- Releasing a hybrid editor with partial schema coverage or mixed lossy/document-preserving save paths.
- Maintaining the legacy and redesigned TUI implementations indefinitely.

## Further Notes

- The Guided editor and Document-preserving save terms are defined in the project domain glossary and are normative for this work.
- The Troposphere migration ADR freezes the persisted schema, TUI compatibility expectations, output paths, and no-op deploy behavior across the template-generation cutover. This redesign must honor its Logical ID and infrastructure compatibility constraints.
- Listener priorities remain persisted optional preferences for compatibility and advanced control. Deployment continues to preserve stack-owned priorities and allocate missing or unavailable priorities.
- Private subnet overrides remain important even with automatic discovery because ECS limits the number of subnets and operators may need explicit placement control.
- Preview listener-priority bounds remain distinct from ordinary listener priorities because they reserve allocation space for active preview environments.
- The complete editor supersedes the earlier idea of discoverability through commented-out TOML fields.
- The implementation is expected as a full atomic cutover, not a partial user-facing rollout.
