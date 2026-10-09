# V0 Field-Level Source Mapping — Review Candidate

**Status:** SOURCE-SCHEMA INSPECTED / MAPPING PROPOSED / NOT RATIFIED  
**Date:** 2026-10-09  
**Parent:** [V0 Integration Contract](integration-contract-v0.md)  
**Scope:** Knowledge/provenance, institutional requirements and governed-message transport. No orchestrator runtime code.

## 1. Exact inspected surfaces

| Domain | Source at observed main | Inspected source | Important qualification |
|---|---|---|---|
| Evidence Attestation | `cogno-us/cognous-evidence-attestation@790cbdad0ccb3f00a2fb6abca39b50ce8c588d43` | `docs/attestation-v1.schema.json`, `docs/verification-v1.schema.json` | v1 signature verification is **issuer_signature_only**, not factual truth |
| Institutional Governance | `cogno-us/cognous-institutional-governance@1386fd236f13896029e5ab47ba5b9c3127509c3d` | `process/implementation/public-stack-v0.1/authority-context.schema.json` | `interface_status=proposed_pending_governor_review` in schema; not operative grants by itself |
| Governed Exchange | `cogno-us/cognous-governed-exchange@a1cbc7b28f702283b0e4f3192bb43e4a9e618ebf` | `experiments/governed_message_transport/profile.md` and `mapping.md` | Experimental local SQLite transport; receipt != effect |
| Evidence Registry | `cogno-us/cognous-evidence-registry@2904a0694f3d0ecea9dbcfc72ddb2544de533b15` | `schema/claim.schema.json` | This is a legacy schema carrying old `the-index` metadata; **not established as authoritative local-chain producer schema** |

No runtime tests were executed for these source inspections.

## 2. Evidence Attestation mapping

| Source fields | Orchestrator treatment | Reject/unknown condition |
|---|---|---|
| `statement.attestation_id`, `issuer`, `key_id`, `subject`, `audience` | Preserve as source-owned identifiers and scope references | Never equate `issuer` to tenant or actor without resolver |
| `statement.content_digest` | Preserve `sha256:<64 lowercase hex>` and require consumer recomputation over exact relied-on bytes | Digest mismatch or unavailable bytes means no independently bound content |
| `issued_at`, `not_before`, `expires_at` | Preserve integer time fields; evaluate using trusted time | Unsupported temporal semantics or expiry => no accepted reliance |
| `verification.outcome` | `verified` or `rejected` as source result | `verified` does not imply truth or permission |
| `verification.assurance` | Only `issuer_signature_only` or `none` | No promotion to institutional authorization |
| `trust_snapshot`, `statement_digest`, `key_status_at`, `evaluated_at` | Preserve provenance of verifier evaluation and snapshot | Missing trust snapshot cannot become an assumed trusted issuer |

The verification result schema requires `outcome`, `reason`, `evaluated_at`, `key_status_at`, and `assurance`. The signed statement requires 12 fields plus the signature envelope. Orchestrator does not reissue these claims or sign on behalf of an upstream authority.

## 3. Institutional Governance mapping

| Source field or nested path | Intended downstream mapping | Boundary |
|---|---|---|
| `schema_version=0.1.0`; `interface_status=proposed_pending_governor_review` | Carry source profile identity/status, not silently call it an active grant | Proposed schema is not institutional adoption |
| `context_id` | Context reference | No automatic grant issuance |
| `institution.institution_id`, `authority_domain`, `authority_basis_ref`, `authority_mode` | Institutional identity/basis metadata | Validate with adopting institution/resolver |
| `principal`, `acting_identity` | Proposed identity references | Must be bound independently to actual tenant/actor |
| `accountable_human_role.role_id`, `human_principal`, `mandate_ref` | Accountability and review route | Does not establish authentication |
| `requirement.governing_sources[].standing` | Distinguish `design_proposal`, `local_policy`, `adopted_rule` | Never upgrade a design proposal to adopted rule |
| `requirement.permissions[].action/targets/data_scopes/max_amount/unit/max_effects` | Candidate authority requirements | Only actual current grant and Control Plane can allow effect |
| `requirement.approvals[]`, `requirement.evidence[]` | Required review and evidence obligations | Stale required evidence => hold effect |

## 4. Governed Exchange mapping

| Source field | Proposed orchestrator interpretation | Forbidden inference |
|---|---|---|
| `message_id`, `content_commitment` | Stable governed message identity and immutable content commitment | Not proof of sender authentication |
| `delivery_attempt_id` / `transport_attempt_id` | Unique message transport attempt namespace | Not executor attempt |
| `acknowledgement_id` / `DURABLE_RECEIPT` | Durable local inbox evidence | Not authorization or execution |
| `producer_refs.decision_id` | Source-produced Control Plane decision ref | Missing ref stays absent |
| `producer_refs.effect_id` | Source-produced effect ref | No manufactured effect from receipt |
| `producer_refs.executor_attempt_id` | Separate executor attempt namespace | Not transport retry ID |
| `PENDING_RETRY`, `UNRESOLVED`, `TERMINAL_REJECTED` | Preserve transport lifecycle | Do not infer substantive policy denial |
| `PROPOSE`, `REQUEST` | Eligible for recipient governance assessment | Eligibility alone never confers grant |
| `REPORT`, `REFUSE`, `NOT_UNDERSTOOD` | Informational; no direct effect | Never route to execution |

The existing profile specifies a local recipient inbox transaction before `DURABLE_RECEIPT`, and separated sender/recipient durable transactions. It does not provide distributed exactly-once delivery.

## 5. Evidence Registry mapping — source mapping available; owner approval pending

The inspected `schema/claim.schema.json` contains `id`, `subject`, `predicate`, `object`, `contributor_id`, `timestamp`, optional `evidence_refs`, `justification`, `status`, and legacy `provenance.attestation_id`. It still describes a historic Index claim format. The current README designates a **local blockchain claim/evidence-commitment contract and indexer** as the bounded authoritative path. Therefore **do not build an orchestrator adapter against this legacy JSON schema**. The authoritative current-source mapping is now documented in [Evidence Registry chain mapping](evidence-registry-chain-mapping-v0.md): `Registered`, `EvidenceSubmitted`, `LifecycleChanged`, the read-only log indexer and provisional/reorganization semantics. Owner approval and typed adapter schema are still pending.

## 6. Required corrections to V0 contract before acceptance

1. Define **orchestrator envelope as reference carrier**, not a new universal transport; Governed Exchange retains governed-message transport identity and delivery semantics.
2. Distinguish `workflow_id` and `correlation_id` (orchestrator-owned) from `message_id` (GAX-owned), `delivery_attempt_id` (transport), `effect_id` and `executor_attempt_id` (runtime).
3. Replace the single ambiguous `verification_status` with typed **issuer signature**, **content binding**, **current institutional authority**, **effect observation**, and **independent verification** statuses; do not guess source equivalents.
4. No automatic acceptance of `Authority Context` when `interface_status` is proposed; require adopting institution and authenticated resolver.
5. Reject provenance upgrades from a legacy Index schema or copied verification record.
6. Separate original producer bytes from derived projections and record source schema, revision, transformation and loss diagnostics.
7. Document a concrete G1 test battery: forged or expired attestation, substituted digest, tenant/actor mismatch, proposed rule mistaken for adopted, durable receipt mistaken for effect, transport retry mistaken for executor retry, absent source effect, unknown delivery and unsupported schema generation.

## 7. Decision / next gate

**Decision:** Accept as a *review candidate* field map, not an implemented interoperable adapter or C1-C8 amendment. Cross-domain integration remains **NOT QUALIFIED**.

**Next:** obtain component-owner field endorsements for the inspected local-chain event/indexer contract and other domains; then revise and ratify CSO-IC-V0 on a reviewable PR. ISS stays disabled and ODES separately optional.
