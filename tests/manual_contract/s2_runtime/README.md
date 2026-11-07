# S2-REFUND-RT-01 harness (DEVELOPMENT ONLY, SYNTHETIC / NONPRODUCTION, UNQUALIFIED, builder-lineage)

Runtime → Replay → Evidence Pack provenance experiment (Architect authorization: Hub #273 comment 6701568606). No Runtime, Replay, Pack or Control Plane change; no adapter or schema.

- `s2_capture.py` — drives the pinned Control Plane 484fdbd2 (strict tenant `tenant-alpha`) and the pinned Execution Runtime f7a55e2a Route A (`PinnedControlPlaneExecutor.execute`, isolated local SQLite) and persists the Runtime's own `export_execution_artifacts` output unmodified. One difference from the Pack's tool `capture_strict_tenant_runtime.py` (denied because it omitted the operation tenant): `ExecutionOperation(tenant_id=proposal.tenant_id)`.
- `test_s2_runtime_provenance.py` — G1 compatibility, P, N1–N8 plus the N2b iteration. Run with `S2_STACK_ROOT=<dir with control_plane runtime replay evidence_pack manifest at the five pins> S2_REQUIRE=1`.
- `evidence/` — original run outputs (including the failures) and one supplementary raw capture (not the capture the tests ran on; throwaway-store ids differ per capture).

## Outcome: **STOPPED at mandatory gate G2 (tenant binding)**
- **G1 PASS** — Runtime f7a55e2a executes the strict-tenant operation under CP 484fdbd2 (`authorized` → `executed`, one effect, one attempt).
- **P PASS** — Replay `reconstruction_complete` with `moltbot_export` present; Pack executor counts sourced from Runtime records.
- **N2 iteration 1 FAIL** — refused, but by `control_plane.observations.destination_state.operation_digest conflicts with committed operation`, not a tenant check.
- **N2b iteration 2 FAIL (G2 STOP)** — with export and Control Plane record digests consistently rewritten for `tenant-beta`, **Replay ACCEPTED** (`reconstruction_complete`). Replay does not compare `execution_envelope.operation.tenant_id` (`_validate_envelope_chain`, importers.py:303-326). N1, N3–N8 were **not run** (stop rule), so they are neither pass nor fail.

Limits: caller-asserted Runtime `repository_revision`; the harness, not the Runtime, persists the export; the effect_id comes from the Control Plane; same-author throwaway stores; no independent custody; source measurement is git HEAD/tree + clean tracked files + module location.
Rollback: delete this directory.
