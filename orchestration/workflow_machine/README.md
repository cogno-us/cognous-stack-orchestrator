# Workflow state machine (step 3.2, part A: pure logic)

Candidate, non-authorizing. Release and production remain on HOLD. This package is the pure state machine that a durable store (separate package, not imported here) will later drive. It has no I/O, clock, randomness, credentials, network, subprocess or database, and imports no other orchestration package (in particular nothing from step 3.4 or from the workflow store). Standard library only.

Design inputs (hub `docs/program-v0.2/`): `s03/workflow-state-reconciliation.md`, `s03/identity-and-lifecycle.md` (sections 4 to 6), `s03/minimum-profile-and-coverage.md` (A4), `s02/ownership-and-sequencing.md`, `s02/contracts/1.2-authority-and-separation.md` (sections 2 and 3).

## Contents

- `vocabulary.py`: closed statuses, closed event types and their exact members, closed refusal codes, bounds, and the explicit transition table (`TRANSITIONS`) with the refusal code of every other cell (`REFUSALS`).
- `machine.py`: `apply_event(state, event)`, `replay(events)`, `next_actions(state)`, `describe(state)`, and a `Fleet` (`apply_fleet`, `replay_fleet`) that enforces the concurrent-workflow bound.

## Statuses and table

Statuses are exactly the reserved list from `orchestration/state-transitions/README.md`: `proposed`, `awaiting_authority`, `authorized`, `dispatched`, `observed`, `unresolved`, `reconciled`, plus the pre-state `initial` (no event seen; not a reported status). `observed` and `reconciled` are terminal.

| From | Event | To |
|---|---|---|
| initial | propose | proposed |
| proposed | request_authority | awaiting_authority |
| awaiting_authority | record_authorized | authorized |
| authorized | dispatch | dispatched |
| dispatched | record_observation | observed |
| dispatched | record_outcome_unknown | unresolved |
| dispatched | crash_recovered | unresolved |
| unresolved | reconcile | reconciled |
| unresolved | reconcile_inconclusive | unresolved |

Every other (state, event) cell is refused. `dispatch` from `initial`, `proposed` or `awaiting_authority` is `authority_required`; `dispatch` from `dispatched`, `observed`, `unresolved` or `reconciled` is `blind_retry_refused`; all other illegal cells are `illegal_transition`.

Reading of the names, as the s03 reconciliation requires: `authorized`, `observed` and `reconciled` are workflow records that a reference exists (`decision_ref`, `observation_ref`); the workflow reads those records and never sets a decision result, attempt status, observation or effect verification. `dispatched` is a write-ahead record that the hand-off to the gate is being made (the store must persist it before handing off); it does not mean an attempt exists or that the effect happened.

## Events

Closed set of nine (`EVENT_TYPES`). An event has exactly the members `type`, `workflow_id`, `seq`, `at` and, per type, one reference member (`proposal_ref`, `decision_ref`, `dispatch_ref`, `observation_ref`; see `EVENT_MEMBERS`). References are opaque non-empty text; the machine never dereferences or judges them. `at` is caller-supplied opaque text and never decides anything. `seq` must equal the number of events already applied plus one.

## Refusal codes (closed)

`schema_invalid`, `unknown_event_type`, `unknown_member`, `forbidden_member`, `workflow_mismatch`, `sequence_mismatch`, `authority_required`, `blind_retry_refused`, `illegal_transition`, `bound_events_exceeded`, `bound_workflows_exceeded`. A refusal raises `Refusal` with a `.code`; states are immutable, so the input state is unchanged. Check order: shape, workflow, sequence, event bound, transition.

## Enforced invariants

1. Not an alternate Control Plane. No event or state carries a verdict, grant, permission, pin or authority member. A member name containing such a token (`FORBIDDEN_MEMBER_TOKENS`, for example `verdict`, `grant_id`, `permission`, `pin`, `authority_context`, `approved`, `result`, `retry_count`) is refused as `forbidden_member`; any other undeclared member is `unknown_member`. Authorization enters only as a reference to a Control Plane decision.
2. No blind retry. A dispatch is legal only from `authorized`, once. A dispatch whose outcome is unknown moves only to `unresolved` and from there only to `reconciled` by an explicit `reconcile` event (or stays `unresolved` on `reconcile_inconclusive`). There is no path from `unresolved` to `dispatched`.
3. Truthful unknown. `describe(state)["effect_outcome"]` is `none`, `unknown`, `observation_referenced` or `reconciliation_referenced`; it is never success, failure or absence. `dispatched` and `unresolved` are `unknown`.
4. Reconcile-only continuation. After a crash the only legal event for a `dispatched` workflow is `crash_recovered` (to `unresolved`, with `record_observation` and `record_outcome_unknown` also legal when evidence arrives); nothing re-dispatches.
5. Determinism. `apply_event`, `replay` and `next_actions` are pure functions of their arguments.
6. Bounded lifecycle. `MAX_EVENTS_PER_WORKFLOW = 16` (further events refused; `next_actions` is empty) and `MAX_CONCURRENT_WORKFLOWS = 64` non-terminal workflows (a `propose` beyond it is refused).
7. Illegal transitions are refused with state unchanged.

## Not done here

Durable storage, restart handling beyond the pure event, any reading of Control Plane, Runtime or observation records, and the 3.4 handoff are separate packages. A Control Plane `hold` or `deny` result is its own record and has no event: the workflow simply stays `awaiting_authority` (no cancel, fail or deny state exists in the reserved list; whether to add coordination states such as `failed` or `cancelled` from the s03 12-state proposal is an open question for review).

Not independently qualified. Tests in `tests/integration/workflow_machine/` are developer tests. Run: `python -m pytest -q tests/integration/workflow_machine`.
