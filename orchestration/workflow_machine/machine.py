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
    ALL_STATES, EVENTS_TO_TERMINAL, EVENT_MEMBERS, EVENT_TYPES, FORBIDDEN_MEMBER_TOKENS, INITIAL, MAX_CONCURRENT_WORKFLOWS,
    MAX_EVENTS_PER_WORKFLOW, REFUSAL_CODES, REFUSALS, STATUSES, TERMINAL_STATUSES, TRANSITIONS,
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


# Event-type spine of each status: (types that carry a reference, in order, then the event count).
# `unresolved` and `reconciled` add one `reconcile_inconclusive` reference and one event per extra loop.
_SPINE = {
    "proposed": (("propose",), 1),
    "awaiting_authority": (("propose",), 2),
    "authorized": (("propose", "record_authorized"), 3),
    "dispatched": (("propose", "record_authorized", "dispatch"), 4),
    "observed": (("propose", "record_authorized", "dispatch", "record_observation"), 5),
    "unresolved": (("propose", "record_authorized", "dispatch"), 5),
    "reconciled": (("propose", "record_authorized", "dispatch"), 6),
}


def _check_state(workflow_id, status, event_count, refs) -> None:
    """Consistency of the four fields with each other. This is a forgery guard for hand-built states,
    not a proof of history: reference text and `at` are not re-derivable, and `record_outcome_unknown`
    versus `crash_recovered` leave no trace in `refs`. Persisted states should still be rebuilt only
    through `replay`."""
    if not isinstance(status, str) or status not in ALL_STATES:
        raise Refusal("schema_invalid", "state status outside the closed set")
    if isinstance(event_count, bool) or not isinstance(event_count, int):
        raise Refusal("schema_invalid", "state event_count must be an integer")
    if not isinstance(refs, tuple) or not all(
            isinstance(r, tuple) and len(r) == 2 and r[0] in EVENT_TYPES and isinstance(r[1], str) and r[1]
            for r in refs):
        raise Refusal("schema_invalid", "state refs must be a tuple of (event type, reference) pairs")
    if status == INITIAL:
        if workflow_id is not None or event_count != 0 or refs != ():
            raise Refusal("schema_invalid", "initial state must have no workflow, events or refs")
        return
    _text(workflow_id, "state workflow_id")
    base_types, base_count = _SPINE[status]
    extra = event_count - base_count
    if extra < 0 or (extra > 0 and status not in ("unresolved", "reconciled")):
        raise Refusal("schema_invalid", f"event_count {event_count} impossible for {status}")
    if event_count > MAX_EVENTS_PER_WORKFLOW or (
            status == "unresolved" and event_count >= MAX_EVENTS_PER_WORKFLOW):  # final slot is reserved
        raise Refusal("schema_invalid", f"event_count {event_count} beyond the bound for {status}")
    types = base_types + ("reconcile_inconclusive",) * extra + (("reconcile",) if status == "reconciled" else ())
    if tuple(r[0] for r in refs) != types:
        raise Refusal("schema_invalid", f"refs do not match the event spine of {status}")


@dataclass(frozen=True)
class State:
    """Immutable workflow state. `refs` is the ordered record of (event type, reference) pairs.
    Fields are checked for mutual consistency on construction (see `_check_state`); `at` is not kept."""
    workflow_id: str | None
    status: str  # INITIAL or one of STATUSES
    event_count: int
    refs: tuple

    def __post_init__(self) -> None:
        _check_state(self.workflow_id, self.status, self.event_count, self.refs)


def initial_state() -> State:
    return State(workflow_id=None, status=INITIAL, event_count=0, refs=())


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
    reserved final slot. A transition is refused (`bound_events_exceeded`) if, after it, the workflow
    could no longer reach a terminal status within MAX_EVENTS_PER_WORKFLOW; so the last slot is kept
    for an event that terminates (for example `reconcile_inconclusive` is refused at event 16)."""
    if not isinstance(state, State) or state.status not in ALL_STATES:
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
    if not _room_to_terminate(state, TRANSITIONS[key]):
        raise Refusal("bound_events_exceeded", f"final event slot reserved for a terminating event: {ev['type']}")
    ref_names = [m for m in EVENT_MEMBERS[ev["type"]] if m.endswith("_ref")]
    new_refs = state.refs + tuple((ev["type"], ev[m]) for m in ref_names)
    return State(ev["workflow_id"], TRANSITIONS[key], state.event_count + 1, new_refs)


def _room_to_terminate(state: State, new_status: str) -> bool:
    return MAX_EVENTS_PER_WORKFLOW - (state.event_count + 1) >= EVENTS_TO_TERMINAL[new_status]


def replay(events: Iterable) -> State:
    """Fold events through the machine from the initial state. Raises Refusal on the first bad event."""
    state = initial_state()
    for event in events:
        state = apply_event(state, event)
    return state


def next_actions(state: State) -> tuple:
    """Event types legal for `state` right now, in canonical order. Performs nothing."""
    if not isinstance(state, State) or state.status not in ALL_STATES:
        raise Refusal("schema_invalid", "invalid state")
    if state.event_count >= MAX_EVENTS_PER_WORKFLOW:
        return ()
    return tuple(e for e in EVENT_TYPES
                 if (state.status, e) in TRANSITIONS and _room_to_terminate(state, TRANSITIONS[(state.status, e)]))


def describe(state: State) -> dict:
    """Truthful, verdict-free description. `effect_outcome` is never success, failure or absence:
    it is `none` (nothing dispatched), `unknown` (dispatched or unresolved), or a reference status.
    `observation_referenced` and `reconciliation_referenced` mean only that a reference string was
    recorded: its content is never dereferenced or checked here (`refs_content_checked` is False)."""
    if state.status in (INITIAL, "proposed", "awaiting_authority", "authorized"):
        outcome = "none"
    elif state.status in ("dispatched", "unresolved"):
        outcome = "unknown"
    elif state.status == "observed":
        outcome = "observation_referenced"
    else:
        outcome = "reconciliation_referenced"
    return {"workflow_id": state.workflow_id, "status": state.status, "event_count": state.event_count,
            "terminal": state.status in TERMINAL_STATUSES, "effect_outcome": outcome,
            "refs": [list(r) for r in state.refs], "refs_content_checked": False}


@dataclass(frozen=True)
class Fleet:
    """Immutable set of workflow states, keyed by workflow id."""
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
        if sum(1 for st in snap.values() if st.status not in TERMINAL_STATUSES) > MAX_CONCURRENT_WORKFLOWS:
            raise Refusal("bound_workflows_exceeded", str(MAX_CONCURRENT_WORKFLOWS))
        object.__setattr__(self, "states", MappingProxyType(snap))

    def active_count(self) -> int:
        return sum(1 for s in self.states.values() if s.status not in TERMINAL_STATUSES)


def _fleet(states: dict) -> Fleet:
    return Fleet(states)


def apply_fleet(fleet: Fleet, event) -> Fleet:
    """Apply an event to its workflow. Order: shape, fleet bound (propose for a new workflow), then the
    machine's own order (workflow, sequence, event bound, transition, reserved final slot). A propose that would exceed MAX_CONCURRENT_WORKFLOWS
    active workflows is refused; a duplicate propose for a known workflow is refused by the machine."""
    ev = _validate_event(event)
    wid = ev["workflow_id"]
    current = fleet.states.get(wid)
    if current is None:
        if ev["type"] == "propose" and fleet.active_count() >= MAX_CONCURRENT_WORKFLOWS:
            raise Refusal("bound_workflows_exceeded", str(MAX_CONCURRENT_WORKFLOWS))
        current = initial_state()
    new = apply_event(current, ev)
    states = dict(fleet.states)
    states[wid] = new
    return _fleet(states)


def replay_fleet(events: Iterable) -> Fleet:
    fleet = _fleet({})
    for event in events:
        fleet = apply_fleet(fleet, event)
    return fleet
