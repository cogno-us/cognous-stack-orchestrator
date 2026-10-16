# O5-C-B — synthetic refund runtime qualification

Issue: `cogno-us/cognous-stack-orchestrator#39`

Accepted orchestrator base: `0aaaa11d1795e4e0cbf081826e9e1d1b3d5ca850`

Accepted Execution Runtime contract pin: `cogno-us/cognous-execution-runtime@da9f52900ee2596dab087ec6c249ba84915d2b13`.

## Scope

This directory qualifies an **orchestrator-local synthetic adapter** for the refund scenario. It mirrors only the accepted runtime boundaries needed by the issue:

- a durable attempt key scoped to tenant, request, order and payment references;
- refusal when an authenticated Control Plane permit fixture is absent, unauthenticated, non-permitting, non-current or mismatched on tenant, request, order, payment, effect ID, amount or currency;
- SQLite `BEGIN IMMEDIATE` linearization for duplicate suppression, cancellation and authority-withdrawal ordering;
- stable effect identity with distinct attempt identity;
- durable duplicate/retry suppression after a simulated effect is committed;
- explicit separation of simulated effect, processor call and settlement observation.

The adapter does **not** import, vendor or modify the Execution Runtime. It does not define a new C1-C8 contract and does not issue institutional authority.

## Race semantics

Cancellation and authority withdrawal participate in the same local SQLite serialization boundary as the synthetic effect ledger.

- If cancellation or authority withdrawal commits first, a later execution attempt refuses and creates no effect row.
- If the simulated effect commits first, later cancellation/withdrawal is recorded but does not rewrite history or claim rollback.
- A duplicate request after commit is suppressed and cannot create another effect row. The suppression row records the persisted effect and decision identity, not caller-substituted values; a duplicate carrying an invalid permit is refused without an attempt row.
- Refusal attempts are durable audit rows but are not processor dispatches.

These are same-host synthetic ordering tests. They do not establish distributed transactionality, remote revocation propagation or external exactly-once behavior.

## Permit fixture boundary

`fixture_control_plane_permit` is test data only. The boolean `authenticated_control_plane_permit` represents the premise that a separate accepted Control Plane adapter authenticated its output. O5-C-B does not perform that authentication and does not infer authority from the fixture. A real cross-component integration remains a Governor merge/qualification task after O5-C-A is reviewed.

## Limitations

No payment processor SDK or endpoint is called. No credentials, real customer data, real merchant grant, institutional permission, ISS mechanism, funds movement, processor acknowledgement or settlement observation is present. `simulated_applied` means only that one local SQLite row was committed. This work does not satisfy operational trust issue #30 or Governor integration issue #14.
