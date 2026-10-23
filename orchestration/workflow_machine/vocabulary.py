"""Closed vocabulary and the explicit transition table. Data only; no logic, no I/O.

Candidate, non-authorizing. Release and production remain on HOLD.
"""
from __future__ import annotations

# Reserved statuses (orchestration/state-transitions/README.md). INITIAL is the pre-state of a
# workflow that has seen no event; it is not a reported status.
INITIAL = "initial"
STATUSES = (
    "proposed", "awaiting_authority", "authorized", "dispatched", "observed", "unresolved", "reconciled",
    "suspended", "failed", "cancelled",
)
TERMINAL_STATUSES = ("observed", "reconciled", "failed", "cancelled")
ALL_STATES = (INITIAL,) + STATUSES

# Candidate, provisional vocabulary identity (step 3.2-A amendment of Q1). The pre-amendment vocabulary is
# retroactively `ocs-workflow-machine/0`. These are coordination names only; neither is a wire profile of
# the store (the store envelope `ocs-workflow-event/0` is unchanged and carries opaque event kinds).
MACHINE_PROFILE = "ocs-workflow-machine/1"
PREDECESSOR_MACHINE_PROFILE = "ocs-workflow-machine/0"

# Derived classifications (data only; never a status, never an effect claim).
# `completed` is a closure class over observed/reconciled: it records that a reference string was supplied,
# not that an effect was verified or settled correctly.
CLOSURE_CLASSES = ("open", "completed", "failed", "cancelled")
CLOSURE_CLASS_OF = {
    "observed": "completed", "reconciled": "completed", "failed": "failed", "cancelled": "cancelled",
}
# Slot classes (derived from replayed status only, never a separate counter). `execution` is the only span
# in which a hand-off to the gate can start; `waiting` records are durable records, not execution capacity.
SLOT_CLASSES = ("none", "execution", "waiting", "closed")
SLOT_CLASS_OF = {
    "authorized": "execution", "dispatched": "execution",
    "proposed": "waiting", "awaiting_authority": "waiting", "suspended": "waiting", "unresolved": "waiting",
    "observed": "closed", "reconciled": "closed", "failed": "closed", "cancelled": "closed",
}
# Statuses with a possibly started effect: no closing event, no release, never archived as completed.
OPEN_EFFECT_STATUSES = ("dispatched", "unresolved")

# Closed event set, in canonical order (next_actions reports in this order).
EVENT_TYPES = (
    "propose",                 # initial -> proposed
    "request_authority",       # proposed -> awaiting_authority
    "record_authorized",       # awaiting_authority -> authorized (reference to a Control Plane decision)
    "dispatch",                # authorized -> dispatched (write-ahead record of the hand-off to the gate)
    "record_observation",      # dispatched -> observed (reference to an independent observation record)
    "record_outcome_unknown",  # dispatched -> unresolved
    "crash_recovered",         # dispatched -> unresolved (restart: outcome unknown, reconcile only)
    "reconcile",               # unresolved -> reconciled (reference to independently observed evidence)
    "reconcile_inconclusive",  # unresolved -> unresolved (evidence still does not settle it)
    "suspend",                 # proposed/awaiting_authority/authorized -> suspended (pause; not termination)
    "resume",                  # suspended -> proposed (the old authorization is never restored)
    "cancel",                  # pre-dispatch -> cancelled (coordination only; reverses nothing)
    "fail",                    # pre-dispatch -> failed (orchestration could not continue; not an effect claim)
)
# Events that close a workflow. They need no remaining event slot to complete (see apply_event).
CLOSING_EVENTS = ("cancel", "fail")

# Exact members of each event. Every event has the common members; refs are reference text only.
COMMON_MEMBERS = ("type", "workflow_id", "seq", "at")
EVENT_MEMBERS = {
    "propose": COMMON_MEMBERS + ("proposal_ref",),
    "request_authority": COMMON_MEMBERS,
    "record_authorized": COMMON_MEMBERS + ("decision_ref",),
    "dispatch": COMMON_MEMBERS + ("dispatch_ref",),
    "record_observation": COMMON_MEMBERS + ("observation_ref",),
    "record_outcome_unknown": COMMON_MEMBERS,
    "crash_recovered": COMMON_MEMBERS,
    "reconcile": COMMON_MEMBERS + ("observation_ref",),
    "reconcile_inconclusive": COMMON_MEMBERS + ("observation_ref",),
    "suspend": COMMON_MEMBERS + ("suspension_ref",),
    "resume": COMMON_MEMBERS + ("resume_ref",),
    "cancel": COMMON_MEMBERS + ("cancellation_ref",),
    "fail": COMMON_MEMBERS + ("failure_ref",),
}

# Member-name tokens that only choose the refusal code (forbidden_member rather than unknown_member).
# The exact per-event member allow-list (EVENT_MEMBERS) is the guard: any member not on it is refused
# either way. Substring families (verdict, grant, permission, authority, authoriz) are matched in
# machine._forbidden, so their token spellings are not repeated here.
FORBIDDEN_MEMBER_TOKENS = (
    "pin", "pins", "approve", "approved", "approval", "allow", "allowed", "deny", "denied", "pass",
    "passed", "fail", "failed", "success", "succeeded", "verified", "certified", "qualified",
    "result", "outcome", "decision_result", "label", "expectation", "oracle", "retry", "attempts",
)

MAX_EVENTS_PER_WORKFLOW = 16
# Unqualified upper bounds, not demonstrated safe defaults, and not configurable here (configurable bounds
# and capacity accounting are step 3.2-B). The two classes are counted separately: held, denied and
# suspended workflows and unresolved effects are waiting records and never consume an execution slot.
MAX_ACTIVE_EXECUTION_SLOTS = 64
MAX_WAITING_RECORDS = 1000

# Closed refusal codes.
REFUSAL_CODES = (
    "schema_invalid",
    "unknown_event_type",
    "unknown_member",
    "forbidden_member",
    "workflow_mismatch",
    "sequence_mismatch",
    "authority_required",
    "blind_retry_refused",
    "illegal_transition",
    "bound_events_exceeded",
    "bound_execution_slots_exceeded",
    "bound_waiting_exceeded",
    "open_effect_refused",
    "workflow_closed",
    "not_releasable",
)

# The whole table: (state, event) -> next status. Every other cell is a refusal (REFUSALS).
TRANSITIONS = {
    (INITIAL, "propose"): "proposed",
    ("proposed", "request_authority"): "awaiting_authority",
    ("awaiting_authority", "record_authorized"): "authorized",
    ("authorized", "dispatch"): "dispatched",
    ("dispatched", "record_observation"): "observed",
    ("dispatched", "record_outcome_unknown"): "unresolved",
    ("dispatched", "crash_recovered"): "unresolved",
    ("unresolved", "reconcile"): "reconciled",
    ("unresolved", "reconcile_inconclusive"): "unresolved",
    ("proposed", "suspend"): "suspended",
    ("awaiting_authority", "suspend"): "suspended",
    ("authorized", "suspend"): "suspended",
    ("suspended", "resume"): "proposed",
    ("proposed", "cancel"): "cancelled",
    ("awaiting_authority", "cancel"): "cancelled",
    ("authorized", "cancel"): "cancelled",
    ("suspended", "cancel"): "cancelled",
    ("proposed", "fail"): "failed",
    ("awaiting_authority", "fail"): "failed",
    ("authorized", "fail"): "failed",
    ("suspended", "fail"): "failed",
}


def _refusals() -> dict:
    """Refusal code for every cell that is not in TRANSITIONS (computed once, total over the matrix)."""
    out = {}
    for s in ALL_STATES:
        for e in EVENT_TYPES:
            if (s, e) in TRANSITIONS:
                continue
            if s in ("failed", "cancelled"):
                out[(s, e)] = "workflow_closed"  # closed: neither a blind retry nor missing authority is the reason
            elif e in ("suspend", "cancel", "fail") and s in OPEN_EFFECT_STATUSES:
                # After a persisted dispatch the hand-off may have happened: no closing, no suspension.
                out[(s, e)] = "open_effect_refused"
            elif e == "dispatch":
                # A dispatch is only legal from authorized. From a state where a dispatch was already
                # recorded it would be a blind retry; before authorization it lacks authority.
                out[(s, e)] = ("blind_retry_refused" if s in ("dispatched", "observed", "unresolved", "reconciled")
                               else "authority_required")
            else:
                out[(s, e)] = "illegal_transition"
    return out


REFUSALS = _refusals()


COMPLETION_STATUSES = ("observed", "reconciled")


def _events_to_completion() -> dict:
    """Events needed to be certain of reaching observed or reconciled, per status. Every status takes the
    fewest events over its exits except `dispatched`, which takes the worst exit: the outcome may turn out
    unknown (`record_outcome_unknown`, `crash_recovered`), after which `reconcile` is still needed, so a
    dispatched workflow always keeps room for both. `failed` and `cancelled` cannot complete and are absent."""
    dist = {s: 0 for s in COMPLETION_STATUSES}
    changed = True
    while changed:
        changed = False
        for s in STATUSES + (INITIAL,):
            nxt = [t for (a, _e), t in TRANSITIONS.items() if a == s and t in dist and t != s]
            if not nxt:
                continue
            d = 1 + (max(dist[t] for t in nxt) if s == "dispatched" else min(dist[t] for t in nxt))
            if s in ("dispatched",) and any(t not in dist for (a, _e), t in TRANSITIONS.items()
                                             if a == s and t != s):
                continue  # wait until every exit of dispatched is known
            if d < dist.get(s, 1 << 30):
                dist[s] = d
                changed = True
    return dist


# Rule R: a non-closing event is accepted only if completion still fits in MAX_EVENTS_PER_WORKFLOW after it,
# so a dispatched workflow keeps room to record an unknown outcome and then reconcile, and the last slot stays reserved.
# A closing event (cancel, fail) terminates the workflow and needs no remaining slot.
EVENTS_TO_COMPLETION = _events_to_completion()

# Explicit raises, not asserts: these checks must survive `python -O`.
if not all(code in REFUSAL_CODES for code in REFUSALS.values()):
    raise RuntimeError("vocabulary: refusal code outside the closed set")
if set(TRANSITIONS) | set(REFUSALS) != {(s, e) for s in ALL_STATES for e in EVENT_TYPES}:
    raise RuntimeError("vocabulary: table is not total over states x events")
if set(TRANSITIONS) & set(REFUSALS):
    raise RuntimeError("vocabulary: a cell is both a transition and a refusal")
if set(EVENTS_TO_COMPLETION) != (set(STATUSES) - {"failed", "cancelled"}) | {INITIAL}:
    raise RuntimeError("vocabulary: a status cannot reach completion")
if set(SLOT_CLASS_OF) != set(STATUSES) or set(CLOSURE_CLASS_OF) != set(TERMINAL_STATUSES):
    raise RuntimeError("vocabulary: slot or closure class table is not total")
if any(
        s in OPEN_EFFECT_STATUSES and t in ("suspended", "failed", "cancelled") for (s, _e), t in TRANSITIONS.items()):
    raise RuntimeError("vocabulary: an open effect has a closing or suspending transition")
if any(s in TERMINAL_STATUSES for (s, _e) in TRANSITIONS):
    raise RuntimeError("vocabulary: a transition leaves a terminal status")
