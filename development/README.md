# Engineering cockpit

**Start here** for orchestrator and cross-repository development. This guide describes the engineering process; the [root README](../README.md) explains the system and its qualification boundaries. The [control issue](https://github.com/cogno-us/cognous-stack-orchestrator/issues/1) is the dashboard, not a separate claim of acceptance. GitHub issues are the task queue; pull requests are the reviewable change records.

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

## How to reproduce a bounded test

1. Identify an accepted test profile, for example [O6-Q4](acceptance/o6-q4/README.md), and note its exact source revisions.
2. Read the corresponding `.github/workflows/o6-q4-authenticated-fence.yml` for precise environment variables, installs and commands. Its actual-source checkouts must match the recorded SHAs.
3. Run only with synthetic fixtures in a disposable checkout. The resulting CI job proves precisely the named bounded tests, not production deployment or independently adopted authority.
4. In a PR record the tested **PR head**, workflow URL/run ID, pass/fail, changed paths and unresolved trust limitations.
5. Compare against the hub [component lock](https://github.com/cogno-us/cognous-open-control-stack/blob/main/component-lock.json) *separately*. Newer passing source tests never silently change the selected release.

**Example failure handling:** if a refund attempt has a lost acknowledgment and the observer reports `unknown`, preserve the original effect/attempt and mark recovery HOLD; do not mint a new attempt because an observation is missing. See [Q6 recovery](acceptance/o6-q6/README.md).

## Inspect an existing recovery export

For the optional supplied-snapshot path, use the [recovery inspection guide](../acceptance/recovery-resolution-inspection/README.md). It documents exact dependency pins, the supported API, reproduction command and retained evidence gaps. Unlike the Q6 intake profile, this adapter accepts an existing export without opening Runtime databases or admitting observations. Its `resolved` producer state remains synthetic-only; inspection cannot authorize retry or establish independent settlement.

The [completed PR #97 review](https://github.com/cogno-us/cognous-stack-orchestrator/pull/97) records 33 CI passes with no failures or skips and inspection of all nine scenario artifacts. This is implementation-agent review, not independent assurance. Selected-release adoption and operator trust #30 remain separate gates.

## Historical planning

The [V0 integration contract](integration-contract-v0.md) and earlier scaffold plans are historical proposed context, **not current implementation status**. The accepted O5-E and O6-Q2–Q6 synthetic suites supersede the phrase “no integration qualified,” while [operator trust #30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30) remains unqualified.
