# O2 — Evidence Registry authoritative chain mapping

**Date:** 2026-10-09
**Status:** SOURCE-INSPECTED / PROPOSED CONSUMER MAPPING / NOT RATIFIED
**Observed source head:** `cogno-us/cognous-evidence-registry@2904a0694f3d0ecea9dbcfc72ddb2544de533b15`
**Source paths:** `chain/PROTOCOL.md`, `chain/contracts/IndexProtocol.sol`, `chain/reconstruct.mjs`, `chain/README.md`, `chain/VALIDATION.md`.
**Release-boundary warning:** no new test execution. Historical validation is from 2026-10-05 and may not qualify this orchestrator.

## Authority of source surfaces

The **chain contract**, not `schema/claim.schema.json` or the legacy FastAPI service, governs the bounded local blockchain claim lifecycle. `IndexProtocol.sol` provides `Registered`, `EvidenceSubmitted`, and `LifecycleChanged` events. Read-only `reconstruct.mjs` rebuilds a state view from ordered chain logs. The legacy JSON schema describes an earlier, distinct API format and MUST NOT be silently treated as the authoritative producer.

## Event-to-reference contract

| Source event | Event fields as defined in Solidity | Proposed orchestrator mapping | Restrictions |
|---|---|---|---|
| `Registered` | `id`, `author`, `content`, `parent` | claim reference: deployment identity + `id`; author wallet; exact content SHA-256 commitment; parent relationship | Author wallet is not institutional actor identity; registration is not truth |
| `EvidenceSubmitted` | `id`, `claim`, `submitter`, `content`, `manifest`, `statement`, `relation` | evidence commitment and claim association; relation `1` support assertion, `2` challenge assertion; optional statement commitment | `statement=0x00..00` means no statement commitment; nonzero is NOT a verified signature |
| `LifecycleChanged` | `id`, `lifecycle`, `successor`, `reason` | claim lifecycle transition and successor/reason commitments | `Active=1`, `Withdrawn=2`, `Superseded=3`; no supported/refuted truth status |

The Solidity `Lifecycle` enum includes `Absent=0`; `Registered` initializes `Active=1`. The contract has no owner/proxy upgrade or truth-voting surface. Support and contradiction assertions do not automatically change lifecycle.

## Deployment and log identity

A future adapter MUST bind: `chainId`, deployment contract address, contract bytecode hash, compiler/source identity, `POLICY`, `DOMAIN`, target block number/hash and confirmation-depth policy. Event provenance needs block hash, block number, transaction hash, log index and ordering. `POLICY` labels `index-lifecycle/1`; `DOMAIN` incorporates chain ID, deployment address and policy via Keccak-256. No cross-chain/deployment interchangeability.

`reconstruct.mjs` returns:
- `claims` keyed by claim ID (author, content, parent, lifecycle, successor);
- `evidence` keyed by evidence ID (submitter, claim, content, manifest, statement, relation);
- `history` entries with event, ID, block hash/number, transaction hash and log index; lifecycle event entries also carry reason/lifecycle/successor;
- `blockNumber`, `blockHash`, and `finality` (either `provisional` or depth label explicitly stating **not consensus finality**).

The indexer sorts logs by block/transaction/log order and compares end-block hash before and after scanning. It raises on removed logs, unknown events, missing claim history and detected mid-scan reorganization; no assured production finality, dishonest-RPC resistance or public-chain deployment is demonstrated.

## Content and attestation bindings

On-chain `bytes32` SHA-256 commitments refer to **exact external bytes**, not recoverable content. Retrievers must independently acquire bytes and recompute their digest. Unavailable bytes mean unusable content assurance, **not** falsehood or deletion. The proposed off-chain `index-evidence-manifest/1` is metadata guidance, not an accepted chain-enforced JSON schema.

Cognous Evidence Attestation verification remains independent and off-chain, pinned in the historical registry profile to `5b5077dafde232a7801cb425c4efddcffb468723`. An attestation verifier must rely on an independently trusted issuer snapshot, recompute the exact byte digest and compare expected subject, type and audience derived from the chain/policy, never from untrusted claimant assertions. A successful signature result proves **issuer_signature_only**, not truth or grant.

## Required negative G1 vectors

1. Same ID with altered claim content or deployment identity => reject; no alias promotion.
2. Claim event under wrong chainId/address/DOMAIN => reject.
3. `EvidenceSubmitted.statement` nonzero without verified upstream envelope => unverified commitment only.
4. `relation=1` presented as scientific support / institution permission => reject promotion.
5. Claim lifecycle `Withdrawn` presented as deleted, or `Superseded` as verified false => reject.
6. Available chain commitment but missing exact off-chain bytes => explicit `content_unavailable`.
7. Wrong retrieved bytes => `commitment_mismatch`.
8. Mid-scan reorganization / removed log / inconsistent end-block hash => no accepted stable observation.
9. Depth label `depth:N;not-consensus-finality` presented as final consensus proof => reject.
10. Wallet author/submitter mapped directly to tenant actor or grant issuer => hold pending authenticated mapping.
11. Copied evidence from distinct wallets presented as independent corroboration => no automatic independence credit.
12. Legacy `schema/claim.schema.json` passed as authoritative local-chain event => reject unsupported generation.

## Consumer contract proposal

The orchestrator may carry source-owned references and qualified observation status. It MUST NOT mint a truth score, assign independent provenance, infer institutional grants, rewrite chain lifecycle, issue attestation results, or represent local read-only indexer output as independent consensus verification. The exact machine-readable adapter schema remains **pending owner ratification**.

## Gate disposition

**O2 source mapping:** evidence chain, events and reconstruction mapped from current source. **O1 and O3 remain blocked** on owner-approved field mapping and schema semantics; no orchestration code, API adapter, CI test or authority acceptance has been performed.
