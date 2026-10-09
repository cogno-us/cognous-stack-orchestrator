# Cognous Stack Orchestrator — V0 Integration Contract

**Document ID:** CSO-IC-V0
**Contract version:** 0.1.0-draft
**Status:** PROPOSED / NOT RATIFIED / NOT IMPLEMENTED
**Owner:** Orchestrator engineering governor; component owners must accept their interfaces separately.
**Location:** `development/integration-contract-v0.md`
**Authority:** This document defines intended orchestration interfaces. It does **not** amend W0 C1–C8, component schemas, institutional grants, or the bounded V1 reference-release selection.

## 1. Purpose and scope

Coordinate the five Cognous domains while preserving component autonomy, release traceability and institutional authority. The orchestrator is a **workflow coordinator** and compatibility boundary, never the source of an action grant and never a second Control Plane.

Domains:
1. Knowledge & Provenance — Cognous Evidence Registry and Cognous Evidence Attestation
2. Institutional Governance — Cognous Institutional Governance (Alvorada)
3. Action Governance — Action Manifest and Control Plane
4. Governed Execution — Cognous Execution Runtime
5. Evidence & Accountability — Replay Bundle, Governance Evidence Pack and optional ODES

**V0 target:** one deliberately bounded, reproducible synthetic local refund journey, optionally enriched with attributable knowledge and institutional-context *references*. The already-qualified four-stage Declare → Control → Replay → Evidence workflow remains owned by the existing hub and its accepted pins. Cross-domain proof is **not yet available**.

Non-goals: production identity; remote execution assurance; generalized prompt-injection resistance; policy synthesis; automatic constitutional amendment; fleet-wide stopping; universal exactly-once effects; independent verification without an actual verifier; live OpenShell qualification; complete ISS cognitive runtime integration.

## 2. Source hierarchy and precedence

1. Human/institutional grant and adopted governance rules in their authoritative systems.
2. Current accepted C1–C8 component contracts, source schemas and scoped release records.
3. Accepted, explicitly pinned domain implementations and adapters.
4. This proposed orchestrator interface.
5. Illustrations and examples.

A lower-ranked artifact cannot silently override a higher-ranked authority. Cognous Institutional Governance (Alvorada) is a governance framework, **not automatically a live approval authority** absent institutional adoption and a real grant issuer. Cognous Evidence Attestation records support provenance, not authorization. ISS reasoning output supports proposals, not permission.

## 3. Canonical identifiers and bounded envelope (proposal)

The orchestrator should pass opaque component-issued identifiers rather than mint false upstream evidence. The proposed transport envelope, versioned independently of source objects:

```json
{
  "schema": "cognous.orchestrator.envelope/0.1-draft",
  "workflow_id": "wf-example",
  "correlation_id": "corr-example",
  "tenant_binding_ref": "tenant-bound-source-reference",
  "actor_ref": "actor-source-reference",
  "step_id": "step-proposal",
  "source_component": "example",
  "source_revision": "FULL_ACCEPTED_SHA_REQUIRED",
  "source_schema": "SOURCE_SCHEMA_VERSION_REQUIRED",
  "payload_kind": "proposed_action",
  "payload_ref": "content-addressed-or-access-controlled-reference",
  "created_at": "2026-10-09T00:00:00Z",
  "integrity": {
    "algorithm": "sha256",
    "digest": "DERIVED_FROM_CANONICAL_BYTES_NOT_THIS_EXAMPLE"
  },
  "provenance_refs": [],
  "authority_ref": null,
  "effect_id": null,
  "attempt_id": null,
  "observation_refs": [],
  "verification_status": "not_established"
}
```

The example is descriptive only: not a normative schema, validated object or fixture. The actual V0 implementation must choose canonical bytes, ID syntax, allowed enums and trusted timestamp semantics via a separate accepted schema proposal.

**Required field semantics:** workflow/step/correlation IDs identify orchestration records only. Tenant and actor references require validation at their owning authority boundary. Source revision and schema declare exact producer generation. The payload reference is not the payload and is never an authorization token. Authority/effect/attempt/observation identifiers are nullable until genuinely produced. Unknown and absent must not be upgraded to validated or verified.

## 4. Domain interface proposals

| Domain | Proposed input | Proposed output | Authority constraint |
|---|---|---|---|
| Knowledge & Provenance | Scoped inquiry, source and attestation references | Claim/evidence refs, provenance, status, freshness, uncertainty | No permission implied |
| Institutional Governance | Proposed action class, consequence context and institution profile | Applicable rule/grant requirements and review route | Actual grants remain external and attributable |
| Action Governance | Manifest-bound proposal, current grant/policy/evidence references | Allow/hold/deny with exact binding and decision trace | Only Control Plane can make its scoped runtime decision |
| Governed Execution | Authorized action binding and executable adapter | Effect ID, attempt ID, result and local observation references | Dispatch cannot bypass current action authority |
| Evidence & Accountability | Validated source objects and reconstruction lineage | Replay bundle, governance pack, optionally portable evidence | Neither replay nor ODES authorizes action |

Adapters must declare versions, capability flags, trust origin, failure behavior, supported tenant identity mapping, and loss reports. No implicit transformation of incompatible source generations.

## 5. Proposed state transitions (not an implementation)

```text
PROPOSED
  -> CONTEXT_GATHERING
  -> AWAITING_AUTHORITY
  -> DENIED | HELD | AUTHORIZED
AUTHORIZED
  -> DISPATCH_REQUESTED
  -> DISPATCHED | DISPATCH_UNKNOWN
DISPATCHED
  -> OBSERVATION_PENDING
  -> OBSERVED | OBSERVATION_UNKNOWN
OBSERVED
  -> RECONCILED | VERIFICATION_PENDING
VERIFICATION_PENDING
  -> VERIFIED | VERIFICATION_UNKNOWN
```

This is an **orchestration view**, not a substitute for source-component state machines. Transitions require references to actual component events. No transition from DISPATCH_UNKNOWN to new dispatch without destination reconciliation and effect-ID-safe retry behavior. `VERIFIED` requires a defined independent verifier and supporting evidence; controller-observed local state alone must carry a narrower label. Denials, failures, stops and recovery attempts remain reconstructable, without implied rollback.

## 6. Trust boundaries and failure policy

- **Knowledge:** provenance and epistemic status must survive import; copied evidence is not independent corroboration.
- **Identity:** reject unresolved tenant/org/actor mapping; never trust asserted identity merely because it appears inside an envelope.
- **Authority:** current grants and policy bind actor, tenant, exact action, target, payload, adapter, time, and version as supported by accepted component contracts.
- **Execution:** preserve stable effect ID, distinct attempt IDs and explicit unknown-delivery states.
- **Observation:** an execution ACK is not authoritative destination state; independent verification remains separately declared.
- **Evidence:** preserve unknown/unsupported/redacted fields; transformations must publish version, source IDs and loss/error diagnostics.
- **Incident/stop:** use only the qualified local stop pathway; no fleet or remote quiescence implication.
- **Network/credential:** default disabled until each integration has least-privilege credentials, boundary checks and a reviewed profile.

On identity, grant, adapter/version, policy or critical-evidence mismatch: **hold/deny before effect**. On uncertain effect delivery: **record unresolved and reconcile**, not blind retry.

## 7. ISS external interface reservation

Source: private `TurwinAI/COGNOUS-client`, described by its own README and architecture. Current placeholder: [integrations/iss](../integrations/iss/README.md).

- `enabled: false` until a separately authorized adapter and security review.
- Proposed interaction: governed cognition request/response; structured **proposal** output; optional read-back of ISS correlation/evidence references.
- No inference that an ISS readiness verdict, proof, lineage hash or signed object grants enterprise effect authority or establishes independent destination verification.
- Tenant/workspace credentials, transport version, payload/correlation mapping, classification, retention, and redaction require explicit contracts and tests.
- Never vendor private ISS implementation or confidential AoM/IGPG algorithms into public runtime components.
- ISS availability failure may affect cognitive proposals but cannot relax Action Governance.

## 8. Compatibility and ownership ledger

| Layer | Contract owner | Source for accepted revision | V0 state |
|---|---|---|---|
| Reference release | cognous-open-control-stack hub | PR #63 and selected profile record | Separate release authority |
| Knowledge/provenance | Evidence Registry / Evidence Attestation owners | To be pinned by O2 | No accepted orchestrator adapter |
| Institutional governance | Cognous Institutional Governance owner and adopting institution | To be pinned by O2 | No accepted authority integration |
| Action governance | Manifest / Control Plane owners | Accepted hub C1–C8 pins | Existing bounded path only |
| Governed execution | Cognous Execution Runtime owner | Accepted hub C1–C8 pins | Existing bounded path only |
| Evidence | Replay / Evidence Pack; ODES owner | Accepted hub C8 pins; optional ODES separately | Replay/Evidence bounded path only |
| ISS | TurwinAI/COGNOUS-client owner | Private repo, pending API version | Placeholder disabled |

The orchestrator must build a machine-checked compatibility manifest only after owners approve exact revisions. Never substitute branch HEAD for an immutable accepted pin.

## 9. Acceptance gates for V0 implementation

**G0 — Contract review:** domain owners acknowledge source interfaces and authority separation; exact versions recorded; freeze scope and migration policy.

**G1 — Pure contract validation:** positive and negative envelope/identifier/tenant/version tests; missing/unknown/redacted states preserved; no fabricated evidence.

**G2 — Source adapter qualification:** actual producer bytes, import loss accounting, forged/mismatched tenant and substituted payload/adapter rejection.

**G3 — Single vertical workflow:** real bounded authorizing decision and local effect; positive/negative cases; destination-state assertion separate from ACK; source-derived Replay/Evidence and artifact hashes.

**G4 — Recovery:** lost ACK, unknown delivery, restart, duplicate attempt prevention, denial, revocation and stop limitations recorded with actual results.

**G5 — Institutional review:** exact SHA, commands, CI run IDs, unexecuted cases, exclusions, reviewer identity, and explicit release decision. A PR merge never silently activates production authority.

ISS and ODES are independently gated optional adapters. A missing ISS service, live OpenShell gateway or optional ODES verifier cannot block the already-qualified narrow core unless a later scope decision explicitly changes that requirement.

## 10. Development tasks

- **O1**: review and ratify (or amend) this draft with owners.
- **O2**: produce source-component exact revision/contract crosswalk with accepted links and qualified claims.
- **O3**: author machine-readable envelope schema with negative vectors *after* O1.
- **O4**: define and qualify one knowledge → institutional context → authorization → effect → replay/evidence integration; do not skip G1–G3.
- **O5**: evaluate the disabled ISS adapter separately, first by API contract and security mapping, without exporting private code.
- **O6**: optional ODES export profile and independent consumer conformance.

Governance tracking: [Engineering Dashboard #1](https://github.com/cogno-us/cognous-stack-orchestrator/issues/1). New implementation tasks must be tracked in existing issues or small issue-scoped PRs; no broad unbounded worker mandate.

## 11. Decision register

- Five domains: **proposed product architecture**.
- Component repository consolidation: **not approved**.
- Four-stage bounded V1: **independent qualified reference**, release authorization follows separate hub records.
- C1–C8 amendment: **none**.
- ISS integration: **disabled placeholder**.
- Production deployment: **not authorized**.

## 12. Field-level reconciliation checkpoint (2026-10-09)

The [source-derived field mapping review](field-mapping-review-v0.md) records exact inspected attestation, Authority Context and Governed Exchange fields, error boundaries and minimum negative vectors. **It is not a ratified contract.**

**Important interface clarifications:**
- The proposed orchestrator envelope in section 3 is a **cross-domain reference carrier**, not a replacement for the existing Governed Exchange transport envelope or the Control Plane decision schema.
- Governed message `message_id` and delivery `transport_attempt_id` remain distinct from source-owned `effect_id` and `executor_attempt_id`.
- The single illustrative `verification_status` in section 3 is **not authoritative as a unified verification state**; future schema work must separately report issuer-signature verification, exact-content binding, current authority, observed effect and any genuine independent verification. Do not implement that example as-is.
- Authority Context `interface_status=proposed_pending_governor_review` is not an approved active grant. Actual institutional adoption and authenticated authority resolution remain prerequisites.
- `cognous-evidence-registry/schema/claim.schema.json` remains a historical schema and is not established as the authoritative local-chain producer format. Its mapping is held pending exact protocol/event/indexer inspection.

The G1 schema may only be proposed after these distinctions and the listed owner-owned source fields are reviewed and accepted. No C1–C8 amendment has been made.

## 13. Evidence Registry event contract clarification (2026-10-09)

The [authoritative local-chain mapping](evidence-registry-chain-mapping-v0.md) now identifies Solidity `Registered`, `EvidenceSubmitted`, `LifecycleChanged` events and the `reconstruct.mjs` log-indexer output at observed source head `2904a0694f3d0ecea9dbcfc72ddb2544de533b15`.

Proposed V0 adapters must bind deployment domain and block provenance, preserve provisional/reorganization uncertainty and commit exact content bytes separately from evidence-submission assertions. A nonzero statement commitment is not an authenticated attestation; a wallet author is not an institutional grantor; a lifecycle value is not truth status. The legacy `schema/claim.schema.json` must not be used as a substitute event format. **Owner acceptance and machine-readable schema validation remain pending.**
