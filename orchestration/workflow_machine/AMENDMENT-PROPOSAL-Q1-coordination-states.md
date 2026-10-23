# Amendment proposal Q1: coordination states, completion, retention and capacity

**PROPOSAL. Non-authorizing. NOT implemented.** Release and production remain on HOLD. This document changes no `.py` file, no workflow file and no behavior of `orchestration/workflow_machine`; the machine described in [README.md](README.md) is unchanged. Implementation of Q1 is not authorized in this round. Nothing here claims clearance, certification, qualification or production readiness, and no independent review has taken place.

Origin: architect decision Q1 (approve, through a separate reviewed state-machine amendment). Inputs read against the merged code at Orchestrator `72fb6ed`: [vocabulary.py](vocabulary.py), [machine.py](machine.py), [README.md](README.md), [../workflow_store/README.md](../workflow_store/README.md) and hub `docs/program-v0.2/s03/workflow-state-reconciliation.md` (hub `c6ef531`, read-only).

Companion proposals: [../workflow_store/AMENDMENT-PROPOSAL-Q9-store-limits-and-archival.md](../workflow_store/AMENDMENT-PROPOSAL-Q9-store-limits-and-archival.md) (durable limits, archival, cached head) and [../EXTERNAL-CHECKPOINT-NOTE-Q10.md](../EXTERNAL-CHECKPOINT-NOTE-Q10.md) (what an external custodian may retain).

## 1. What is wrong today (verified in the merged code)

1. `TERMINAL_STATUSES = ("observed", "reconciled")` (`vocabulary.py:13`). No status says "this workflow will not continue and nothing was handed off".
2. A workflow in `awaiting_authority` after a Control Plane `hold` or `deny` has no outgoing event except `record_authorized`, so it stays there and consumes one of the 64 slots (`MAX_CONCURRENT_WORKFLOWS`, `vocabulary.py:54`, enforced in `Fleet.__post_init__` and `apply_fleet`, `machine.py:226-227`, `248-249`). The README records this as an operator decision.
3. Terminal workflows stay in `Fleet.states` forever (only non-terminal ones count against the 64), so fleet memory is unbounded, and `replay_fleet` raises `bound_workflows_exceeded` when a replayed history holds more than 64 non-terminal workflows, so a restart can refuse to load a history that was legal when written.
4. One counter (64) conflates two different resources: workflows that are executing or about to execute, and records that are merely waiting.

## 2. Summary of the proposal

| Item | Proposal |
|---|---|
| New statuses | `suspended` (non-terminal), `failed` (terminal), `cancelled` (terminal) |
| New events | `suspend`, `resume`, `cancel`, `fail` (each carries one opaque reference) |
| `workflow.completed` | Defined as a **closure class**, not a new status and not a new event: it is the set of terminal statuses `{observed, reconciled}`. Alternative in section 5 |
| Closure on an open effect | `suspend`, `cancel` and `fail` are refused from `dispatched` and `unresolved` (`open_effect_refused`). An effect whose outcome is unknown can only leave through `record_observation` or `reconcile` |
| Capacity | Two separate bounds replace the single 64: `active_execution_slots` and `waiting_records` |
| Slot release | Derived from replayed status, never from a separate counter. Terminal workflows are released from the active fleet by a pure `release_terminal` step after they are safely archived (Q9 document) |
| New refusal codes | `bound_execution_slots_exceeded`, `bound_waiting_exceeded`, `open_effect_refused`, `workflow_closed`, `not_releasable`; `bound_workflows_exceeded` is retired in the new vocabulary |
| Identity | Not wire-compatible as an API; histories valid under the current machine remain valid. New vocabulary identity proposed (section 12) |

These are coordination states only. None of them records, implies or permits any claim that an effect failed, was reversed, was compensated or was verified (section 3).

## 3. Meaning of the new states (what each does and does not say)

| Status | Says | Does not say |
|---|---|---|
| `suspended` | The coordinator has paused a workflow that has not handed anything to the gate. It keeps its record and its place in the waiting bound | That it ended, that its authorization is still current, or that anything is cancelled. Suspension is not termination: it is never terminal, never archived, never released from `waiting_records`, and `resume` is the only way forward other than closure |
| `failed` | Orchestration could not continue (for example a timeout waiting for a decision, a coordinator fault) before any dispatch was recorded | That an effect failed. Effect failure, if any, is the attempt record another component owns. `describe()["effect_outcome"]` stays `none` |
| `cancelled` | A caller asked that a workflow with no recorded dispatch stop | That anything was reversed, undone, compensated or revoked. It does not revoke or supersede a Control Plane decision; compensation or reversal needs new authority and a new workflow |
| completed (class) | The workflow reached `observed` or `reconciled`, each of which only records that an observation or reconciliation reference string was supplied | That an effect was verified or settled correctly. `refs_content_checked` remains `False` |

Why closure is refused on an open effect: after `dispatch` is persisted the hand-off may have happened. A `cancelled` or `failed` status there would let an unresolved effect be archived as if nothing was outstanding, which Q1 forbids (do not archive unresolved effects as completed; do not equate suspension with termination). Therefore `dispatched` and `unresolved` have no closing event. Whether an operator may ever abandon an unresolved effect is a separate decision with external authority (open question 1); the table below gives no path for it.

## 4. Statuses and events

Statuses (11 states including the pre-state): `initial`, `proposed`, `awaiting_authority`, `authorized`, `dispatched`, `observed`, `unresolved`, `reconciled`, `suspended`, `failed`, `cancelled`. Terminal: `observed`, `reconciled`, `failed`, `cancelled`. Non-terminal: the rest except `initial`, which is not reported.

Events (13, canonical order; the first nine are unchanged):

| Event | Members beyond `type`, `workflow_id`, `seq`, `at` | Meaning |
|---|---|---|
| `propose` | `proposal_ref` | unchanged |
| `request_authority` | none | unchanged |
| `record_authorized` | `decision_ref` | unchanged; the caller duty to verify a current `authorized` decision is unchanged |
| `dispatch` | `dispatch_ref` | unchanged; write-ahead record |
| `record_observation` | `observation_ref` | unchanged |
| `record_outcome_unknown` | none | unchanged |
| `crash_recovered` | none | unchanged |
| `reconcile` | `observation_ref` | unchanged |
| `reconcile_inconclusive` | `observation_ref` | unchanged |
| `suspend` | `suspension_ref` | pause a workflow with no recorded dispatch |
| `resume` | `resume_ref` | leave `suspended`; always re-enters at `proposed` (section 6) |
| `cancel` | `cancellation_ref` | close a workflow with no recorded dispatch at a caller's request |
| `fail` | `failure_ref` | close a workflow with no recorded dispatch because orchestration cannot continue |

All four new references are opaque, non-empty, trimmed text of at most 256 characters, never dereferenced or judged (same rule as the existing `_ref` members). The member names were chosen so none matches `FORBIDDEN_MEMBER_TOKENS` or the substring families in `machine._forbidden` (`failure_ref` splits to tokens `failure` and `ref`; the forbidden token is `fail`/`failed`, which do not match). A test must pin that, because a later edit of the token list could silently turn a new member into `forbidden_member`.

## 5. `workflow.completed` and the retention policy

### 5.1 Definition (recommended: closure class)

`completed` is a derived classification, not a status:

- `closure_class(status)` is `completed` for `observed` and `reconciled`, `failed` for `failed`, `cancelled` for `cancelled`, and `open` for every non-terminal status including `suspended`, `dispatched` and `unresolved`.
- `describe()` gains `closure_class` (and `slot_class`, section 8). `terminal` stays `status in TERMINAL_STATUSES` with the enlarged set.
- A workflow whose status is `dispatched` or `unresolved` is never `completed` and is never eligible for archival as completed.

Reasons: it adds no event (the existing 16-event budget and reserve arithmetic are untouched), existing histories keep their meaning, and it matches the s03 sentence that completed "never states that an effect was verified". The price is that s03's `completed` is a class here rather than one of 12 states (section 10).

Alternative (not recommended): add `completed` as a status reached by an explicit `complete` event from `observed` or `reconciled`. That makes those two non-terminal, consumes one more event of the 16 on every successful path, changes `EVENTS_TO_TERMINAL` for every status, and gives a reader a second place to over-read verification. If chosen, `complete` must carry a reference only and `completed` must not be reachable from `unresolved`.

### 5.2 Terminal-state retention policy (proposal; durations are the operator's, none is set here)

| Class | Held in the active fleet | Held in the durable store | Never |
|---|---|---|---|
| `open` (incl. `suspended`, `dispatched`, `unresolved`) | yes | yes, as live record | archived, released, deleted, counted as completed |
| `completed` | until safely archived | read-only until archived, then in the archive | edited, re-opened, deleted by the machine or the store |
| `failed`, `cancelled` | until safely archived | same | treated as evidence about an effect |

Safe archival (defined fully in the Q9 document, section 6) requires all of: terminal status by replay; chain fully validated and clean `inspect`; lock released; the head sequence and digest delivered to the external custodian, or the archive receipt explicitly marked `external_checkpoint: not_retained`; no unrecorded quarantine. Retention duration per class, and whether archived records are ever deleted, are external custody decisions (open question 3). The machine never deletes and holds no clock; any expiry is applied by the caller, who then records the outcome with `fail` or `cancel` and a reference.

## 6. Complete transition table

Legal cells (21). Every cell not listed is refused. `capacity` marks the cells subject to a fleet bound (section 8).

| From | Event | To | Notes |
|---|---|---|---|
| initial | propose | proposed | `waiting_records` admission check |
| proposed | request_authority | awaiting_authority | |
| proposed | suspend | suspended | |
| proposed | cancel | cancelled | |
| proposed | fail | failed | |
| awaiting_authority | record_authorized | authorized | `active_execution_slots` check |
| awaiting_authority | suspend | suspended | |
| awaiting_authority | cancel | cancelled | the way out of a `hold`/`deny` the Control Plane recorded |
| awaiting_authority | fail | failed | for example decision wait timed out (the caller owns the clock) |
| authorized | dispatch | dispatched | write-ahead rule unchanged |
| authorized | suspend | suspended | releases the execution slot |
| authorized | cancel | cancelled | releases the execution slot |
| authorized | fail | failed | releases the execution slot |
| dispatched | record_observation | observed | |
| dispatched | record_outcome_unknown | unresolved | never refused for capacity (section 8) |
| dispatched | crash_recovered | unresolved | never refused for capacity |
| unresolved | reconcile | reconciled | |
| unresolved | reconcile_inconclusive | unresolved | |
| suspended | resume | proposed | the old authorization is not restored; the workflow walks `request_authority` and `record_authorized` again with a new `decision_ref` |
| suspended | cancel | cancelled | |
| suspended | fail | failed | |

`resume` re-enters at `proposed` so that a decision obtained before the suspension can never be silently reused to dispatch after it. The machine still cannot judge decision currency; the caller duty (verify a current `authorized` result before `record_authorized`) is unchanged.

### 6.1 Illegal cells, explicit (122 of 143) and their refusal codes

Rows are states, columns are the 13 events. `I` is `illegal_transition`; other codes are named. A cell marked `legal` is in the table above. The existing special cases for `dispatch` are kept: `blind_retry_refused` where a dispatch was already recorded, `authority_required` before authorization.

| State | propose | request_authority | record_authorized | dispatch | record_observation | record_outcome_unknown | crash_recovered | reconcile | reconcile_inconclusive | suspend | resume | cancel | fail |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| initial | legal | I | I | authority_required | I | I | I | I | I | I | I | I | I |
| proposed | I | legal | I | authority_required | I | I | I | I | I | legal | I | legal | legal |
| awaiting_authority | I | I | legal | authority_required | I | I | I | I | I | legal | I | legal | legal |
| authorized | I | I | I | legal | I | I | I | I | I | legal | I | legal | legal |
| dispatched | I | I | I | blind_retry_refused | legal | legal | legal | I | I | open_effect_refused | I | open_effect_refused | open_effect_refused |
| observed | I | I | I | blind_retry_refused | I | I | I | I | I | I | I | I | I |
| unresolved | I | I | I | blind_retry_refused | I | I | I | legal | legal | open_effect_refused | I | open_effect_refused | open_effect_refused |
| reconciled | I | I | I | blind_retry_refused | I | I | I | I | I | I | I | I | I |
| suspended | I | I | I | authority_required | I | I | I | I | I | I | legal | legal | legal |
| failed | workflow_closed (all 13 events, including dispatch) | | | | | | | | | | | | |
| cancelled | workflow_closed (all 13 events, including dispatch) | | | | | | | | | | | | |

Count check (computed from this table by a scratch model, not committed): 21 legal cells; 11 states times 13 events is 143 cells; 122 illegal.

Rationale for the choices that are not obvious: `suspend` from `suspended` is `illegal_transition` (a second suspend would add an event with no state change); `resume` anywhere except `suspended` is `illegal_transition`; `dispatch` from `suspended` is `authority_required` because a suspended workflow holds no usable authorization; `failed` and `cancelled` use the new `workflow_closed` for every event, including `dispatch`, because neither a blind retry (nothing was dispatched) nor a missing authority is the true reason. The existing cells for `observed` and `reconciled` are not changed in this amendment (they stay `illegal_transition` and `blind_retry_refused`); harmonizing them with `workflow_closed` would be a separate incompatible change.

Check order in `apply_event` is unchanged (shape, workflow, sequence, event bound, transition table, reserved final slot); the fleet capacity check runs in `apply_fleet` after shape and before the machine's own order, as the fleet bound does today.

## 7. The 16-event bound, the reserved final slot and `EVENTS_TO_TERMINAL`

The per-workflow bound `MAX_EVENTS_PER_WORKFLOW = 16` stays a property of the coordination machine only. It counts machine events, not store records, and is not derived from the durable store limit (section 9).

`EVENTS_TO_TERMINAL` today is the fewest events to any terminal status. With `cancel` and `fail` available before dispatch that definition would be 1 for `authorized`, so `record_authorized` would be accepted as late as event 15 (count 14 before it), leaving a workflow in `authorized` with 15 events recorded that can only close and can never dispatch while it holds an execution slot. To avoid this trap the amendment splits the measure:

- `EVENTS_TO_COMPLETION`: fewest events to `observed` or `reconciled`. This is exactly the current table for the current statuses (`dispatched` 1, `unresolved` 1, `authorized` 2, `awaiting_authority` 3, `proposed` 4, `initial` 5) and adds `suspended` 5 (`resume`, then 4). Computed from the proposed table.
- Rule R: a non-closing event is accepted only if completion still fits in the 16 after it (`MAX - (count + 1) >= EVENTS_TO_COMPLETION[new status]`), exactly as today. A closing event (`cancel`, `fail`) is accepted whenever it is legal and the count is below 16: it terminates the workflow, so it needs no remaining slot. The last slot is therefore still reserved, now for any terminating event, and `reconcile_inconclusive` is still refused at the 16th event so `unresolved` can always reach `reconciled`.

Computed consequences (scratch model over the proposed table):

- Every status reachable under Rule R can still reach a terminal status; there is no dead end among 116 reachable (status, event count) pairs. A pre-dispatch workflow can always close; a post-dispatch workflow can always complete.
- A path that ends in `observed` or `reconciled` can contain at most 5 `suspend`/`resume` cycles (each cycle from `proposed` costs 2 events).
- Highest event count (events already recorded) at which each event is still accepted on a reachable path: `suspend` 10 (it needs room for 5 more to complete), `resume` 11, `request_authority` 12, `record_authorized` 13, `dispatch` 14, `record_outcome_unknown` 14, `crash_recovered` 14, `reconcile_inconclusive` 14, `cancel` 14, `fail` 14, `record_observation` 15, `reconcile` 15. (`cancel` and `fail` are legal up to count 15 by the rule, but no reachable pre-dispatch state has more than 14 events.) The test plan must pin these numbers.
- The existing statement "`reconcile_inconclusive` can occur at most 10 times (events 6 to 15)" is unchanged.

`State` consistency check: `_SPINE` and `_check_state` (`machine.py:37-76`) assume one fixed path of reference-carrying events. Suspend/resume loops break that assumption. The amendment replaces the spine check with a table-driven one: `State` gains a bounded `history` tuple of event types (at most 16 entries), and construction requires that replaying `history` through `TRANSITIONS` ends at `status`, that `len(history) == event_count`, and that `refs` equals the reference-carrying subsequence. This also closes a documented gap (`record_outcome_unknown` versus `crash_recovered` leave no trace in `refs`). It is still a consistency guard, not proof of history.

## 8. Capacity: execution slots versus waiting records

### 8.1 Slot classes (derived from status only)

| Slot class | Statuses | Why |
|---|---|---|
| execution | `authorized`, `dispatched` | A hand-off to the gate is imminent or in flight; this is the only span in which an effect can be started |
| waiting | `proposed`, `awaiting_authority`, `suspended`, `unresolved` | The coordinator is handing off nothing. A held or denied workflow, a suspended workflow and an unresolved effect awaiting reconciliation evidence are durable records, not execution capacity. For `unresolved` the effect outcome is unknown and the effect may still be in flight downstream; "waiting" describes the coordinator, not the world |
| closed | `observed`, `reconciled`, `failed`, `cancelled` | Terminal. The status-derived classes never count a terminal workflow against either bound (execution and waiting are counted by status only); an unreleased terminal workflow still occupies fleet memory and a live store directory until `release_terminal` and archival, which is why the configuration invariant in 8.1 includes `unreleased_terminal` |

Two bounds, both configurable upper bounds in the same sense as Q9 (not demonstrated safe defaults):

- `active_execution_slots`: maximum number of workflows in the execution class. Carry the current value 64 as the ceiling to be qualified; the proposal does not claim 64 is safe.
- `waiting_records`: maximum number of workflows in the waiting class. Proposed ceiling is tied to the store workflow limit (1000 in Q9) minus the slots in other classes; no safe default is claimed.

Invariant at configuration time: `active_execution_slots + waiting_records + unreleased_terminal <= store max_workflows`, otherwise the store refuses `store_full` before the machine's bounds matter (the fleet bound must not be the surprise).

### 8.2 Where each bound is checked

| Event | Bound | Refusal |
|---|---|---|
| `propose` for a new workflow | `waiting_records` must not already be full | `bound_waiting_exceeded` |
| `record_authorized` (enter execution) | `active_execution_slots` must not already be full | `bound_execution_slots_exceeded`; the workflow stays `awaiting_authority`, which is a waiting record, so a full execution pool does not lose the decision reference |
| `dispatched` to `unresolved` (`record_outcome_unknown`, `crash_recovered`) | none: moving from execution to waiting is never refused for capacity | recording an unknown outcome must never be refused; it would hide an open effect |
| `authorized` to `suspended` | none, same reason | |
| `resume` (suspended to proposed) | none (waiting to waiting) | |

Because moves from execution to waiting are not refused, the waiting class can exceed `waiting_records` by at most `active_execution_slots`; the hard ceiling is the sum of the two. This copies the shape of the store's recovery reserve (events beyond `max_events` for `store.*` records only). Held workflows therefore cannot occupy execution slots at all: a `hold` or `deny` leaves the workflow in `awaiting_authority`, a waiting record, until the caller closes or suspends it.

### 8.3 Release

Release is a pure function of replayed state, not a mutable counter, so a crash cannot leak a slot:

- leaving `authorized`/`dispatched` releases an execution slot by definition (the status changed);
- `release_terminal(fleet, workflow_id)` (proposed API) returns a new fleet without the workflow plus a receipt (workflow id, terminal status, closure class, event count). It refuses `not_releasable` unless the status is terminal and refuses with `open_effect_refused` for `dispatched` and `unresolved`. It does not archive anything itself: the store performs archival (Q9 document) and the caller calls `release_terminal` only after the archive receipt exists. `Fleet.states` then holds only workflows that are not yet released, which bounds fleet memory.

### 8.4 Replay must not refuse because of capacity

Capacity bounds are admission controls applied when an event is first submitted. Replaying persisted history (restart) must not refuse a legal history because the configured bound was lowered or because the history is larger than today's limit (today `Fleet.__post_init__` raises on more than 64 non-terminal workflows). Proposal: `replay_fleet(events, limits=None)` computes counts without refusing; `apply_fleet(fleet, event, limits)` enforces limits on new events; a restart that finds counts above the configured limits reports `over_limit` and refuses only new admissions.

## 9. Interaction with the durable store (write-ahead, archival, separate limits)

The store (`orchestration/workflow_store`) does not import the machine and the machine does not import the store; the adapter that joins them is step 3.4 and is not designed here. Requirements this amendment places on that adapter:

1. Write-ahead for every new event. `dispatch` must already be durable before any hand-off (unchanged). `suspend`, `resume`, `cancel` and `fail` must be appended and their outcome known (not `outcome_ambiguous`) before the caller acts on them, for example before releasing a lock, telling anyone the workflow is closed, or calling `release_terminal`. After `outcome_ambiguous` the adapter reloads and replays before doing anything.
2. Closure never precedes the record. A caller must not treat a workflow as `cancelled` or `failed` because it intends to; only a persisted, replayed event counts.
3. Store `store.*` records (`store.lock_broken`, `store.torn_tail_quarantined`) are not machine events. The adapter must filter them out of the machine replay and renumber machine `seq` as the ordinal among machine events. They do not count toward the 16.
4. The 16-event machine bound and the store `max_events` (default ceiling 10000) are independent. Constraint at open: store `max_events` must be at least 16 plus the number of non-machine records the adapter writes per workflow; the store limit must never be the reason a workflow cannot close. Reaching the store limit is a store refusal (`workflow_full`), never a machine state. The recovery reserve (64) is for `store.*` records only and is not machine capacity. It is shared by every `store.*` record in the workflow, including the proposed `store.archive_intent` (Q9 document, section 6.2), and the store README (line 67) says it can be exhausted; an archival intent therefore competes with lock-break and quarantine records, and an exhausted reserve must make archival refuse rather than skip the intent.
5. Archival is a store operation after closure (Q9 document, section 6). The machine's only part is `release_terminal`, called after the archive receipt.
6. `describe()` output gains `closure_class` and `slot_class`; adapters that parse `describe()` must tolerate the added members.

## 10. Mapping to the s03 12-state list

Source: hub `docs/program-v0.2/s03/workflow-state-reconciliation.md` (section 3 result; Proposed, documentation only; unchanged by this proposal). The proposal does not adopt the s03 vocabulary wholesale; it only closes the three states the architect approved.

| s03 state | Amended machine | Status of the match |
|---|---|---|
| `proposed` | `proposed` | same name |
| `validating` | none | still omitted (internal to the coordinator) |
| `awaiting_authority` | `awaiting_authority` | same name |
| `ready` | none (`authorized` is a reference marker, not s03's `ready`) | still omitted; s03 removes `authorized` as a workflow state, the machine keeps it |
| `dispatched` | `dispatched` | same name |
| `reconciling` | none (`reconciled` is the terminal marker) | still differs from s03 |
| `unresolved` | `unresolved` | same name |
| `completed` | closure class over `observed`, `reconciled` (not a status) | defined here; never states verification |
| `failed` | `failed` | added; orchestration failure only, never an effect failure, never from an open effect |
| `cancel_requested` | none | deliberately not added: cancellation is refused from `dispatched`/`unresolved`, and before dispatch it is immediate, so there is nothing to request |
| `cancelled` | `cancelled` | added; coordination only, no reversal |
| `suspended` | `suspended` | added; non-terminal |

After the amendment the machine shares eight names with s03 (the four it shared plus `failed`, `cancelled`, `suspended`, and `completed` as a class). It still keeps `authorized`, `observed` and `reconciled` that s03 would remove; whether to remove them is not decided here.

## 11. Test plan (for the later implementation round; none of these exist yet)

Exhaustive walk (extends `tests/integration/workflow_machine/test_machine.py`):

1. Full matrix test over 11 states and 13 events: every cell is exactly one of legal (with the table above) or refused with the code in section 6.1; the table in this document is the oracle and the test must fail if either side changes without the other (a docs-versus-vocabulary check by parsing this table or a data fixture derived from it).
2. Breadth-first walk of every reachable (status, event count, history) up to 16 events: no dead end; closing always possible before dispatch; completion always possible after dispatch; `EVENTS_TO_COMPLETION` equals a recomputation; the reachable-pair count and the highest-accepted counts in section 7 (including `resume` 11 and `cancel`/`fail` 14 on reachable paths) are pinned.
3. Path properties over the walk: at most one `dispatch` on any path; `failed`, `cancelled`, `suspended` unreachable from `dispatched` and `unresolved`; nothing leaves `failed`/`cancelled`/`observed`/`reconciled`; `next_actions` is `()` for every terminal status; `resume` always lands in `proposed` and the next `record_authorized` needs a new `decision_ref` (it must not equal the old one by construction).
4. Describe invariants: `effect_outcome` is never success, failure or absence for any status including `failed` and `cancelled` (both `none`); `closure_class` is `completed` only for `observed`/`reconciled`; no status can be both `open` and archivable.
5. Capacity: with small limits (for example 2 execution, 3 waiting), exhaustive interleavings of up to 4 workflows: `propose` refused at the waiting bound, `record_authorized` refused at the execution bound leaves the workflow `awaiting_authority`, moves from execution to waiting never refused, waiting overshoot never exceeds the execution bound, `release_terminal` frees exactly one place, replay with lowered limits does not refuse.
6. Static tests carried over and extended: the closed refusal-code set equals the literals in the package and each new code has a named negative test; the purity test (no I/O, no clock) still passes; the new member names are not forbidden tokens; `-O` survival.

Fuzz oracle:

7. An independent reference model written from section 6 as pure data (a set of legal triples and a code map), not from `vocabulary.py`, compared with `apply_event` on seeded random streams of 1 to 20 events that mix legal and illegal types, wrong `seq`, wrong workflow, malformed and forbidden members. Compare status, count, refs, history, raised code and unchanged-state-on-refusal. Fixed seeds in CI plus a larger recorded seed list; any divergence is a test failure, not a retry.
8. Fleet fuzz: random interleavings across workflows with small limits against a counting oracle; assert the slot invariants of section 8 and that replay of the produced history under the same and under lower limits yields identical states.
9. Mutation checks (as the hub register already uses for other components): deleting any one refusal row or flipping any one legal cell must be caught by test 1.

## 12. Migration and versioning

- The amendment is additive for histories: every event sequence legal under the current machine is legal under the amended one, with the same states. It is not additive for the API: a refusal code is retired (`bound_workflows_exceeded`), `State` gains `history`, `describe()` gains members, `Fleet` and `replay_fleet` gain `limits`, and `TERMINAL_STATUSES` grows.
- The machine today carries no profile identity of its own (the store's `ocs-workflow-event/0` envelope carries opaque `kind` values and does not name a machine vocabulary). Proposal: name the current vocabulary retroactively `ocs-workflow-machine/0` (provisional, per Q4 practice) and the amended vocabulary `ocs-workflow-machine/1`, and have the adapter record the identity in the body of a workflow's first record. A replayer that does not know the identity refuses the history with a typed adapter-level refusal rather than guessing. New event kinds inside the existing store envelope do not change `ocs-workflow-event/0`.
- No stored production histories are known to exist; developer tests and fixtures are the only known users. If any stored `/0` history exists, it replays unchanged under `/1`; a `/1` history containing `suspend`, `resume`, `cancel` or `fail` cannot be replayed by a `/0` machine and must be refused there.
- A change to any cell of section 6, to Rule R, to the slot classes, or to the meaning of `completed` after freeze would be an incompatible change and needs a new identity (`/2`), not an edit.
- This amendment, once implemented, would be a change to a candidate component and, as for the rest of this repository, needs independent review; it does not alter locked components, Qualification expectations or the registry-activation gate (2.4).

## 13. Open questions for the architect or operator

1. Is any path to close an unresolved effect wanted (operator abandonment)? This proposal gives none. If wanted it needs external authority, a new status that is not terminal-as-completed, and a rule that it is never archived as `completed`.
2. Is the closure-class definition of `completed` acceptable, or is an explicit `completed` status (with one more event on every successful path) wanted?
3. Retention durations per class and whether archived workflows may ever be deleted (an external custody decision; Q10).
4. Ceilings for `active_execution_slots` and `waiting_records`. The proposal carries 64 and a store-tied figure only as upper bounds to be qualified; no safe default is claimed until the load plan in the Q9 document has run.
5. Should `resume` re-enter at `proposed` (this proposal) or return to the pre-suspension status when the pre-suspension status was `proposed`? The former is simpler and never reuses authority; the latter saves up to two events.
6. Who owns the clock for decision-wait and suspension timeouts? The machine and the store have none; the adapter or an operator must decide who issues `fail` or `cancel`.
