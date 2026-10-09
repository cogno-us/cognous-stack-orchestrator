# Canonical repository names — 2026-10-09

**Source:** founder-supplied 20-repository organization inventory, with new primary links validated where applicable. This is a naming index, **not** a component lock, claim of deployment or instruction to update all source repositories.

## Current repository inventory (20)

| # | Current repository | Visibility per supplied inventory | Orchestrator relationship |
|---|---|---|---|
| 1 | [cognous-stack-orchestrator](https://github.com/cogno-us/cognous-stack-orchestrator) | Private | Integration orchestration and development cockpit |
| 2 | [cognous-open-control-stack](https://github.com/cogno-us/cognous-open-control-stack) | Public | Existing bounded reference hub and release governance |
| 3 | [cognous-governance-evidence-pack](https://github.com/cogno-us/cognous-governance-evidence-pack) | Public | Evidence & Accountability |
| 4 | [cognous-replay-bundle](https://github.com/cogno-us/cognous-replay-bundle) | Public | Evidence & Accountability |
| 5 | [cognous-execution-runtime](https://github.com/cogno-us/cognous-execution-runtime) | Public | Governed Execution; includes former Moltbot Safe identity |
| 6 | [cognous-control-plane](https://github.com/cogno-us/cognous-control-plane) | Public | Action Governance |
| 7 | [cognous-action-manifest](https://github.com/cogno-us/cognous-action-manifest) | Public | Action Governance |
| 8 | [cognous-institutional-governance](https://github.com/cogno-us/cognous-institutional-governance) | Public | Institutional Governance (Alvorada) |
| 9 | [portable-reasoning-protocol](https://github.com/cogno-us/portable-reasoning-protocol) | Public | Optional reasoning discipline |
| 10 | [cognous-governed-exchange](https://github.com/cogno-us/cognous-governed-exchange) | Public | Optional governed message/exchange boundary; contract discovery required |
| 11 | [open-decision-evidence-standard](https://github.com/cogno-us/open-decision-evidence-standard) | Public | Optional portable evidence standard |
| 12 | [research-intelligence-protocol](https://github.com/cogno-us/research-intelligence-protocol) | Public | Optional research/evidence acquisition |
| 13 | [truth-freedom-agency-protocol](https://github.com/cogno-us/truth-freedom-agency-protocol) | Public | Optional human-interaction principles |
| 14 | [cognous-evidence-registry](https://github.com/cogno-us/cognous-evidence-registry) | Public | Knowledge & Provenance; formerly The Index |
| 15 | [cognous-evidence-attestation](https://github.com/cogno-us/cognous-evidence-attestation) | Public template | Knowledge & Provenance; formerly BitRep |
| 16 | [comprehension-stack](https://github.com/cogno-us/comprehension-stack) | Public | Ecosystem orientation |
| 17 | [comprehension-scope](https://github.com/cogno-us/comprehension-scope) | Public | Optional human sensemaking |
| 18 | [site](https://github.com/cogno-us/site) | Public | Website |
| 19 | [igpg-practice-system](https://github.com/cogno-us/igpg-practice-system) | Private | Proprietary/optional; not imported |
| 20 | [architecture-of-mind](https://github.com/cogno-us/architecture-of-mind) | Private | Proprietary/optional; not imported |

**Outside this organization inventory:** [TurwinAI/COGNOUS-client](https://github.com/TurwinAI/COGNOUS-client), private ISS integration source; not counted as one of the 20.

## Rename crosswalk

| Historical term or repository | Current repository / preferred current title |
|---|---|
| The Index; `the-index` | **Cognous Evidence Registry** — `cognous-evidence-registry` |
| BitRep; `bitrep` | **Cognous Evidence Attestation** — `cognous-evidence-attestation` |
| Alvorada; `constitutional-governance-for-institutions` | **Cognous Institutional Governance (Alvorada)** — `cognous-institutional-governance` |
| Moltbot Safe; `moltbot-safe` | **Cognous Execution Runtime** — `cognous-execution-runtime` |
| Older exchange/ODEX naming | **Cognous Governed Exchange** — `cognous-governed-exchange`; exact historical lineage not independently verified |

Use historical names only when documenting original tests, commits, migrations or provenance; do not rewrite immutable evidence. Keep original C1–C8 contract IDs and historical lock content unchanged.

## Five-domain naming

1. **Knowledge & Provenance** — Cognous Evidence Registry + Cognous Evidence Attestation
2. **Institutional Governance** — Cognous Institutional Governance (Alvorada)
3. **Action Governance** — Cognous Action Manifest + Cognous Control Plane
4. **Governed Execution** — Cognous Execution Runtime
5. **Evidence & Accountability** — Cognous Replay Bundle + Cognous Governance Evidence Pack + optional Open Decision Evidence Standard

Cognous Governed Exchange is a separately evaluated optional message interoperability component; it is **not** ODES and is not automatically required by the V0 chain.

## Maintenance rule

Future issue titles, PRs, release collateral and integration work should cite the **current** repository names and paths. Historical citations retain the name/ref that actually existed when evidence was produced. This document does not claim that every upstream README, old GitHub issue or archived artifact has been renamed.
