"""Pure state machine: apply, replay, next_actions. No clock, randomness, I/O or imports of other
workers' code. Every function is a pure function of its arguments; failures raise Refusal and leave
the (immutable) input state unchanged.

Candidate, non-authorizing. The Orchestrator is not an alternate Control Plane: no event or state
carries a verdict, grant, permission, pin or authority member.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from .vocabulary import (
    ALL_STATES, CLOSING_EVENTS, CLOSURE_CLASS_OF, EVENTS_TO_COMPLETION, EVENT_MEMBERS, EVENT_TYPES,
    FORBIDDEN_MEMBER_TOKENS, INITIAL, MAX_ACTIVE_EXECUTION_SLOTS, MAX_EVENTS_PER_WORKFLOW, MAX_WAITING_RECORDS,
    OPEN_EFFECT_STATUSES, REFUSAL_CODES, REFUSALS, SLOT_CLASS_OF, STATUSES, TERMINAL_STATUSES, TRANSITIONS,
)

_TEXT_MAX = 256
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


class Refusal(Exception):
    """Typed refusal; `.code` is a member of the closed REFUSAL_CODES set."""

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in REFUSAL_CODES:  # explicit raise, not assert: must survive `python -O`
            raise ValueError(f"refusal code outside the closed set: {code!r}")
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _ref_names(etype: str) -> list:
    return [m for m in EVENT_MEMBERS[etype] if m.endswith("_ref")]


def _room_to_complete(count_before: int, etype: str, new_status: str) -> bool:
    """Rule R. A closing event needs no remaining slot; any other event must leave room to complete."""
    if etype in CLOSING_EVENTS:
        return True
    return MAX_EVENTS_PER_WORKFLOW - (count_before + 1) >= EVENTS_TO_COMPLETION[new_status]


def _check_state(workflow_id, status, event_count, refs, history) -> None:
    """Consistency of the five fields with each other, table-driven: `history` (event types, in order) must
    replay through TRANSITIONS, under Rule R and the 16-event bound, to `status`; `event_count` is its length;
    `refs` carries exactly the reference-carrying members of that history. This is a forgery guard for
    hand-built states, not a proof of history: reference text and `at` are not re-derivable. Persisted
    states should still be rebuilt only through `replay`."""
    if not isinstance(status, str) or status not in ALL_STATES:
        raise Refusal("schema_invalid", "state status outside the closed set")
    if isinstance(event_count, bool) or not isinstance(event_count, int):
        raise Refusal("schema_invalid", "state event_count must be an integer")
    if not isinstance(refs, tuple) or not all(
            isinstance(r, tuple) and len(r) == 2 and r[0] in EVENT_TYPES and isinstance(r[1], str) and r[1]
            for r in refs):
        raise Refusal("schema_invalid", "state refs must be a tuple of (event type, reference) pairs")
    if not isinstance(history, tuple) or not all(isinstance(h, str) and h in EVENT_TYPES for h in history):
        raise Refusal("schema_invalid", "state history must be a tuple of event types")
    if status == INITIAL:
        if workflow_id is not None or event_count != 0 or refs != () or history != ():
            raise Refusal("schema_invalid", "initial state must have no workflow, events, refs or history")
        return
    _text(workflow_id, "state workflow_id")
    if len(history) != event_count or event_count > MAX_EVENTS_PER_WORKFLOW:
        raise Refusal("schema_invalid", f"event_count {event_count} does not match the history or the bound")
    walk = INITIAL
    for index, etype in enumerate(history):
        key = (walk, etype)
        if key not in TRANSITIONS:
            raise Refusal("schema_invalid", f"history has no transition {etype} from {walk}")
        if not _room_to_complete(index, etype, TRANSITIONS[key]):
            raise Refusal("schema_invalid", f"history breaks the reserved final slot at event {index + 1}")
        walk = TRANSITIONS[key]
    if walk != status:
        raise Refusal("schema_invalid", f"history ends at {walk}, not {status}")
    if tuple(r[0] for r in refs) != tuple(e for e in history for _ in _ref_names(e)):
        raise Refusal("schema_invalid", f"refs do not match the history of {status}")


@dataclass(frozen=True)
class State:
    """Immutable workflow state. `refs` is the ordered record of (event type, reference) pairs and `history`
    the ordered event types. Fields are checked for mutual consistency on construction (see `_check_state`);
    `at` is not kept."""
    workflow_id: str | None
    status: str  # INITIAL or one of STATUSES
    event_count: int
    refs: tuple
    history: tuple

    def __post_init__(self) -> None:
        _check_state(self.workflow_id, self.status, self.event_count, self.refs, self.history)


def initial_state() -> State:
    return State(workflow_id=None, status=INITIAL, event_count=0, refs=(), history=())


def _text(value, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _TEXT_MAX or value != value.strip():
        raise Refusal("schema_invalid", f"{name} must be non-empty trimmed text of at most {_TEXT_MAX} characters")
    return value


def _forbidden(member: str) -> bool:
    tokens = [t for t in _TOKEN_SPLIT.split(member.lower()) if t]
    joined = "_".join(tokens)
    return any(t in FORBIDDEN_MEMBER_TOKENS for t in tokens) or any(
        f in joined for f in ("verdict", "grant", "permission", "authority", "authoriz"))


def _validate_event(event) -> dict:
    """Shape check only (no state). Order: type, forbidden members, unknown members, member values.
    The mapping is copied once, first; everything is validated and returned from that copy, so a
    mapping that answers differently on a second read cannot pass validation and then change."""
    if not isinstance(event, Mapping):
        raise Refusal("schema_invalid", "event must be a mapping")
    try:
        event = dict(event)
    except Exception:
        raise Refusal("schema_invalid", "event mapping could not be copied") from None
    etype = event.get("type")
    if not isinstance(etype, str) or etype not in EVENT_TYPES:
        raise Refusal("unknown_event_type", repr(etype)[:80])
    for member in event:
        if not isinstance(member, str):
            raise Refusal("schema_invalid", "member names must be text")
        if member not in EVENT_MEMBERS[etype] and _forbidden(member):
            raise Refusal("forbidden_member", member)
    allowed = EVENT_MEMBERS[etype]
    for member in event:
        if member not in allowed:
            raise Refusal("unknown_member", member)
    for member in allowed:
        if member not in event:
            raise Refusal("schema_invalid", f"missing member {member}")
    _text(event["workflow_id"], "workflow_id")
    _text(event["at"], "at")  # caller-supplied opaque data; never decides anything
    seq = event["seq"]
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise Refusal("schema_invalid", "seq must be an integer >= 1")
    for member in allowed:
        if member.endswith("_ref"):
            _text(event[member], member)
    return event


def apply_event(state: State, event) -> State:
    """Return the next state or raise Refusal. Order: shape, workflow, sequence, event bound, transition,
    reserved final slot (Rule R). A non-closing transition is refused (`bound_events_exceeded`) if, after it,
    the workflow could no longer reach observed or reconciled within MAX_EVENTS_PER_WORKFLOW (for example
    `reconcile_inconclusive` is refused at event 16); a closing event (`cancel`, `fail`) needs no remaining slot."""
    if type(state) is not State or state.status not in ALL_STATES:
        raise Refusal("schema_invalid", "invalid state")
    ev = _validate_event(event)
    if state.workflow_id is not None and ev["workflow_id"] != state.workflow_id:
        raise Refusal("workflow_mismatch", ev["workflow_id"])
    if ev["seq"] != state.event_count + 1:
        raise Refusal("sequence_mismatch", f"expected {state.event_count + 1}, got {ev['seq']}")
    if state.event_count >= MAX_EVENTS_PER_WORKFLOW:
        raise Refusal("bound_events_exceeded", str(MAX_EVENTS_PER_WORKFLOW))
    key = (state.status, ev["type"])
    if key not in TRANSITIONS:
        raise Refusal(REFUSALS[key], f"{ev['type']} from {state.status}")
    if not _room_to_complete(state.event_count, ev["type"], TRANSITIONS[key]):
        raise Refusal("bound_events_exceeded", f"final event slot reserved: {ev['type']}")
    new_refs = state.refs + tuple((ev["type"], ev[m]) for m in _ref_names(ev["type"]))
    return State(ev["workflow_id"], TRANSITIONS[key], state.event_count + 1, new_refs,
                 state.history + (ev["type"],))


def replay(events: Iterable) -> State:
    """Fold events through the machine from the initial state. Raises Refusal on the first bad event."""
    state = initial_state()
    for event in events:
        state = apply_event(state, event)
    return state


def next_actions(state: State) -> tuple:
    """Event types legal for `state` right now, in canonical order. Performs nothing."""
    if type(state) is not State or state.status not in ALL_STATES:
        raise Refusal("schema_invalid", "invalid state")
    if state.event_count >= MAX_EVENTS_PER_WORKFLOW:
        return ()
    return tuple(e for e in EVENT_TYPES
                 if (state.status, e) in TRANSITIONS
                 and _room_to_complete(state.event_count, e, TRANSITIONS[(state.status, e)]))


def describe(state: State) -> dict:
    """Truthful, verdict-free description. `effect_outcome` is never success, failure or absence:
    it is `none` (nothing dispatched, including `suspended`, `failed` and `cancelled`, which say nothing about
    any effect), `unknown` (dispatched or unresolved), or a reference status.
    `observation_referenced` and `reconciliation_referenced` mean only that a reference string was
    recorded: its content is never dereferenced or checked here (`refs_content_checked` is False)."""
    if type(state) is not State or state.status not in ALL_STATES:
        raise Refusal("schema_invalid", "invalid state")
    if state.status in (INITIAL, "proposed", "awaiting_authority", "authorized", "suspended", "failed",
                        "cancelled"):  # failed/cancelled/suspended are only reachable before any dispatch
        outcome = "none"
    elif state.status in ("dispatched", "unresolved"):
        outcome = "unknown"
    elif state.status == "observed":
        outcome = "observation_referenced"
    else:
        outcome = "reconciliation_referenced"
    return {"workflow_id": state.workflow_id, "status": state.status, "event_count": state.event_count,
            "terminal": state.status in TERMINAL_STATUSES, "effect_outcome": outcome,
            "closure_class": CLOSURE_CLASS_OF.get(state.status, "open"),
            "slot_class": SLOT_CLASS_OF.get(state.status, "none"),
            "refs": [list(r) for r in state.refs], "refs_content_checked": False}


@dataclass(frozen=True)
class Fleet:
    """Immutable set of workflow states, keyed by workflow id. Construction does not enforce capacity: a
    restart may find more records than today's bounds and must still replay (see `over_limit`)."""
    states: Mapping

    def __post_init__(self) -> None:
        # Snapshot first (a hostile Mapping may answer differently on each read), then validate the copy.
        if not isinstance(self.states, Mapping):
            raise Refusal("schema_invalid", "fleet states must be a mapping")
        try:
            snap = dict(self.states)
        except Exception:
            raise Refusal("schema_invalid", "fleet states could not be copied") from None
        for wid, st in snap.items():
            if not isinstance(st, State) or not isinstance(wid, str) or st.workflow_id != wid:
                raise Refusal("schema_invalid", "fleet entries must be State objects keyed by their workflow_id")
        object.__setattr__(self, "states", MappingProxyType(snap))

    def slot_counts(self) -> dict:
        """Counts by slot class, derived from status only. `closed` are terminal workflows not yet released."""
        out = {"execution": 0, "waiting": 0, "closed": 0}
        for st in self.states.values():
            out[SLOT_CLASS_OF[st.status]] += 1
        return out

    def active_count(self) -> int:
        """Workflows in the execution class only. Waiting records are not execution capacity."""
        return self.slot_counts()["execution"]

    def over_limit(self) -> tuple:
        """Names of the classes whose count exceeds today's bound (empty when within). Never refuses; a
        restart reports this and only new admissions are refused."""
        c = self.slot_counts()
        return tuple(n for n, count, bound in (("execution", c["execution"], MAX_ACTIVE_EXECUTION_SLOTS),
                                               ("waiting", c["waiting"], MAX_WAITING_RECORDS)) if count > bound)


def _fleet(states: dict) -> Fleet:
    return Fleet(states)


def _step_fleet(fleet: Fleet, event, enforce: bool) -> Fleet:
    ev = _validate_event(event)
    wid = ev["workflow_id"]
    current = fleet.states.get(wid)
    if enforce:
        counts = fleet.slot_counts()
        if current is None:
            if ev["type"] == "propose" and counts["waiting"] >= MAX_WAITING_RECORDS:
                raise Refusal("bound_waiting_exceeded", str(MAX_WAITING_RECORDS))
        elif ev["type"] == "record_authorized" and current.status == "awaiting_authority" \
                and counts["execution"] >= MAX_ACTIVE_EXECUTION_SLOTS:
            # The workflow stays awaiting_authority (a waiting record): the decision reference is not lost.
            raise Refusal("bound_execution_slots_exceeded", str(MAX_ACTIVE_EXECUTION_SLOTS))
    if current is None:
        current = initial_state()
    new = apply_event(current, ev)
    states = dict(fleet.states)
    states[wid] = new
    return _fleet(states)


def apply_fleet(fleet: Fleet, event) -> Fleet:
    """Apply an event to its workflow as a new admission. Order: shape, capacity, then the machine's own order
    (workflow, sequence, event bound, transition, reserved final slot). Capacity: a `propose` for a new workflow
    is refused at MAX_WAITING_RECORDS waiting records (`bound_waiting_exceeded`); `record_authorized` is refused
    at MAX_ACTIVE_EXECUTION_SLOTS execution workflows (`bound_execution_slots_exceeded`). Moves from execution to
    waiting (`record_outcome_unknown`, `crash_recovered`, `suspend`) are never refused for capacity, so an
    unknown outcome can always be recorded. A duplicate propose for a known workflow is refused by the machine."""
    if type(fleet) is not Fleet:
        raise Refusal("schema_invalid", "invalid fleet")
    return _step_fleet(fleet, event, True)


def replay_fleet(events: Iterable) -> Fleet:
    """Rebuild a fleet from persisted events. Capacity is an admission control, not a replay check: a legal
    history is never refused because a bound was lowered or exceeded (use `Fleet.over_limit`)."""
    fleet = _fleet({})
    for event in events:
        fleet = _step_fleet(fleet, event, False)
    return fleet


def release_terminal(fleet: Fleet, workflow_id: str):
    """Return (new fleet without the workflow, receipt) for a terminal workflow. Pure; it archives nothing.
    Call it only after the store's archive receipt exists. Refusals: `open_effect_refused` for `dispatched` or
    `unresolved` (an unresolved effect is never released or archived as completed), `not_releasable` for any
    other non-terminal status or an unknown workflow."""
    if type(fleet) is not Fleet:
        raise Refusal("schema_invalid", "invalid fleet")
    st = fleet.states.get(workflow_id) if isinstance(workflow_id, str) else None
    if st is None:
        raise Refusal("not_releasable", "unknown workflow")
    if st.status in OPEN_EFFECT_STATUSES:
        raise Refusal("open_effect_refused", st.status)
    if st.status not in TERMINAL_STATUSES:
        raise Refusal("not_releasable", st.status)
    states = dict(fleet.states)
    del states[workflow_id]
    receipt = {"workflow_id": workflow_id, "terminal_status": st.status,
               "closure_class": CLOSURE_CLASS_OF[st.status], "event_count": st.event_count}
    return _fleet(states), receipt


def restart_recovery_needed(fleet: Fleet) -> tuple:
    """Workflow ids that a restart must record `crash_recovered` for: those replayed as `dispatched` (the hand-off
    may have happened, the outcome is unknown). Sorted; pure. Nothing else is resumed, closed or released by a
    restart: held, suspended and unresolved workflows stay as they are."""
    if type(fleet) is not Fleet:
        raise Refusal("schema_invalid", "invalid fleet")
    return tuple(sorted(w for w, st in fleet.states.items() if st.status == "dispatched"))
