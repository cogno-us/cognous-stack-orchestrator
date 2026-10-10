# O6-Q6 optional recovery reconciliation and adapter conformance

Issue [#82](https://github.com/cogno-us/cognous-stack-orchestrator/issues/82). This is a bounded resilience profile, not a release change.

## Source boundary

The test checks out actual accepted Runtime merge `1b0a9e32d010797711004ae612051a277b07912a`, verifies Git HEAD, and imports the existing `engine.revocation_closeout.RevocationCloseoutStore` and `OrderingEvidence`. The new `RecoveryCoordinator` is an **orchestrator-owned intake sidecar** around these actual source methods. It does not alter them, run a provider, create an effect/attempt, or authenticate independent source truth.

The adapter contract declares client-reference search, stable effect-ID dedupe, bounded deadlines, observation coverage, destination watermark and provider-acceptance closure. All must be declared true before any incoming observation is considered. These are **capability declarations only**; no live adapter or independent observation provider is qualified by this profile.

Observations must include original exact effect/attempt identity, adapter identity, effect-bound client reference, ordering and watermark reference, independently sourced observer reference and (for `applied` or `partial`) provider-acceptance reference. Missing/mismatched fields result in HOLD. The caller supplies these references: they are not independently cryptographically authenticated here. `absent` and `unknown` are always unresolved and never authorize retry. `applied` and `partial` close the **same retained original attempt**, with `retry_eligible=False`. Such closure is a record of caller-supplied observation, **not** proof of independently verified settlement.

## Scoped synthetic failure matrix

- Revocation while executing and crash/restart before observation
- Restart persistence of unknown/absent and no retry permission
- Positive applied/partial closeout of original attempt without replacement ID
- Swapped effect, attempt, adapter and client reference; missing observer/watermark/acceptance
- Six adapter capability declarations each forced off (negative mutation controls)
- Conflicting late observer after restart
- Concurrent conflicting observers: only one persisted original-attempt record
- Disabled underlying Runtime closeout writer detected as HOLD
- Overdue count/age and minimized durable metric surface (no payload logging)

## Known limitation

The underlying Runtime `original_attempt_closeouts_v1` table is one-write-per-original-attempt. A persisted `unknown` cannot later be silently replaced by `applied` through this coordinator; conflicting updates HOLD and require a separately reviewed versioned transition contract. This is intentionally safer than permitting unauthorized mutation or automatic retry, but it means Q6 does **not yet** implement full late authoritative resolution of unknown outcomes. Concurrent admission relies on SQLite uniqueness plus fail-closed exception handling, not an external distributed transaction. The overdue metric counts recorded `in_doubt` rows even after a closeout, reflecting the current accepted Runtime store's semantics; do not label it a current unresolved backlog without an additional state model.

The synthetic conformance fixture is not a real adapter certification, operator trust #30 remains open, and no C2/C3, payment settlement, institutional grant issuance or production readiness is claimed. No hub lock, mandatory executor selection or credentials are modified.
