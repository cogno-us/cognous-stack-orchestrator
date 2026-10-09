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

## PR #60 / #61 reconciliation — final review

The independent source interfaces differ in shape and provenance. The O5-E-A
missing-grant HOLD is a genuine pinned Control Plane decision (`result=hold`,
`reasons=issued_grant_missing`) with **no created claim, no execution attempt
ID, and zero attempt/effect rows**. The Control Plane still supplies a stable
decision and effect ID. A Runtime execution after an authorized synthetic
handoff may generate an attempt ID, while pre-dispatch denials have
`attempted=False` and `attempt_id=None`. The original
`trace_contract.py` envelope is a strict hypothetical illustrative shape;
it is **not a lossless serialization of the PR #60 HOLD**.

PR #61 independently defines an event stream (`trace_id`, `correlation_id`,
`request_id`, `tenant_id`, and ordered `events`), with each event carrying
`event_id`, `kind`, `sequence` and
`provenance.{source_component,source_revision,source_record_id}`. Its
`authority_state=hold`, `refusal_state=refused`,
`execution_state=refused`, `receipt_state=not_sent` and
`settlement=not_observed` are **different stage states** and must not be
coerced into a single permission or execution state. The example Replay
`runtime_attempt` identifier is synthetic, **not evidence that PR #60's
missing-grant HOLD generated an attempt**.

`reconciliation.py` is the machine-checkable structural bridge for the
*actual* interfaces. It does not join their independent fixture runs by
fabricating shared IDs. `compare_connected_boundaries` intentionally reports
`same_trajectory_proven=False`. A future combined integration must supply
identical authentic producer identities and demonstrate correspondence
before claiming a single connected end-to-end run.

PR #61's `settlement_observation.independent=True` describes the source
observer's declared independence, **not a verified settled transaction**.
The value remains `not_observed`, and the Replay/Evidence Pack output's
`independent_effect_verification` is false. Source provenance strings do
not authenticate an issuer, and neither a synthetic owner resolver flag nor
a control decision establishes a currently adopted merchant grant.

The `trace_contract.py` first-pass envelope remains retained for backward
review but must not be represented as interoperable serialization. The
authoritative handoff comparison is now `reconciliation.py`, which
explicitly preserves absent attempt IDs, source event lineage, and all
evidence/authority separations. Its tests use structural source-shaped
fixtures **only**; actual pinned executions are independently owned by
PRs #60 and #61, and their upstream absence fails their own qualification.
