"""Refund Desk (F3) M1-2 developer CHECKS A, B, C (two supported F1 profiles).

DEVELOPMENT ONLY / SYNTHETIC / test-owner developer checks, NOT independent qualification.
Expectations are frozen in Amendment M2 of applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md; this file asserts them as frozen.

Run: F3_STACK_ROOT=<assembled pinned stack> F3_REQUIRE=1 python -m unittest discover -s tests/applications/refund_desk -p 'test_m12_checks.py' -v
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_file_location("_refund_desk_m12_support", Path(__file__).with_name("_m12_support.py"))
M = sys.modules.get("_refund_desk_m12_support") or importlib.util.module_from_spec(_spec)
sys.modules["_refund_desk_m12_support"] = M
if not hasattr(M, "HIGH"):
    _spec.loader.exec_module(M)
S = M.S

APP_CONTRACT = "refund-desk/0.1.0-dev"
LEGACY_KEYS = {"app_contract", "f1_contract_version", "case_id", "outcome", "message", "control_plane", "native", "execution_claim", "effect", "evidence",
               "refusal", "permitted_next_actions", "retry_permission", "effect_absence_established", "labels", "limitations", "cleanup"}
M2_KEYS = LEGACY_KEYS | {"profile", "requested_profile"}
SUCCESS_WORDS = re.compile(r"\b(executed|succeeded|success|successful|applied)\b")


def not_verified() -> tuple[str, ...]:
    from orchestration.adapters.refund_disposition.contract import NOT_VERIFIED

    return NOT_VERIFIED


class Base(unittest.TestCase):
    def shape_ok(self, d: dict) -> None:
        self.assertEqual(d["app_contract"], APP_CONTRACT)
        self.assertEqual(set(d), M2_KEYS, "exactly the historical keys plus profile and requested_profile")
        json.dumps(d)
        self.assertEqual(json.loads(json.dumps(d)), d)

    def labels_ok(self, d: dict) -> None:
        lb = d["labels"]
        self.assertIs(lb["synthetic_authority"], True)
        self.assertIs(lb["authenticated"], False)
        self.assertEqual(lb["evidence_basis"], "producer_reported")
        self.assertIs(lb["nonproduction"], True)
        self.assertEqual(lb["retry_permission"], "not_established")
        self.assertEqual(d["retry_permission"], "not_established")
        self.assertTrue(d["cleanup"]["ok"], d["cleanup"])


class CheckA(Base):
    def assert_a(self, d: dict, state: Path, spec: dict, *, profile_id: str, requested, amount: float, first: bool = True, rows_expected=None):
        self.shape_ok(d)
        self.assertEqual(d["case_id"], spec["case_id"])
        self.assertEqual(d["outcome"], "executed", d)
        self.assertEqual(d["control_plane"]["result"], "authorized")
        self.assertEqual(list(d["control_plane"]["reasons"]), [])
        n = d["native"]
        self.assertEqual(n["disposition"], "executed")
        if first:
            self.assertEqual(n["runtime_status"], "executed")
        self.assertIs(n["newly_executed"], first)
        self.assertEqual(n["runtime_invocations"], 1)
        self.assertIs(n["runtime_invoked"], True)
        self.assertIs(d["execution_claim"]["supported"], True)
        rows = S.effect_rows(state)
        self.assertEqual(len(rows), 1, rows)
        self.assertTrue(d["effect"]["effect_id"])
        self.assertEqual(d["effect"]["effect_id"], rows[0]["effect_id"])
        self.assertEqual((rows[0]["state"], rows[0]["amount"], rows[0]["unit"]), ("applied", amount, "USD"))
        if rows_expected is not None:
            self.assertEqual(rows, rows_expected)
        # profile identity block and requested_profile
        self.assertEqual(d["profile"], M.IDENTITY[profile_id])
        self.assertEqual(d["requested_profile"], requested)
        # Replay evidence, independently recomputed
        ev = d["evidence"]
        self.assertEqual(ev["replay_state"], "imported", ev)
        self.assertIs(ev["replay"]["resolvable"], True)
        self.assertEqual(ev["replay"]["status"], "reconstruction_complete")
        self.assertEqual(ev["replay"]["sha256"], S.sha256_file(ev["replay"]["path"]))
        self.assertTrue(ev["source"])
        for src in ev["source"]:
            self.assertIs(src["resolvable"], True, src)
            self.assertEqual(src["sha256"], S.sha256_file(src["path"]), src)
        self.labels_ok(d)
        self.assertEqual(d["permitted_next_actions"], [])
        # limitations
        if profile_id == M.ROUTINE:
            self.assertEqual(d["limitations"], list(not_verified()) + list(M.LEGACY_APP_NOTES), "default limitations byte-identical to the legacy list")
        else:
            for s in M.HIGH_DISCLOSURES:
                self.assertIn(s, d["limitations"])
                self.assertIn(s, d["labels"]["not_verified"])
            self.assertNotIn(M.LEGACY_APP_NOTES[2], d["limitations"])
            self.assertFalse(any("100.00 USD" in s for s in d["limitations"]), d["limitations"])
        return rows

    def _run(self, root, spec, **kw):
        from refund_desk import process_refund

        with S.tempdir("m12-a-") as td:
            state = Path(td)
            with S.native_counters(root) as n:
                d = process_refund(M.make_case(spec), S.make_config(root, state)).to_dict()
            rows = self.assert_a(d, state, spec, **kw)
            self.assertEqual((n["execute"], n["commit"]), (1, 1))
            d2 = process_refund(M.make_case(spec), S.make_config(root, state)).to_dict()
            self.assertEqual((n["execute"], n["commit"]), (1, 1), "idempotent repeat: no additional native execute/commit")
            self.assertEqual(d2["outcome"], "executed", d2)
            self.assertEqual(d2["effect"]["effect_id"], d["effect"]["effect_id"])
            self.assertIs(d2["native"]["newly_executed"], False)
            self.assertEqual(S.effect_rows(state), rows)
            self.assertEqual(d2["profile"], d["profile"])
            self.assertEqual(d2["requested_profile"], d["requested_profile"])
            return d

    def test_a1_default_profile_api_and_repeat(self):
        root = S.require_stack(self)
        d = self._run(root, M.A1, profile_id=M.ROUTINE, requested=None, amount=64.25)
        self.assertEqual(set(d) - LEGACY_KEYS, {"profile", "requested_profile"}, "default output = legacy shape plus the two additive keys")

    def test_a2_high_profile_api_and_repeat(self):
        root = S.require_stack(self)
        self._run(root, M.A2, profile_id=M.HIGH, requested=M.HIGH, amount=150.0)

    def test_a1_and_a2_have_distinct_effects(self):
        root = S.require_stack(self)
        from refund_desk import process_refund

        with S.tempdir("m12-a-d1-") as t1, S.tempdir("m12-a-d2-") as t2:
            d1 = process_refund(M.make_case(M.A1), S.make_config(root, Path(t1))).to_dict()
            d2 = process_refund(M.make_case(M.A2), S.make_config(root, Path(t2))).to_dict()
            self.assertNotEqual(d1["effect"]["effect_id"], d2["effect"]["effect_id"])

    def test_a1_default_via_cli_and_repeat(self):
        root = S.require_stack(self)
        from refund_desk import process_refund

        with S.tempdir("m12-a1-cli-") as td, S.tempdir("m12-a1-api-") as td2:
            state = Path(td)
            p = S.run_cli(M.cli_args("process", M.A1, state), root=root)
            self.assertEqual(p.returncode, 0, (p.stdout, p.stderr))
            d = json.loads(p.stdout)
            rows = self.assert_a(d, state, M.A1, profile_id=M.ROUTINE, requested=None, amount=64.25)
            api = process_refund(M.make_case(M.A1), S.make_config(root, Path(td2))).to_dict()
            self.assertEqual(S.key_shape(d), S.key_shape(api))
            p2 = S.run_cli(M.cli_args("process", M.A1, state), root=root)
            self.assertEqual(p2.returncode, 0, (p2.stdout, p2.stderr))
            d2 = json.loads(p2.stdout)
            self.assertEqual(d2["effect"]["effect_id"], d["effect"]["effect_id"])
            self.assertIs(d2["native"]["newly_executed"], False)
            self.assertEqual(S.effect_rows(state), rows)

    def test_a2_high_via_cli_and_repeat(self):
        root = S.require_stack(self)
        with S.tempdir("m12-a2-cli-") as td:
            state = Path(td)
            p = S.run_cli(M.cli_args("process", M.A2, state), root=root)
            self.assertEqual(p.returncode, 0, (p.stdout, p.stderr))
            d = json.loads(p.stdout)  # exactly one JSON object on stdout
            rows = self.assert_a(d, state, M.A2, profile_id=M.HIGH, requested=M.HIGH, amount=150.0)
            p2 = S.run_cli(M.cli_args("process", M.A2, state), root=root)
            self.assertEqual(p2.returncode, 0, (p2.stdout, p2.stderr))
            d2 = json.loads(p2.stdout)
            self.assertEqual(d2["outcome"], "executed")
            self.assertEqual(d2["effect"]["effect_id"], d["effect"]["effect_id"])
            self.assertIs(d2["native"]["newly_executed"], False)
            self.assertEqual(S.effect_rows(state), rows)

    def test_a2_boundary_1000_executes_api_and_cli(self):
        root = S.require_stack(self)
        from refund_desk import process_refund

        with S.tempdir("m12-a2-max-") as td:
            state = Path(td)
            d = process_refund(M.make_case(M.A2_BOUNDARY), S.make_config(root, state)).to_dict()
            self.assert_a(d, state, M.A2_BOUNDARY, profile_id=M.HIGH, requested=M.HIGH, amount=1000.0)
        with S.tempdir("m12-a2-max-cli-") as td:
            state = Path(td)
            p = S.run_cli(M.cli_args("process", M.A2_BOUNDARY, state), root=root)
            self.assertEqual(p.returncode, 0, (p.stdout, p.stderr))
            self.assert_a(json.loads(p.stdout), state, M.A2_BOUNDARY, profile_id=M.HIGH, requested=M.HIGH, amount=1000.0)


class CheckB(Base):
    def assert_b(self, d: dict, state: Path, spec: dict, *, outcome: str, code: str, profile_id, reasons=None, contains=None) -> None:
        self.shape_ok(d)
        self.assertEqual(d["case_id"], spec["case_id"])
        self.assertEqual(d["outcome"], outcome, d)
        self.assertNotEqual(d["outcome"], "executed")
        self.assertEqual(d["refusal"]["code"], code, d["refusal"])
        self.assertIs(d["native"]["runtime_invoked"], False)
        self.assertEqual(d["native"]["runtime_invocations"], 0)
        self.assertIs(d["execution_claim"]["supported"], False)
        self.assertFalse(S.db_path(state).exists(), "no SQLite database file (so no effect rows and no grant mirror)")
        self.assertEqual(S.effect_rows(state), [])
        self.assertEqual([f for f in S.all_files(state) if f.endswith((".sqlite3", ".sqlite", ".db"))], [])
        self.assertIsNone(d["evidence"]["replay"])
        self.assertEqual(d["evidence"]["replay_state"], "not_run")
        self.assertEqual(d["permitted_next_actions"], [])
        self.assertEqual(d["retry_permission"], "not_established")
        self.assertIs(d["effect_absence_established"], False)
        self.assertIsNone(SUCCESS_WORDS.search(d["message"].lower()), d["message"])
        if profile_id is None:
            self.assertIsNone(d["effect"]["effect_id"])
        # a native hold carries the would-be effect id from the Control Plane; no effects row exists (checked above), so only the claim is asserted
        self.assertEqual(d["requested_profile"], spec.get("profile"), "requested_profile is echoed in every refusal/hold")
        if profile_id is None:
            self.assertIsNone(d["profile"], "pre-flight refusals carry no profile block")
        else:
            self.assertEqual(d["profile"], M.IDENTITY[profile_id])
        if reasons is not None:
            self.assertEqual(sorted(d["control_plane"]["reasons"]), sorted(reasons))
            self.assertEqual(sorted(d["refusal"]["reasons"]), sorted(reasons))
        if contains is not None:
            self.assertIn(contains, " ".join([*d["refusal"]["reasons"], d["refusal"]["explanation"], d["message"]]))
        self.labels_ok(d)

    def go(self, spec: dict, **kw):
        root = S.require_stack(self)
        from refund_desk import process_refund

        with S.tempdir("m12-b-") as td:
            state = Path(td)
            with S.native_counters(root) as n:
                d = process_refund(M.make_case(spec), S.make_config(root, state)).to_dict()
            self.assert_b(d, state, spec, **kw)
            self.assertEqual((n["execute"], n["commit"]), (0, 0), "independent native counters must read 0")
        with S.tempdir("m12-b-cli-") as td:
            state = Path(td)
            p = S.run_cli(M.cli_args("process", spec, state), root=root)
            self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
            dc = json.loads(p.stdout)
            self.assert_b(dc, state, spec, **kw)
            self.assertEqual(S.key_shape(dc), S.key_shape(d))
        return d

    def hold(self, spec, profile_id, reasons=None):
        d = self.go(spec, outcome="held", code="control_plane_hold", profile_id=profile_id, reasons=reasons)
        self.assertEqual(d["control_plane"]["result"], "hold")
        self.assertEqual(d["native"]["disposition"], "held")
        return d

    def test_b1_unsupported_profile_refused(self):
        d = self.go(M.B1, outcome="refused", code="profile_unsupported", profile_id=None)
        self.assertEqual(d["requested_profile"], "refund-ghost-v1")

    def test_b2_customer_001_under_high_is_out_of_scope(self):
        d = self.hold(M.B2, M.HIGH)
        self.assertIn("target_out_of_scope", d["control_plane"]["reasons"])
        self.assertIn("target_out_of_scope", d["refusal"]["reasons"])
        self.assertIn("target", d["refusal"]["explanation"].lower(), "explanation names the target")

    def test_b3_customer_002_under_routine_is_out_of_scope(self):
        d = self.hold(M.B3, M.ROUTINE)
        self.assertIn("target_out_of_scope", d["control_plane"]["reasons"])
        self.assertIn("target_out_of_scope", d["refusal"]["reasons"])

    def test_b4_high_over_limit_is_held_with_three_native_reasons(self):
        self.hold(M.B4, M.HIGH, reasons=["amount_exceeded", "grant_scope_mismatch", "requirement_scope_mismatch"])

    def test_b5_high_without_case_reference_refused(self):
        self.go(M.B5, outcome="refused", code="request_invalid", profile_id=None, contains="case_reference_required_for_profile")

    def test_b6_routine_with_case_reference_refused(self):
        self.go(M.B6, outcome="refused", code="request_invalid", profile_id=None, contains="case_reference_not_allowed_for_profile")
        self.go(M.B6_OMITTED, outcome="refused", code="request_invalid", profile_id=None, contains="case_reference_not_allowed_for_profile")

    def test_b7_revoked_authority_under_routine_and_high(self):
        for spec, pid in ((M.B7_ROUTINE, M.ROUTINE), (M.B7_HIGH, M.HIGH)):
            with self.subTest(profile=pid):
                d = self.hold(spec, pid)
                self.assertIn("grant_revoked", d["control_plane"]["reasons"])
                self.assertIn("grant_revoked", d["refusal"]["reasons"])
                self.assertIn("revoked", d["refusal"]["explanation"].lower())

    def test_no_forbidden_runtime_call_on_any_hold_or_refusal_via_one_counter_scope(self):
        root = S.require_stack(self)
        from refund_desk import process_refund

        specs = (M.B1, M.B2, M.B3, M.B4, M.B5, M.B6, M.B7_ROUTINE, M.B7_HIGH)
        with S.native_counters(root) as n:
            for spec in specs:
                with S.tempdir("m12-b-all-") as td:
                    process_refund(M.make_case(spec), S.make_config(root, Path(td)))
        self.assertEqual((n["execute"], n["commit"]), (0, 0))


class CheckC(Base):
    def assert_unknown(self, d: dict) -> None:
        self.shape_ok(d)
        self.assertEqual(d["outcome"], "uncertain", d)
        self.assertEqual(d["permitted_next_actions"], ["reconcile"])
        self.assertIs(d["effect_absence_established"], False)
        self.assertIs(d["execution_claim"]["supported"], False)
        self.assertEqual(d["native"]["disposition"], "unknown", "native disposition preserved")
        self.assertEqual(d["retry_permission"], "not_established")
        self.assertEqual(d["profile"], M.IDENTITY[M.HIGH])
        self.labels_ok(d)

    def test_uncertain_present_repeat_and_reconcile_high(self):
        root = S.require_stack(self)
        import refund_desk.cli as cli
        from refund_desk import present, process_refund, reconcile_case

        spec = M.CASE_C_HIGH
        with S.tempdir("m12-c-") as td:
            state = Path(td)
            case, cfg = M.make_case(spec), S.make_config(root, state)
            with S.native_counters(root) as n:
                u = M.f1_unknown_high(self, root, state)  # asserts the F1 result is `unknown` first
                self.assertEqual(u.profile.profile_id, M.HIGH)
                self.assertIs(u.native.acknowledged, False)
                self.assertEqual((n["execute"], n["commit"]), (1, 1))
                rows = S.effect_rows(state)
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["state"], rows[0]["amount"]), ("applied", 150.0))

                d = present(u, spec["case_id"]).to_dict()
                self.assert_unknown(d)
                self.assertEqual(cli._EXIT[d["outcome"]], 3)
                self.assertIsNone(re.search(r"\b(failed|succeeded|no effect)\b", d["message"].lower()), d["message"])

                d3 = process_refund(case, cfg).to_dict()
                self.shape_ok(d3)
                self.assertEqual(d3["outcome"], "uncertain", d3)
                self.assertEqual(d3["refusal"]["code"], "prior_uncertain_dispatch")
                self.assertEqual(d3["permitted_next_actions"], ["reconcile"])
                self.assertEqual(d3["requested_profile"], M.HIGH)
                self.assertEqual((n["execute"], n["commit"]), (1, 1), "no additional native execute/commit")
                self.assertEqual(S.effect_rows(state), rows)

                d4 = reconcile_case(case, cfg).to_dict()
                self.assert_reconciled(d4, state, rows)
                self.assertEqual((n["execute"], n["commit"]), (1, 1))

    def assert_reconciled(self, d: dict, state: Path, rows_before: list) -> None:
        self.shape_ok(d)
        self.assertEqual(d["outcome"], "executed", d)
        self.assertEqual(d["native"]["runtime_status"], "observed")
        self.assertEqual(d["native"]["observed_state"], "applied")
        self.assertIs(d["native"]["newly_executed"], False)
        self.assertIs(d["native"]["acknowledged"], False)
        self.assertEqual(d["native"]["runtime_invocations"], 0)
        self.assertEqual(S.effect_rows(state), rows_before, "effects row must be byte-identical after reconcile")
        self.assertEqual(d["profile"], M.IDENTITY[M.HIGH])
        self.assertEqual(d["requested_profile"], M.HIGH)
        self.assertEqual(d["retry_permission"], "not_established")

    def test_reconcile_via_cli_exit_0(self):
        root = S.require_stack(self)
        with S.tempdir("m12-c-cli-") as td:
            state = Path(td)
            M.f1_unknown_high(self, root, state)
            rows = S.effect_rows(state)
            self.assertEqual(len(rows), 1)
            p = S.run_cli(M.cli_args("reconcile", M.CASE_C_HIGH, state), root=root)
            self.assertEqual(p.returncode, 0, (p.stdout, p.stderr))
            self.assert_reconciled(json.loads(p.stdout), state, rows)

    def test_reconcile_with_routine_profile_is_refused_without_dispatch(self):
        root = S.require_stack(self)
        from refund_desk import reconcile_case

        routine_spec = {k: v for k, v in M.CASE_C_HIGH.items() if k not in ("profile", "case_reference")}
        with S.tempdir("m12-c-routine-") as td:
            state = Path(td)
            with S.native_counters(root) as n:
                M.f1_unknown_high(self, root, state)
                rows = S.effect_rows(state)
                d = reconcile_case(M.make_case(routine_spec), S.make_config(root, state)).to_dict()
                self.shape_ok(d)
                self.assertEqual(d["outcome"], "refused", d)
                self.assertEqual(d["refusal"]["code"], "no_authorized_decision_for_proposal")
                self.assertEqual(d["native"]["runtime_invocations"], 0)
                self.assertEqual((n["execute"], n["commit"]), (1, 1), "no dispatch")
                self.assertEqual(S.effect_rows(state), rows)
                self.assertIsNone(d["requested_profile"])
            p = S.run_cli(M.cli_args("reconcile", routine_spec, state), root=root)
            self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
            self.assertEqual(json.loads(p.stdout)["refusal"]["code"], "no_authorized_decision_for_proposal")
            self.assertEqual(S.effect_rows(state), rows)

    def test_patched_f1_raising_fails_closed_and_keeps_requested_profile(self):
        import refund_desk.desk as desk

        def boom(*a, **k):
            raise RuntimeError("synthetic F1 failure")

        with S.tempdir("m12-c-raise-") as td, S.tempdir("m12-c-raise-stack-") as fake:
            cfg = S.make_config(Path(fake), Path(td))
            for fn_name, fn in (("dispose_refund", desk.process_refund), ("reconcile_refund", desk.reconcile_case)):
                with self.subTest(call=fn_name), mock.patch.object(desk, fn_name, boom):
                    d = fn(M.make_case(M.CASE_C_HIGH), cfg).to_dict()
                    self.shape_ok(d)
                    self.assertEqual(d["outcome"], "uncertain", d)
                    self.assertEqual(d["permitted_next_actions"], ["reconcile"])
                    self.assertIs(d["effect_absence_established"], False)
                    self.assertIs(d["execution_claim"]["supported"], False)
                    self.assertEqual(d["requested_profile"], M.HIGH)
                    self.assertIsNone(d["profile"], "F1 returned no profile")
            self.assertEqual(S.effect_rows(Path(td)), [])

    def test_no_fault_option_exposed_with_new_parameters(self):
        import inspect

        import refund_desk

        words = ("fault", "inject", "simulate")
        for name in ("RefundCase", "DeskConfig", "process_refund", "reconcile_case", "present"):
            for pname in inspect.signature(getattr(refund_desk, name)).parameters:
                self.assertFalse(any(w in pname.lower().replace("default", "") for w in words), f"{name} parameter {pname!r}")
        text = (lambda p: (p.stdout + p.stderr).lower())(S.run_cli(["--help"], root=None))
        self.assertIn("--profile", text)
        self.assertIn("--case-reference", text)
        self.assertFalse(any(w in text for w in words), text)


if __name__ == "__main__":
    unittest.main()
