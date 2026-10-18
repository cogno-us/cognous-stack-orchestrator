"""Duplicate, lost-acknowledgement and delayed-commit flows against the Runtime's opt-in destinations (operation-identity/0.1,
delayed-commit/0.1), driven with the orchestrator's inputs (pinned Action Manifest example, tenant-bound proposal).

Synthetic only; no network; the destinations are CI/local SQLite and have no authority of their own. Passing shows the stated
behaviour on the candidate revisions; it does not show provider-side behaviour or anything about a deployment. The orchestrator's
accepted route (atomic claim) reaches the operation guard only through the opt-in classes of runtime fc034d14 (R2); the default atomic
route cannot carry an operation id: `test_atomic_route_carries_an_operation_id_only_on_the_opt_in_path` records that as data.
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


def test_atomic_route_carries_an_operation_id_only_on_the_opt_in_path(candidate_destinations):
    """Runtime fc034d14 (R2). The accepted atomic route can now carry an operation id, opt-in only:
    - `AtomicLocalControlPlaneExecutor.__init__` has an `operation_identity` parameter, default False; `execute` still has NO operation id
      parameter (the id is derived from the persisted Control Plane decision, never supplied by the caller);
    - `AtomicAuthorityEffectDestination.execute_claim_atomic` takes an optional `operation_id`; the base class is NOT an operation-identity
      class and has no capability (default path unchanged);
    - `OperationIdentityAtomicAuthorityEffectDestination` subclasses it and declares `operation-identity/0.1`;
    - no delayed-commit surface on the atomic route (the atomic commit has no in-flight state)."""
    s = results(candidate_destinations)["atomic_route_surface"]
    assert "operation_identity" in s["atomic_executor_init_params"] and s["atomic_executor_operation_identity_default"] is False
    assert "operation_id" not in s["atomic_executor_execute_params"], "the id is derived, not caller-supplied"
    assert "operation_id" in s["atomic_destination_execute_claim_atomic_params"]
    assert s["atomic_destination_has_operation_identity_capability"] is False, "the base atomic destination stays a plain destination"
    assert s["atomic_destination_subclasses_operation_identity"] is False
    assert s["operation_identity_atomic_destination_subclasses_atomic"] is True
    assert s["operation_identity_atomic_destination_capability"] == "operation-identity/0.1"
    assert s["atomic_destination_has_delayed_commit_surface"] is False
    assert s["atomic_executor_mentions_operation_id"] is True and s["atomic_destination_mentions_operation_id"] is True
    section("atomic_route_surface", s)


# ---- F-5 probe on the atomic route (AtomicLocalControlPlaneExecutor + AtomicAuthorityEffectDestination) ----------------------------
#
# Setup common to these tests: the same orchestrator inputs; Control Plane profile set `off`, `identity` (operation identity on) or `full`;
# a per-grant effect cap of 1 (the shipped manifest) or 2 (a grant that legitimately allows two effects). The atomic destination has no
# operation id by default, no delayed-commit mode and no dedupe: it commits claim, budget, attempt and effect in one SQLite transaction, so there
# is no "in flight" state to renew into. The renewal re-approves under a new approval reference and moves the authority row to
# revision 2 through the destination's own writer (`set_grant_status`); `landed_same_approval` renews without a new approval reference.

ATOMIC_SETS = ("off", "identity", "full")


def atomic(r, profile, cap, case):
    return r[f"atomic_renewal[profile={profile},cap={cap},case={case}]"]


def test_atomic_route_stale_claim_is_refused_after_renewal(candidate_destinations):
    """Renewal while claim 1 is issued and not yet executed: the stale claim cannot commit (the authority row moved to revision 2, the
    destination re-validates it inside the commit transaction), r2 commits. One effect, with the profiles off or on and at either cap."""
    r = results(candidate_destinations)
    for profile in ATOMIC_SETS:
        for cap in (1, 2):
            s = atomic(r, profile, cap, "outstanding")
            assert s["d2_result"] == "authorized" and s["d2_effect_id"] != s["d1_effect_id"]
            assert s["provision2"]["raised"] is None and s["r2"]["status"] == "executed"
            assert s["r1_late"]["status"] == "denied" and s["r1_late"]["error"] == "authoritative grant state invalid"
            assert s["ledger_final"] == [s["d2_effect_id"]] and s["claim1_state"] == "issued"
            assert s["budget"]["used_effects"] == 1
    section("atomic_renewal_outstanding_claim", {"variants": 6, "effects_each": 1})


def test_atomic_route_cap_of_one_blocks_the_second_effect_after_landing(candidate_destinations):
    """Renewal after claim 1 committed (acknowledged or acknowledgement lost): with the shipped cap of 1 the shared per-grant budget
    refuses r2, so one effect. This is the cap acting, not an operation guard: see the cap-2 tests below."""
    r = results(candidate_destinations)
    for profile in ATOMIC_SETS:
        for case in ("landed", "lost_ack"):
            s = atomic(r, profile, 1, case)
            assert s["ledger_before_renewal"] == [s["d1_effect_id"]]
            assert s["d2_result"] == "authorized" and s["provision2"]["raised"] is None
            assert s["r2"]["status"] == "denied" and s["r2"]["error"] == "authoritative effect budget exhausted"
            assert s["ledger_final"] == [s["d1_effect_id"]] and s["budget"] == {"max_effects": 1, "used_effects": 1}
            if case == "lost_ack":  # blind retry of the same claim is refused: the claim is consumed
                assert s["r1"]["status"] == "unknown" and s["r1"]["observed_state"] == "applied"
                assert s["retry1"]["status"] == "denied" and s["retry1"]["error"] == "execution claim is not usable"
                assert s["claim1_state"] == "consumed"
    section("atomic_renewal_cap_one", {"variants": 6, "effects_each": 1, "barrier": "per-grant budget"})


def test_atomic_route_profile_off_still_double_commits_after_renewal_at_cap_two(candidate_destinations):
    """Legacy behaviour, still asserted (F-5 stays OPEN with the key off): the default atomic route (`AtomicAuthorityEffectDestination`,
    executor without `operation_identity`) commits TWO effects for ONE operation when the grant allows two effects.

    After claim 1 has committed (acknowledged, or acknowledgement lost) a renewal gives a new revision, effect_id and claim; the only
    cross-revision barrier is the shared per-grant budget, and with a cap of 2 it has room. Nothing was changed on this route by the
    opt-in key. Any change here (a guard appearing without the key) FAILS this test and must be recorded in the gap report."""
    r = results(candidate_destinations)
    for case in ("landed", "lost_ack"):
        s = atomic(r, "off", 2, case)
        assert s["d2_result"] == "authorized" and s["d2_effect_id"] != s["d1_effect_id"]
        assert s["provision2"]["raised"] is None
        assert s["r2"]["status"] == "executed" and s["r2"]["acknowledged"] is True
        assert sorted(s["ledger_final"]) == sorted([s["d1_effect_id"], s["d2_effect_id"]]), "profile off: two effects for one operation"
        assert s["budget"] == {"max_effects": 2, "used_effects": 2}
        assert s["attempt_joins"] == 0 and s["operations"] == 0
        if case == "lost_ack":
            assert s["retry1"]["status"] == "denied" and s["retry1"]["error"] == "execution claim is not usable"
    section("atomic_renewal_profile_off_double_commit_remains", {"effects_for_one_operation_profile_off": 2, "cap1_effects": 1})


def test_CLOSED_F5_atomic_route_with_the_operation_key_refuses_the_second_effect_at_cap_two(candidate_destinations):
    """F-5 CLOSED on the opt-in path (runtime fc034d14, R2): `AtomicLocalControlPlaneExecutor(operation_identity=True)` with
    `OperationIdentityAtomicAuthorityEffectDestination`, Control Plane profile sets `identity` and `full`, grant cap 2.

    After claim 1 committed (acknowledged, or acknowledgement lost) the renewal is authorized and claim 2 is provisioned, but the
    destination refuses the second effect for the same operation inside the commit transaction: `operation_already_committed`, the
    effect is not written, the budget is not consumed (1 of 2), and claim 2 stays `issued`. One effect. A second effect here would be a
    new finding and fails this test."""
    r = results(candidate_destinations)
    for profile in ("identity", "full"):
        for case in ("landed", "lost_ack"):
            s = atomic(r, profile, 2, case)
            assert s["ledger_before_renewal"] == [s["d1_effect_id"]]
            assert s["d2_result"] == "authorized" and s["d2_effect_id"] != s["d1_effect_id"] and s["provision2"]["raised"] is None
            assert s["r2"]["status"] == "denied" and s["r2"]["error"] == "operation_already_committed"
            assert s["r2"]["acknowledged"] is False and s["r2"]["raised"] is None
            assert len(s["ledger_final"]) == 1 and s["ledger_final"] == [s["d1_effect_id"]], "DOUBLE COMMIT with the operation key on (FINDING)"
            assert s["budget"] == {"max_effects": 2, "used_effects": 1}
            assert s["claim1_state"] == "consumed" and s["claim2_state"] == "issued"
            assert s["operations"] == 1
            if case == "lost_ack":
                assert s["retry1"]["status"] == "denied" and s["retry1"]["error"] == "execution claim is not usable"
    on = atomic(r, "identity", 2, "landed")
    section("atomic_renewal_F5_closed_opt_in", {"effects_for_one_operation_identity_on": len(on["ledger_final"]),
                                               "effects_for_one_operation_full": len(atomic(r, "full", 2, "landed")["ledger_final"]),
                                               "effects_for_one_operation_profile_off": len(atomic(r, "off", 2, "landed")["ledger_final"]),
                                               "r2_error": on["r2"]["error"], "claim2_state": on["claim2_state"], "cap1_effects": 1})


def test_atomic_route_renewal_without_a_new_approval_cannot_be_provisioned(candidate_destinations):
    """Renewing the grant revision while keeping the old approval reference: the destination refuses to provision the renewed claim
    (`existing authoritative approval state rejects claim provisioning`), so no second effect even with cap 2. The destination exposes no
    writer that moves an approval to a new grant revision (only its status), so a renewal on this route has to bring a new approval."""
    r = results(candidate_destinations)
    for profile in ATOMIC_SETS:
        s = atomic(r, profile, 2, "landed_same_approval")
        assert s["d2_result"] == "authorized"
        assert s["provision2"]["raised"] == "PermissionError: existing authoritative approval state rejects claim provisioning"
        assert "r2" not in s and s["ledger_final"] == [s["d1_effect_id"]]
    section("atomic_renewal_same_approval", {"variants": 3, "effects_each": 1})
