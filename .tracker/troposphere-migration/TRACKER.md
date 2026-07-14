# Tracker for troposphere-migration

## Purpose

This document tracks the status of all tickets in the epic. The goal is to
replace the Jinja2 CloudFormation templates with a troposphere object
pipeline, behaviorally invisible to deployed stacks: an unchanged
`darth-infra.toml` must produce a no-op deploy on every existing stack.
Structured as expand–contract: the new pipeline lands inert beside Jinja
(tickets 01–09), one cutover ticket swaps it in and deletes the Jinja CFN
templates (10), and a release-gate ticket verifies against real stacks (11).
`main` stays pure-Jinja-rendered and releasable until ticket 10 ships as a
minor release. See `SPEC.md` in this directory and
`docs/adr/0001-troposphere-template-generation.md`.

## Current Status

Overall status: `In Progress` — all implementation tickets (01–10) Completed;
only ticket 11's real-stack release gate remains, which requires a human with
AWS credentials.

Current ticket: 11 (awaiting human validation — the `--verify-noop` tooling is
built, unit-tested, and documented; the against-real-stacks run and release
publish are the remaining human steps).

Last updated: 2026-07-14

## Ledger

| Number | Filename | Status | Depends On |
| --- | --- | --- | --- |
| 01 | `01-typed-render-context.md` | Completed | None |
| 02 | `02-pipeline-and-root-core.md` | Completed | 01 |
| 03 | `03-service-stack-core.md` | Completed | 02 |
| 04 | `04-dedicated-alb-dns.md` | Completed | 03 |
| 05 | `05-rds-and-secrets.md` | Completed | 03 |
| 06 | `06-service-discovery-s3.md` | Completed | 03 |
| 07 | `07-cloudfront.md` | Completed | 04, 06 |
| 08 | `08-ec2-launch-type.md` | Completed | 03 |
| 09 | `09-structural-deploy-validation.md` | Completed | 03, 05 |
| 10 | `10-cutover.md` | Completed | 04, 05, 06, 07, 08, 09 |
| 11 | `11-release-verification.md` | Needs Human Validation or Intervention | 10 |
