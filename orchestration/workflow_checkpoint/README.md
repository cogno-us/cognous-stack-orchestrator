# workflow_checkpoint: external checkpoint interface, local synthetic reference (Q6)

**Non-authorizing. Local, synthetic, non-effecting. Release, publication and production remain on HOLD.** Nothing here claims clearance, certification, qualification, authenticity, complete tamper-evidence or production readiness.

**Claim, unchanged:** until a custody interface is adopted and qualified, the accurate statement is **local chain consistency with limited truncation detection** (against a head a caller retained outside the store). This directory is a design reference and a synthetic stand-in; it does not change that claim.

Origin: architect decisions Q6 and Q10. Design: [INTERFACE-DESIGN.md](INTERFACE-DESIGN.md).

## Parts

| Module | Role | Side |
|---|---|---|
| `record.py`, `producer.py` | build and validate a per-workflow checkpoint (workflow id, head count, head digest, store profile and schema identity, producer, checkpoint sequence, predecessor, digest) from a store head | Orchestrator |
| `custodian.py` | synthetic append-only retention in local files; refuses duplicate, gap, regression, fork, producer change | proposed custodian (Evidence Attestation, subject to its owner's acceptance; **no change to Evidence Attestation**) |
| `verifier.py` | `verify(custody_root, workflow_id, Candidate)` returns `match`, `mismatch` or `unverifiable` with a closed code | Qualification-style caller |

The existing `workflow_store` is only read (`LoadedWorkflow`, `canonical`); it is not modified.

## Provisional names (not frozen)

`ocs-workflow-checkpoint/0`, its member names, file layout and the result codes are provisional. No freeze, schema digest or consumer agreement exists; a freeze needs its own review (see Q17).

## Not decided here (operator)

Final external custody commitment, whether Evidence Attestation accepts the custodian role, any locked Evidence Attestation change and its F3 package, retention and access rules, and transport.

## Tests

`PYTHONPATH=. python -m pytest -q tests/integration/workflow_checkpoint` (Python 3.11 and 3.13). Negative controls cover truncation, rollback, fork, missing and duplicate checkpoint, workflow and profile mismatch, corruption and re-signed retained sets.
