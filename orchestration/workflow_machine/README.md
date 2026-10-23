# Workflow state machine (step 3.2, part A: pure logic)

Candidate, non-authorizing. Release and production remain on HOLD. This package is the pure state machine that a durable store (separate package, not imported here) will later drive. It has no I/O, clock, randomness, credentials, network, subprocess or database, and imports no other orchestration package (in particular nothing from step 3.4 or from the workflow store). Standard library only (the package imports `re`, `dataclasses`, `types`, `typing`, `__future__` and itself; an ast test enforces this and bans `open`, `__import__`, `eval`, `exec`). Checks are explicit raises, not `assert`, so they hold under `python -O`.

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

Every other (state, event) cell is refused. A legal cell is also refused (`bound_events_exceeded`) when it would leave too few of the 16 event slots to terminate (see Bounds). `dispatch` from `initial`, `proposed` or `awaiting_authority` is `authority_required`; `dispatch` from `dispatched`, `observed`, `unresolved` or `reconciled` is `blind_retry_refused`; all other illegal cells are `illegal_transition`.

Reading of the names: `authorized`, `observed` and `reconciled` only record that a reference string was supplied (`decision_ref`, `observation_ref`). The machine does not read, dereference or check those records and never sets a decision result, attempt status, observation or effect verification. `dispatched` is a write-ahead record that the hand-off to the gate is being made; it does not mean an attempt exists or that the effect happened.

### Divergence from s03 (operator-visible; the choice is for the governor)

`s03/workflow-state-reconciliation.md` is **Proposed, documentation only**; it does not decide anything and does not require this machine's vocabulary. This package follows the 7-name reserved list in `orchestration/state-transitions/README.md` instead, and so differs from s03 as follows:

- s03 proposes 12 workflow states (`proposed`, `validating`, `awaiting_authority`, `ready`, `dispatched`, `reconciling`, `unresolved`, `completed`, `failed`, `cancel_requested`, `cancelled`, `suspended`) and says `authorized`, `observed` and `reconciled`/RECONCILING (as a set status) restate records another component owns: it removes `authorized` and `observed` as workflow states (references to the decision and the observation instead) and replaces `reconciled` with `reconciling`. This machine keeps all three as statuses (`observed` and `reconciled` are its terminal statuses), as pure markers that a reference was supplied.
- Four names are shared with s03: `proposed`, `awaiting_authority`, `dispatched`, `unresolved`.
- s03 states omitted here: `validating`, `ready`, `reconciling`, `completed`, `failed`, `cancel_requested`, `cancelled`, `suspended`. No coordination state is added; whether to add `failed`, `cancelled` or `suspended` is an operator decision.
- The reserved list was taken from `orchestration/state-transitions/README.md` (Orchestrator `a745e131`), which s03 quotes.

## Events

Closed set of nine (`EVENT_TYPES`). An event has exactly the members `type`, `workflow_id`, `seq`, `at` and, per type, one reference member (`proposal_ref`, `decision_ref`, `dispatch_ref`, `observation_ref`; see `EVENT_MEMBERS`). References are opaque non-empty text; the machine never dereferences or judges them. `at` is caller-supplied opaque text, never decides anything, and is not retained in `State` (`State.refs` holds only `(event type, reference)` pairs; keep `at` in the event log). `seq` must equal the number of events already applied plus one.

### What the caller (store, step 3.4) must verify

The machine checks event shape and order only. It does not check that `decision_ref` names a Control Plane decision whose result is a current `authorized`, nor that `observation_ref` names anything. Before submitting `record_authorized` the caller must verify the decision is a current `authorized` result (a `hold`, `deny`, expired or superseded decision must not produce this event). Before submitting `record_observation` the caller must verify the observation is independent evidence that settles the outcome; an observation that is `unknown`, `partial` or absent must be routed to `record_outcome_unknown` (from `dispatched`) or `reconcile_inconclusive` (from `unresolved`), never to `record_observation` or `reconcile`. A caller that skips these checks gets a machine that reports `observed` for a workflow whose outcome is not settled. `describe()` repeats this in its output: `refs_content_checked` is always `False`, and `observation_referenced` / `reconciliation_referenced` mean only that a reference string was recorded.

### Write-ahead is a store requirement

The store must durably persist the `dispatch` event before it hands anything to the gate. The machine cannot detect a missing write-ahead. If the process crashes after the hand-off but before `dispatch` was persisted, the workflow is still `authorized` after restart and a second `dispatch` is legal: that is a blind retry the machine cannot see. If `dispatch` was persisted and the process crashes, the workflow is `dispatched`; restart handling records `crash_recovered` (`dispatched` to `unresolved`), after which only reconciliation is legal.

## Refusal codes (closed)

`schema_invalid`, `unknown_event_type`, `unknown_member`, `forbidden_member`, `workflow_mismatch`, `sequence_mismatch`, `authority_required`, `blind_retry_refused`, `illegal_transition`, `bound_events_exceeded`, `bound_workflows_exceeded`. A refusal raises `Refusal` with a `.code`; states are immutable, so the input state is unchanged. Check order in `apply_event`: shape (the event mapping is copied once and the copy is validated), workflow, sequence, event bound (16 already applied), transition table, reserved final slot. `apply_fleet` runs shape first, then the fleet bound (a `propose` for a new workflow when 64 workflows are non-terminal), then the `apply_event` order above. The shape step refuses in this order: type, forbidden member, unknown member, missing member, member values.

## Enforced invariants

1. Not an alternate Control Plane. The exact per-event member allow-list (`EVENT_MEMBERS`) is the guard: any member not on it is refused, so no event carries a verdict, grant, permission, pin or authority member, and `State` has only four fixed fields. The forbidden-token list (`FORBIDDEN_MEMBER_TOKENS` plus substring families such as `verdict`, `grant`, `permission`, `authoriz`) only chooses the refusal code: a member whose name matches is `forbidden_member`, any other undeclared member is `unknown_member`. Authorization enters only as an opaque reference string. The machine does not check that the reference names a Control Plane decision or that the decision authorizes anything (see the caller duties above).
2. No blind retry. A dispatch is legal only from `authorized`, once. A dispatch whose outcome is unknown moves only to `unresolved` and from there only to `reconciled` by an explicit `reconcile` event (or stays `unresolved` on `reconcile_inconclusive`). There is no path from `unresolved` to `dispatched`.
3. No success or failure claim. `describe(state)["effect_outcome"]` is `none`, `unknown`, `observation_referenced` or `reconciliation_referenced`; it is never success, failure or absence. `dispatched` and `unresolved` are `unknown`. The two `*_referenced` values mean a reference string was recorded and nothing more: whether the observation settled anything is not checked here.
4. Reconcile-only continuation after a persisted `dispatch`. A `dispatched` workflow can only move to `observed`, or to `unresolved` by `record_outcome_unknown` or `crash_recovered`; nothing re-dispatches, and from `unresolved` only `reconcile` or `reconcile_inconclusive` are legal. This holds only if the store persisted `dispatch` before the hand-off (see Write-ahead above); the machine cannot see a missing write-ahead.
5. Determinism. `apply_event`, `replay` and `next_actions` are pure functions of their arguments.
6. Bounded lifecycle, see Bounds below.
7. Illegal transitions are refused with state unchanged.
8. Consistent state. `State` and `Fleet` check themselves on construction (`__post_init__`): status, `event_count` and `refs` must agree with each other (for example `dispatched` needs exactly 4 events and the `propose`, `record_authorized`, `dispatch` references), fleet keys must equal each state's `workflow_id`, and the fleet input is snapshotted. This catches hand-built or corrupted states, not forged history: reference text and `at` cannot be re-derived, and `record_outcome_unknown` versus `crash_recovered` leave no trace in `refs`. Persisted states must still be rebuilt only through `replay`/`replay_fleet`, not deserialized field by field.

## Bounds (operator-visible design choices)

- `MAX_EVENTS_PER_WORKFLOW = 16`. The last event slot is reserved so a workflow never dead-ends at the bound: an event is accepted only if a terminating path still fits afterwards (`EVENTS_TO_TERMINAL` in `vocabulary.py`). In practice `reconcile_inconclusive` can occur at most 10 times (events 6 to 15); at the 16th event it is refused (`bound_events_exceeded`) while `reconcile` is still legal, so an `unresolved` workflow can always reach `reconciled`. At the bound a terminal workflow has `next_actions() == ()`. After the 15th event an `unresolved` workflow's only action is `reconcile`.
- `apply_event`, `next_actions`, `describe` and `apply_fleet` require exactly `type(state) is State` / `type(fleet) is Fleet` (a subclass that skips `__post_init__` is `schema_invalid`). They do not re-validate a state's fields on each call: a state mutated with `object.__setattr__` after construction is not detected by `describe()` or `next_actions()`. Treat states as values built only by `replay` or the constructor.
- `MAX_CONCURRENT_WORKFLOWS = 64` non-terminal workflows (a `propose` for a new workflow beyond it is `bound_workflows_exceeded`).
- A workflow in `awaiting_authority` after a Control Plane `hold` or `deny` never terminates: there is no event for either result, so it stays `awaiting_authority` and consumes one of the 64 Fleet slots until the store acts. Terminal workflows are not removed from `Fleet.states`, so total Fleet size is unbounded; only non-terminal workflows count against the 64. The durable store must therefore handle slot release and archival (for example archiving terminal workflows out of the Fleet, and deciding what to do with held or denied workflows). This is an operator-visible design choice: adding a coordination state (`failed`, `cancelled`, `suspended`) would change it and is an operator decision, not made here.

## Not done here

Durable storage, restart handling beyond the pure event, any reading of Control Plane, Runtime or observation records, and the 3.4 handoff are separate packages. A Control Plane `hold` or `deny` result is its own record and has no event: the workflow simply stays `awaiting_authority` forever (see Bounds; no cancel, fail or deny state exists in the reserved list; whether to add coordination states such as `failed` or `cancelled` from the s03 12-state proposal is an operator decision).

Not independently qualified. Tests in `tests/integration/workflow_machine/` are developer tests. Run: `python -m pytest -q tests/integration/workflow_machine`.
