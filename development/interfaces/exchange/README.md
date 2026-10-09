# O4c-D exchange reference handoff

Status: **candidate, read-only compatibility mapping** for issue #13. This directory does not implement message delivery, dispatch an effect, issue authority, verify an external effect, or modify C1-C8.

## Inspected source

- Repository: `cogno-us/cognous-governed-exchange`
- Inspected revision: `a1cbc7b28f702283b0e4f3192bb43e4a9e618ebf`
- Contract/profile: `experiments/governed_message_transport/profile.md`
- Implementation: `experiments/governed_message_transport/transport.py`, specifically `LocalDurableTransport.evidence()` and its transport/recipient stores
- Upstream negative evidence: `tests/test_governed_message_transport.py`

The upstream profile explicitly separates stable governed `message_id`, per-delivery `delivery_attempt_id`, acknowledgement identity, recipient-provided `decision_id`, `effect_id`, and `executor_attempt_id`. It also states that durable receipt is not institutional authorization, execution, successful effect, destination observation, or independent verification.

## Interface

`reference_handoff.py::map_exchange_evidence()` accepts an already-produced `LocalDurableTransport.evidence()` object and returns namespace-tagged references only. Missing producer references are `unknown`; malformed optional producer references are `invalid`. The mapper does not fetch, retry, route, acknowledge, assess, authorize, execute, reconcile, or verify anything.

Receipt and authorization remain distinct:

- `DURABLE_RECEIPT` -> `receipt_only`
- `DURABLE_RECEIPT_UNRESOLVED` -> `receipt_unresolved`
- `TERMINAL_REJECTION` -> `transport_rejection_only`
- every acknowledgement -> authorization/effect/independent verification `not_established`
- every producer decision/effect/executor attempt identifier -> `reported_reference` only
- source authenticity, dispatch authority, effect occurrence, and effect verification -> `not_established`

A refusal or rejection can therefore be referenced without becoming an authorization decision. A lost acknowledgement can remain pending/unresolved without being interpreted as a failed or successful effect. Duplicate delivery attempts retain their distinct transport attempt identities and retry lineage while sharing the governed message identity.

## Tests

Run:

```text
python -m unittest discover -s tests/contracts/exchange -p 'test_*.py' -v
```

Negative vectors cover lost acknowledgement, duplicate-suppressed retry lineage, unknown effect/executor references, transport rejection/refusal, unresolved durable receipt, malformed producer references, and unsupported source revision.

## Residual limits

This handoff trusts the supplied evidence object only as input data. It does not authenticate the Exchange repository at runtime, cryptographically authenticate transport identities, validate Control Plane decisions, prove effect occurrence, or supply institutional Authority Context. Those remain separate accepted interfaces/gates.
