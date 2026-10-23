"""Developer tests for the pure workflow state machine (step 3.2 part A). Not independent acceptance."""
from __future__ import annotations

import ast
import itertools
import subprocess
import sys
from collections.abc import Mapping
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
    with pytest.raises(ValueError):
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


def _unresolved_at(count: int) -> "wm.State":
    s = state_at("unresolved")
    while s.event_count < count:
        s = wm.apply_event(s, ev("reconcile_inconclusive", s.event_count + 1))
    return s


def test_bound_events_per_workflow_reserves_final_slot_for_reconcile():
    n = wm.MAX_EVENTS_PER_WORKFLOW
    s = _unresolved_at(n - 1)  # 15 events: the last non-terminal loop that was allowed
    assert s.status == "unresolved" and s.event_count == n - 1
    # the final slot is reserved: inconclusive is refused (closed code), reconcile still works
    assert wm.next_actions(s) == ("reconcile",)
    assert refusal(s, ev("reconcile_inconclusive", n)) == "bound_events_exceeded"
    assert s.status == "unresolved" and s.event_count == n - 1
    done = wm.apply_event(s, ev("reconcile", n))
    assert done.status == "reconciled" and done.event_count == n
    assert wm.next_actions(done) == ()
    assert refusal(done, ev("reconcile", n + 1)) == "bound_events_exceeded"


def test_no_dead_end_at_the_bound_every_reachable_state_can_terminate():
    """Exhaustive over legal event-type paths to the bound: every reachable state with room is either
    terminal or has a legal next action, and following legal actions always reaches a terminal status."""
    n = wm.MAX_EVENTS_PER_WORKFLOW
    frontier = [wm.initial_state()]
    seen = 0
    while frontier:
        nxt = []
        for s in frontier:
            seen += 1
            acts = wm.next_actions(s)
            if s.status in voc.TERMINAL_STATUSES:
                assert acts == ()
                continue
            assert acts, (s.status, s.event_count)  # never a non-terminal dead end
            assert s.event_count < n
            # a terminating continuation fits in the remaining slots
            assert n - s.event_count >= voc.EVENTS_TO_TERMINAL[s.status]
            for a in acts:
                nxt.append(wm.apply_event(s, ev(a, s.event_count + 1)))
        frontier = nxt
    assert seen > 30


def test_every_status_reaches_a_terminal_status_in_the_table():
    assert set(voc.EVENTS_TO_TERMINAL) == set(voc.ALL_STATES)
    for t in voc.TERMINAL_STATUSES:
        assert voc.EVENTS_TO_TERMINAL[t] == 0
    assert voc.EVENTS_TO_TERMINAL["unresolved"] == 1 and voc.EVENTS_TO_TERMINAL["initial"] == 5


def test_event_bound_still_refuses_past_the_last_slot():
    s = _unresolved_at(14)
    s = wm.apply_event(s, ev("reconcile", 15))
    assert s.event_count == 15 and s.status == "reconciled"
    # states built for the bound cannot be pushed past it
    with pytest.raises(wm.Refusal) as ei:
        wm.State("wf-1", "reconciled", 17, wm.replay([ev(t, i + 1) for i, t in enumerate(
            ("propose", "request_authority", "record_authorized", "dispatch", "record_outcome_unknown",
             "reconcile"))]).refs)
    assert ei.value.code == "schema_invalid"


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


ALLOWED_IMPORTS = {"re", "dataclasses", "types", "typing", "__future__"}
BANNED_CALLS = {"open", "__import__", "eval", "exec"}


def _package_trees():
    for p in sorted((ROOT / "orchestration/workflow_machine").glob("*.py")):
        yield p.name, ast.parse(p.read_text())


def test_modules_import_only_the_allow_list_and_call_no_banned_builtins():
    checked = 0
    for name, tree in _package_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] in ALLOWED_IMPORTS, (name, a.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:  # absolute import: allow-list only
                    assert (node.module or "").split(".")[0] in ALLOWED_IMPORTS, (name, node.module)
                else:  # package-relative only: no `from .. import x` escaping the package
                    assert node.level == 1, (name, node.level)
            elif isinstance(node, ast.Call):
                f = node.func
                called = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
                assert called not in BANNED_CALLS, (name, called)
            elif isinstance(node, ast.Name) and node.id in BANNED_CALLS:
                raise AssertionError((name, node.id))  # also catches aliasing: f = open
            checked += 1
    assert checked > 500


def test_purity_walk_detects_a_violation():
    bad = ast.parse("import os\nfrom time import time\nx = open('f')\n")
    mods = {(n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0]
            for n in ast.walk(bad) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert mods - ALLOWED_IMPORTS == {"os", "time"}
    assert any(isinstance(n, ast.Name) and n.id in BANNED_CALLS for n in ast.walk(bad))


def test_package_has_no_assert_statements():
    """Asserts vanish under `python -O`; every check in the package is an explicit raise."""
    for name, tree in _package_trees():
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Assert)], name


def test_checks_survive_python_dash_O():
    """Run a probe under -O (asserts stripped): the explicit raises must still fire."""
    code = ("import sys; sys.path.insert(0, %r); import workflow_machine as wm\n"
            "try:\n wm.Refusal('nope')\nexcept ValueError: pass\nelse: raise SystemExit(1)\n"
            "try:\n wm.State('w','proposed',5,())\nexcept wm.Refusal as e: raise SystemExit(0 if e.code=='schema_invalid' else 3)\n"
            "raise SystemExit(2)\n" % str(ROOT / "orchestration"))
    r = subprocess.run([sys.executable, "-O", "-B", "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, (r.returncode, r.stderr)


# ---------------------------------------------------------------- state and fleet forgery, hostile mappings

@pytest.mark.parametrize("args", [
    ("w", "bogus", 1, ()),                                        # status outside the closed set
    (None, "proposed", 1, (("propose", "p"),)),                   # no workflow id
    ("w", "initial", 0, (("propose", "p"),)),                     # initial with refs
    ("w", "initial", 0, ()),                                      # initial with a workflow id
    (None, "initial", 1, ()),
    ("w", "proposed", 0, ()), ("w", "proposed", 5, (("propose", "p"),)),
    ("w", "proposed", 1, ()), ("w", "awaiting_authority", 1, (("propose", "p"),)),
    ("w", "authorized", 3, (("propose", "p"),)),                  # missing decision ref
    ("w", "dispatched", 4, (("propose", "p"), ("record_authorized", "d"))),
    ("w", "dispatched", 4, (("propose", "p"), ("dispatch", "x"), ("record_authorized", "d"))),
    ("w", "observed", 4, (("propose", "p"), ("record_authorized", "d"), ("dispatch", "x"),
                          ("record_observation", "o"))),
    ("w", "unresolved", 4, (("propose", "p"), ("record_authorized", "d"), ("dispatch", "x"))),
    ("w", "unresolved", 16, (("propose", "p"), ("record_authorized", "d"), ("dispatch", "x")) +
     (("reconcile_inconclusive", "r"),) * 11),                    # final slot reserved
    ("w", "reconciled", 5, (("propose", "p"), ("record_authorized", "d"), ("dispatch", "x"))),
    ("w", "proposed", True, (("propose", "p"),)), ("w", "proposed", 1, [("propose", "p")]),
    ("w", "proposed", 1, (["propose", "p"],)), ("w", "proposed", 1, (("propose", ""),)),
    ("w", "proposed", 1, (("bogus", "p"),)), ("w", " w", 1, (("propose", "p"),)),
])
def test_forged_states_are_refused(args):
    with pytest.raises(wm.Refusal) as ei:
        wm.State(*args)
    assert ei.value.code == "schema_invalid"


def test_every_replayed_state_passes_its_own_consistency_check():
    for path, _ in _all_legal_paths(12):
        s = wm.replay(_events(path))
        assert wm.State(s.workflow_id, s.status, s.event_count, s.refs) == s


def test_fleet_rejects_inconsistent_entries_and_snapshots_its_input():
    s = state_at("proposed")
    for bad in ({"other": s}, {1: s}, {"wf-1": "nope"}, [("wf-1", s)], None):
        with pytest.raises(wm.Refusal) as ei:
            wm.Fleet(bad)  # type: ignore[arg-type]
        assert ei.value.code == "schema_invalid"
    src = {"wf-1": s}
    f = wm.Fleet(src)
    src["wf-1"] = state_at("awaiting_authority")
    src["zzz"] = s
    assert set(f.states) == {"wf-1"} and f.states["wf-1"].status == "proposed"
    states = {f"w{i}": wm.replay([ev("propose", 1, wid=f"w{i}")]) for i in range(wm.MAX_CONCURRENT_WORKFLOWS + 1)}
    with pytest.raises(wm.Refusal) as ei:
        wm.Fleet(states)
    assert ei.value.code == "bound_workflows_exceeded"


class Shifty(Mapping):
    """Hostile mapping: valid on the first read of each key, forged on every later read."""

    def __init__(self, good: dict, bad: dict) -> None:
        self.good, self.bad, self.reads = good, bad, {}

    def _pick(self, k):
        n = self.reads[k] = self.reads.get(k, 0) + 1
        return self.good if n == 1 else self.bad

    def __getitem__(self, k):
        return self._pick(k)[k]

    def get(self, k, default=None):
        d = self._pick(k)
        return d.get(k, default)

    def __iter__(self):
        return iter(self.good)

    def __len__(self):
        return len(self.good)


class Exploding(Mapping):
    def __getitem__(self, k):
        raise RuntimeError("boom")

    def __iter__(self):
        raise RuntimeError("boom")

    def __len__(self):
        return 1


def test_hostile_mapping_is_snapshotted_before_validation():
    good = ev("propose", 1)
    bad = dict(good, seq=99, proposal_ref="", verdict="x", type="dispatch")
    s = wm.apply_event(wm.initial_state(), Shifty(good, bad))
    assert s.status == "proposed" and s.event_count == 1 and s.refs == (("propose", "propose-ref"),)
    f = wm.apply_fleet(wm.Fleet({}), Shifty(good, bad))
    assert f.states[W].refs == (("propose", "propose-ref"),)
    assert wm.replay([Shifty(good, bad)]).refs == (("propose", "propose-ref"),)


def test_mapping_that_raises_while_copied_is_schema_invalid():
    assert refusal(wm.initial_state(), Exploding()) == "schema_invalid"
    with pytest.raises(wm.Refusal) as ei:
        wm.apply_fleet(wm.Fleet({}), Exploding())
    assert ei.value.code == "schema_invalid"
    with pytest.raises(wm.Refusal) as ei:
        wm.Fleet(Exploding())
    assert ei.value.code == "schema_invalid"


def test_describe_marks_reference_content_as_unchecked():
    d = wm.describe(state_at("observed"))
    assert d["refs_content_checked"] is False and d["effect_outcome"] == "observation_referenced"


def test_forbidden_tokens_only_choose_the_refusal_code():
    # An undeclared member is refused whether or not it looks forbidden; only the code differs.
    assert refusal(wm.initial_state(), ev("propose", 1, harmless="x")) == "unknown_member"
    assert refusal(wm.initial_state(), ev("propose", 1, grant="x")) == "forbidden_member"
    for tok in voc.FORBIDDEN_MEMBER_TOKENS:
        assert wm.machine._forbidden(tok)
