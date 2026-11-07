# S3 contract-validation results (DEVELOPMENT ONLY / builder-lineage / non-authorizing / HOLD)

Verifier `7caf25411b8be61178b12e71c48eeea7f62d8eb9`; orchestrator base `dae935cdcda71c3f69414ced0828ed6433e73e95`. Oracle frozen at commit `40fb9e07` (Hub #273 comment 6709118843) before execution.

| Test | Frozen oracle | Native result (exit / overall) | Classification |
|---|---|---|---|
| G0 source identity | preconditions | pass | PASS (precondition, not provenance) |
| P1 unchanged S2 record | 25 confirmed + 7 ledger could_not_check | 3 / ABSTAIN, 25/7/0 | PASS for the limited oracle; PARTIAL outcome, not whole-record verification |
| N1 proposal commitment | proposal-commitment refuted | 1 / REJECT | PASS |
| N2 effect_id | effect-id refuted | 1 / REJECT (3 refuted incl. collateral) | PASS |
| N3a payload commitment | payload-commitment refuted | 1 / REJECT | PASS |
| N3b manifest binding | manifest-digest refuted (2 codes) | 1 / REJECT | PASS |
| N4a missing proposal | 7 identity could_not_check | 3 / ABSTAIN | PASS |
| N4b missing run record | usage refusal | 2 / ERROR (usage, nothing verified) | PASS (usage refusal, not an assurance verdict) |
| N5 original | unknown_enum_value @ binding.generation | 1 / REJECT, but generic `schema_violation` @ binding | **FAIL (original adverse evidence)** |
| N5 iteration 2 | generic schema closure (frozen post-observation) | 1 / REJECT | PASS (characterization, not prediction) |
| N6 | 7 ledger could_not_check, not ACCEPT | reuses P1 | PASS |
| N7 Replay/Pack | — | not run | NOT EXECUTED — UNSUPPORTED NATIVE CONTRACT |
| N7b runtime_export as run record | unsupported_document | 3 / ABSTAIN | PASS (not a Replay/Pack claim) |
| N8 self-consistent forgery | Outcome A | 3 / ABSTAIN, verdict vector identical to P1 | PASS as characterization: limitation demonstrated; NOT authenticity |

Raw output for every run, including the failed one, is under `evidence/`. Nonclaims: see README.md and s3_oracle.json.
