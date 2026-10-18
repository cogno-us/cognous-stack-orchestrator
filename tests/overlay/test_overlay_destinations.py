"""Duplicate, lost-acknowledgement and delayed-commit flows against the Runtime's opt-in destinations (operation-identity/0.1,
delayed-commit/0.1), driven with the orchestrator's inputs (pinned Action Manifest example, tenant-bound proposal).

Synthetic only; no network; the destinations are CI/local SQLite and have no authority of their own. Passing shows the stated
behaviour on the candidate revisions; it does not show provider-side behaviour or anything about a deployment. The orchestrator's
accepted route (atomic claim) cannot reach these destinations; `test_atomic_route_cannot_carry_an_operation_id` records that as data.
"""
from __future__ import annotations

import json

from conftest import section


def results(candidate_destinations):
    return json.loads((candidate_destinations / "results.json").read_text(encoding="utf-8"))


def test_lost_ack_then_late_landing_is_one_effect_and_never_licenses_retry(candidate_destinations):
    """Both with and without operation identity: absent after a lost acknowledgement is not 'never executed'."""
    r = results(candidate_destinations)
    for tag in ("off", "on"):
        s = r[f"lost_ack_then_land[identity={tag}]"]
        assert s["first"]["status"] == "unknown" and s["first"]["acknowledged"] is False and s["first"]["observed_state"] == "absent"
        assert s["ledger_while_absent"] == [] and s["in_flight_before_land"] == 1
        assert s["retry"]["status"] == "denied" and s["retry"]["attempted"] is False
        assert len(s["attempts_before_land"]) == 1 and s["attempts_before_land"][0]["status"] == "unknown"
        assert s["reconciliations"] and all(x["result"] == "observed_absent" and x["retry_eligible"] is False for x in s["reconciliations"])
        assert s["safe_to_retry_rows"] == []
        assert s["ledger_after_land"] == [s["effect_id"]]
        assert s["reconcile_after_land"] == {"result": "applied", "retry_eligible": False}
    section("destinations_lost_ack", {"variants": 2, "assertions_hold": True})


def test_renewal_race_legacy_destination_commits_two_effects_for_one_operation(candidate_destinations):
    """Expected today (default destination semantics, profile off): a renewed grant changes effect_id; a delayed first attempt
    then commits a second effect. This is the gap the opt-in profile exists to close, shown here with the orchestrator's inputs."""
    s = results(candidate_destinations)["renewal_race[identity=off]"]
    assert s["d2_result"] == "authorized" and s["d2_effect_id"] != s["d1_effect_id"]
    assert s["r1"]["status"] == "executed" and s["r2"]["status"] == "executed"
    assert sorted(s["ledger"]) == sorted([s["d1_effect_id"], s["d2_effect_id"]]), "two effects for one operation"
    assert s["attempt_joins"] == 0 and s["operations"] == 0
    section("destinations_renewal_race_profile_off", {"effects_for_one_operation": len(s["ledger"])})


def test_renewal_race_with_operation_identity_commits_one_effect(candidate_destinations):
    s = results(candidate_destinations)["renewal_race[identity=on]"]
    assert s["d2_result"] == "authorized" and s["d2_effect_id"] != s["d1_effect_id"], "the legacy effect_id still changes per revision"
    assert s["ledger"] == [s["d2_effect_id"]], "one effect, committed by r2"
    assert s["r2"]["status"] == "executed"
    assert s["r1"]["status"] == "failed" and s["r1"]["error"] == "operation_already_committed" and s["r1"]["observed_state"] == "absent"
    assert s["operations"] == 1 and s["attempt_joins"] == 2
    section("destinations_renewal_race_operation_identity", {"effects_for_one_operation": len(s["ledger"]), "attempt_joins": s["attempt_joins"]})


def test_renewal_during_lost_ack_adapter_route_f5_probe(candidate_destinations):
    """F-5 probe (adapter route, the runtime's own delayed-commit destination classes; synthetic, no network).

    r1's commit is deferred (acknowledgement lost, outcome unknown), the grant is renewed (effect_id changes), r2 is attempted while r1
    is still outstanding, then r1 lands late. Observed at the candidate revisions:
    - profile off: r2 commits, then r1's late landing commits too: TWO effects for one operation (the legacy gap, expected).
    - operation identity on: r2 commits, r1's late landing is refused by the destination guard (`operation_already_committed`): ONE effect.
      The control plane does not hold r2 while r1 is outstanding; the destination guard is the only barrier here.
    A double commit with the identity profile ON would be a new finding and fails this test.
    """
    r = results(candidate_destinations)
    off, on = r["renewal_during_lost_ack[identity=off]"], r["renewal_during_lost_ack[identity=on]"]
    for s in (off, on):
        assert s["d2_result"] == "authorized" and s["d2_effect_id"] != s["d1_effect_id"]
        assert s["r1"]["status"] == "unknown" and s["r1"]["acknowledged"] is False
        assert s["r2"]["status"] == "executed" and s["in_flight_after_r1"] == s["in_flight_before_land"] == 1
        assert s["ledger_before_land"] == [s["d2_effect_id"]] and s["in_flight_after_land"] == 0
    assert off["land_refusal"] is None and sorted(off["ledger_after_land"]) == sorted([off["d1_effect_id"], off["d2_effect_id"]])
    assert off["operations"] == 0 and off["attempt_joins"] == 0
    assert on["land_refusal"] == "PermissionError: operation_already_committed", "late landing must be refused by the destination guard"
    assert on["ledger_after_land"] == [on["d2_effect_id"]], "DOUBLE COMMIT with operation identity on (FINDING)"
    assert on["operations"] == 1 and on["attempt_joins"] == 2
    section("destinations_renewal_during_lost_ack_F5_probe", {"effects_profile_off": len(off["ledger_after_land"]),
                                                              "effects_identity_on": len(on["ledger_after_land"]),
                                                              "late_landing_refused_identity_on": True})


def test_renewal_after_late_landing_adapter_route_f5_probe(candidate_destinations):
    """F-5 probe, second order: r1 lands late first, then the grant is renewed and the same operation is decided again.

    Profile off: the renewed decision commits a second effect. Identity on: r2 is refused (`operation_already_committed`), one effect.
    """
    r = results(candidate_destinations)
    off, on = r["renewal_after_landing[identity=off]"], r["renewal_after_landing[identity=on]"]
    for s in (off, on):
        assert s["d2_result"] == "authorized" and s["d2_effect_id"] != s["d1_effect_id"]
        assert s["r1"]["status"] == "unknown" and s["land_refusal"] is None and s["ledger_after_land"] == [s["d1_effect_id"]]
    assert off["r2"]["status"] == "executed" and sorted(off["ledger_final"]) == sorted([off["d1_effect_id"], off["d2_effect_id"]])
    assert on["r2"]["status"] == "failed" and on["r2"]["error"] == "operation_already_committed"
    assert on["ledger_final"] == [on["d1_effect_id"]], "DOUBLE COMMIT with operation identity on (FINDING)"
    section("destinations_renewal_after_landing_F5_probe", {"effects_profile_off": len(off["ledger_final"]),
                                                            "effects_identity_on": len(on["ledger_final"])})


def test_atomic_route_cannot_carry_an_operation_id(candidate_destinations):
    """The orchestrator's accepted route (AtomicLocalControlPlaneExecutor + AtomicAuthorityEffectDestination) has no operation id
    parameter and its destination is not an OperationIdentityDestination or delayed-commit class. Recorded as a finding, not a defect
    claim: the opt-in profiles were built on the adapter route (PinnedControlPlaneExecutor)."""
    s = results(candidate_destinations)["atomic_route_surface"]
    assert "operation_id" not in s["atomic_executor_execute_params"]
    assert "operation_id" not in s["atomic_destination_execute_claim_atomic_params"]
    assert s["atomic_destination_has_operation_identity_capability"] is False
    assert s["atomic_destination_subclasses_operation_identity"] is False
    assert s["atomic_destination_has_delayed_commit_surface"] is False
    assert s["atomic_executor_mentions_operation_id"] is False and s["atomic_destination_mentions_operation_id"] is False
    section("atomic_route_surface", s)
