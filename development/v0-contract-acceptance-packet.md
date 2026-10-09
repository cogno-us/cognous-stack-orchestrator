# O1 acceptance packet — CSO-IC-V0

**Status:** READY FOR REVIEW, NOT ACCEPTED
**Review issue:** [#2](https://github.com/cogno-us/cognous-stack-orchestrator/issues/2)
**Date:** 2026-10-09
**Contract:** [integration-contract-v0.md](integration-contract-v0.md)

## Architecture decision proposed

Use five product domains and one thin orchestrator for versioned workflow coordination and reference transport. Existing component owners retain their source contracts. No second authority service or parallel Governed Exchange transport implementation. Keep the bounded reference release and its independent acceptance status unchanged.

## Evidence available for review

| Component / boundary | Inspected record | Review disposition |
|---|---|---|
| Cognous Evidence Registry | Solidity contract events and read-only indexer; [chain mapping](evidence-registry-chain-mapping-v0.md) | Source inspected; exact adapter schema not endorsed |
| Cognous Evidence Attestation | Signed-statement and verification-result JSON schemas; [field map](field-mapping-review-v0.md) | Source inspected; issuer trust and reliance policy not endorsed |
| Cognous Institutional Governance | Authority Context 0.1.0 proposed schema | Source inspected; institution adoption and resolver not demonstrated |
| Cognous Governed Exchange | Message transport profile and handoff mapping | Source inspected; transport identity/receipt semantics clear; new orchestrator compatibility not tested |
| Existing Action Governance / Runtime / Replay / Evidence | Accepted W7 scoped pins documented by hub | No new five-domain qualification |

## Open decisions for accountable owners

1. Confirm exact source revisions/producer shapes and consumer source-version ranges for each cross-domain interface.
2. Specify reference-envelope canonical bytes, ownership and explicit error/loss statuses; avoid duplicating GAX envelope.
3. Specify authenticated tenant/actor/organization mapping, including mismatch/unknown behavior.
4. Specify institutional adoption/grant-resolution route and how current authority is rechecked.
5. Specify exact evidence admission and reorganization/finality handling; distinguish available bytes, commitment checks and issuer signature.
6. Agree on the minimal negative vectors for O3, and explicit test environment/fixtures.
7. Approve the concrete revised contract HEAD and record review attribution.

## Proposed review outcomes

**ACCEPT:** Source owners approve exact mappings, acceptance criteria and revisions with evidence attached to issue #2.

**AMEND:** Owner records a specific contract defect and required correction. Draft remains non-authorizing.

**DEFER:** Missing owner or technical evidence. Do not infer acceptance from silence.

## Next allowed implementation

Once accepted, O3 may implement a machine-readable **reference-only envelope** and contract negative tests on an isolated reviewable branch. No ISS adapter, general orchestration runtime, release or production deployment as part of O3.
