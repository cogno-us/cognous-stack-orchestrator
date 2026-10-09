# O5-D-B — pinned Execution Runtime refund qualification

Issue: `cogno-us/cognous-stack-orchestrator#48`

This slice qualifies the **actual pinned Execution Runtime source**, not the earlier orchestrator-local refund implementation.

## Pinned sources

- Orchestrator accepted base: `1017a82bf7cdd6b013bb2393d51cc0bfee94e7ff`
- Execution Runtime: `cogno-us/cognous-execution-runtime@da9f52900ee2596dab087ec6c249ba84915d2b13`
- Control Plane support dependency used by the Runtime atomic claim model: `cogno-us/cognous-control-plane@e66e5f163c5d5c112ff345a2f332b4c3893ee183`

CI checks out those revisions into isolated directories and the tests import the Runtime modules directly from that checkout. The tests also assert the checked-out Git HEADs. If either upstream cannot be checked out or imported, qualification fails; there is no orchestrator-local fallback.

## Interfaces exercised

The synthetic refund cases invoke these upstream Runtime surfaces directly:

- `engine.atomic_local_control_plane_executor.AtomicLocalControlPlaneExecutor.execute`
- `engine.local_authority_effect.AtomicAuthorityEffectDestination`
  - `set_grant_status`
  - `set_approval_status`
  - `execute_claim_atomic` through the executor
  - `reconcile_claim`
  - `failure_history`
- `engine.refund_intent.RefundIntentRegistry`
  - `provision`
  - `reserve`
  - `mark_dispatch_started`
  - `export_intent`

The Runtime's own pinned test fixtures are used only to construct its supported synthetic envelope/claim model and stop barrier. They do not replace the Runtime implementation under test.

## Qualification cases

1. Revoked grant refuses before dispatch, leaves the claim unconsumed, writes no effect and retains an `authority_hold` failure record.
2. Withdrawn approval refuses before dispatch and writes no effect.
3. Local cancellation/stop while the Runtime is inside the pre-commit transaction leaves no durable effect or attempt; reconciliation returns `hold` with `retry_eligible=false`.
4. Repeating a consumed claim is denied without a second durable effect or attempt.
5. Lost acknowledgement is reconciled against the original effect and cannot authorize a blind retry.
6. The Runtime refund-intent registry retains one original effect owner and one dispatch claim; a replacement effect cannot take ownership.
7. An `executed` result is asserted only as a durable **local synthetic destination effect**. It is not described as payment settlement or external processor confirmation.

## Security and authority boundary

This qualification uses synthetic IDs and local SQLite state only. It creates no institutional grants, credentials or payment-processor calls. The Control Plane model dependency supplies claim structure/verification code required by the pinned Runtime implementation; the test does not assert that any real institution adopted or issued that authority.

The local process stop case proves only the tested worker/process and SQLite transaction boundary. It does not prove fleet-wide quiescence, remote cancellation, OS sandbox escape resistance, payment-provider cancellation or destination settlement.

## Reproduction

The scoped workflow `.github/workflows/o5-d-b-upstream-runtime.yml` performs the source checkout, exact-SHA verification and test run. Its test command is:

```bash
python -m pytest tests/scenarios/customer_refunds/live_components/runtime/test_actual_runtime.py -q
```

with `PYTHONPATH` pointing only at the pinned Runtime root, Runtime tests directory, and pinned Control Plane `src` directory.
