# S2-REFUND-RT-01 harness (DEVELOPMENT ONLY, SYNTHETIC / NONPRODUCTION, UNQUALIFIED, builder-lineage, non-authorizing, HOLD)

Execution Runtime → Replay → Evidence Pack provenance experiment. No Runtime, Replay, Pack, Control Plane or Manifest change; no adapter or schema.

- `s2_capture.py` — drives the pinned Control Plane (strict tenant `tenant-alpha`) and Runtime Route A (`PinnedControlPlaneExecutor.execute`, isolated local SQLite) and persists the Runtime's own `export_execution_artifacts` output unmodified. Differs from the Pack's tool `capture_strict_tenant_runtime.py` (which was denied because it omitted the operation tenant) only by `ExecutionOperation(tenant_id=proposal.tenant_id)`. The export's `repository_revision` is caller-asserted.
- `source_tuples.json` — versioned candidate tuples. S2-CANDIDATE-1 (Replay `93a76e28`, superseded) and **S2-CANDIDATE-2** (Replay `7eb7d76e`, the main merge of Replay PR #89 with the tenant-binding correction). Development references, not a source lock.
- `test_s2_runtime_provenance.py` — G1, P (Replay/Pack parts), N1–N8, N2b. Run with `S2_STACK_ROOT=<dir with control_plane runtime replay evidence_pack manifest at the tuple-2 pins> S2_REQUIRE=1`.
- `evidence/` — every original run output including failures (`runs/` = tuple 1, `runs_tuple2/` = tuple 2, `iterations/` = prior test-file versions) and one supplementary raw capture.

## Tuple 1 (Replay 93a76e28): stopped at gate G2
G1 and P passed; N2/N2b FAILED (Replay accepted a coherently rewritten foreign-tenant operation). N1, N3–N8 were not run. Preserved under `evidence/runs/`.

## Tuple 2 (Replay 7eb7d76e, Pack 06515085): BLOCKED at the Pack
Replay-level tests all passed (P-replay, N1, N2/N2b refused with `binding_contract_mismatch` on `execution_envelope.operation.tenant_id`, N3–N6, N7-replay, N8-replay); the three Pack-level tests failed because Pack 06515085 hard-pins Replay `93a76e28`. Preserved under `evidence/runs_tuple2/`.

## Tuple 3 (S2-CANDIDATE-3: Pack 1906c1fb with the explicit opt-in `replay_generation="cp2-replay-7eb7d76e-tenant-binding-dev-0.1"`): P-pack, N7-pack, N8-pack PASS (first run, 3 passed)
- **P-pack:** Replay `reconstruction_complete`; Pack `validated_complete`, candidate recorded, validator clean; executor records (`destination_attempt`, `destination_effect`, `execution_result`) are separate kinds from Control Plane records and equal the raw Runtime export; `executor_attempt_count` 1, `destination_effect_count` 1, `execution_result_state_counts` {applied:1}, `control_plane_attempt_count` 1, `independent_verification` unavailable.
- **N7-pack:** export `reconciled` / `acknowledged` false / `newly_executed` false; no second attempt or effect; `acknowledgement_counts` {control_plane_unknown:1, execution_result_unknown:1} versus P-pack's {control_plane_received:1, execution_result_received:1}. `execution_result_state_counts` is {applied:1} (reconciled is normalized to applied; it does not distinguish a lost acknowledgment, the acknowledgement counts do).
- **N8-pack (`moltbot_export=None`):** Replay `reconstruction_partial`; Pack `validated_partial`; `executor_attempt_count` 0, `destination_effect_count` 0, `execution_result_state_counts` {}; no executor kinds; BUT `control_plane_attempt_count` 1, `execution_attempted` "yes", `destination_observed` "applied" (scope: "latest supplied Control Plane reconciliation per exact effect; not a fresh query"), acknowledgement "received" (Control Plane transition); Replay `destination_observation` "not_performed"; the CLI prints `executor_attempt_count : 0` beside `destination_observed : applied` with no qualifier. Recorded as observed Pack presentation (defect candidate D2), not corrected.
- Outputs, including the CLI summarize/validate text: `evidence/runs_tuple3/`.
- Replay-level tests were not re-run as a campaign (only G1 and P-replay as a minimal shared-fixture check). N3–N6 still assert only that a refusal occurs (messages are logged).

Limits: caller-asserted Runtime `repository_revision`; the harness, not the Runtime, persists the export; the effect_id comes from the Control Plane; same-author throwaway stores; no independent custody; source measurement = git HEAD + unmodified tracked files + module `__file__` location + remediation-ancestor check + presence of the corrected function (Control Plane and Runtime module identity are NOT measured; untracked files are not checked). `ODES_ALLOW_UNVERIFIED_REPLAY=0` is set process-wide by the fixture.
Rollback: delete this directory.
