# O5-D-C exact-pinned Replay and Evidence Pack qualification

This directory is scoped to orchestrator issue #49. It qualifies synthetic customer-refund evidence against **actual source checkouts** of:

- `cogno-us/cognous-replay-bundle@2069a0ba1398812c3a8669331a7d8b87c80c4a48`
- `cogno-us/cognous-governance-evidence-pack@87293cfcbe8dfa2368d5bf77019945ba8ef1ae71`

`qualification.py` refuses to run when either checkout is absent or its Git HEAD differs from the accepted pin. The Replay `ReconstructionBundle` parser and Evidence Pack `EvidencePack` parser plus `validate_evidence_pack` are imported from those source trees. Orchestrator-local fixtures are therefore not sufficient for a passing qualification.

## Boundary under test

The bounded trajectories retain distinct namespaces and meanings for transport receipt, historical authorization state, simulated execution/effect references, duplicate suppression, and settlement observation. A transport receipt is not authorization, an execution reference is not settlement, and schema/validator success is not independent effect verification. Positive settlement evidence is intentionally rejected because this task has no independently authenticated payment-destination observer.

No payment processor, credentials, institutional grants, or real funds are used. All execution references are explicitly synthetic (`simulation=true`).

## CI

The scoped workflow checks out both upstream repositories at the exact accepted SHAs and runs only `tests/scenarios/customer_refunds/live_components/evidence/`. If repository access is unavailable, checkout fails and the qualification fails closed rather than silently falling back to local fixtures.

## Limitations

This task proves compatibility with the exact pinned Replay reconstruction model and Evidence Pack model/validator for the bounded synthetic records. It does **not** claim current authorization, payment settlement, destination-state observation, independent verification, production credential isolation, or end-to-end operational deployment. It also does not exercise the Evidence Pack manifest-to-reconstruction transformer because the refund fixture is not represented as a retained source under that transformer's historical Control Plane/Manifest producer profile; adding such a profile would be a separate source-contract change outside issue #49.
