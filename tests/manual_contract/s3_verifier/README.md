# VNEXT-S3-CONTRACT-VALIDATION-01 (DEVELOPMENT ONLY / SYNTHETIC / NONPRODUCTION / UNQUALIFIED / builder-lineage / non-authorizing / HOLD)

One bounded, provider-free developer contract-validation harness that runs the existing, source-pinned Verifier
(`cogno-us/cognous-open-control-stack-verifier` @ `7caf25411b8be61178b12e71c48eeea7f62d8eb9`, ALPHA / ON HOLD)
through its native entry point `cognous_verify.cli:main` against the retained S2 Control Plane records
(`../s2_runtime/evidence/raw_supplementary_capture/`) and minimal isolated mutated copies.

Authority: static plan #281 (controlling), Hub #273, Architect authorization #273 comment 6709001983.
This is NOT independent qualification, NOT S3 implementation or acceptance, and NOT a Replay/Pack-to-Verifier integration.

## Files
- `s3_oracle.json` — expectations, frozen and posted to Hub #273 before execution (never edited to fit results).
- `test_s3_verifier_contract.py` — the harness. Native Verifier functions only; no re-implemented check.
- `evidence/` — raw per-run output including any failed runs.

## Run
```bash
S3_VERIFIER_ROOT=<verifier checkout @7caf2541> S3_MANIFEST_ROOT=<cognous-action-manifest @fa170815> \
S3_EVIDENCE_DIR=<dir> S3_REQUIRE=1 PYTHONPATH=".:src" python -m pytest -q tests/manual_contract/s3_verifier
```

## What this can show
Native structural parsing; native commitment recomputation; native refusal discrimination on minimal mutations; honest handling of an absent Control Plane-native destination ledger (seven `v4.ledger.*` checks `could_not_check`, overall ABSTAIN, never ACCEPT).

## What this does NOT show
Exact producer source authentication (the SHA checks are harness preconditions); authenticated provenance; independent custody; independent execution verification; independent assessor accountability; Replay- or Evidence Pack-to-Verifier integration; S3 internal acceptance; production qualification. A coherently resealed record set passes the same internal consistency checks (N8) — consistency is not authenticity.

## Rollback
Delete this directory (`tests/manual_contract/s3_verifier/`). No other repository, schema, workflow or source is touched.
