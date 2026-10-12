# Synthetic recovery: proposed owner decisions

Status: **OPERATOR APPROVED / TECHNICAL COMPATIBILITY REVIEW PENDING**. Task [#95](https://github.com/cogno-us/cognous-stack-orchestrator/issues/95); integration gate [#94](https://github.com/cogno-us/cognous-stack-orchestrator/issues/94). This records the operator-approved decision slate for [the recovery proposal](RECOVERY_RESOLUTION_PROPOSAL.md). It does not amend accepted C1–C8 contracts or establish consumer compatibility.

## Recommended scope

Qualify a **read-only synthetic inspection integration first**. It would preserve and inspect retained recovery evidence without admitting observations, retrying effects, resolving disputes, migrating v1 data, or asserting real settlement. The operator explicitly approved this narrowing of #94 on 2026-10-11.

Source anchors:
- Orchestrator baseline: `06bb9245fcc9769f82c5b0347ae8a1f9fc147e76`.
- Merged Runtime: `8e7d634cf0a22b6f3c1fc6d93afe92c7414fa243`; [implementation](https://github.com/cogno-us/cognous-execution-runtime/blob/8e7d634cf0a22b6f3c1fc6d93afe92c7414fa243/engine/recovery_resolution.py), Git blob `463a8814a4b61ab79ba78482b25e9c6c7fdf47a2`.
- Producer profile: `cognous-recovery-resolution/synthetic-0.1`.
- Inspection export: `cognous-recovery-inspection/synthetic-0.1`.
- Admission policy: `synthetic-structural/2`.
- Serialization label: `python-json-sort-ascii-compact/1`.

These are proposed input anchors, not selected-release pins. Replay and Evidence Pack consumer versions remain to be chosen through owning-repository review; their earlier preflight revisions do not imply support.

## Decisions to disposition

All ten choices below were **accepted by the project operator** for this bounded scope. Technical compatibility and consumer implementation acceptance remain separate, pending reviews.

| ID | Recommended choice for this scope | Consequence / deferred work |
| --- | --- | --- |
| RD-01 | One explicitly supplied synthetic local store. Obtain original effect/attempt/grant-related identity through Runtime's supported export/query behavior. Reject unavailable, changed, or ambiguous required identity. Preserve missing tenant/actor facts as unavailable. | No authenticated multi-tenant claim and no generated tenant identifiers to satisfy a consumer. Stronger namespace binding needs another profile. |
| RD-02 | Preserve exact producer bytes when retained; check their SHA-256 using the serialization below. Keep receipt identity separate from the submitted-envelope digest. | No RFC 8785 or signed identity claim. Collision records may lack the committed body; record that gap instead of inventing bytes or falsely declaring a digest verified. |
| RD-03 | Treat `event_id` as the producer's admission identity and `observation_ref` as an opaque evidence reference, not a proven globally unique source-event key. Exact repeated admissions retain the original receipt and current projection. The consumer performs no resubmission. | Same observation with different expected revision/predecessor is not an exact replay. A future intake adapter must separately specify stable source-event identity and stale-submission handling; it cannot infer those semantics here. |
| RD-04 | Preserve policy label, evaluated times, declared ordering domain/counter, and the producer's admission checks verbatim. The producer's new-admission age check is 0 through 86,400 seconds inclusive under the write lock; exact duplicates retain their earlier receipt. | Do not re-label imported historical admissions as freshly admitted or authenticated. Clock uncertainty, trusted source ordering, and verifier identity remain unestablished. |
| RD-05 | Preserve `resolved` only as a producer work-state assertion with `synthetic_profile_only` finality. Keep unknown/absent, partial follow-up, and conflict distinct. | No retry, independent verification, provider acceptance proof, or settlement follows from that state. |
| RD-06 | Preserve permanent conflict HOLD, conflict reasons, and retained commitments. Report that rejected malformed/stale inputs have no durable refusal record in this producer. | Read-only integration does not add adjudication or claim a complete intake/refusal audit. Production admission remains blocked on separate audit and correction design. |
| RD-07 | Describe the historical denominator as **currently retained v1 in-doubt dispositions**, separate from current unresolved synthetic work and attempts awaiting first observation. Preserve the producer's metric fields with this definition. | No guaranteed lifetime count or inferred archive completeness. |
| RD-08 | Interpret v1 preservation as unchanged logical v1 rows, schema, interfaces, and historical interpretation; sidecar tables change physical database bytes. Keep legacy entries distinguishable in the export. | No migration or physical-file identity claim. Legacy facts do not silently resolve the new stream. |
| RD-09 | Dispatch only on the exact profile/export pair above. Preserve initial uncertainty, retained events/receipts, current projection, legacy entries, and all explicit gaps. Produce a per-field loss report; required evidence loss blocks supported reconstruction. | Unknown/mixed versions do not fall back to generic model parsing. A consumer may retain unsupported evidence for inspection but must not label it a successfully reconstructed recovery trace. |
| RD-10 | After documented dispositions and C4/C5/C8 review, scope native mappings in their owning repositories and test actual pinned components. Keep Q6, O5-E-B, default workflow, and selected lock unchanged. | Source merge, proposal review, integration qualification, and release adoption remain separate decisions. |

## Collision commitments and reconstruction limits

The Runtime stores full submitted envelope bytes for ordinary observations. On reuse of an event ID with changed committed content, it can store only `conflicting_digest` and `event_id` as the event body, together with the admission receipt and conflict state. That abbreviated body is **not** the original envelope hashed by the stored digest.

Recommended consumer behavior:
1. Preserve the conflict entry, digest, receipt, revision, and current HOLD.
2. Mark the conflicting submitted body unavailable and digest recomputation for that body not performed.
3. Do not hash the abbreviated body and compare it as if it were the submitted envelope.
4. Do not reconstruct missing observation facts from a prior event or the current projection.
5. Distinguish preservation of a retained commitment from full-payload reconstruction. If a receiving format cannot express this gap, reject that mapping rather than drop the event.

A predecessor reference can be compared to the preceding retained digest without proving that every digest has an available preimage. Integrity of all original payloads and completeness of all rejected submissions remain stronger, unestablished claims.

## Serialization vectors

The current implementation uses Python JSON serialization with sorted keys, ASCII escaping, compact comma/colon separators, and `allow_nan=False`; hashes are SHA-256 over UTF-8 with no trailing newline. Observation times are normalized to UTC using Python `datetime.isoformat()`. No Unicode normalization is added. These vectors cover the submitted envelope only, not receipt identity, source authenticity, or full-format conformance.

Run the following from the exact Runtime checkout above. The fixed observation digest is synthetic input; it is not a claimed hash of an acquired source artifact.

```python
from datetime import datetime, timezone
import hashlib
from engine.recovery_resolution import (
    SyntheticObservation, PROFILE, CANONICALIZATION, _json,
)

observation = SyntheticObservation(
    event_id="event-1", effect_id="effect-1", attempt_id="attempt-1",
    adapter_id="synthetic", client_reference="client-1", state="unknown",
    observed_at=datetime(2026, 10, 11, 12, tzinfo=timezone.utc),
    ordering_domain="fixture-1", order=1,
    observation_ref="synthetic:obs-1", observation_digest="a" * 64,
    observer_ref="synthetic:observer-1", watermark_ref="synthetic:watermark-1",
    provider_acceptance_ref="synthetic:acceptance-1",
    evidence_location_ref="synthetic:café",
)
vectors = [
    (0, None, 736, "45261286ba67597f5d5d4d8fd82fa2505568dd523f45710661e07689d6a7940a"),
    (1, "b" * 64, 798, "c40565e935111b53f3a2aac03c8ac2c84a27bbe0248ff7836c8fb06e5547148c"),
]
for revision, predecessor, size, expected in vectors:
    envelope = {
        "profile": PROFILE, "canonicalization": CANONICALIZATION,
        "observation": observation.payload(),
        "expected_revision": revision, "predecessor_digest": predecessor,
    }
    encoded = _json(envelope).encode("utf-8")
    assert len(encoded) == size
    assert hashlib.sha256(encoded).hexdigest() == expected
print("2 serialization vectors passed")
```

Using the private serializer here is an inspection technique, not a proposed supported consumer API. The second vector is a serialization contrast, not a successful append or a valid predecessor chain. It proves that changing the admission envelope changes the digest despite unchanged observation facts.

## Owner record and implementation gate

For each RD row, record the accountable owner, accept/reject/amend disposition, exact document commit, rationale, conditions, and review date in the review record. Silence, a source merge, or green CI is not a disposition.

Before implementation:
- Operator disposition completed: RD-01–RD-10 and the read-only inspection scope approved; see the record below.
- Applicable C4/C5/C8 owners review compatibility; any amendment follows the existing governance process.
- Receiver owners agree exact native mapping versions, loss representation, and positive/negative cases. No fabricated decision or tenant payloads may satisfy existing importers.
- Scope producer changes separately if owners require a complete rejection audit, authenticated admission, migration, or full conflicting-body retention. Those changes are not supplied by this document.

Validation for this proposal is limited to source inspection, two serialization vectors, and documentation checks. Actual consumer integration and behavioral/production qualification remain unexecuted. C0 check-to-commit limits, optional same-host C1, no C2/C3, no real settlement, and operational [#30 HOLD](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30) remain.

## Operator disposition record

- Decision maker: André de Lima, project operator, through this task conversation.
- Decision date: 2026-10-11, America/Los_Angeles.
- Reviewed decision revision: `7d6f84feb370286a18fe03a835e91b0aa84076b4` in PR #96.
- Approval request: approve RD-01–RD-10 and the read-only synthetic integration scope, then proceed with the required compatibility review.
- Response: “i approve”.
- Disposition: accept all ten listed decisions and the read-only narrowing of #94. Each decision retains its stated consequence and deferred work; no broader admission, authority, settlement, or release permission is added.
- Basis: explicit operator approval of the concrete decision slate. This is not an independent Runtime, Replay, Evidence Pack, or C4/C5/C8 technical review, and no such review is attributed to the operator.
- Next gate: complete the technical compatibility assessment and resolve actual receiver mapping/version requirements before implementation; preserve all loss and assurance limits.

## Technical compatibility assessment — 2026-10-11

Method: source and contract inspection by the implementation agent, not independent consumer-owner acceptance. No model or connected integration run was performed for this assessment. Earlier preflight execution remains separately recorded in #94.

Inspected current consumer sources:

| Repository | Exact revision | Relevant source blobs |
| --- | --- | --- |
| Replay | `6a5ef9ccfbf3da23cbad74a9278820c7642d6981` | `reconstruction.py: dae0aa6feac3e81f6026cdb139eeb12fc1e654d0`; `importers.py: 3d9e5238e91b8ee6c7dbaa9c62b56bda7d1591dc` |
| Evidence Pack | `4172a0d535ff861a9f6f6cfee0b684bae63ca445` | `models.py: ce0ced76d63a7d069da60ba2fcc3cf48f5d31e47`; `importer.py: b91d9b778c1b082aeb3a6a1ea7145d5d775aaafd` |

Replay's two inspected code blobs and Evidence Pack's model blob match the earlier preflight sources. Current source acceptance has not supplied a recovery-successor mapping in these interfaces. The selected hub at `3efe456d10a37dcdd2277b4a37d9034403380f09` still documents Replay `459e4ba62fca49364aebb0050cd5fb2dd5a71bfa`, Evidence Pack `b4baccd823d2a73be276c1de745b19cf7c56a0d6`, Reconstruction Bundle 0.2.0 and transformation `agep-manifest-reconstruction-import/0.3.2`. Those selected historical combinations remain unchanged.

| Boundary | Inspected basis | Assessment and implementation requirement |
| --- | --- | --- |
| C4 failure semantics | Control Plane `11a4c6417a97e97e9b99bec01018d5b9d4478957`, `docs/w0-c1-c2-c4-c6-contracts.md` | The candidate addendum names bounded-path failure classes and dispatch stages. Recovery intake exceptions have no retained equivalent record. Preserve this absence; do not relabel an inspection-format rejection as a historical policy denial, dispatch error, or proof of no effect. A future inspection importer needs its own clearly attributed import finding. |
| C5 observation/recovery | Runtime source above, `docs/w0-c3-c5-c7-contracts.md` and implementation | Preserve original effect/attempt, observed state, recorded freshness evaluation, synthetic finality, and uncertainty. Current read-only scope issues no retry or new effect, so it need not redefine admission or dispatch. It cannot claim authenticated destination scope or independently established finality. |
| C8 Replay | Replay source above, `docs/reconstruction_import.md` and `docs/w0-c8-compatibility-contract.md` | Existing bounded importer requires Control Plane records and explicitly supported producer pairs. The recovery inspection export is neither. Generic model parsing is not a mapping. Add a separately named native inspection import/validation API with exact dispatch and loss representation; retain historical importer behavior. |
| C8 Evidence Pack | Evidence Pack source above, `importer.py` and `docs/w0-c8-compatibility-contract.md` | Current manifest/reconstruction import checks native producer profiles, accepted revisions, and runtime decision semantics. Do not fabricate a manifest, decision, tenant, or old executor profile to pass it. A separate native inspection transformation must consume the actual qualified Replay output and carry its unsupported/unavailable findings. |

The W0 addenda explicitly label themselves candidate contracts. They are design-review context, not proof that their proposals are accepted, implemented, or satisfied. This assessment proposes no amendment to selected contracts and does not grant an independent C4/C5/C8 owner signoff.

### Required downstream work

1. Scope Replay's optional read-only inspection mapping in the Replay repository. Preserve full retained JSON, original byte commitments where available, record identity, receipt versus current-state distinctions, collision-body unavailability, and a per-field loss report. Choose an exact API/profile version in that owning change; do not reserve a version here.
2. Scope Evidence Pack's corresponding inspection transformation in its repository, dependent on the accepted Replay implementation/version. It must show synthetic resolution separately from verification/settlement and must not route inspection output through the historical manifest importer.
3. Only then qualify orchestrator #94 with actual pinned Runtime, Replay and Evidence Pack implementations. Require positive retained-history and conflict-gap cases, and negative wrong-profile, changed-identity, lost-event, altered-commitment and false-settlement cases. A commitment with no retained preimage remains explicitly unverified, not an automatic integrity pass or invented payload.

Assessment result: **no direct compatibility demonstrated; separate native consumer mappings required**. Operator decisions are complete. Owning-repository API acceptance and composed qualification remain open. Inspection can preserve unavailable evidence without claiming full-payload reconstruction; any required mapping loss must remain blocking under the approved RD-09 rule.
