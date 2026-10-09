# O5-E-C connected refund contract

Issue #58 freezes the provisional machine-checkable handoff contract used to compare workers O5-E-A and O5-E-B before Governor integration. It does **not** change C1-C8, issue authority, dispatch a refund, authenticate a merchant environment, or prove settlement.

## Frozen identities

The trace keeps these identities separate: `request_id`, `decision_id`, `attempt_id`, `evidence_id`, `receipt_id`, and `observation_id`. `intent_id` and `effect_id` are carried as stable correlation identifiers where required, but neither is interchangeable with a stage-record identifier. Any collision among stage-record identifiers fails validation.

`trace_contract.validate_trace()` enforces tenant and lineage equality across references, exact accepted O5-D source revisions, HOLD/REFUSED-only decisions, and `settlement.state == not_observed`. A transport receipt can describe transport only. Replay/Evidence artifacts can reconstruct or review records only. No field or source mapping is allowed to infer merchant authority or settlement.

## Interfaces for parallel workers

`interface_projection()` defines the comparison surface without editing either worker's implementation:

- **A — connected Control/Runtime:** request, decision, execution-attempt and transport records.
- **B — connected Replay/Evidence:** the four correlation references plus evidence, receipt reference and settlement observation.

The Governor must compare actual A/B outputs against this candidate contract before combined qualification. If an exact pinned upstream checkout is unavailable, connected qualification fails; a local fixture is not evidence of actual integration.

## Adversarial disposition

The contract requires fail-closed behavior for missing grant, altered policy digest, withdrawn approval, duplicate intent, unknown delivery, forged/unverified receipt claims, forged settlement claims and tenant mismatch. Tests also reject identity collisions that would collapse request, decision, execution, evidence, transport or observation into a single asserted event.

## Limitations

Synthetic contract qualification only. No real funds, payment processor, merchant credential, institutional grant, production trust, effect dispatch, destination observation, or independent settlement verification is present. Governor #14 and operator-trust #30 remain open.
