# O4d-C source-owner interface acceptance matrix

Status: **review candidate only — technical compatibility documented; owner approval not established**.

Issue: #23  
Accepted O4c orchestrator head: `3df758ec5e0a65af28f6f9f3be5c9263458ab83b`

This packet records the exact source revisions and source-owned paths consumed by the accepted O4c implementations. It does not self-ratify any interface. A passing local contract test demonstrates consistency with the pinned O4c implementation only. It is not attributable source-owner approval, institutional adoption, production trust, or permission to execute an effect.

## Acceptance matrix

| Domain | Source owner / pin | Source-owned interface paths | Accepted O4c consumer | Documented compatibility | Owner approval |
|---|---|---|---|---|---|
| Registry | `cogno-us/cognous-evidence-registry@d5e45d275cb301d9684b543e93b05997991d1cf2` | `chain/contracts/IndexProtocol.sol`; `chain/reconstruct.mjs`; `chain/PROTOCOL.md` | `orchestration/adapters/registry/observation.py` | Read-only projection checks deployment identity, event/log identity, commitments, ordering and reorg/provisional semantics. Chain inclusion remains neither truth nor authority. | **Pending attributable Registry-owner review.** |
| Attestation | `cogno-us/cognous-evidence-attestation@5b5077dafde232a7801cb425c4efddcffb468723` | `models/verification.py`; `utils/trust.py`; `utils/verification.py` | `orchestration/adapters/attestation/verifier.py` | Delegates canonicalization/signature/time/key-state verification to the exact pinned upstream implementation and independently binds expected subject/audience/content. `verified` means `issuer_signature_only`. | **Pending attributable Attestation-owner review.** |
| Institutional Governance | `cogno-us/cognous-institutional-governance@1386fd236f13896029e5ab47ba5b9c3127509c3d` | `process/implementation/public-stack-v0.1/authority-context.schema.json`; `process/implementation/public-stack-v0.1/AUTHORITY_CONTEXT.md`; `testing/harness/authority_context.py` | `development/interfaces/institutional/authority_context_mapping.py` | Maps proposed Authority Context 0.1.0 requirements and identity bindings while forcing `authority=not_established` and `effect_disposition=hold_effect`. | **Pending attributable Governance-owner review and adopting-institution approval.** |
| Governed Exchange | `cogno-us/cognous-governed-exchange@a1cbc7b28f702283b0e4f3192bb43e4a9e618ebf` | `experiments/governed_message_transport/profile.md`; `experiments/governed_message_transport/transport.py`; `tests/test_governed_message_transport.py` | `development/interfaces/exchange/reference_handoff.py` | Read-only handoff preserves message, transport-attempt, acknowledgement, decision/effect/executor-reference namespaces. Receipt/reference presence never becomes authorization or verified effect. | **Pending attributable Exchange-owner review.** |

## Exact field mappings and boundaries

### Registry

- `chainId`, `contractAddress`, source revision/path, reconstructor path and runtime-bytecode hash -> trusted deployment identity comparison only.
- `Registered.id/author/content/parent` -> claim identity, author address, content commitment and parent reference.
- `EvidenceSubmitted.id/claim/submitter/content/manifest/statement/relation` -> evidence identity, claim association and commitments; a nonzero statement commitment is not signature verification.
- `LifecycleChanged.id/lifecycle/successor/reason` -> lifecycle reconstruction.
- `blockHash`, `transactionHash`, `blockNumber`, `logIndex` -> observation provenance and ordering.
- `provisional` or `depth:N;not-consensus-finality` -> bounded observation label only; never consensus finality.

### Attestation

- `statement.issuer + key_id` -> lookup in the operator-controlled trust snapshot.
- `subject`, `audience`, `content_digest`, canonical statement bytes/digest -> independently compared consumer bindings.
- `issued_at`, `not_before`, `expires_at`, trust-snapshot validity and key validity/revocation -> evaluated at operator-supplied trusted time.
- upstream `VerificationResult.outcome=verified` + `assurance=issuer_signature_only` -> consumer signature/content-binding success only.
- Any successful signature result -> `authority=not_established`; no institutional grant inference.

### Institutional Governance

- `schema_version=0.1.0` + `interface_status=proposed_pending_governor_review` -> proposed requirements profile identity only.
- `institution.institution_id`, `authority_domain`, `principal`, `acting_identity` -> must match an explicit supplied identity binding; this is consistency, not authentication.
- `requirement.requirement_id`, permissions and required evidence -> requirement references only.
- optional `grant.issuer/requirement_id/grantee/acting_identity` -> claimed grant fields requiring external issuer authentication.
- `institutional_adoption_ref` -> `reference_present_unverified`, never adopted authority.
- even a fully consistent mapping -> `requirements_mapped_hold`, `authority=not_established`, `hold_effect`.

### Governed Exchange

- `message_id` -> `exchange.governed_message`.
- `transport_attempt_id` -> `exchange.transport.delivery_attempt`; distinct from executor attempt identity.
- `acknowledgement_id` -> `exchange.transport.acknowledgement`.
- `DURABLE_RECEIPT` -> `receipt_only`; `DURABLE_RECEIPT_UNRESOLVED` -> `receipt_unresolved`; `TERMINAL_REJECTION` -> `transport_rejection_only`.
- missing producer `decision_id/effect_id/executor_attempt_id` -> `unknown`; malformed optional references -> `invalid`; valid strings -> `reported_reference`.
- every acknowledgement and producer reference -> authorization/effect/independent verification remain `not_established`.

## Negative acceptance examples

The machine-readable sibling file is normative for these contract examples.

1. **Registry unknown:** absent snapshot -> `status=unknown`, observation not accepted; forbidden inference: no chain state, truth, grant or finality.
2. **Registry rejected:** source revision/deployment/log/reorg inconsistency -> failed/rejected observation; forbidden inference: no source authenticity or authority.
3. **Attestation unknown:** missing/invalid trust snapshot, missing trusted time, or absent independent expected binding -> `status=unknown`; forbidden inference: do not fall back to caller claims.
4. **Attestation rejected:** unsupported revision, malformed/signature/key/time/binding mismatch -> `status=rejected`; forbidden inference: no issuer authenticity or authority.
5. **Institutional hold:** adoption reference present and mapping otherwise consistent -> still `authority=not_established`, `hold_effect`; forbidden inference: reference is not adoption or grant.
6. **Institutional rejected:** tenant/actor/institution/principal/acting identity/issuer/required-evidence mismatch -> rejected + hold; forbidden inference: no repair-by-assumption.
7. **Exchange unknown:** missing decision/effect/executor references -> `unknown`; forbidden inference: receipt cannot manufacture them.
8. **Exchange invalid/rejected boundary:** malformed optional producer reference -> `invalid`; unsupported revision/profile -> mapping error; forbidden inference: no authorization/effect from transport success.
9. **Exchange receipt-only:** `DURABLE_RECEIPT` -> receipt only; forbidden inference: not institutional authorization, execution, destination observation or independent verification.

## Ratification state and limitations

- O1 technical ratification #2 remains open.
- Governor gate #14 remains open.
- This worker does not represent any source owner and cannot convert compatibility evidence into owner approval.
- No chain RPC authenticity, production deployment identity, production key custody, institution-approved resolver, cryptographic transport identity, external effect observation, or independent verification is established by this packet.
- No C1-C8 contract is changed; no runtime path is changed; no production credential is used.
- Required next gate: attributable review by each named source owner plus Governor disposition. Only that later evidence may change an owner-approval state.
