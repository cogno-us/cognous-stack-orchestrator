# Optional recovery inspection chain 0.1

Status: **candidate; local qualification executed; CI and governor disposition recorded in the PR**. Owning issue: [#94](https://github.com/cogno-us/cognous-stack-orchestrator/issues/94). This is an isolated read-only integration under the [operator-approved decisions](../../RECOVERY_RESOLUTION_DECISIONS.md), not a replacement for Q6, O5-E-B, or the selected release.

## Source selection

| Component | Exact revision | Native interface |
| --- | --- | --- |
| Runtime | `8e7d634cf0a22b6f3c1fc6d93afe92c7414fa243` | `cognous-recovery-inspection/synthetic-0.1` from the existing export API |
| Replay | `696e7bc2432fc7b5cf2d6e6c5f0b944b2d9a265f` | `cognous-replay-recovery-inspection/0.1` |
| Evidence Pack | `bc20a65c0452b85333f9b036853d77aad0b08964` | `cognous-recovery-inspection-evidence/0.1`, transformation `agep-recovery-inspection/0.1` |
| Orchestrator baseline | `2e493beff0a2425c408f8412bd2bf58fe1d50c6f` | New optional result `cognous-recovery-inspection-chain/0.1` |

Replay PR #23 and Evidence Pack PR #23 were reviewed by the implementation agent and merged under operator authorization. Their passing CI is component evidence, not independent assurance or this composed campaign. This candidate introduces no accepted C1–C8 amendment or selected-lock change.

## Data flow and supported API

`development/recovery/recovery_resolution/inspection.py` accepts an already supplied Runtime export, an explicit five-field original identity selection, and the exact three-component revision map. It imports and invokes the actual native Replay importer/validator and Evidence Pack builder/validator. It does not instantiate a Runtime ledger, open SQLite, invoke admission, or contact a destination.

```python
from development.recovery.recovery_resolution.inspection import (
    COMPONENT_REVISIONS, inspect_recovery_export, validate_inspection_chain,
)

result = inspect_recovery_export(
    supplied_runtime_export,
    expected_identity=selected_original_identity,
    component_revisions=COMPONENT_REVISIONS,
)
validate_inspection_chain(result)
```

The original identity must contain `effect_id`, `attempt_id`, `decision_id`, `grant_id`, and `grant_revision`, legitimately selected by the caller. No missing tenant, actor, manifest, runtime decision, or authority record is invented. Consumer checks establish consistency with this supplied selection, not authenticated identity. Dependency revision strings also remain caller assertions outside the verified test/CI environment.

The result retains the complete Evidence Pack native artifact, which retains the full Replay inspection and original supplied export. The adapter checks source retention and loss-report equality in addition to invoking consumer-owned semantics. It does not implement substitute Replay/Evidence Pack models or broaden historical decoder profiles.

`inspection_status` is:
- `inspected_retained_records` when the native report lists no unavailable evidence;
- `inspected_with_unavailable_evidence` when collision payloads or legacy provenance are unavailable.

Neither status says that an effect succeeded, all real-world evidence was supplied, or a claim was independently verified. Invalid/unsupported input raises `InspectionHold` with a reason such as `unsupported_component_revisions`, `unsupported_producer_profile`, `native_consumer_unavailable`, or `invalid_or_inconsistent_inspection`. These are inspection failures, not historical C4 dispatch classifications. No durable refusal ledger is supplied.

## Executed local qualification

Python 3.12 with pytest 9.1.1: **33 tests passed in 1.66 seconds**, including two disposable mutation controls. Each mutation control first passes the same negative check against intact code and then requires failure after removing the revision guard or unavailable-evidence status distinction. Nested checks are not added to the 33-test count.

Tests use pinned Replay's fixture helpers, actual Runtime APIs and temporary SQLite stores, plus actual native Replay and Evidence Pack packages. Imported consumer paths and source blobs are verified; the helpers also verify both Runtime module blobs. Local files were materialized through the connector, not full authenticated Git checkouts. CI additionally verifies full checkout revisions.

An initial run had 32 passes and one failure in a physical SQLite-file byte comparison. Physical-byte identity is outside approved RD-08 and may change during SQLite checkpoint/connection cleanup. The final check compares all logical database records before/after and raises if the inspection path opens SQLite; all nine positive scenarios passed that boundary. No production behavior was changed to satisfy the test.

Positive scenarios and inspected generated artifacts:

| Scenario | Retained events | Producer work state | Evidence gap retained |
| --- | ---: | --- | --- |
| No first observation | 0 | `awaiting_observation` | None declared by the producer |
| Unknown | 1 | `awaiting_finality` | None declared by the producer |
| Absent | 1 | `awaiting_finality` | None declared by the producer |
| Partial | 1 | `partial_followup` | None declared by the producer |
| Unknown → synthetic applied | 2 | `resolved` | None declared by the producer |
| Partial → synthetic applied | 2 | `resolved` | None declared by the producer |
| Conflict | 2 | `conflict_review` | One submitted payload unavailable |
| Exact duplicate after conflict | 3 | `conflict_review` | One submitted payload unavailable; duplicate adds no event |
| Legacy closeout | 0 | `awaiting_observation` | Six legacy provenance gaps |

Every generated result keeps settlement verification and retry eligibility false. `resolved` retains synthetic-only finality. Repeated inspection is deterministic and preserves the input without changing logical Runtime records.

Negative coverage: unsupported component selection/profile/export, missing or wrong original identity, missing/duplicated events, altered predecessor/digest, projection mismatch, dropped provenance, fabricated tenant, changed loss report, false independent-verification/settlement claims, and tampered chain status or pins. A separate test demonstrates that generic ReconstructionBundle parsing can yield zero records and is not accepted as native integration.

## Reproduction and CI artifacts

Install the exact Replay and Evidence Pack checkouts with their existing dependencies and pytest. Provide the exact Runtime source checkout. From the orchestrator root:

```bash
COGNOUS_RUNTIME_SOURCE=/absolute/path/to/runtime COGNOUS_REPLAY_SOURCE=/absolute/path/to/replay COGNOUS_EVIDENCE_SOURCE=/absolute/path/to/evidence RECOVERY_INSPECTION_ARTIFACTS=/absolute/path/to/output python -m pytest -q tests/integration/recovery_resolution/inspection_checks.py --junitxml=/absolute/path/to/output/junit.xml
```

The optional qualification file is explicitly selected; it fails on missing fixture configuration rather than silently skipping. Existing default test selection and dependency generations are unchanged.

Workflow `.github/workflows/recovery-resolution-inspection.yml` checks out all three exact dependencies, verifies their Git heads, installs actual native consumers, and uploads nine synthetic scenario JSON files plus JUnit and `artifact-manifest.json`. The manifest records actual checkout revisions (including the tested orchestrator checkout) and per-file SHA-256. A retained artifact or successful upload alone is not a passing test result. At initial publication, remote artifact contents have not been inspected; record the exact run/head and inspection outcome in the PR after CI.

## Limits and next gate

This establishes only the executed synthetic read-only mapping at these pins. Supplied records, identity assertions and digests are not authenticated source evidence. Missing collision preimages cannot be recomputed; legacy provenance and unrecorded rejected submissions are not reconstructed. Coordinated changes to unauthenticated source and corresponding summaries are outside the consistency guarantee. No fresh observation, admission, retry, adjudication, migration, provider finality, or complete refusal audit is established.

Full unrelated orchestrator suites were not run locally. Independent review, operational trust and selected-release adoption remain separate decisions. No private ISS, AoM or IGPG material is used. Preserve C0 check-to-commit limits, optional same-host C1, no C2/C3, no real settlement, and operational #30 HOLD.

Next gate: exact-head scoped CI and attributable review of this candidate and its retained artifacts. A merge accepts only the bounded source change; it does not activate a production effect or update the selected hub lock.
