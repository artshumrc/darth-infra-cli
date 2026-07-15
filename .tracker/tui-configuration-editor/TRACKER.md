# Tracker for tui-configuration-editor

## Purpose

This document tracks the full atomic replacement of the legacy TUI with a
complete, document-preserving Guided editor for project configuration.

## Current Status

Overall status: `In Progress`

Current ticket: None

Last updated: 2026-07-14 (ticket 03 completed)

## Ledger

| Number | Filename | Status | Depends On |
| --- | --- | --- | --- |
| 01 | `01-schema-field-registry.md` | Completed | None |
| 02 | `02-document-preserving-session.md` | Completed | 01 |
| 03 | `03-document-diff-merge-reversion.md` | Completed | 02 |
| 04 | `04-editor-shell-project.md` | Completed | 01, 02 |
| 05 | `05-network-aws-discovery.md` | Not Started | 04 |
| 06 | `06-core-services-editor.md` | Not Started | 04 |
| 07 | `07-advanced-services-references.md` | Not Started | 05, 06 |
| 08 | `08-alb-routing.md` | Not Started | 05, 07 |
| 09 | `09-cloudfront-routing.md` | Not Started | 05, 07, 08 |
| 10 | `10-database-editor.md` | Not Started | 04, 07 |
| 11 | `11-storage-editor.md` | Not Started | 04, 07 |
| 12 | `12-secrets-editor.md` | Not Started | 05, 07 |
| 13 | `13-environments-preview-editor.md` | Not Started | 07, 10 |
| 14 | `14-review-topology-risk.md` | Not Started | 03, 08, 09, 10, 11, 12, 13 |
| 15 | `15-session-safety-workflows.md` | Not Started | 03, 04, 14 |
| 16 | `16-atomic-cutover.md` | Not Started | 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15 |
