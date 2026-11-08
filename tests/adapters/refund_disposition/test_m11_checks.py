"""M1-1 developer checks A, B, C against the oracles frozen in orchestration/adapters/refund_disposition/ORACLES_M1_1.md (commit 9ea5825).
DEVELOPMENT ONLY / SYNTHETIC / builder-lineage developer tests; NOT independent qualification.

Run: G3_STACK_ROOT=<assembled pinned stack> F1_REQUIRE=1 python3 -m unittest discover -s tests/adapters/refund_disposition -p 'test_m11_checks.py' -v
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _fault_injection as F
import _m11_support as M
import _support as S
from orchestration.adapters.refund_disposition import PROFILE_REGISTRY_VERSION, dispose_refund, reconcile_refund
from orchestration.adapters.refund_disposition.contract import NOT_VERIFIED

HIGH_DISCLOSURES_KEYS = (("synthetic", "alias"), ("evidence", "not"))


def check_high_disclosures(tc, r):
    extra = [s for s in r.labels.not_verified if s not in NOT_VERIFIED]
    tc.assertEqual(len(extra), 2, r.labels.not_verified)
    for s in NOT_VERIFIED:
        tc.assertIn(s, r.labels.not_verified)
    low = [s.lower() for s in extra]
    tc.assertTrue(any("reviewer" in s and "alias" in s and "synthetic" in s for s in low), extra)
    tc.assertTrue(any("evidence" in s and "not evaluated" in s for s in low), extra)


def one_row_checks(tc, state, r, amount, customer):
    rows = M.effect_rows(state)
    tc.assertEqual(len(rows), 1)
    tc.assertEqual((rows[0]["state"], rows[0]["amount"], rows[0]["unit"]), ("applied", amount, "USD"))
    tc.assertIn(M.ACCOUNT + customer, json.dumps(list(rows[0].values()), default=str))
    tc.assertEqual(rows[0]["effect_id"], r.native.effect_id)
    return rows


def check_executed(tc, root, state, n, r, profile_id, amount, customer):
    tc.assertEqual(r.disposition, "executed", r)
    tc.assertEqual((r.native.cp_result, r.native.cp_reasons), ("authorized", ()))
    tc.assertEqual((r.native.runtime_status, r.native.acknowledged, r.native.newly_executed, r.native.observed_state), ("executed", True, True, "applied"))
    tc.assertEqual((r.runtime_invocations, n["execute"], n["commit"]), (1, 1, 1))
    rows = one_row_checks(tc, state, r, amount, customer)
    cp = json.loads(M.src_text(r, "cp_run_record"))
    authorized = [d for d in cp["decisions"] if d["result"] == "authorized"]
    tc.assertEqual([d["effect_id"] for d in authorized], [rows[0]["effect_id"]])
    # profile identity and its binding in CP record / Runtime export / Replay bundle
    tc.assertIsNotNone(r.profile)
    tc.assertEqual(r.profile, M.expected_identity(profile_id))
    tc.assertEqual(r.profile.registry_version, PROFILE_REGISTRY_VERSION)
    texts = {"cp": M.src_text(r, "cp_run_record"), "export": M.src_text(r, "runtime_export")}
    if r.evidence.replay is not None:
        texts["replay"] = Path(r.evidence.replay.path).read_text(encoding="utf-8")
    for name, t in texts.items():
        if t is None:
            continue
        for needle in (M.MANIFEST_ID, M.MANIFEST_VERSION, M.MANIFEST_DIGEST, r.profile.action_id):
            tc.assertIn(needle, t, f"{name} lacks {needle}")
    tc.assertIn(M.MANIFEST_DIGEST, texts["cp"])
    tc.assertIn(r.profile.action_id, texts["cp"])
    # replay
    tc.assertEqual(r.evidence.replay_state, "imported", r.evidence)
    ref = r.evidence.replay
    tc.assertTrue(Path(ref.path).is_file())
    tc.assertEqual(ref.sha256, S.sha256_file(ref.path))
    tc.assertEqual(json.loads(Path(ref.path).read_text())["status"], "reconstruction_complete")
    M.assert_common_labels(tc, r)
    M.assert_cleanup_ok(tc, r)
    if profile_id == "refund-high-v1":
        check_high_disclosures(tc, r)
    else:
        tc.assertEqual(tuple(r.labels.not_verified), tuple(NOT_VERIFIED))
    return rows


def repeat_checks(tc, make, root, state, n, r1, rows):
    r2 = dispose_refund(make())
    tc.assertEqual(r2.disposition, "executed", r2)
    tc.assertEqual(r2.native.runtime_status, "reconciled")
    tc.assertIs(r2.native.newly_executed, False)
    tc.assertEqual(r2.native.effect_id, r1.native.effect_id)
    tc.assertEqual(M.effect_rows(state), rows)
    tc.assertEqual(n["commit"], 1)
    tc.assertEqual(r2.profile, r1.profile)


class CheckA(unittest.TestCase):
    def _routine(self, profile, tag):
        root = M.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="m11-a1-") as td:
            state = Path(td)
            mk = lambda: M.make_routine_request(root, state, profile=profile, correlation=tag)
            with M.native_counters(root) as n:
                r1 = dispose_refund(mk())
                rows = check_executed(self, root, state, n, r1, "refund-routine-v1", 50.0, "customer-001")
                repeat_checks(self, mk, root, state, n, r1, rows)
            return r1.native.effect_id

    def test_a1_routine_explicit_profile(self):
        self._routine("refund-routine-v1", "m11-a1")

    def test_a1_routine_default_profile_none(self):
        self._routine(None, "m11-a1d")

    def test_a2_high_and_idempotent_repeat_and_distinct_effects(self):
        root = M.require_stack(self)
        a1 = self._routine("refund-routine-v1", "m11-a1x")
        with tempfile.TemporaryDirectory(prefix="m11-a2-") as td:
            state = Path(td)
            mk = lambda: M.make_high_request(root, state, case_reference="CASE-M11-0001", correlation="m11-a2")
            with M.native_counters(root) as n:
                r1 = dispose_refund(mk())
                rows = check_executed(self, root, state, n, r1, "refund-high-v1", 150.0, "customer-002")
                repeat_checks(self, mk, root, state, n, r1, rows)
            self.assertNotEqual(a1, r1.native.effect_id)

    def test_high_boundary_1000_executes(self):
        root = M.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="m11-a3-") as td:
            state = Path(td)
            with M.native_counters(root) as n:
                r = dispose_refund(M.make_high_request(root, state, amount=1000.0, case_reference="CASE-M11-1000", correlation="m11-a3"))
            self.assertEqual(r.disposition, "executed", r)
            self.assertEqual((n["execute"], n["commit"]), (1, 1))
            self.assertEqual(len(M.effect_rows(state)), 1)
            self.assertEqual(M.effect_rows(state)[0]["amount"], 1000.0)


class CheckB(unittest.TestCase):
    def _refuse_or_hold(self, make_req, disposition, *, reasons=None, contains=None, code=None, refusal_code=None, prefix="m11-b-", profile_present=True):
        root = M.require_stack(self)
        with tempfile.TemporaryDirectory(prefix=prefix) as td:
            state = Path(td)
            req = make_req(root, state)
            with M.native_counters(root) as n:
                r = dispose_refund(req)
            self.assertEqual(r.disposition, disposition, r)
            M.assert_no_native_activity(self, r, n, state)
            M.assert_common_labels(self, r)
            if reasons is not None:
                self.assertEqual(sorted(r.native.cp_reasons), sorted(reasons), r.native)
            if contains is not None:
                self.assertIn(contains, r.native.cp_reasons)
            if refusal_code is not None:
                self.assertIsNotNone(r.refusal)
                self.assertEqual(r.refusal.code, refusal_code, r.refusal)
            if disposition == "held":
                self.assertEqual(r.native.cp_result, "hold")
                self.assertIsNotNone(r.profile)
            return r

    def test_b1_unsupported_profile_ids(self):
        for pid in ("refund-ghost-v1", "", 7, ["refund-high-v1"]):
            with self.subTest(profile=pid):
                r = self._refuse_or_hold(lambda root, st: M.make_routine_request(root, st, profile=pid), "refused", refusal_code="profile_unsupported")
                self.assertIsNone(r.profile)
                self.assertEqual(r.native.cp_result, None)

    def test_b2_customer001_under_high_target_out_of_scope(self):
        def mk(root, st):
            lin = lambda b: b["origins"][0]["permission_scope"].__setitem__("targets", [M.ACCOUNT + "customer-001", M.ACCOUNT + "customer-002"])
            def fm(f):
                f["requirement"]["permissions"][0]["targets"] = [M.ACCOUNT + "customer-001", M.ACCOUNT + "customer-002"]
            return M.make_high_request(root, st, customer="customer-001", facts_mutator=fm, lineage_mutator=lin)
        r = self._refuse_or_hold(mk, "held", reasons=["target_out_of_scope"])

    def test_b3_customer002_under_routine_target_out_of_scope(self):
        def mk(root, st):
            lin = lambda b: b["origins"][0]["permission_scope"].__setitem__("targets", [M.ACCOUNT + "customer-001", M.ACCOUNT + "customer-002"])
            def fm(f):
                f["requirement"]["permissions"][0]["targets"] = [M.ACCOUNT + "customer-001", M.ACCOUNT + "customer-002"]
            return M.make_routine_request(root, st, profile="refund-routine-v1", customer="customer-002", facts_mutator=fm, lineage_mutator=lin)
        self._refuse_or_hold(mk, "held", reasons=["target_out_of_scope"])

    AMOUNT3 = ["amount_exceeded", "grant_scope_mismatch", "requirement_scope_mismatch"]

    def test_b4_high_over_limit(self):
        self._refuse_or_hold(lambda root, st: M.make_high_request(root, st, amount=1000.01), "held", reasons=self.AMOUNT3)

    def test_b5_routine_over_limit(self):
        self._refuse_or_hold(lambda root, st: M.make_routine_request(root, st, profile="refund-routine-v1", amount=100.01), "held", reasons=self.AMOUNT3)

    def test_b6_cross_tenant_request_invalid(self):
        r = self._refuse_or_hold(lambda root, st: M.make_high_request(root, st, tenant="tenant-other"), "refused", refusal_code="request_invalid")
        self.assertIsNone(r.profile)

    def test_b7_revoked_lineage(self):
        self._refuse_or_hold(lambda root, st: M.make_high_request(root, st, lineage="high_lineage_revoked.json"), "held", contains="grant_revoked")
        self._refuse_or_hold(lambda root, st: M.make_routine_request(root, st, bundle="root_lineage_revoked.json"), "held", contains="grant_revoked")

    FOUR = ["authority_requirement_mismatch", "consequence_tier_mismatch", "requirement_scope_mismatch", "review_requirement_not_resolved"]

    def test_b8a_high_profile_routine_facts_high_lineage(self):
        # Amendment 2026-11-08 (ORACLES_M1_1.md): exactly the four reasons for routine FACTS with the HIGH lineage
        self._refuse_or_hold(lambda root, st: M.make_high_profile_routine_facts_request(root, st, high_lineage=True), "held", reasons=self.FOUR)

    def test_b8b_high_profile_routine_facts_routine_lineage(self):
        # Amendment 2026-11-08: the same four plus grant_scope_mismatch when the lineage is also the routine one
        self._refuse_or_hold(lambda root, st: M.make_high_profile_routine_facts_request(root, st, high_lineage=False), "held",
                             reasons=sorted(self.FOUR + ["grant_scope_mismatch"]))

    def test_b9_institution_mismatch(self):
        def lin(b):
            b["origins"][0]["institution_id"] = "urn:cognous:institution:m11-other"
        self._refuse_or_hold(lambda root, st: M.make_high_request(root, st, lineage_mutator=lin), "held", contains="institution_mismatch")

    def test_b10_case_reference_profile_payload(self):
        self._refuse_or_hold(lambda root, st: M.make_high_request(root, st, case_reference=None), "refused", refusal_code="request_invalid")
        self._refuse_or_hold(lambda root, st: M.make_routine_request(root, st, profile="refund-routine-v1", case_reference="CASE-X"), "refused", refusal_code="request_invalid")
        self._refuse_or_hold(lambda root, st: M.make_routine_request(root, st, profile=None, case_reference="CASE-X"), "refused", refusal_code="request_invalid")
        r = self._refuse_or_hold(lambda root, st: M.make_high_request(root, st, case_reference=None), "refused", refusal_code="request_invalid")
        self.assertIn("case_reference_required_for_profile", r.refusal.reason)
        r = self._refuse_or_hold(lambda root, st: M.make_routine_request(root, st, case_reference="CASE-X"), "refused", refusal_code="request_invalid")
        self.assertIn("case_reference_not_allowed_for_profile", r.refusal.reason)

    def test_b11_registry_digest_mismatch(self):
        import dataclasses
        from unittest import mock
        from orchestration.adapters.refund_disposition import profiles
        bad = dataclasses.replace(profiles.REGISTRY["refund-high-v1"], manifest_digest="sha256:" + "0" * 64)
        with mock.patch.dict(profiles.REGISTRY, {"refund-high-v1": bad}):
            r = self._refuse_or_hold(lambda root, st: M.make_high_request(root, st), "refused", refusal_code="profile_manifest_digest_mismatch")
        self.assertIsNone(r.profile)

    def test_b12_declared_evidence_obligation_holds(self):
        def fm(f):
            f["requirement"]["evidence"] = [{"obligation_id": "urn:cognous:evidence:refund-entitlement", "source_ref": "urn:cognous:harborview-synthetic:evidence-1",
                                              "kind": "authorization", "required": True, "max_age_seconds": 3600}]
        r = self._refuse_or_hold(lambda root, st: M.make_high_request(root, st, facts_mutator=fm), "held")
        self.assertNotEqual(r.disposition, "executed")

    def test_b13_wrong_role_alias_holds(self):
        def fm(f):
            f["role_mapping"]["aliases"] = {"refund-authorizer": ["urn:cognous:role:someone-else"]}
        r = self._refuse_or_hold(lambda root, st: M.make_high_request(root, st, facts_mutator=fm), "held", contains="review_requirement_not_resolved")

    def test_unit_mismatch_eur(self):
        self._refuse_or_hold(lambda root, st: M.make_high_request(root, st, unit="EUR"), "held", contains="amount_unit_mismatch")


class CheckC(unittest.TestCase):
    def test_high_lost_ack_unknown_then_reconcile_and_cross_profile(self):
        root = M.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="m11-c-") as td:
            state = Path(td)
            mk = lambda: M.make_high_request(root, state, case_reference="CASE-M11-0002", correlation="m11-c")
            with M.native_counters(root) as n:
                r = F.dispose_with_lost_ack_unavailable_observation(mk())
                self.assertEqual(r.disposition, "unknown", r)
                self.assertEqual(r.native.runtime_status, "unknown")
                self.assertIs(r.native.acknowledged, False)
                self.assertEqual((n["execute"], n["commit"], r.runtime_invocations), (1, 1, 1))
                rows = M.effect_rows(state)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["state"], "applied")
                self.assertIs(r.effect_absence_established, False)
                self.assertEqual(r.next_step, "reconcile_read_only")
                self.assertEqual(r.profile, M.expected_identity("refund-high-v1"))
                cp = M.src_text(r, "cp_run_record")
                self.assertIn(r.profile.manifest_digest, cp)
                self.assertIn(r.profile.action_id, cp)
                M.assert_common_labels(self, r)
                M.assert_cleanup_ok(self, r)
                # re-dispose: refused prior_uncertain_dispatch, nothing dispatched
                r2 = dispose_refund(mk())
                self.assertEqual(r2.disposition, "refused", r2)
                self.assertEqual(r2.refusal.code, "prior_uncertain_dispatch")
                self.assertEqual(r2.runtime_invocations, 0)
                self.assertEqual((n["execute"], n["commit"]), (1, 1))
                self.assertEqual(M.effect_rows(state), rows)
                # reconcile with the same profile
                rec = reconcile_refund(mk())
                self.assertEqual(rec.disposition, "executed", rec)
                self.assertEqual(rec.native.runtime_status, "observed")
                self.assertEqual(rec.native.observed_state, "applied")
                self.assertIs(rec.native.newly_executed, False)
                self.assertIs(rec.native.acknowledged, False)
                self.assertEqual(rec.runtime_invocations, 0)
                self.assertEqual(rec.mode, "reconcile")
                self.assertEqual((n["execute"], n["commit"]), (1, 1))
                self.assertEqual(M.effect_rows(state), rows)
                self.assertEqual(rec.profile, r.profile)
                M.assert_common_labels(self, rec)
                # reconcile under the other profile finds no authorized decision
                wrong = reconcile_refund(M.make_routine_request(root, state, profile="refund-routine-v1", correlation="m11-c"))
                self.assertEqual(wrong.disposition, "refused", wrong)
                self.assertEqual(wrong.refusal.code, "no_authorized_decision_for_proposal")
                self.assertEqual(wrong.runtime_invocations, 0)
                self.assertEqual((n["execute"], n["commit"]), (1, 1))
                self.assertEqual(M.effect_rows(state), rows)


if __name__ == "__main__":
    unittest.main()
