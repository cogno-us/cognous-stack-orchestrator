# V0 Gate Review — Source Interfaces and Authority Boundaries

**Date:** 2026-10-09  
**Disposition:** source discovery verified; integration contract **not ratified**; no source-code changes.

## Primary source checkpoints

| Component | Observed main | Historical hub-selected revision stated by component README | Relevant surface | Gate |
|---|---|---|---|---|
| Cognous Evidence Registry | `2904a0694f3d0ecea9dbcfc72ddb2544de533b15` | `d5e45d275cb301d9684b543e93b05997991d1cf2` | Local-chain claim/evidence commitments, lifecycle events, read-only indexer; off-chain attestation verification | Owner-approved source mapping and commitment/reorg semantics |
| Cognous Evidence Attestation | `790cbdad0ccb3f00a2fb6abca39b50ce8c588d43` | `5b5077dafde232a7801cb425c4efddcffb468723` | Ed25519 v1 issuer signature verification, configured trust snapshot, subject/audience/content digest and time | Trust registry and canonical verifier result mapping |
| Cognous Institutional Governance | `1386fd236f13896029e5ab47ba5b9c3127509c3d` | `fb3d97938969a89e149e8ff8db2756091d1233fc` | Authority Context profile 0.1.0 as requirements; adoption and actual credential/grant issuer external | Adopted institutional authority resolver required |
| Cognous Governed Exchange | `a1cbc7b28f702283b0e4f3192bb43e4a9e618ebf` | `9984d9011568ccdf3d562fa9760ad41368947b34` | GAX recipient assessment, local durable transport, retained Replay/ODES/IMX references, redelivery/recovery | Preserve exchange/acceptance/action distinctions; candidate optional transport adapter |

These are branch and README inspections, **not** executed verification of implementation internals or compatibility. Selected revisions reported by README belong to the existing hub integration choice and must not be silently reselected for this orchestrator.

## Architectural conclusions

1. The Index/BitRep historic concepts now map to **Cognous Evidence Registry** and **Cognous Evidence Attestation**. Their paired selected local reference already documents separate chain inclusion, signature checking and factual interpretation. None authorizes effects.
2. **Cognous Institutional Governance** is a framework for proposed policies and Authority Context requirements, not a self-authenticating grant service. The actual adopting institution and runtime resolver must be identified for a practical integration.
3. **Cognous Governed Exchange** is relevant to orchestration: it handles bounded message assessment, durable transport and recipient outcomes. It should be *adapted or reused* rather than duplicated with a second independently invented transport in the orchestrator.
4. The **orchestrator** should own workflow routing, dependency pins, correlated lifecycle tracking, and cross-domain loss accounting only. It must not create a second action gate or declare transport receipt to be execution.
5. The selected bounded four-stage W7 integration evidence remains a separate scope and authority. Five-domain integration is not yet qualified.

## V0 contract review findings

- **Accept as conceptual proposals:** five domains; separate provenance/authority/execution/observation/verification; explicit unknown results; ISS disabled.
- **Requires tightening before ratification:** canonical envelope ownership, exact schemas and producer bytes, component versions, subject/tenant mapping, trusted time, provenance admission and redaction rules, handling of chain reorganization/provisional state, exchange retry identity, source-error propagation.
- **Reuse rather than rebuild:** Governed Exchange local transport/recipient semantics; existing Runtime effect/attempt/reconciliation; Replay/Evidence consumer transformation.
- **Security/authority hold:** no real institution-approved grant issuer or verified cross-domain tenant mapping has been identified here; no runnable five-domain authorization claim.

## Next bounded issues

**O2 completion:** owner-confirm schema paths and stable interfaces against the recorded immutable commits, capturing precise fields and negative vectors (no runtime code changes).

**O1 review:** narrow the transport envelope to references and define an explicit versioned mapping from the existing GAX/Runtime/Replay schemas, with no independent authorization state machine.

**O3 preparation:** only after owner signoff, create G1 machine-readable schema and negative tests on an isolated PR. Do not activate ISS or ODES.

No additional contracts are accepted by this review.
