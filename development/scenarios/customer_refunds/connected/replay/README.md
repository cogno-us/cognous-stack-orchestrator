# O5-E-B connected refund Replay / Evidence Pack qualification

Issue: #57. Branch: `worker/o5-e-b-connected-replay`.

This work qualifies one **synthetic connected refund refusal/HOLD trace** through the actual accepted source implementations:

- Replay: `cogno-us/cognous-replay-bundle@2069a0ba1398812c3a8669331a7d8b87c80c4a48`
- Evidence Pack: `cogno-us/cognous-governance-evidence-pack@87293cfcbe8dfa2368d5bf77019945ba8ef1ae71`

The qualification refuses to run if either checkout is missing or its Git HEAD differs from the exact pin. Passing therefore requires importing and invoking the pinned Replay `ReconstructionBundle`, Evidence Pack `EvidencePack`, and `validate_evidence_pack` implementations. Local fixtures alone cannot qualify this path.

## Boundary discipline

The connected trace keeps request, screening, policy/authority decision, approval withdrawal, refusal, runtime attempt, transport receipt, external effect observation and settlement observation as distinct records. Every record carries source provenance and the same tenant, correlation and request identifiers.

A transport receipt is not an execution result. A runtime attempt is not an externally observed effect. An effect observation is not payment settlement. Evidence Pack validation is not independent settlement verification.

The accepted synthetic trajectory is fail-closed: authority is HOLD then withdrawn, the runtime attempt is refused, no transport is sent, no external effect is observed, and independent settlement observation reports `not_observed`.

## Negative qualification

Tests reject:

- a swapped merchant tenant;
- missing per-event provenance;
- duplicate event, provenance, effect or attempt identifiers;
- a transport receipt promoted to settlement;
- a false positive settlement claim;
- a non-independent settlement observer;
- unavailable or wrong-revision upstream sources.

## Integration status and limitation

The issue-57 trace shape is intentionally **provisional** because issue #58 independently owns the frozen O5-E interstage contract. Governor integration must compare and reconcile the #56, #57 and #58 outputs before any combined qualification. This worker does not modify C1-C8 or other worker paths.

No payment processor, merchant credential, institutional grant, real funds, actual payment dispatch, destination settlement, or production trust is used or claimed. Governor #14 and operational trust #30 remain open.
