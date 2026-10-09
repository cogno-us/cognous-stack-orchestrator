# Engineering cockpit

**Start here** for orchestrator and cross-repository development. The [control issue](https://github.com/cogno-us/cognous-stack-orchestrator/issues/1) is the dashboard, not a separate claim of acceptance. GitHub issues are the task queue; pull requests are the reviewable change records.

## One-command-by-conversation operating model

The operator may say **"work on task #N"** or **"show engineering dashboard"**. A governor or worker first reads this file, [AGENTS.md](../AGENTS.md), and the referenced issue; then inspects exact target revisions and reports a bounded plan. The issue is the authoritative task specification, not a repeatedly pasted prompt. Work happens on an isolated branch in the owning repository and returns an attributable PR and test ledger.

## Stages

BACKLOG -> SCOPED -> ASSIGNED -> IMPLEMENTING -> PR_OPEN -> CI_VERIFIED -> GOVERNOR_ACCEPTED -> CLOSED.
BLOCKED and DEFERRED are explicit alternative states; never interpret PR opening or green CI as Governor acceptance.

## Mandatory task fields

Issue ID; accountable worker/owner; repo/path boundaries; source HEAD SHA(s); objective and non-goals; affected C1-C8 contract(s); dependencies and accepted pins; acceptance tests and negative cases; security/IP review; resulting PR(s); CI IDs and exact head; residual risks; Governor disposition.

## Change control

- One task issue and one working branch per independently reviewable change; reuse existing issues when applicable.
- No new integration semantics or C1-C8 changes without separate documented amendment and review.
- No force-push of accepted base, no direct edits to the bounded release lock, no promotion from candidate to published by inference.
- No private ISS, AoM, or IGPG internals committed to this repository.
- Evidence, policy decision, execution ACK, observation and independent verification must remain separate.
- Do not write to subcomponent repositories without scoped ownership and an explicit reviewable PR.
- No automatic merges, releases, authority grants or production deployment.
- Each worker must stop at a finite checkpoint if a test is pending or access unavailable; no CI polling loops.

## New task

Use **New issue** in this repository and select *Engineering task*; fill in the fields. The governor updates the pinned control issue's task table. For changes in subcomponents, link the source-repository issue/PR, not a parallel implementation in this orchestrator.

## V0 sequence

1. Engineering dashboard and templates (this phase)
2. [V0 Integration Contract](integration-contract-v0.md) — proposed contract, not yet cross-repo ratified
3. Contract review and version pins, with owners and tests agreed
4. Smallest vertical integration pilot spanning agreed domain interfaces
5. Only then broader features or ISS adapter implementation
