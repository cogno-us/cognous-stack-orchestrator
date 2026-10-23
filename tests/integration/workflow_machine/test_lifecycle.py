"""Developer tests for the step 3.2-A lifecycle amendment of the pure workflow machine: coordination states
`suspended`, `failed`, `cancelled`, the `completed` closure class, Rule R, slot classes and release.
Not independent acceptance. Coordination states only: none of them says an effect failed, was reversed or
was verified."""
from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "orchestration"))
import workflow_machine as wm  # noqa: E402
from workflow_machine import vocabulary as voc  # noqa: E402

from test_machine import ev, state_at  # noqa: E402

DOC = ROOT / "orchestration/workflow_machine/AMENDMENT-PROPOSAL-Q1-coordination-states.md"
W = "wf-1"


def run(types, wid=W):
    return wm.replay([ev(t, i + 1, wid=wid) for i, t in enumerate(types)])


def code(state, event):
    with pytest.raises(wm.Refusal) as ei:
        wm.apply_event(state, event)
    return ei.value.code


# ------------------------------------------------------------ table versus the design document (the oracle)

def _doc_tables():
    text = DOC.read_text()
    legal = set()
    for m in re.finditer(r"^\| (\w+) \| (\w+) \| (\w+) \|", text, re.M):
        if m.group(1) in voc.ALL_STATES and m.group(2) in voc.EVENT_TYPES and m.group(3) in voc.STATUSES:
            legal.add((m.group(1), m.group(2), m.group(3)))
    header = next(l for l in text.splitlines() if l.startswith("| State | propose |"))
    events = [c.strip() for c in header.strip("|").split("|")][1:]
    matrix = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| ") and cells[0] in ("failed", "cancelled") and cells[1].startswith("workflow_closed"):
            for e in events:
                matrix[(cells[0], e)] = "workflow_closed"
        elif line.startswith("| ") and cells[0] in voc.ALL_STATES and len(cells) == 14:
            for e, c in zip(events, cells[1:]):
                matrix[(cells[0], e)] = c
    return legal, events, matrix


def diff_against_doc(transitions, refusals):
    """Differences between a (transitions, refusals) pair and the document's tables; empty means equal."""
    legal, events, matrix = _doc_tables()
    out = []
    got_legal = {(s, e, t) for (s, e), t in transitions.items()}
    out += [("legal", x) for x in sorted(got_legal ^ legal)]
    for (s, e), c in matrix.items():
        want = ("legal" if c == "legal" else {"I": "illegal_transition"}.get(c, c))
        have = "legal" if (s, e) in transitions else refusals.get((s, e))
        if have != want:
            out.append(("cell", s, e, have, want))
    if len(matrix) != len(voc.ALL_STATES) * len(voc.EVENT_TYPES):
        out.append(("matrix size", len(matrix)))
    return out


def test_document_tables_have_the_expected_shape():
    legal, events, matrix = _doc_tables()
    assert len(legal) == 21 and events == list(voc.EVENT_TYPES) and len(matrix) == 143
    assert sum(1 for c in matrix.values() if c == "legal") == 21


def test_vocabulary_table_equals_the_design_document():
    assert diff_against_doc(dict(voc.TRANSITIONS), dict(voc.REFUSALS)) == []


def test_oracle_catches_a_flipped_cell_a_removed_refusal_and_a_changed_code():
    """Negative control (mutation): the document check must fail if either side changes alone."""
    t, r = dict(voc.TRANSITIONS), dict(voc.REFUSALS)
    t2 = dict(t)
    t2[("dispatched", "cancel")] = "cancelled"  # an open effect gets a closing cell
    r2 = {k: v for k, v in r.items() if k != ("dispatched", "cancel")}
    assert diff_against_doc(t2, r2)
    t3 = dict(t)
    del t3[("authorized", "suspend")]
    assert diff_against_doc(t3, {**r, ("authorized", "suspend"): "illegal_transition"})
    assert diff_against_doc(t, {**r, ("unresolved", "fail"): "illegal_transition"})
    assert diff_against_doc(t, {**r, ("failed", "dispatch"): "blind_retry_refused"})


# ------------------------------------------------------------ meaning of the new coordination states

def test_closing_and_suspension_events_are_refused_from_an_open_effect():
    for status in voc.OPEN_EFFECT_STATUSES:
        s = state_at(status)
        for etype in ("suspend", "cancel", "fail"):
            assert code(s, ev(etype, s.event_count + 1)) == "open_effect_refused"
            assert etype not in wm.next_actions(s)
        assert code(s, ev("resume", s.event_count + 1)) == "illegal_transition"


def test_failed_and_cancelled_are_closed_for_every_event_including_dispatch():
    for status in ("failed", "cancelled"):
        s = state_at(status)
        assert wm.next_actions(s) == ()
        for etype in voc.EVENT_TYPES:
            assert code(s, ev(etype, s.event_count + 1)) == "workflow_closed"


def test_cancellation_cannot_reverse_or_undo_an_effect():
    """Cancel is a pre-dispatch coordination close. From every status where a dispatch was recorded
    (or an outcome was referenced) it is refused or illegal, never a transition."""
    for status in ("dispatched", "unresolved", "observed", "reconciled"):
        s = state_at(status)
        assert code(s, ev("cancel", s.event_count + 1)) in ("open_effect_refused", "illegal_transition")
        assert "cancel" not in wm.next_actions(s)
    # no path contains a dispatch followed by failed/cancelled/suspended
    for (src, _e), dst in voc.TRANSITIONS.items():
        assert not (src in voc.OPEN_EFFECT_STATUSES and dst in ("failed", "cancelled", "suspended"))


def test_no_reachable_history_has_a_dispatch_before_a_close_or_suspension():
    seen, frontier = set(), [wm.initial_state()]
    while frontier:
        nxt = []
        for s in frontier:
            key = (s.status, s.event_count, s.history)
            if key in seen:
                continue
            seen.add(key)
            if s.status in ("failed", "cancelled", "suspended"):
                assert "dispatch" not in s.history
                assert wm.describe(s)["effect_outcome"] == "none"
            for a in wm.next_actions(s):
                nxt.append(wm.apply_event(s, ev(a, s.event_count + 1)))
        frontier = nxt
        if len(seen) > 20000:
            break
    assert len(seen) > 1000


def test_suspension_is_not_termination_and_resume_never_restores_authority():
    s = run(["propose", "request_authority", "record_authorized", "suspend"])
    assert s.status == "suspended" and "suspended" not in voc.TERMINAL_STATUSES
    d = wm.describe(s)
    assert d["terminal"] is False and d["closure_class"] == "open" and d["slot_class"] == "waiting"
    assert d["effect_outcome"] == "none"
    assert wm.next_actions(s) == ("resume", "cancel", "fail")
    assert code(s, ev("dispatch", 5)) == "authority_required"
    assert code(s, ev("record_authorized", 5)) == "illegal_transition"
    assert code(s, ev("suspend", 5)) == "illegal_transition"
    r = wm.apply_event(s, ev("resume", 5))
    assert r.status == "proposed"  # re-enters at proposed: the earlier decision cannot dispatch
    assert code(r, ev("dispatch", 6)) == "authority_required"
    assert code(r, ev("record_authorized", 6)) == "illegal_transition"
    r = wm.replay([ev(t, i + 1) for i, t in enumerate(
        ["propose", "request_authority", "record_authorized", "suspend", "resume", "request_authority"])])
    r = wm.apply_event(r, ev("record_authorized", 7, decision_ref="new-decision"))
    assert r.status == "authorized" and ("record_authorized", "new-decision") in r.refs


def test_refs_of_the_new_events_and_forbidden_token_pins():
    for etype, member in (("suspend", "suspension_ref"), ("resume", "resume_ref"),
                          ("cancel", "cancellation_ref"), ("fail", "failure_ref")):
        assert voc.EVENT_MEMBERS[etype] == voc.COMMON_MEMBERS + (member,)
        assert not wm.machine._forbidden(member)  # a later edit of the token list must not turn it forbidden
    s = run(["propose", "cancel"])
    assert s.refs == (("propose", "propose-ref"), ("cancel", "cancel-ref")) and s.history == ("propose", "cancel")
    assert code(wm.initial_state(), ev("propose", 1, failure_ref="x")) == "unknown_member"


def test_closure_classes_and_slot_classes_are_total_and_never_overlap():
    cls = {s: wm.describe(state_at(s))["closure_class"] for s in voc.STATUSES}
    assert {s for s, c in cls.items() if c == "completed"} == {"observed", "reconciled"}
    assert cls["failed"] == "failed" and cls["cancelled"] == "cancelled"
    assert {s for s, c in cls.items() if c == "open"} == {
        "proposed", "awaiting_authority", "authorized", "dispatched", "unresolved", "suspended"}
    for status in voc.OPEN_EFFECT_STATUSES:  # never completed, never archivable as completed
        assert cls[status] == "open"
    slots = {s: wm.describe(state_at(s))["slot_class"] for s in voc.STATUSES}
    assert {s for s, c in slots.items() if c == "execution"} == {"authorized", "dispatched"}
    assert {s for s, c in slots.items() if c == "waiting"} == {
        "proposed", "awaiting_authority", "suspended", "unresolved"}
    assert {s for s, c in slots.items() if c == "closed"} == set(voc.TERMINAL_STATUSES)
    for s in voc.STATUSES:
        assert (slots[s] == "closed") == (wm.describe(state_at(s))["terminal"])
        assert not (slots[s] == "closed" and cls[s] == "open")
    assert wm.describe(wm.initial_state())["slot_class"] == "none"


def test_describe_of_new_states_never_claims_an_effect_outcome():
    for status in ("suspended", "failed", "cancelled"):
        d = wm.describe(state_at(status))
        assert d["effect_outcome"] == "none" and d["refs_content_checked"] is False


# ------------------------------------------------------------ Rule R and the 16-event bound

def test_rule_r_pins_reachable_pairs_and_highest_accepted_counts():
    seen, frontier, high = set(), [wm.initial_state()], {}
    while frontier:
        nxt = []
        for s in frontier:
            if (s.status, s.event_count) in seen:
                continue
            seen.add((s.status, s.event_count))
            for a in wm.next_actions(s):
                high[a] = max(high.get(a, -1), s.event_count)
                nxt.append(wm.apply_event(s, ev(a, s.event_count + 1)))
        frontier = nxt
    assert len(seen) == 116
    assert high == {"propose": 0, "request_authority": 12, "record_authorized": 13, "dispatch": 14,
                    "record_observation": 15, "record_outcome_unknown": 14, "crash_recovered": 14,
                    "reconcile": 15, "reconcile_inconclusive": 14, "suspend": 10, "resume": 11,
                    "cancel": 14, "fail": 14}


def test_closing_event_needs_no_remaining_slot_but_dispatch_is_refused_late():
    # 14 events pre-dispatch, still closable at the last slot
    s = run(["propose", "suspend", "resume", "suspend", "resume", "suspend", "resume", "suspend", "resume",
             "suspend", "resume"])  # 11 events, proposed
    assert s.status == "proposed" and s.event_count == 11
    assert code(s, ev("suspend", 12)) == "bound_events_exceeded"  # 5 more would be needed to complete
    s = wm.apply_event(s, ev("request_authority", 12))
    s = wm.apply_event(s, ev("record_authorized", 13))
    s = wm.apply_event(s, ev("dispatch", 14))
    assert s.status == "dispatched" and s.event_count == 14
    # a different path: close at event 16 is legal for a pre-dispatch workflow at count 15 (only by table)
    c = run(["propose", "suspend", "resume", "suspend", "resume", "suspend", "resume", "suspend", "resume",
             "suspend", "resume", "request_authority"])
    assert c.status == "awaiting_authority" and c.event_count == 12
    assert wm.apply_event(c, ev("cancel", 13)).status == "cancelled"


def test_at_most_five_suspend_resume_cycles_on_a_completing_path():
    path = ["propose"]
    for _ in range(5):
        path += ["suspend", "resume"]
    s = run(path)
    assert s.event_count == 11 and code(s, ev("suspend", 12)) == "bound_events_exceeded"
    s = run(["propose"] + ["suspend", "resume"] * 4 + ["suspend"])
    assert wm.next_actions(s) == ("resume", "cancel", "fail")  # event 10 accepted, resume still fits


def test_forged_histories_are_refused():
    good = run(["propose", "suspend", "resume"])
    bad_histories = [
        ("propose", "resume", "suspend"),                 # no transition
        ("propose", "suspend", "suspend"),
        ("propose", "dispatch", "resume"),
        ("propose", "fail", "propose"),                   # leaves a closed status
    ]
    for h in bad_histories:
        with pytest.raises(wm.Refusal) as ei:
            wm.State(W, "proposed", len(h), good.refs, h)
        assert ei.value.code == "schema_invalid"
    with pytest.raises(wm.Refusal):  # status disagrees with the history
        wm.State(W, "suspended", good.event_count, good.refs, good.history)
    with pytest.raises(wm.Refusal):  # refs disagree with the history
        wm.State(W, "proposed", 3, good.refs[:-1], good.history)
    with pytest.raises(wm.Refusal):  # history breaks Rule R
        wm.State(W, "proposed", 12, (("propose", "p"),) + (("suspend", "s"), ("resume", "r")) * 5 + (("suspend", "s"),),
                 ("propose",) + ("suspend", "resume") * 5 + ("suspend",) + ("resume",))
    # crash_recovered and record_outcome_unknown now leave a trace in history
    a, b = state_at("unresolved"), run(["propose", "request_authority", "record_authorized", "dispatch",
                                         "crash_recovered"])
    assert a.history[-1] == "record_outcome_unknown" and b.history[-1] == "crash_recovered" and a != b


# ------------------------------------------------------------ independent reference model (fuzz oracle)

_REF_LEGAL = {
    ("initial", "propose"): "proposed", ("proposed", "request_authority"): "awaiting_authority",
    ("awaiting_authority", "record_authorized"): "authorized", ("authorized", "dispatch"): "dispatched",
    ("dispatched", "record_observation"): "observed", ("dispatched", "record_outcome_unknown"): "unresolved",
    ("dispatched", "crash_recovered"): "unresolved", ("unresolved", "reconcile"): "reconciled",
    ("unresolved", "reconcile_inconclusive"): "unresolved", ("suspended", "resume"): "proposed",
    **{(s, "suspend"): "suspended" for s in ("proposed", "awaiting_authority", "authorized")},
    **{(s, "cancel"): "cancelled" for s in ("proposed", "awaiting_authority", "authorized", "suspended")},
    **{(s, "fail"): "failed" for s in ("proposed", "awaiting_authority", "authorized", "suspended")},
}
_TO_COMPLETE = {"initial": 5, "proposed": 4, "awaiting_authority": 3, "authorized": 2, "dispatched": 1,
                "unresolved": 1, "suspended": 5, "observed": 0, "reconciled": 0}


def _ref_apply(status, count, etype):
    """(new status, count) or the refusal code, written from the document's rules and not from vocabulary.py."""
    if count >= 16:
        return "bound_events_exceeded"
    if status in ("failed", "cancelled"):
        return "workflow_closed"
    if (status, etype) not in _REF_LEGAL:
        if etype == "dispatch":
            return "blind_retry_refused" if status in ("dispatched", "observed", "unresolved", "reconciled") \
                else "authority_required"
        if etype in ("suspend", "cancel", "fail") and status in ("dispatched", "unresolved"):
            return "open_effect_refused"
        return "illegal_transition"
    new = _REF_LEGAL[(status, etype)]
    if etype not in ("cancel", "fail") and 16 - (count + 1) < _TO_COMPLETE[new]:
        return "bound_events_exceeded"
    return new, count + 1


@pytest.mark.parametrize("seed", range(40))
def test_fuzz_against_the_independent_reference_model(seed):
    rnd = random.Random(seed)
    for _ in range(60):
        state, status, count = wm.initial_state(), "initial", 0
        for _step in range(rnd.randint(1, 20)):
            etype = rnd.choice(voc.EVENT_TYPES)
            seq = count + 1 if rnd.random() < 0.9 else rnd.choice([0, count, count + 2, 99])
            event = ev(etype, seq, wid=W if rnd.random() < 0.95 else "other")
            if rnd.random() < 0.03:
                event["verdict"] = "x"
            before = state
            try:
                state = wm.apply_event(state, event)
            except wm.Refusal as e:
                assert state == before  # unchanged on refusal
                if e.code in ("schema_invalid", "forbidden_member", "workflow_mismatch", "sequence_mismatch"):
                    continue
                assert _ref_apply(status, count, etype) == e.code, (seed, etype, status, count)
                continue
            expect = _ref_apply(status, count, etype)
            assert expect == (state.status, state.event_count), (seed, etype, status, count)
            status, count = state.status, state.event_count
            assert len(state.history) == count and wm.State(
                state.workflow_id, state.status, state.event_count, state.refs, state.history) == state


# ------------------------------------------------------------ capacity: execution slots versus waiting records

PATH_TO_AWAITING = ["propose", "request_authority"]


def _fleet_with(n_execution=0, n_waiting=0, n_held=0):
    events = []
    for i in range(n_execution):
        events += [ev(t, k + 1, wid=f"x{i}") for k, t in enumerate(PATH_TO_AWAITING + ["record_authorized"])]
    for i in range(n_waiting):
        events.append(ev("propose", 1, wid=f"p{i}"))
    for i in range(n_held):
        events += [ev(t, k + 1, wid=f"h{i}") for k, t in enumerate(PATH_TO_AWAITING)]
    return wm.replay_fleet(events)


def test_held_and_denied_workflows_never_consume_execution_slots(monkeypatch):
    monkeypatch.setattr(wm.machine, "MAX_ACTIVE_EXECUTION_SLOTS", 2)
    monkeypatch.setattr(wm.machine, "MAX_WAITING_RECORDS", 10)
    fleet = _fleet_with(n_held=8)  # eight workflows parked after a hold or deny
    assert fleet.slot_counts() == {"execution": 0, "waiting": 8, "closed": 0}
    f = wm.apply_fleet(fleet, ev("record_authorized", 3, wid="h0"))
    f = wm.apply_fleet(f, ev("record_authorized", 3, wid="h1"))
    assert f.slot_counts()["execution"] == 2 and f.slot_counts()["waiting"] == 6


def test_record_authorized_refused_at_the_execution_bound_leaves_a_waiting_record(monkeypatch):
    monkeypatch.setattr(wm.machine, "MAX_ACTIVE_EXECUTION_SLOTS", 2)
    fleet = _fleet_with(n_execution=2, n_held=1)
    with pytest.raises(wm.Refusal) as ei:
        wm.apply_fleet(fleet, ev("record_authorized", 3, wid="h0"))
    assert ei.value.code == "bound_execution_slots_exceeded"
    assert fleet.states["h0"].status == "awaiting_authority"  # decision reference not lost, still recoverable
    # a slot frees when an execution workflow is suspended, closed or leaves for unresolved
    for etype in ("suspend", "cancel", "fail"):
        f = wm.apply_fleet(fleet, ev(etype, 4, wid="x0"))
        assert f.slot_counts()["execution"] == 1
        assert wm.apply_fleet(f, ev("record_authorized", 3, wid="h0")).states["h0"].status == "authorized"


def test_moves_from_execution_to_waiting_are_never_refused_for_capacity(monkeypatch):
    monkeypatch.setattr(wm.machine, "MAX_ACTIVE_EXECUTION_SLOTS", 2)
    monkeypatch.setattr(wm.machine, "MAX_WAITING_RECORDS", 2)
    fleet = _fleet_with(n_execution=2, n_waiting=2)  # waiting already full
    f = wm.apply_fleet(fleet, ev("suspend", 4, wid="x0"))  # authorized -> suspended
    f = wm.apply_fleet(f, ev("dispatch", 4, wid="x1"))
    f = wm.apply_fleet(f, ev("record_outcome_unknown", 5, wid="x1"))  # dispatched -> unresolved
    assert f.slot_counts() == {"execution": 0, "waiting": 4, "closed": 0}
    assert f.over_limit() == ("waiting",)  # overshoot is visible, bounded by the execution bound
    with pytest.raises(wm.Refusal) as ei:
        wm.apply_fleet(f, ev("propose", 1, wid="new"))
    assert ei.value.code == "bound_waiting_exceeded"
    f2 = wm.apply_fleet(f, ev("resume", 5, wid="x0"))  # waiting to waiting, never refused
    assert f2.states["x0"].status == "proposed"


def test_replay_never_refuses_for_capacity_even_with_lowered_bounds(monkeypatch):
    events = [e for i in range(6) for e in
              (ev("propose", 1, wid=f"w{i}"), ev("request_authority", 2, wid=f"w{i}"),
               ev("record_authorized", 3, wid=f"w{i}"))]
    events += [ev("propose", 1, wid="held"), ev("request_authority", 2, wid="held")]
    monkeypatch.setattr(wm.machine, "MAX_ACTIVE_EXECUTION_SLOTS", 2)
    monkeypatch.setattr(wm.machine, "MAX_WAITING_RECORDS", 0)
    fleet = wm.replay_fleet(events)
    assert fleet.slot_counts() == {"execution": 6, "waiting": 1, "closed": 0}
    assert fleet.over_limit() == ("execution", "waiting")
    for event, want in ((ev("record_authorized", 3, wid="held"), "bound_execution_slots_exceeded"),
                        (ev("propose", 1, wid="fresh"), "bound_waiting_exceeded")):
        with pytest.raises(wm.Refusal) as ei:  # only new admissions are refused
            wm.apply_fleet(fleet, event)
        assert ei.value.code == want
    # existing work still proceeds, and the unknown outcome can always be recorded
    f = wm.apply_fleet(fleet, ev("dispatch", 4, wid="w0"))
    assert wm.apply_fleet(f, ev("record_outcome_unknown", 5, wid="w0")).states["w0"].status == "unresolved"


# ------------------------------------------------------------ release of terminal workflows

def test_release_terminal_frees_exactly_the_closed_workflow_and_keeps_a_receipt():
    done = {"observed": ["propose", "request_authority", "record_authorized", "dispatch", "record_observation"],
            "reconciled": ["propose", "request_authority", "record_authorized", "dispatch",
                           "record_outcome_unknown", "reconcile"],
            "failed": ["propose", "fail"], "cancelled": ["propose", "cancel"]}
    for status, path in done.items():
        fleet = wm.replay_fleet([ev(t, i + 1, wid="t") for i, t in enumerate(path)] + [ev("propose", 1, wid="live")])
        assert fleet.slot_counts()["closed"] == 1
        new, receipt = wm.release_terminal(fleet, "t")
        assert set(new.states) == {"live"} and set(fleet.states) == {"t", "live"}  # input unchanged
        assert receipt == {"workflow_id": "t", "terminal_status": status,
                           "closure_class": wm.describe(fleet.states["t"])["closure_class"],
                           "event_count": len(path)}
        assert new.slot_counts() == {"execution": 0, "waiting": 1, "closed": 0}


def test_release_terminal_refuses_open_effects_and_nonterminal_workflows():
    for status in ("dispatched", "unresolved"):
        fleet = wm.Fleet({W: state_at(status)})
        with pytest.raises(wm.Refusal) as ei:
            wm.release_terminal(fleet, W)
        assert ei.value.code == "open_effect_refused"
        assert W in fleet.states
    for status in ("proposed", "awaiting_authority", "authorized", "suspended"):
        with pytest.raises(wm.Refusal) as ei:
            wm.release_terminal(wm.Fleet({W: state_at(status)}), W)
        assert ei.value.code == "not_releasable"
    for bad in ("ghost", None, 5):
        with pytest.raises(wm.Refusal) as ei:
            wm.release_terminal(wm.Fleet({}), bad)  # type: ignore[arg-type]
        assert ei.value.code == "not_releasable"
    with pytest.raises(wm.Refusal) as ei:
        wm.release_terminal({}, W)  # type: ignore[arg-type]
    assert ei.value.code == "schema_invalid"


def test_slots_are_derived_from_status_so_a_crash_cannot_leak_one():
    """No counter exists: an identical replay gives identical counts however often it is repeated."""
    events = [ev(t, i + 1, wid="a") for i, t in enumerate(["propose", "request_authority", "record_authorized"])]
    assert [wm.replay_fleet(events).slot_counts() for _ in range(3)] == [
        {"execution": 1, "waiting": 0, "closed": 0}] * 3
    assert not any(isinstance(v, int) for v in vars(wm.Fleet({})).values())


# ------------------------------------------------------------ restart

def test_restart_records_crash_recovered_for_dispatched_only_and_resumes_nothing():
    events = []
    for wid, path in (("held", ["propose", "request_authority"]),
                      ("susp", ["propose", "suspend"]),
                      ("auth", ["propose", "request_authority", "record_authorized"]),
                      ("disp", ["propose", "request_authority", "record_authorized", "dispatch"]),
                      ("unres", ["propose", "request_authority", "record_authorized", "dispatch",
                                 "record_outcome_unknown"]),
                      ("done", ["propose", "cancel"])):
        events += [ev(t, i + 1, wid=wid) for i, t in enumerate(path)]
    fleet = wm.replay_fleet(events)
    assert wm.restart_recovery_needed(fleet) == ("disp",)
    after = wm.apply_fleet(fleet, ev("crash_recovered", 5, wid="disp"))
    assert after.states["disp"].status == "unresolved" and wm.restart_recovery_needed(after) == ()
    for wid in ("held", "susp", "auth", "unres", "done"):  # untouched by restart
        assert after.states[wid] == fleet.states[wid]
    # an unresolved effect is never closed or released by recovery
    with pytest.raises(wm.Refusal):
        wm.release_terminal(after, "disp")
    with pytest.raises(wm.Refusal):
        wm.apply_fleet(after, ev("cancel", 6, wid="disp"))
    with pytest.raises(wm.Refusal):
        wm.restart_recovery_needed(None)  # type: ignore[arg-type]


def test_machine_profile_identity_is_provisional_and_distinct():
    assert voc.MACHINE_PROFILE == "ocs-workflow-machine/1" and voc.PREDECESSOR_MACHINE_PROFILE.endswith("/0")
