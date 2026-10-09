# O5-C-C refund replay qualification

Scope: synthetic, deterministic, offline reconstruction of refund-request trajectories for issue #40.

## Accepted starting base and source pins

- Orchestrator base: `0aaaa11d1795e4e0cbf081826e9e1d1b3d5ca850`
- Replay: `cogno-us/cognous-replay-bundle@2069a0ba1398812c3a8669331a7d8b87c80c4a48`
- Evidence Pack: `cogno-us/cognous-governance-evidence-pack@87293cfcbe8dfa2368d5bf77019945ba8ef1ae71`
- Replay reconstruction contract target: `ReconstructionBundle/0.2.0`
- Evidence Pack schema target: `0.2.0`

The Replay source contract states that reconstruction does not renew authorization, re-run models, execute effects, independently observe a destination, or independently verify an effect. This fixture preserves those distinctions.

## Qualified synthetic trajectories

The fixture and tests cover:

- intake with an attributable producer claim;
- policy screening;
- hold;
- transport receipt, explicitly receipt-only;
- approval withdrawal;
- denial;
- duplicate suppression without new effect creation;
- simulated runtime refusal with effect/attempt references;
- simulated accepted execution intent with effect/attempt references;
- settlement explicitly recorded as `not_observed`.

Issuer claims, transport identifiers, policy decisions, and simulated effect/attempt identifiers remain separate namespaces. No field promotion is permitted between them.

## Evidence boundaries

The generated reconstruction is source-derived review evidence. The companion evidence projection is intentionally not represented as an upstream Evidence Pack validation result.

The following are **not established**:

- institutional authorization or grant issuance;
- payment dispatch;
- payment-processor acknowledgement;
- destination observation;
- settlement;
- independent effect verification;
- compliance or deployment approval.

A transport receipt cannot assert an effect. A simulated execution intent cannot assert settlement. Any positive settlement claim is rejected by this bounded fixture because no independently authenticated destination evidence exists in scope.

## Upstream compatibility

`reconstruct.py` contains a best-effort compatibility probe:

- if the accepted Replay package is installed, the generated object is validated through its `ReconstructionBundle` Pydantic model;
- if it is not installed, status is reported as `not_executed_dependency_unavailable`;
- Evidence Pack import is not manufactured because the accepted importer requires a compatible manifest plus reconstruction artifact and its package is not installed by the orchestrator's scoped O5 CI.

Thus local CI proves the deterministic fixture and negative boundaries only. It does not claim upstream package execution when that dependency is absent.

## Tests

Scoped repository CI discovers:

```text
python -m unittest discover -s tests/scenarios/customer_refunds -p 'test_*.py' -v
```

Negative cases include:

- transport receipt attempting to assert an effect;
- positive settlement claim without destination evidence;
- unsimulated effect reference;
- cross-tenant trajectory event;
- reordered/non-deterministic sequence.

This work changes only issue-owned replay paths and does not modify C1-C8, other workers' files, authority semantics, or any live payment integration.
