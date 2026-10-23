"""Developer tests for the pure workflow state machine (step 3.2 part A). Not independent acceptance."""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "orchestration"))
import workflow_machine as wm  # noqa: E402
from workflow_machine import vocabulary as voc  # noqa: E402

W = "wf-1"
REFS = {"propose": "proposal_ref", "record_authorized": "decision_ref", "dispatch": "dispatch_ref",
        "record_observation": "observation_ref", "reconcile": "observation_ref",
        "reconcile_inconclusive": "observation_ref"}


def ev(etype: str, seq: int, wid: str = W, **over) -> dict:
    e = {"type": etype, "workflow_id": wid, "seq": seq, "at": "2026-01-01T00:00:00Z"}
    if etype in REFS:
        e[REFS[etype]] = f"{etype}-ref"
    e.update(over)
    return e


def state_at(status: str) -> "wm.State":
    """A state with the given status, reached only through legal events."""
    paths = {
        "initial": [], "proposed": ["propose"],
        "awaiting_authority": ["propose", "request_authority"],
        "authorized": ["propose", "request_authority", "record_authorized"],
        "dispatched": ["propose", "request_authority", "record_authorized", "dispatch"],
        "observed": ["propose", "request_authority", "record_authorized", "dispatch", "record_observation"],
        "unresolved": ["propose", "request_authority", "record_authorized", "dispatch", "record_outcome_unknown"],
        "reconciled": ["propose", "request_authority", "record_authorized", "dispatch",
                       "record_outcome_unknown", "reconcile"],
    }
    return wm.replay([ev(t, i + 1) for i, t in enumerate(paths[status])])


# ---------------------------------------------------------------- vocabulary and table

def test_vocabulary_is_the_reserved_set():
    assert voc.STATUSES == ("proposed", "awaiting_authority", "authorized", "dispatched",
                            "observed", "unresolved", "reconciled")
    assert len(set(voc.EVENT_TYPES)) == len(voc.EVENT_TYPES) == 9
    assert set(voc.EVENT_MEMBERS) == set(voc.EVENT_TYPES)


def test_full_matrix_exhaustive():
    expected = {
        ("initial", "propose"): "proposed", ("proposed", "request_authority"): "awaiting_authority",
        ("awaiting_authority", "record_authorized"): "authorized", ("authorized", "dispatch"): "dispatched",
        ("dispatched", "record_observation"): "observed", ("dispatched", "record_outcome_unknown"): "unresolved",
        ("dispatched", "crash_recovered"): "unresolved", ("unresolved", "reconcile"): "reconciled",
        ("unresolved", "reconcile_inconclusive"): "unresolved",
    }
    assert dict(voc.TRANSITIONS) == expected
    for status, etype in itertools.product(voc.ALL_STATES, voc.EVENT_TYPES):
        s = state_at(status)
        event = ev(etype, s.event_count + 1, wid=s.workflow_id or W)
        if (status, etype) in expected:
            n = wm.apply_event(s, event)
            assert n.status == expected[(status, etype)] and n.event_count == s.event_count + 1
            assert etype in wm.next_actions(s)
        else:
            with pytest.raises(wm.Refusal) as ei:
                wm.apply_event(s, event)
            assert ei.value.code == voc.REFUSALS[(status, etype)]
            assert ei.value.code in {"illegal_transition", "authority_required", "blind_retry_refused"}
            assert etype not in wm.next_actions(s)
            assert s == state_at(status)  # input unchanged


def test_refusal_codes_for_dispatch_cells():
    for status in ("initial", "proposed", "awaiting_authority"):
        assert voc.REFUSALS[(status, "dispatch")] == "authority_required"
    for status in ("dispatched", "observed", "unresolved", "reconciled"):
        assert voc.REFUSALS[(status, "dispatch")] == "blind_retry_refused"


def test_terminal_states_have_no_actions():
    for status in voc.TERMINAL_STATUSES:
        assert wm.next_actions(state_at(status)) == ()


def test_next_actions_lists_only_legal_events_in_canonical_order():
    assert wm.next_actions(state_at("initial")) == ("propose",)
    assert wm.next_actions(state_at("dispatched")) == ("record_observation", "record_outcome_unknown", "crash_recovered")
    assert wm.next_actions(state_at("unresolved")) == ("reconcile", "reconcile_inconclusive")
    assert "dispatch" not in wm.next_actions(state_at("unresolved"))


# ---------------------------------------------------------------- invariants (property style)

def _all_legal_paths(max_len: int):
    """Every legal event-type sequence up to max_len from the initial state."""
    frontier = [((), "initial")]
    for _ in range(max_len + 1):
        nxt = []
        for path, status in frontier:
            yield path, status
            for e in voc.EVENT_TYPES:
                if (status, e) in voc.TRANSITIONS:
                    nxt.append((path + (e,), voc.TRANSITIONS[(status, e)]))
        frontier = nxt


def _events(path):
    return [ev(t, i + 1) for i, t in enumerate(path)]


def test_dispatched_only_via_authorized_and_unresolved_never_directly_dispatched():
    seen = 0
    for path, _ in _all_legal_paths(8):
        evs = _events(path)
        status = "initial"
        for i, t in enumerate(path):
            prev, status = status, voc.TRANSITIONS[(status, t)]
            if status == "dispatched":
                assert prev == "authorized" and t == "dispatch"
                assert "record_authorized" in path[:i]
            if prev == "unresolved":
                assert status in ("unresolved", "reconciled")  # never dispatched/observed directly
            seen += 1
        assert wm.replay(evs).status == status
    assert seen > 100


def test_dispatch_count_at_most_one_on_any_legal_path():
    for path, _ in _all_legal_paths(10):
        assert path.count("dispatch") <= 1


def test_unresolved_leaves_only_by_explicit_reconcile():
    for path, _ in _all_legal_paths(9):
        status = "initial"
        for t in path:
            prev, status = status, voc.TRANSITIONS[(status, t)]
            if prev == "unresolved" and status != "unresolved":
                assert t == "reconcile" and status == "reconciled"


def test_replay_of_every_legal_prefix_is_deterministic_and_matches_incremental():
    for path, _ in _all_legal_paths(8):
        evs = _events(path)
        a, b = wm.replay(evs), wm.replay([dict(e) for e in evs])
        assert a == b and hash(a) == hash(b)
        s = wm.initial_state()
        for e in evs:
            s = wm.apply_event(s, e)
        assert s == a


def test_timestamp_never_decides_anything():
    base = _events(("propose", "request_authority", "record_authorized", "dispatch", "record_outcome_unknown"))
    for at in ("1970-01-01", "9999-12-31", "not even a date", "x"):
        evs = [dict(e, at=at) for e in base]
        assert wm.replay(evs).status == "unresolved"


def test_describe_never_reports_success_failure_or_absence():
    allowed = {"none", "unknown", "observation_referenced", "reconciliation_referenced"}
    for status in voc.ALL_STATES:
        d = wm.describe(state_at(status))
        assert d["effect_outcome"] in allowed
        assert not any(w in str(d["effect_outcome"]) for w in ("success", "fail", "absent", "applied"))
    for status in ("dispatched", "unresolved"):
        assert wm.describe(state_at(status))["effect_outcome"] == "unknown"
    # an inconclusive reconciliation stays unknown
    s = wm.apply_event(state_at("unresolved"), ev("reconcile_inconclusive", 6))
    assert s.status == "unresolved" and wm.describe(s)["effect_outcome"] == "unknown"


def test_crash_continuation_is_reconcile_only():
    s = wm.apply_event(state_at("dispatched"), ev("crash_recovered", 5))
    assert s.status == "unresolved"
    assert wm.next_actions(s) == ("reconcile", "reconcile_inconclusive")
    with pytest.raises(wm.Refusal) as ei:
        wm.apply_event(s, ev("dispatch", 6))
    assert ei.value.code == "blind_retry_refused"


def test_no_transition_or_state_carries_verdict_grant_or_authority_members():
    for members in voc.EVENT_MEMBERS.values():
        assert not [m for m in members if wm.machine._forbidden(m)]
    assert not [f for f in wm.State.__dataclass_fields__ if wm.machine._forbidden(f)]


# ---------------------------------------------------------------- negatives per refusal code

def refusal(state, event) -> str:
    with pytest.raises(wm.Refusal) as ei:
        wm.apply_event(state, event)
    return ei.value.code


def test_refusal_codes_are_closed_and_each_is_exercised():
    assert set(wm.REFUSAL_CODES) == {
        "schema_invalid", "unknown_event_type", "unknown_member", "forbidden_member", "workflow_mismatch",
        "sequence_mismatch", "authority_required", "blind_retry_refused", "illegal_transition",
        "bound_events_exceeded", "bound_workflows_exceeded"}
    with pytest.raises(AssertionError):
        wm.Refusal("some_new_code")


@pytest.mark.parametrize("bad", [
    None, [], "propose", 5,
    {"type": "propose"},                                            # missing members
    ev("propose", 1, at=""), ev("propose", 1, at=5), ev("propose", 1, workflow_id=""),
    ev("propose", 0), ev("propose", True), ev("propose", "1"), ev("propose", 1, proposal_ref=""),
    ev("propose", 1, proposal_ref={"x": 1}), ev("propose", 1, proposal_ref=" padded "),
    ev("propose", 1, proposal_ref="x" * 257), {3: "x", **ev("propose", 1)},
])
def test_schema_invalid(bad):
    assert refusal(wm.initial_state(), bad) == "schema_invalid"


def test_missing_ref_member_is_schema_invalid():
    e = ev("record_authorized", 3)
    del e["decision_ref"]
    assert refusal(state_at("awaiting_authority"), e) == "schema_invalid"


@pytest.mark.parametrize("t", ["", "Propose", "retry", "approve", "grant", "deny", None, 3])
def test_unknown_event_type(t):
    assert refusal(wm.initial_state(), dict(ev("propose", 1), type=t)) == "unknown_event_type"


@pytest.mark.parametrize("m", ["extra", "note", "owner", "decision", "payload"])
def test_unknown_member(m):
    assert refusal(wm.initial_state(), ev("propose", 1, **{m: "x"})) == "unknown_member"


@pytest.mark.parametrize("m", [
    "verdict", "grant", "grant_id", "permission", "permissions", "pin", "pin_selection", "authority",
    "authority_context", "authorized", "approved", "decision_result", "result", "outcome", "success",
    "passed", "failed", "verified", "retry", "retry_count", "allow", "deny", "label", "Verdict",
    "expectation", "oracle", "certified", "grantedBy", "granted", "x-grant",
])
def test_verdict_like_or_grant_like_members_are_forbidden(m):
    for etype, s in (("propose", wm.initial_state()), ("record_authorized", state_at("awaiting_authority")),
                     ("reconcile", state_at("unresolved"))):
        assert refusal(s, ev(etype, s.event_count + 1, **{m: "x"})) == "forbidden_member"


def test_forbidden_member_with_non_text_value_is_still_forbidden():
    assert refusal(wm.initial_state(), ev("propose", 1, verdict=True)) == "forbidden_member"
    assert refusal(wm.initial_state(), ev("propose", 1, grant={"scope": "*"})) == "forbidden_member"


def test_workflow_mismatch():
    assert refusal(state_at("proposed"), ev("request_authority", 2, wid="other")) == "workflow_mismatch"


@pytest.mark.parametrize("seq", [1, 3, 99])
def test_sequence_mismatch(seq):
    assert refusal(state_at("proposed"), ev("request_authority", seq)) == "sequence_mismatch"


def test_authority_required_and_blind_retry():
    assert refusal(state_at("proposed"), ev("dispatch", 2)) == "authority_required"
    assert refusal(state_at("awaiting_authority"), ev("dispatch", 3)) == "authority_required"
    assert refusal(wm.initial_state(), ev("dispatch", 1)) == "authority_required"
    assert refusal(state_at("dispatched"), ev("dispatch", 5)) == "blind_retry_refused"
    assert refusal(state_at("unresolved"), ev("dispatch", 6)) == "blind_retry_refused"
    assert refusal(state_at("reconciled"), ev("dispatch", 7)) == "blind_retry_refused"


def test_illegal_transition_leaves_state_unchanged_and_replay_stops():
    s = state_at("authorized")
    before = (s.status, s.event_count, s.refs)
    assert refusal(s, ev("reconcile", 4)) == "illegal_transition"
    assert (s.status, s.event_count, s.refs) == before
    with pytest.raises(wm.Refusal):
        wm.replay([ev("propose", 1), ev("record_authorized", 2)])


def test_replay_requires_propose_first_and_single_workflow():
    with pytest.raises(wm.Refusal) as ei:
        wm.replay([ev("request_authority", 1)])
    assert ei.value.code == "illegal_transition"
    with pytest.raises(wm.Refusal) as ei:
        wm.replay([ev("propose", 1), ev("request_authority", 2, wid="zzz")])
    assert ei.value.code == "workflow_mismatch"
    assert wm.replay([]) == wm.initial_state()


def test_bound_events_per_workflow():
    n = wm.MAX_EVENTS_PER_WORKFLOW
    s = wm.initial_state()
    for e in _events(("propose", "request_authority", "record_authorized", "dispatch", "record_outcome_unknown")):
        s = wm.apply_event(s, e)
    while s.event_count < n:
        s = wm.apply_event(s, ev("reconcile_inconclusive", s.event_count + 1))
    assert s.event_count == n and s.status == "unresolved"
    assert wm.next_actions(s) == ()
    assert refusal(s, ev("reconcile", n + 1)) == "bound_events_exceeded"
    assert s.status == "unresolved"


def test_bound_concurrent_workflows():
    m = wm.MAX_CONCURRENT_WORKFLOWS
    fleet = wm.replay_fleet([ev("propose", 1, wid=f"w{i}") for i in range(m)])
    assert fleet.active_count() == m
    with pytest.raises(wm.Refusal) as ei:
        wm.apply_fleet(fleet, ev("propose", 1, wid="overflow"))
    assert ei.value.code == "bound_workflows_exceeded"
    assert "overflow" not in fleet.states
    # existing workflows still progress; a terminal one frees a slot
    done = wm.replay_fleet([ev(t, i + 1, wid="d") for i, t in enumerate(
        ("propose", "request_authority", "record_authorized", "dispatch", "record_observation"))])
    assert done.active_count() == 0
    f2 = wm.apply_fleet(fleet, ev("request_authority", 2, wid="w0"))
    assert f2.states["w0"].status == "awaiting_authority" and fleet.states["w0"].status == "proposed"


def test_fleet_duplicate_propose_and_unknown_workflow_event_refused():
    fleet = wm.replay_fleet([ev("propose", 1)])
    with pytest.raises(wm.Refusal) as ei:
        wm.apply_fleet(fleet, ev("propose", 2))
    assert ei.value.code == "illegal_transition"
    with pytest.raises(wm.Refusal):
        wm.apply_fleet(fleet, ev("request_authority", 1, wid="ghost"))


def test_state_and_fleet_are_immutable():
    s = state_at("proposed")
    with pytest.raises(Exception):
        s.status = "authorized"  # type: ignore[misc]
    fleet = wm.replay_fleet([ev("propose", 1)])
    with pytest.raises(TypeError):
        fleet.states["x"] = s  # type: ignore[index]


def test_module_has_no_io_clock_or_random_imports():
    src = "".join(p.read_text() for p in (ROOT / "orchestration/workflow_machine").glob("*.py"))
    for banned in ("import time", "import datetime", "import random", "import os", "import subprocess",
                   "import socket", "import sqlite3", "import secrets", "import uuid", "open(",
                   "workflow_store", "handoff"):
        assert banned not in src, banned
