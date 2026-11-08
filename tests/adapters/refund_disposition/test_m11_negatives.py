"""M1-1 additional mandatory affected-path T3 checks (ORACLES_M1_1.md, last section). DEVELOPMENT ONLY / SYNTHETIC / builder-lineage.

Run: G3_STACK_ROOT=<assembled pinned stack> F1_REQUIRE=1 python3 -m unittest discover -s tests/adapters/refund_disposition -p 'test_m11_negatives.py' -v
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _m11_support as M
import orchestration.adapters.refund_disposition as pkg
from orchestration.adapters.refund_disposition import dispose_refund, reconcile_refund


class Surface(unittest.TestCase):
    def test_request_has_no_manifest_path_or_bytes_or_fault_names(self):
        for cls in (pkg.DispositionRequest, pkg.RefundProposal, pkg.SyntheticEnvironment, pkg.AuthorityFacts):
            names = [f.name.lower() for f in dataclasses.fields(cls)]
            for bad in ("manifest", "inject", "fault", "simulate", "dev_fault"):
                self.assertFalse([x for x in names if bad in x], (cls, names))
        self.assertIn("profile", [f.name for f in dataclasses.fields(pkg.DispositionRequest)])
        self.assertIn("case_reference", [f.name for f in dataclasses.fields(pkg.RefundProposal)])
        for fn in (pkg.dispose_refund, pkg.reconcile_refund):
            self.assertEqual(list(inspect.signature(fn).parameters), ["request"])

    def test_all_has_no_fault_or_injection_names(self):
        for name in pkg.__all__:
            low = name.lower()
            for bad in ("fault", "inject", "simulate", "dev_fault", "testinjection"):
                self.assertNotIn(bad, low, name)
        for needed in ("PROFILE_REGISTRY_VERSION", "ProfileIdentity"):
            self.assertIn(needed, pkg.__all__)

    def test_registry_is_closed_and_frozen(self):
        from orchestration.adapters.refund_disposition import profiles
        self.assertEqual(sorted(profiles.REGISTRY), ["refund-high-v1", "refund-routine-v1"])
        self.assertEqual(profiles.REGISTRY["refund-routine-v1"].action_id, M.ROUTINE_ACTION)
        self.assertEqual(profiles.REGISTRY["refund-high-v1"].action_id, M.HIGH_ACTION)
        for p in profiles.REGISTRY.values():
            self.assertEqual((p.manifest_id, p.manifest_version, p.manifest_digest), (M.MANIFEST_ID, M.MANIFEST_VERSION, M.MANIFEST_DIGEST))
            with self.assertRaises(dataclasses.FrozenInstanceError):
                p.action_id = "x"  # type: ignore[misc]
        self.assertEqual(pkg.PROFILE_REGISTRY_VERSION, M.REGISTRY_VERSION)

    def test_no_forbidden_imports(self):
        root = Path(pkg.__file__).parent
        for f in root.glob("*.py"):
            for line in f.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith(("import ", "from ")):
                    low = s.lower()
                    for bad in ("verifier", "attestation", "odes", "gax"):
                        self.assertNotIn(bad, low.split("#")[0].split(), f"{f.name}: {s}")
                    self.assertFalse(any(b in low for b in ("verifier", "attestation", "registry_service", " odes", " gax")), f"{f.name}: {s}")


class Negatives(unittest.TestCase):
    def _run(self, make, *, fn=dispose_refund, prefix="m11-n-"):
        root = M.require_stack(self)
        with tempfile.TemporaryDirectory(prefix=prefix) as td:
            state = Path(td)
            req = make(root, state)
            with M.native_counters(root) as n:
                r = fn(req)
            return r, n, state

    def _no_effect(self, r, n, state):
        M.assert_no_native_activity(self, r, n, state)
        M.assert_common_labels(self, r)

    def test_three_reason_exact_sets_high_and_routine(self):
        want = ["amount_exceeded", "grant_scope_mismatch", "requirement_scope_mismatch"]
        for label, mk in (("high", lambda root, st: M.make_high_request(root, st, amount=1000.01)),
                          ("routine", lambda root, st: M.make_routine_request(root, st, profile="refund-routine-v1", amount=100.01))):
            with self.subTest(label):
                r, n, st = self._run(mk)
                self.assertEqual(r.disposition, "held")
                self.assertEqual(sorted(set(r.native.cp_reasons)), want)
                self._no_effect(r, n, st)

    def test_reason_sets_cross_profile_facts(self):
        four = ["authority_requirement_mismatch", "consequence_tier_mismatch", "requirement_scope_mismatch", "review_requirement_not_resolved"]
        for high_lineage, expected in ((True, four), (False, sorted(four + ["grant_scope_mismatch"]))):
            with self.subTest(high_lineage=high_lineage):
                r, n, st = self._run(lambda root, s: M.make_high_profile_routine_facts_request(root, s, high_lineage=high_lineage))
                self.assertEqual(r.disposition, "held")
                self.assertEqual(sorted(set(r.native.cp_reasons)), expected)
                self._no_effect(r, n, st)

    def test_routine_facts_with_high_manifest_reverse(self):
        # high facts/lineage under the routine profile: held, never executed, no native effect
        r, n, st = self._run(lambda root, s: M.make_high_request(root, s, profile="refund-routine-v1", case_reference=None))
        self.assertEqual(r.disposition, "held", r)
        self._no_effect(r, n, st)

    def test_declared_evidence_obligation_holds_never_executes(self):
        def fm(f):
            f["requirement"]["evidence"] = [{"obligation_id": "urn:cognous:evidence:refund-entitlement", "source_ref": "urn:cognous:harborview-synthetic:evidence-1",
                                              "kind": "authorization", "required": True, "max_age_seconds": 3600}]
        r, n, st = self._run(lambda root, s: M.make_high_request(root, s, facts_mutator=fm))
        self.assertEqual(r.disposition, "held", r)
        self.assertNotEqual(r.disposition, "executed")
        self._no_effect(r, n, st)

    def test_wrong_role_alias_holds_and_never_authenticated(self):
        def fm(f):
            f["role_mapping"]["aliases"] = {"refund-authorizer": ["urn:cognous:role:not-the-authorizer"]}
        r, n, st = self._run(lambda root, s: M.make_high_request(root, s, facts_mutator=fm))
        self.assertEqual(r.disposition, "held")
        self.assertIn("review_requirement_not_resolved", r.native.cp_reasons)
        self.assertIs(r.labels.authenticated, False)
        self._no_effect(r, n, st)

    def test_institution_mismatch(self):
        def lin(b):
            b["origins"][0]["institution_id"] = "urn:cognous:institution:m11-other"
        r, n, st = self._run(lambda root, s: M.make_high_request(root, s, lineage_mutator=lin))
        self.assertEqual(r.disposition, "held")
        self.assertIn("institution_mismatch", r.native.cp_reasons)
        self._no_effect(r, n, st)

    def test_authority_domain_mismatch_holds(self):
        def lin(b):
            b["origins"][0]["authority_domain"] = "m11-other-domain"
        r, n, st = self._run(lambda root, s: M.make_high_request(root, s, lineage_mutator=lin))
        self.assertEqual(r.disposition, "held", r)
        self._no_effect(r, n, st)

    def test_unit_mismatch(self):
        r, n, st = self._run(lambda root, s: M.make_high_request(root, s, unit="EUR"))
        self.assertEqual(r.disposition, "held")
        self.assertIn("amount_unit_mismatch", r.native.cp_reasons)
        self._no_effect(r, n, st)

    def test_malformed_case_reference_refused(self):
        for bad in ("", "   ", "\t\n", 7, b"CASE", ["CASE-1"], {"a": 1}):
            with self.subTest(case_reference=bad):
                r, n, st = self._run(lambda root, s: M.make_high_request(root, s, case_reference=bad))
                self.assertEqual(r.disposition, "refused", r)
                self.assertEqual(r.refusal.code, "request_invalid")
                self.assertIsNone(r.profile)
                self._no_effect(r, n, st)

    def test_unsupported_profile_ids_refused(self):
        for bad in ("refund-ghost-v1", "REFUND-HIGH-V1", " refund-high-v1", "", 0, 1.5, ["refund-high-v1"], object()):
            with self.subTest(profile=bad):
                r, n, st = self._run(lambda root, s: M.make_high_request(root, s, profile=bad))
                self.assertEqual(r.disposition, "refused", r)
                self.assertEqual(r.refusal.code, "profile_unsupported")
                self.assertIsNone(r.profile)
                self._no_effect(r, n, st)

    def test_reconcile_unsupported_profile_refused(self):
        r, n, st = self._run(lambda root, s: M.make_high_request(root, s, profile="refund-ghost-v1"), fn=reconcile_refund)
        self.assertEqual(r.disposition, "refused", r)
        self.assertEqual(r.refusal.code, "profile_unsupported")
        self._no_effect(r, n, st)

    def test_manifest_digest_tampering_refuses_before_any_effect(self):
        from orchestration.adapters.refund_disposition import profiles
        for pid, mk in (("refund-high-v1", lambda root, s: M.make_high_request(root, s)),
                        ("refund-routine-v1", lambda root, s: M.make_routine_request(root, s, profile="refund-routine-v1"))):
            with self.subTest(pid):
                bad = dataclasses.replace(profiles.REGISTRY[pid], manifest_digest="sha256:" + "f" * 64)
                with mock.patch.dict(profiles.REGISTRY, {pid: bad}):
                    r, n, st = self._run(mk)
                self.assertEqual(r.disposition, "refused", r)
                self.assertEqual(r.refusal.code, "profile_manifest_digest_mismatch")
                self.assertIsNone(r.profile)
                self._no_effect(r, n, st)

    def test_manifest_errors_nonempty_is_profile_manifest_invalid(self):
        from orchestration.adapters.refund_disposition import profiles
        root = M.require_stack(self)
        from orchestration.adapters.refund_disposition.stack import load_stack
        S_ = load_stack(root)
        target = None
        for owner in (S_.B, getattr(S_, "control_plane", None)):
            if owner is not None and hasattr(owner, "manifest_errors"):
                target = owner
                break
        if target is None:
            self.skipTest("manifest_errors seam not reachable as S.B.manifest_errors in this stack handle")
        with mock.patch.object(target, "manifest_errors", return_value=["synthetic_error"]):
            r, n, st = self._run(lambda root, s: M.make_high_request(root, s))
        self.assertEqual(r.disposition, "refused", r)
        self.assertEqual(r.refusal.code, "profile_manifest_invalid")
        self._no_effect(r, n, st)

    def test_cross_tenant_request_invalid(self):
        r, n, st = self._run(lambda root, s: M.make_high_request(root, s, tenant="tenant-alpha"))
        self.assertEqual((r.disposition, r.refusal.code), ("refused", "request_invalid"))
        self._no_effect(r, n, st)

    def test_policy_never_exceeds_manifest_cap(self):
        # an authorized path beyond the manifest cap is impossible: 100.01 routine / 1000.01 high never reach the Runtime even with wide facts
        def wide_f(f):
            f["requirement"]["permissions"][0]["max_amount"] = 5000.0
        def wide_l(b):
            b["origins"][0]["permission_scope"]["max_amount"] = 5000.0
        for mk in (lambda root, s: M.make_high_request(root, s, amount=1000.01, facts_mutator=wide_f, lineage_mutator=wide_l),
                   lambda root, s: M.make_routine_request(root, s, profile="refund-routine-v1", amount=100.01, facts_mutator=wide_f, lineage_mutator=wide_l)):
            r, n, st = self._run(mk)
            self.assertNotEqual(r.disposition, "executed", r)
            self.assertEqual(M.effect_rows(st), [])
            self.assertEqual((n["execute"], n["commit"]), (0, 0)) if r.runtime_invocations == 0 else self.assertEqual(n["commit"], 0)

    def test_derived_runtime_policy_equals_manifest_values(self):
        root = M.require_stack(self)
        from orchestration.adapters.refund_disposition import dispose as D
        from orchestration.adapters.refund_disposition.stack import load_stack
        S_ = load_stack(root)
        seen = []
        real = S_.engine_safe_executor.LocalExecutionPolicy

        def spy(*a, **k):
            seen.append(k)
            return real(*a, **k)
        manifest = json.loads((root / "control_plane/tests/fixtures/refund_integration_v1_1.manifest.json").read_text())
        for pid, action_id, cust, amount in (("refund-routine-v1", M.ROUTINE_ACTION, "customer-001", 50.0), ("refund-high-v1", M.HIGH_ACTION, "customer-002", 150.0)):
            act = next(a for a in manifest["actions"] if a["action_id"] == action_id)
            seen.clear()
            with tempfile.TemporaryDirectory(prefix="m11-pol-") as td:
                req = (M.make_high_request(root, Path(td), customer=cust, amount=amount) if pid == "refund-high-v1"
                       else M.make_routine_request(root, Path(td), profile=pid))
                with mock.patch.object(S_.engine_safe_executor, "LocalExecutionPolicy", spy):
                    r = dispose_refund(req)
            self.assertEqual(r.disposition, "executed", r)
            self.assertTrue(seen, "policy constructed")
            k = seen[-1]
            self.assertEqual(float(k["max_amount"]), float(act["effect_limits"]["max_amount"]))
            self.assertEqual(set(k["allowed_units"]), {act["effect_limits"]["unit"]})
            self.assertEqual(k["max_effects"], act["effect_limits"]["max_effects"])

    def test_cross_profile_reuse_on_reconcile(self):
        root = M.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="m11-x-") as td:
            state = Path(td)
            r = dispose_refund(M.make_high_request(root, state, case_reference="CASE-M11-0003"))
            self.assertEqual(r.disposition, "executed", r)
            rows = M.effect_rows(state)
            for mk in (lambda: M.make_routine_request(root, state, profile="refund-routine-v1", correlation="m11-check"),
                       lambda: M.make_routine_request(root, state, profile=None, correlation="m11-check")):
                with M.native_counters(root) as n:
                    w = reconcile_refund(mk())
                self.assertEqual(w.disposition, "refused", w)
                self.assertEqual(w.refusal.code, "no_authorized_decision_for_proposal")
                self.assertEqual((w.runtime_invocations, n["execute"], n["commit"]), (0, 0, 0))
                self.assertEqual(M.effect_rows(state), rows)

    def test_idempotent_repeat_per_profile_one_row(self):
        root = M.require_stack(self)
        for pid in ("refund-routine-v1", "refund-high-v1"):
            with self.subTest(pid), tempfile.TemporaryDirectory(prefix="m11-i-") as td:
                state = Path(td)
                mk = (lambda: M.make_high_request(root, state, correlation="m11-idem")) if pid == "refund-high-v1" \
                    else (lambda: M.make_routine_request(root, state, profile=pid, correlation="m11-idem"))
                r1, r2, r3 = dispose_refund(mk()), dispose_refund(mk()), dispose_refund(mk())
                self.assertEqual([x.disposition for x in (r1, r2, r3)], ["executed"] * 3)
                self.assertEqual(len(M.effect_rows(state)), 1)
                self.assertEqual({x.native.effect_id for x in (r1, r2, r3)}, {r1.native.effect_id})

    def test_workspace_cleanup_reported_ok_on_every_path(self):
        root = M.require_stack(self)
        cases = [
            lambda s: M.make_high_request(root, s),
            lambda s: M.make_high_request(root, s, amount=1000.01),
            lambda s: M.make_high_request(root, s, case_reference=None),
            lambda s: M.make_high_request(root, s, profile="refund-ghost-v1"),
            lambda s: M.make_routine_request(root, s, profile="refund-routine-v1"),
        ]
        for i, mk in enumerate(cases):
            with self.subTest(i), tempfile.TemporaryDirectory(prefix="m11-w-") as td:
                r = dispose_refund(mk(Path(td)))
                M.assert_cleanup_ok(self, r)


if __name__ == "__main__":
    unittest.main()
