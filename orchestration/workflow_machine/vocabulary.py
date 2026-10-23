"""Closed vocabulary and the explicit transition table. Data only; no logic, no I/O.

Candidate, non-authorizing. Release and production remain on HOLD.
"""
from __future__ import annotations

# Reserved statuses (orchestration/state-transitions/README.md). INITIAL is the pre-state of a
# workflow that has seen no event; it is not a reported status.
INITIAL = "initial"
STATUSES = (
    "proposed", "awaiting_authority", "authorized", "dispatched", "observed", "unresolved", "reconciled",
)
TERMINAL_STATUSES = ("observed", "reconciled")
ALL_STATES = (INITIAL,) + STATUSES

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
)

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
}

# Member-name tokens that mark verdict-, grant-, permission-, pin- or authority-bearing data.
# A member whose name contains any of these tokens is refused as forbidden (not merely unknown).
FORBIDDEN_MEMBER_TOKENS = (
    "verdict", "grant", "grants", "permission", "permissions", "pin", "pins", "authority", "authorization",
    "authorized", "approve", "approved", "approval", "allow", "allowed", "deny", "denied", "pass",
    "passed", "fail", "failed", "success", "succeeded", "verified", "certified", "qualified",
    "result", "outcome", "decision_result", "label", "expectation", "oracle", "retry", "attempts",
)

MAX_EVENTS_PER_WORKFLOW = 16
MAX_CONCURRENT_WORKFLOWS = 64

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
    "bound_workflows_exceeded",
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
}


def _refusals() -> dict:
    """Refusal code for every cell that is not in TRANSITIONS (computed once, total over the matrix)."""
    out = {}
    for s in ALL_STATES:
        for e in EVENT_TYPES:
            if (s, e) in TRANSITIONS:
                continue
            if e == "dispatch":
                # A dispatch is only legal from authorized. From a state where a dispatch was already
                # recorded it would be a blind retry; before authorization it lacks authority.
                out[(s, e)] = ("blind_retry_refused" if s in ("dispatched", "observed", "unresolved", "reconciled")
                               else "authority_required")
            else:
                out[(s, e)] = "illegal_transition"
    return out


REFUSALS = _refusals()
assert all(code in REFUSAL_CODES for code in REFUSALS.values())
assert set(TRANSITIONS) | set(REFUSALS) == {(s, e) for s in ALL_STATES for e in EVENT_TYPES}
assert not set(TRANSITIONS) & set(REFUSALS)
