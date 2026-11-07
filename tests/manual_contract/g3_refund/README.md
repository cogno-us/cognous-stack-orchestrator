# G3-REFUND (DEVELOPMENT ONLY / SYNTHETIC / NONPRODUCTION / UNQUALIFIED / builder-lineage / non-authorizing)

One bounded synthetic refund workflow across the merged development components, with three frozen functional checks. Authorization: Hub #273 comment 6711274204; frozen mapping and oracles: #273 comment 6711352677. Frozen S2 evidence (`../s2_runtime/`) is untouched. No component source, lock, workflow, ODES or GAX is involved.

```
G2 root lineage (IG) -> Control Plane decide() -> Runtime execute (one real local SQLite INSERT)
  -> Replay 7eb7d76e -> Pack 1906c1fb (opt-in generation) -> Verifier (abstain) -> G1 attestation -> G1b Registry (disposable chain)
```
Exact pins: `source_manifest.json` (verified: HEAD = pin and tracked tree clean, before any import). Replay is used with the Pack's explicit opt-in generation `cp2-replay-7eb7d76e-tenant-binding-dev-0.1`; `ODES_ALLOW_UNVERIFIED_REPLAY=0`.

## Files
`g3_capture.py` (S2 capture pattern with the merged G2 resolver; CP `decide()` is the only authority; Runtime runs only after `authorized`) · `g3_stages.py` (thin stage runner + final-observation renderer) · `g1b_run.mjs` (calls the merged G1b `run()`) · `test_g3_refund.py` (three checks) · `evidence/` (raw outputs of every run, including the failed one).

## Run
```bash
G3_STACK_ROOT=<dir with control_plane runtime replay evidence_pack manifest institutional_governance verifier evidence_attestation evidence_registry, each at its pin> \
G3_REQUIRE=1 G3_EVIDENCE_DIR=<dir> python -m pytest -q tests/manual_contract/g3_refund
```
Needs Python with pydantic, cryptography and jsonschema (`PYTHON` = the interpreter running pytest) and Node with `npm ci` done in `evidence_registry/chain`.

## Frozen checks
1. **Positive chain**: CP `authorized`; one Runtime INSERT `applied`; Replay `reconstruction_complete`; Pack `validated_complete`; Verifier exit 3 `abstain` with all four executor kinds present; G1 signature valid under the synthetic snapshot; G1b `PRESENT_PROVISIONAL`. 
2. **Revoked refusal**: CP `hold` + `grant_revoked`; every downstream stage NOT RUN; no SQLite row; no Registry write.
3. **Missing execution evidence**: check 1's CP record with the executor export omitted -> Replay `reconstruction_partial`; Pack `validated_partial`; Verifier `abstain`, four executor kinds absent; execution assurance NOT VERIFIED; G1/G1b NOT RUN.

## What each result does and does not mean
Synthetic authorization (resolver `authenticated=false`; identity/mandate flags are fixture assertions) is not institutional authority. The Runtime write is real but local and **producer-reported**, not independently observed. The Verifier is ALPHA/HOLD and only abstains. The signature is valid only under a synthetic ephemeral snapshot and is not chain-bound. Registry inclusion is provisional on a disposable loopback chain: no custody, no finality. Nothing here is independent qualification.

## Rollback
Delete `tests/manual_contract/g3_refund/`. The isolated SQLite file and the Ganache chain are disposed after each run.
