# Architecture — five-domain integration scaffold

This repository is an orchestration surface, not a monolithic replacement for owned components. The existing `cognous-open-control-stack` hub governs the bounded reference release, contract freeze and selection.

| Domain | Component roles | Integration posture |
|---|---|---|
| Knowledge & Provenance | The Index: claims and epistemic state; BitRep: attributable attestations | Proposed adapter; no qualified flow to authority |
| Institutional Governance | Alvorada: institutional provisions and accountable authority procedures | Requirements mapping; no self-granting policy changes |
| Action Governance | Action Manifest: declarations; Control Plane: effective authorization | Preserve both contracts and separate declaration from grant |
| Governed Execution | Execution Runtime: exact effect/attempt protocol; Moltbot Safe: constrained worker profile | Environment-specific, tested claims only |
| Evidence & Accountability | Replay: reconstruction; Evidence Pack: review projection; ODES: optional portable evidence | Never infer effect verification or approval from record validation |

## Flow and boundaries

Knowledge can inform a proposal but cannot grant execution authority. Institutional grants and current policy must be checked at the action boundary. Authorization is not execution; executor ACK is not independent observation. Replay and evidence reconstruct what was recorded and cannot re-authorize actions. Workflow coordination must not bypass these component-level controls.

## ISS

ISS is an **optional proposal/analysis producer** through a versioned, tenant-bound adapter. Its private implementation is outside this repository; no ISS status or model output grants action authority. See [ISS placeholder](integrations/iss/README.md).

## Maturity

Five-domain end-to-end integration: **NOT IMPLEMENTED / NOT QUALIFIED**. The four-stage synthetic SQLite refund reference retains its separately documented, narrower qualification.
