# O2 — Component Contract and Revision Crosswalk

**Status:** INVENTORY CHECKPOINT / NOT ACCEPTED AS AN INTEGRATION LOCK
**Recorded:** 2026-10-09
**Parent:** [Engineering dashboard #1](https://github.com/cogno-us/cognous-stack-orchestrator/issues/1)
**Normative source:** [V0 draft](integration-contract-v0.md)
**Existing reference authority:** [Hub PR #63](https://github.com/cogno-us/cognous-open-control-stack/pull/63); original hub C1–C8 contracts, not this file.

## Revision rules

- **Selected reference pin** = component revision recorded by the W7 bounded reference-release selection candidate; **not** the default branch or a universal stable release.
- **Observed latest commit** = most recent commit returned by a one-time repository search; **not** automatically accepted for orchestrator integration.
- **Unresolved** = metadata/query could not substantiate a full SHA or current interface. Do not replace missing revisions by remembered aliases.
- This inventory does not change the historical `component-lock.json`, W7 candidate lock, or PR #63 authorization.
- Public product-grouping is not an instruction to merge repositories or collapse responsibilities.

## Five-domain crosswalk

| Domain | Component repository | Selected bounded V1 pin | Observed latest commit (one-time 2026-10-09 lookup) | Integration responsibility / maturity |
|---|---|---|---|---|
| 1 Knowledge & Provenance | `cogno-us/cognous-evidence-registry` | Not part of selected five-repo core | Unresolved — commit listing failed | Structured claims and epistemic state; not qualified into this orchestrator |
| 1 Knowledge & Provenance | `cogno-us/cognous-evidence-attestation` | Not part of selected five-repo core | Unresolved — commit listing failed | Attestations/provenance; independent authenticity and current applicability still require qualification |
| 2 Institutional Governance | `cogno-us/cognous-institutional-governance` | Not part of selected five-repo core | Unresolved — commit listing failed | Cognous Institutional Governance (Alvorada) supplies governance context; adopted grants require real institution/source |
| 3 Action Governance | `cogno-us/cognous-action-manifest` | `8d1572d4f926c968a8704cb912a6e9d49166f74a` | Same as selected pin | Declared action, tenant-aware proposal; declaration not grant |
| 3 Action Governance | `cogno-us/cognous-control-plane` | `e66e5f163c5d5c112ff345a2f332b4c3893ee183` | `99bb62fff879a8d4e87d7badb0d7d8a17501e4c1` | Runtime authorization and effect-time checks; current HEAD has optional W5 Microsoft adapter merged and is NOT automatically the selected release pin |
| 4 Governed Execution | `cogno-us/cognous-execution-runtime` | `da9f52900ee2596dab087ec6c249ba84915d2b13` | Same as selected pin | Effect identity, attempt/recovery, bounded local execution |
| 4 Governed Execution | `cogno-us/cognous-execution-runtime` | Same repository as qualified runtime pin above | See qualified runtime row above | Formerly Moltbot Safe; do not treat as a separate current repository or duplicate dependency |
| 5 Evidence & Accountability | `cogno-us/cognous-replay-bundle` | `2069a0ba1398812c3a8669331a7d8b87c80c4a48` | Same as selected pin | Source-derived reconstruction, non-authorizing |
| 5 Evidence & Accountability | `cogno-us/cognous-governance-evidence-pack` | `87293cfcbe8dfa2368d5bf77019945ba8ef1ae71` | Same as selected pin | Projection for review, non-authorizing |
| 5 Evidence & Accountability | `cogno-us/open-decision-evidence-standard` | Optional; not part of selected core | `c5e9a0f3695ae836b803be06c46d2c669642ee03` | Independent decision-evidence exchange; README describes pder-v0.1 record schema under v0.2 narrative; no orchestrator conformance acceptance |

## Optional cross-cutting system

| Interface | Repository | Status | Safety boundary |
|---|---|---|---|
| ISS cognitive client | `TurwinAI/COGNOUS-client` (private) | Disabled placeholder; no adapter accepted | Output may propose actions, but never grant execution authority; no private code exported |
| OpenAPPA | Optional W4 profile | Existing optional qualification separate | Information-flow approval is not action authority |
| Microsoft AGT | Optional W5 profile | HEAD diverges from selected control-plane pin | Pre-tool checks remain conjunctive with native authority |
| OpenShell | Optional W6 profile | Founder-deferred live qualification | No live confinement claim |

## Verified source anchors

- [Reference selection PR #63](https://github.com/cogno-us/cognous-open-control-stack/pull/63) contains the five full core pins above; Governor's previous snapshot reported 71 scoped source tests and pending publication authority.
- [Selected CI run 37858259590](https://github.com/cogno-us/cognous-open-control-stack/actions/runs/37858259590) is historical exact-head qualification, not a five-domain integrated qualification.
- Control Plane current README describes bounded authorization and source-of-record decisions; the latest observed merge is optional Microsoft AGT PR #17.
- ODES current README states portable evidence does not grant action authorization.

## Proposed interface mapping, subject to source-owner validation

| From | To | Proposed exchanged object | Requirement before coding |
|---|---|---|---|
| Evidence Registry / Evidence Attestation | Institutional context and action proposal | Source claim refs, attestation refs, freshness, contradiction, source trust | Pin schema/version, admission and source-verification contracts |
| Cognous Institutional Governance (Alvorada) | Action Governance | Adopted institutional profile + accountable grant issuer reference | Distinguish doctrinal framework from legally/operationally adopted authority |
| Action Manifest | Control Plane | Exact manifest-bound action proposal | Reuse accepted C1/C2 generation and known compatibility fixtures |
| Control Plane | Execution Runtime | Current exact authority and effect binding | Preserve C3/C5/C7 timing and destination constraints |
| Execution Runtime / Control Plane | Replay | Immutable producer record refs, effect/attempt/observation lineage | Reuse selected C8 source bytes; reject unsupported generations |
| Replay | Evidence Pack | Validated reconstruction and loss/unknown status | Traceable transform/version, no assumed reviewer approval |
| Evidence Pack / Replay | ODES | Optional portable export | Independent consumer schema and verifier qualification |
| ISS | Action Governance | Untrusted structured proposal and correlation references | Private API review, tenant/credential schema, no implicit grants |

## Gaps and exact next gate

1. Recover reliable immutable default-head SHAs and active API/schema surfaces for Cognous Evidence Registry, Cognous Evidence Attestation, Cognous Institutional Governance, and the former Moltbot Safe runtime identity (GitHub content/commit connector queries returned errors; repository existence was verified). Use source-owner confirmations, not invented pins.
2. Verify whether currently observed newer Control Plane revision changes the bounded core interfaces, or is strictly an optional adapter addition. **Do not auto-upgrade** the selected pin.
3. Record actual schema names, canonicalization rules, source field mapping, and negative case fixture IDs for each new cross-domain edge.
4. Obtain component-owner review on the [V0 Integration Contract](integration-contract-v0.md) before interpreting proposed envelopes/state transitions as accepted interfaces.
5. Build G1 schema/compatibility tests first; defer runtime composition, ISS and ODES until their specific gates.

## Release and authorization posture

The current five-domain integration is **NOT IMPLEMENTED OR QUALIFIED**. The pre-existing bounded four-stage reference qualification is distinct. This crosswalk is documentation only, neither a production deployment authorization nor a C1–C8 amendment.
