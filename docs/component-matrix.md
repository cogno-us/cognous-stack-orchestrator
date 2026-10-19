# Component ownership and integration matrix

Groups use the hub names (see the hub [stack map](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/stack-map.md)). The `domains/` directory keeps the earlier domain names; the README maps them. The status column states what this repository qualifies and no more.

| Hub group | Component | Source | Initial status |
|---|---|---|---|
| 01 Knowledge & Provenance | Cognous Evidence Registry (The Index) | cogno-us/cognous-evidence-registry | Bounded adapter and source tests only (see O4d, O6-Q2); no flow to authority |
| 01 Knowledge & Provenance | Cognous Evidence Attestation (BitRep) | cogno-us/cognous-evidence-attestation | Bounded adapter and source tests only (see O4d, O6-Q2); no flow to authority |
| 02 Institutional Governance | Cognous Institutional Governance (Alvorada) | cogno-us/cognous-institutional-governance | Not integrated here |
| 03 Declaration & Policy Control | Action Manifest | cogno-us/cognous-action-manifest | Qualified only in bounded chain |
| 03 Declaration & Policy Control | Control Plane | cogno-us/cognous-control-plane | Qualified only in bounded chain |
| 04 Constrained Execution | Cognous Execution Runtime (formerly Moltbot Safe) | cogno-us/cognous-execution-runtime | Qualified only in bounded chain; runtime and worker implementation with scoped qualification only |
| 05 Replay & Evidence | Replay Bundle | cogno-us/cognous-replay-bundle | Qualified only in bounded chain |
| 05 Replay & Evidence | Governance Evidence Pack | cogno-us/cognous-governance-evidence-pack | Qualified only in bounded chain |
| 05 Replay & Evidence | ODES | cogno-us/open-decision-evidence-standard | Optional, unqualified here |
| Cross-cutting exchange | Governed Exchange (GAX/IMX) | cogno-us/cognous-governed-exchange | Read-only compatibility mapping and source tests (see O4c-D, O6-Q2, O6-Q4); no flow to authority |
| Not a stack component | ISS client | private repository (not mirrored here) | Disabled external-interface placeholder |

This is a responsibility map, not proof of combined operation. Verify current repository locations and release pins before assigning implementation.
