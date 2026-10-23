# Workflow state machine (step 3.2, part A: pure logic)

Candidate, non-authorizing. Release and production remain on HOLD. Step 3.2-A amended this machine (coordination states, completion class, slot classes, release); the amendment follows [AMENDMENT-PROPOSAL-Q1-coordination-states.md](AMENDMENT-PROPOSAL-Q1-coordination-states.md), which stays as the historical proposal (its deviations are listed under "Amendment 3.2-A" below). No independent review or qualification has taken place. This package is the pure state machine that a durable store (separate package, not imported here) will later drive. It has no I/O, clock, randomness, credentials, network, subprocess or database, and imports no other orchestration package (in particular nothing from step 3.4 or from the workflow store). Standard library only (the package imports `re`, `dataclasses`, `types`, `typing`, `__future__` and itself; an ast test enforces this and bans `open`, `__import__`, `eval`, `exec`). Checks are explicit raises, not `assert`, so they hold under `python -O`.

Design inputs (hub `docs/program-v0.2/`): `s03/workflow-state-reconciliation.md`, `s03/identity-and-lifecycle.md` (sections 4 to 6), `s03/minimum-profile-and-coverage.md` (A4), `s02/ownership-and-sequencing.md`, `s02/contracts/1.2-authority-and-separation.md` (sections 2 and 3).

## Contents

- `vocabulary.py`: closed statuses, closed event types and their exact members, closed refusal codes, bounds, and the explicit transition table (`TRANSITIONS`) with the refusal code of every other cell (`REFUSALS`).
- `machine.py`: `apply_event(state, event)`, `replay(events)`, `next_actions(state)`, `describe(state)`, and a `Fleet` (`apply_fleet`, `replay_fleet`, `release_terminal`, `restart_recovery_needed`) with separate execution-slot and waiting-record bounds.

## Amendment 3.2-A (what changed; read this first)

Architect decisions Q1 and Q5 (Q1-Q17 disposition) authorize this change in the unlocked Orchestrator only. Everything here is **coordination**: no new status or event says that an effect failed, was reversed, was compensated or was verified.

| Status | Says | Does not say |
|---|---|---|
| `suspended` (non-terminal) | the coordinator paused a workflow that had not been dispatched; it keeps its record and stays a waiting record | that it ended, that its authorization is still current, or that anything was cancelled. Suspension is not termination |
| `failed` (terminal) | orchestration could not continue before any dispatch was recorded | that an effect failed (`effect_outcome` stays `none`) |
| `cancelled` (terminal) | a caller asked a workflow with no recorded dispatch to stop | that anything was reversed, undone, compensated or revoked; it does not supersede a Control Plane decision. Reversal needs new authority and a new workflow |
| `completed` (a **closure class**, not a status) | the workflow reached `observed` or `reconciled` | that an effect was verified or settled correctly; `refs_content_checked` stays `False` |

Four new events (13 in all): `suspend` (`suspension_ref`), `resume` (`resume_ref`), `cancel` (`cancellation_ref`), `fail` (`failure_ref`); references are opaque text like the existing ones. `describe()` gains `closure_class` (`open`, `completed`, `failed`, `cancelled`) and `slot_class` (`none`, `execution`, `waiting`, `closed`); `terminal` is now true for `observed`, `reconciled`, `failed`, `cancelled`.

- No closing event from an open effect: `suspend`, `cancel` and `fail` from `dispatched` or `unresolved` are refused (`open_effect_refused`). An effect whose outcome is unknown leaves only through `record_observation` or `reconcile`; the machine gives no path to abandon it, and an unresolved workflow is never `completed`, never released and (with the store) never archived.
- `resume` re-enters at `proposed`; the earlier decision is never restored, so a new `request_authority`/`record_authorized` with a new `decision_ref` is required to dispatch. The machine still cannot judge decision currency (caller duty unchanged).
- `failed` and `cancelled` refuse every event with `workflow_closed`, including `dispatch`. `observed` and `reconciled` keep their original cells.
- Slot classes are derived from replayed status only (no counter, so a crash cannot leak a slot): **execution** = `authorized`, `dispatched`; **waiting** = `proposed`, `awaiting_authority`, `suspended`, `unresolved`; **closed** = the four terminal statuses. A hold or deny leaves a workflow `awaiting_authority`: a durable waiting record that consumes no execution slot. Closed workflows count against neither bound; they remain in `Fleet.states` (memory) until `release_terminal`.
- Two bounds replace the single 64 (`MAX_ACTIVE_EXECUTION_SLOTS = 64`, `MAX_WAITING_RECORDS = 1000`). They are unqualified upper bounds, not measured safe defaults, and are module constants here: configurable bounds, capacity accounting and load characterization are step 3.2-B and are not part of this change.
- Admission: `apply_fleet` refuses `propose` of a new workflow at the waiting bound (`bound_waiting_exceeded`) and `record_authorized` at the execution bound (`bound_execution_slots_exceeded`; the workflow stays `awaiting_authority`, so the decision reference is not lost). Moves from execution to waiting (`record_outcome_unknown`, `crash_recovered`, `suspend`) and waiting to waiting (`resume`) are never refused for capacity, so an unknown outcome can always be recorded; the waiting class can therefore exceed its bound by at most the execution bound.
- `replay_fleet` never refuses for capacity (a restart must be able to load what exists); `Fleet.over_limit()` reports a class above its bound and only new admissions are refused. `bound_workflows_exceeded` is retired.
- `release_terminal(fleet, workflow_id)` returns `(new fleet, receipt)` for a terminal workflow, pure and without archiving anything; call it only after the store's archive receipt exists. It refuses `open_effect_refused` for `dispatched`/`unresolved` and `not_releasable` for any other non-terminal status or unknown workflow.
- `restart_recovery_needed(fleet)` lists the workflows replayed as `dispatched`; a restart records `crash_recovered` for exactly those. Nothing else is resumed, closed or released by a restart.
- `State` gained a fifth field `history` (event types in order) and its consistency check is table-driven (it replays `history` through the table and Rule R; this also gives `record_outcome_unknown` versus `crash_recovered` a trace). It remains a consistency guard, not proof of history.
- Backward compatibility: relative to the pre-amendment machine (`ocs-workflow-machine/0`), every history legal there stays legal (under `/0` `dispatch` was always the 4th event, far from the new limits). Relative to the first 3.2-A commit (88ec248) the highest accepted counts for `suspend`, `resume`, `request_authority`, `record_authorized`, `dispatch`, `cancel`, `fail` and `record_observation` each moved down by one. The API is not backward compatible: `State` has a new **required** fifth field `history` (any caller constructing `State(...)` must pass it; rebuild through `replay`), `Fleet` construction no longer refuses for capacity, `replay_fleet` never enforces bounds, `bound_workflows_exceeded` and `MAX_CONCURRENT_WORKFLOWS` are gone, and `describe()` has two new members.
- Provisional vocabulary identity: the previous vocabulary is retroactively `ocs-workflow-machine/0`, this one `ocs-workflow-machine/1` (`MACHINE_PROFILE`). Histories legal under `/0` are legal under `/1`; a `/1` history with `suspend`, `resume`, `cancel` or `fail` is not replayable by `/0`. The store envelope `ocs-workflow-event/0` is unchanged by the machine (it carries opaque event kinds); nothing records the machine identity in a store yet (adapter, step 3.4).

Deviations from the proposal text, all deliberate and minimal: the proposed `limits` argument of `replay_fleet`/`apply_fleet` is not implemented (configurable bounds are 3.2-B); the module constants are used and `over_limit()` reports; the invariant `active + waiting + unreleased <= store max_workflows` is not enforced here (the store refuses `store_full` first). Open questions 1 to 6 of the proposal are unchanged and unanswered: no operator abandonment path for an unresolved effect exists, retention durations are not set, and the timeout clock for `fail`/`cancel` belongs to the caller.

## Statuses and table

Statuses: the reserved list from `orchestration/state-transitions/README.md` (`proposed`, `awaiting_authority`, `authorized`, `dispatched`, `observed`, `unresolved`, `reconciled`) plus `suspended`, `failed`, `cancelled` (amendment 3.2-A) and the pre-state `initial` (no event seen; not a reported status). Terminal: `observed`, `reconciled`, `failed`, `cancelled`.

Legal cells (21; every other cell is refused). The test `test_vocabulary_table_equals_the_design_document` parses the tables of the proposal document and fails if the vocabulary and the document differ.

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
| proposed, awaiting_authority, authorized | suspend | suspended |
| suspended | resume | proposed |
| proposed, awaiting_authority, authorized, suspended | cancel | cancelled |
| proposed, awaiting_authority, authorized, suspended | fail | failed |

Refusal code of each illegal cell: any event from `failed` or `cancelled` is `workflow_closed`; `suspend`, `cancel` or `fail` from `dispatched` or `unresolved` is `open_effect_refused`; `dispatch` from `initial`, `proposed`, `awaiting_authority` or `suspended` is `authority_required`; `dispatch` from `dispatched`, `observed`, `unresolved` or `reconciled` is `blind_retry_refused`; everything else is `illegal_transition` (a second `suspend`, `resume` outside `suspended`, any event out of `observed`/`reconciled` other than `dispatch`).

A legal cell is also refused (`bound_events_exceeded`) under Rule R (see Bounds). Reading of the names: `authorized`, `observed` and `reconciled` only record that a reference string was supplied (`decision_ref`, `observation_ref`). The machine does not read, dereference or check those records and never sets a decision result, attempt status, observation or effect verification. `dispatched` is a write-ahead record that the hand-off to the gate is being made; it does not mean an attempt exists or that the effect happened.

### Divergence from s03 (operator-visible; the choice is for the governor)

`s03/workflow-state-reconciliation.md` is **Proposed, documentation only**; it does not decide anything and does not require this machine's vocabulary. After the amendment this machine shares `proposed`, `awaiting_authority`, `dispatched`, `unresolved`, `failed`, `cancelled`, `suspended` with s03, and `completed` as a closure class rather than a status. It omits `validating`, `ready`, `reconciling` and `cancel_requested` (cancellation before dispatch is immediate and after dispatch is refused, so nothing is ever "requested"), and it keeps `authorized`, `observed` and `reconciled` as pure reference markers that s03 would remove.

## Events

Closed set of thirteen (`EVENT_TYPES`). An event has exactly the members `type`, `workflow_id`, `seq`, `at` and, per type, one reference member (`proposal_ref`, `decision_ref`, `dispatch_ref`, `observation_ref`, `suspension_ref`, `resume_ref`, `cancellation_ref`, `failure_ref`; see `EVENT_MEMBERS`; a test pins that none of the new names is a forbidden token). References are opaque non-empty text; the machine never dereferences or judges them. `at` is caller-supplied opaque text, never decides anything, and is not retained in `State` (`State.refs` holds only `(event type, reference)` pairs; keep `at` in the event log). `seq` must equal the number of events already applied plus one.

### What the caller (store, step 3.4) must verify

The machine checks event shape and order only. It does not check that `decision_ref` names a Control Plane decision whose result is a current `authorized`, nor that `observation_ref` names anything. Before submitting `record_authorized` the caller must verify the decision is a current `authorized` result (a `hold`, `deny`, expired or superseded decision must not produce this event). Before submitting `record_observation` the caller must verify the observation is independent evidence that settles the outcome; an observation that is `unknown`, `partial` or absent must be routed to `record_outcome_unknown` (from `dispatched`) or `reconcile_inconclusive` (from `unresolved`), never to `record_observation` or `reconcile`. A caller that skips these checks gets a machine that reports `observed` for a workflow whose outcome is not settled. `describe()` repeats this in its output: `refs_content_checked` is always `False`, and `observation_referenced` / `reconciliation_referenced` mean only that a reference string was recorded.

### Write-ahead is a store requirement

The store must durably persist the `dispatch` event before it hands anything to the gate. The same holds for `suspend`, `resume`, `cancel` and `fail`: a workflow counts as closed or suspended only when the event is persisted and its outcome is known (not `outcome_ambiguous`; reload and replay first), and `release_terminal` is called only after archival succeeded. The machine cannot detect a missing write-ahead. If the process crashes after the hand-off but before `dispatch` was persisted, the workflow is still `authorized` after restart and a second `dispatch` is legal: that is a blind retry the machine cannot see. If `dispatch` was persisted and the process crashes, the workflow is `dispatched`; restart handling records `crash_recovered` (`dispatched` to `unresolved`), after which only reconciliation is legal.

## Refusal codes (closed)

`schema_invalid`, `unknown_event_type`, `unknown_member`, `forbidden_member`, `workflow_mismatch`, `sequence_mismatch`, `authority_required`, `blind_retry_refused`, `illegal_transition`, `bound_events_exceeded`, `bound_execution_slots_exceeded`, `bound_waiting_exceeded`, `open_effect_refused`, `workflow_closed`, `not_releasable` (`bound_workflows_exceeded` is retired). A refusal raises `Refusal` with a `.code`; states are immutable, so the input state is unchanged. Check order in `apply_event`: shape (the event mapping is copied once and the copy is validated), workflow, sequence, event bound (16 already applied), transition table, reserved final slot. `apply_fleet` runs shape first, then capacity (`propose` for a new workflow at the waiting bound; `record_authorized` for a workflow in `awaiting_authority` at the execution bound), then the `apply_event` order above. The shape step refuses in this order: type, forbidden member, unknown member, missing member, member values.

## Enforced invariants

1. Not an alternate Control Plane. The exact per-event member allow-list (`EVENT_MEMBERS`) is the guard: any member not on it is refused, so no event carries a verdict, grant, permission, pin or authority member, and `State` has only five fixed fields (workflow id, status, event count, refs, history). The forbidden-token list (`FORBIDDEN_MEMBER_TOKENS` plus substring families such as `verdict`, `grant`, `permission`, `authoriz`) only chooses the refusal code: a member whose name matches is `forbidden_member`, any other undeclared member is `unknown_member`. Authorization enters only as an opaque reference string. The machine does not check that the reference names a Control Plane decision or that the decision authorizes anything (see the caller duties above).
2. No blind retry. A dispatch is legal only from `authorized`, once. A dispatch whose outcome is unknown moves only to `unresolved` and from there only to `reconciled` by an explicit `reconcile` event (or stays `unresolved` on `reconcile_inconclusive`). There is no path from `unresolved` to `dispatched`.
3. No success or failure claim. `describe(state)["effect_outcome"]` is `none`, `unknown`, `observation_referenced` or `reconciliation_referenced`; it is never success, failure or absence. `dispatched` and `unresolved` are `unknown`. The two `*_referenced` values mean a reference string was recorded and nothing more: whether the observation settled anything is not checked here.
4. Reconcile-only continuation after a persisted `dispatch`. A `dispatched` workflow can only move to `observed`, or to `unresolved` by `record_outcome_unknown` or `crash_recovered`; nothing re-dispatches, and from `unresolved` only `reconcile` or `reconcile_inconclusive` are legal. This holds only if the store persisted `dispatch` before the hand-off (see Write-ahead above); the machine cannot see a missing write-ahead.
5. Determinism. `apply_event`, `replay` and `next_actions` are pure functions of their arguments.
6. Bounded lifecycle, see Bounds below.
7. Illegal transitions are refused with state unchanged.
8. Consistent state. `State` and `Fleet` check themselves on construction (`__post_init__`): status, `event_count`, `refs` and `history` must agree with each other (`history` must replay through the transition table and Rule R to `status`, and `refs` must be exactly the reference members of that history), fleet keys must equal each state's `workflow_id`, and the fleet input is snapshotted. This catches hand-built or corrupted states, not forged history: reference text and `at` cannot be re-derived. Persisted states must still be rebuilt only through `replay`/`replay_fleet`, not deserialized field by field.

## Bounds (operator-visible design choices)

- `MAX_EVENTS_PER_WORKFLOW = 16`, counting machine events only; it is not derived from the store's durable `max_events`, and a store refusal (`workflow_full`) is never a machine state. Rule R: a non-closing event is accepted only if completion (`observed` or `reconciled`) is still certain afterwards. `EVENTS_TO_COMPLETION` is the fewest events over a status's exits, except `dispatched`, which counts its worst exit: an unknown outcome (`record_outcome_unknown` or `crash_recovered`) followed by `reconcile`. Values: `unresolved` 1, `dispatched` 2, `authorized` 3, `awaiting_authority` 4, `proposed` 5, `suspended` 6, `initial` 6. A closing event (`cancel`, `fail`) needs no remaining slot. So a pre-dispatch workflow can always close, a dispatched workflow can always record an unknown outcome and then reconcile (so every id `restart_recovery_needed` returns can be resolved; a test checks every reachable history), and `reconcile_inconclusive` is refused at the 16th event while `reconcile` is still legal. Pinned over all 108 reachable (status, event count) pairs: the highest number of events already applied (the count before the event) at which each event is accepted is `suspend` 9, `resume` 10, `request_authority` 11, `record_authorized` 12, `dispatch`/`cancel`/`fail` 13, `record_outcome_unknown`/`crash_recovered`/`reconcile_inconclusive`/`record_observation` 14, `reconcile` 15. At the bound a terminal workflow has `next_actions() == ()`.
- `apply_event`, `next_actions`, `describe` and `apply_fleet` require exactly `type(state) is State` / `type(fleet) is Fleet` (a subclass that skips `__post_init__` is `schema_invalid`). They do not re-validate a state's fields on each call: a state mutated with `object.__setattr__` after construction is not detected. Treat states as values built only by `replay` or the constructor.
- Capacity: see Amendment 3.2-A. Terminal workflows are not removed from `Fleet.states` until `release_terminal`; total fleet size is bounded only by the caller releasing them after archival.

## Not done here

Durable storage, the adapter that joins this machine to the store (step 3.4), configurable bounds, capacity accounting and load characterization (3.2-B), any reading of Control Plane, Runtime or observation records, and the 3.4 handoff are separate. A Control Plane `hold` or `deny` result is its own record and has no event: the workflow stays `awaiting_authority` (a waiting record, no execution slot) until the caller records `suspend`, `cancel`, `fail` or a later `record_authorized`; the machine holds no clock, so who issues a timeout `fail`/`cancel` is the caller's decision. There is no path to abandon an unresolved effect. Retention periods and deletion of archives are external custody decisions and are not made here.

Not independently qualified. Tests in `tests/integration/workflow_machine/` are developer tests. Run: `python -m pytest -q tests/integration/workflow_machine` (the machine-plus-store lifecycle tests are `tests/integration/workflow_store/test_workflow_store_lifecycle.py`).
