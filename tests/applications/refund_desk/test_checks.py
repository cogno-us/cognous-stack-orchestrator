"""Refund Desk (F3) developer CHECKS A, B, C.

DEVELOPMENT ONLY / SYNTHETIC / test-owner developer checks, NOT independent qualification.
Expectations are frozen in applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md; this file asserts them as frozen.

Run: F3_STACK_ROOT=<assembled pinned stack> F3_REQUIRE=1 python -m unittest discover -s tests/applications/refund_desk -p 'test_checks.py' -v
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_refund_desk_test_support", Path(__file__).with_name("_support.py"))
S = sys.modules.get("_refund_desk_test_support") or importlib.util.module_from_spec(_spec)
sys.modules["_refund_desk_test_support"] = S
if not hasattr(S, "REPO"):
    _spec.loader.exec_module(S)

APP_CONTRACT = "refund-desk/0.1.0-dev"
DICT_KEYS = {"app_contract", "f1_contract_version", "case_id", "outcome", "message", "control_plane", "native", "execution_claim", "effect", "evidence",
             "refusal", "permitted_next_actions", "retry_permission", "effect_absence_established", "labels", "limitations", "cleanup"}


def not_verified() -> tuple[str, ...]:
    from orchestration.adapters.refund_disposition.contract import NOT_VERIFIED

    return NOT_VERIFIED


class Base(unittest.TestCase):
    def shape_ok(self, d: dict) -> None:
        self.assertEqual(d["app_contract"], APP_CONTRACT)
        self.assertTrue(DICT_KEYS <= set(d), f"missing keys: {DICT_KEYS - set(d)}")
        for k in ("result", "reasons"):
            self.assertIn(k, d["control_plane"])
        for k in ("disposition", "runtime_status", "runtime_invoked", "runtime_invocations", "acknowledged", "newly_executed", "observed_state", "error"):
            self.assertIn(k, d["native"], k)
        json.dumps(d)  # JSON-serializable

    def labels_ok(self, d: dict) -> None:
        lb = d["labels"]
        self.assertIs(lb["synthetic_authority"], True)
        self.assertIs(lb["authenticated"], False)
        self.assertEqual(lb["evidence_basis"], "producer_reported")
        self.assertIs(lb["nonproduction"], True)
        self.assertEqual(d["retry_permission"], "not_established")
        self.assertTrue(d["cleanup"]["ok"], d["cleanup"])


class CheckA(Base):
    def assert_a(self, d: dict, state: Path, *, first: bool = True) -> None:
        self.shape_ok(d)
        self.assertEqual(d["outcome"], "executed", d)
        self.assertEqual(d["control_plane"]["result"], "authorized")
        self.assertEqual(list(d["control_plane"]["reasons"]), [])
        self.assertEqual(d["native"]["disposition"], "executed")
        self.assertEqual(d["native"]["runtime_status"], "executed" if first else "reconciled")
        self.assertIs(d["native"]["newly_executed"], first)
        self.assertEqual(d["native"]["runtime_invocations"], 1)
        self.assertIs(d["execution_claim"]["supported"], True)
        self.assertTrue(d["execution_claim"]["basis"])
        rows = S.effect_rows(state)
        self.assertEqual(len(rows), 1, rows)
        self.assertTrue(d["effect"]["effect_id"])
        self.assertEqual(d["effect"]["effect_id"], rows[0]["effect_id"])
        self.assertEqual((rows[0]["state"], rows[0]["amount"], rows[0]["unit"]), ("applied", 64.25, "USD"))
        ev = d["evidence"]
        self.assertEqual(ev["replay_state"], "imported", ev)
        self.assertIsNotNone(ev["replay"])
        self.assertIs(ev["replay"]["resolvable"], True)
        self.assertEqual(ev["replay"]["status"], "reconstruction_complete")
        self.assertEqual(ev["replay"]["sha256"], S.sha256_file(ev["replay"]["path"]))  # independent recomputation
        self.assertTrue(ev["source"])
        for src in ev["source"]:
            self.assertIs(src["resolvable"], True, src)
            self.assertEqual(src["sha256"], S.sha256_file(src["path"]), src)
        self.labels_ok(d)
        for s in not_verified():
            self.assertIn(s, d["limitations"])
        self.assertEqual(d["retry_permission"], "not_established")
        self.assertEqual(d["permitted_next_actions"], [])

    def test_authorized_action_and_idempotent_repeat(self):
        root = S.require_stack(self)
        from refund_desk import process_refund

        with S.tempdir("f3-a-") as td:
            state = Path(td)
            case, cfg = S.make_case(S.CASE_A), S.make_config(root, state)
            d1 = process_refund(case, cfg).to_dict()
            self.assert_a(d1, state)
            before = S.effect_rows(state)
            d2 = process_refund(case, cfg).to_dict()
            after = S.effect_rows(state)
            self.assertEqual(len(after), 1)
            self.assertEqual(after, before)
            self.assertEqual(d2["effect"]["effect_id"], d1["effect"]["effect_id"])
            self.assertIs(d2["native"]["newly_executed"], False)
            self.assertEqual(d2["outcome"], "executed")

    def test_authorized_action_via_cli(self):
        root = S.require_stack(self)
        from refund_desk import process_refund

        with S.tempdir("f3-a-cli-") as td, S.tempdir("f3-a-api-") as td2:
            state = Path(td)
            p = S.run_cli(S.cli_args("process", S.CASE_A, state), root=root)
            self.assertEqual(p.returncode, 0, (p.stdout, p.stderr))
            d = json.loads(p.stdout)  # exactly one JSON object on stdout
            self.assertIsInstance(d, dict)
            self.assert_a(d, state)
            api = process_refund(S.make_case(S.CASE_A), S.make_config(root, Path(td2))).to_dict()
            self.assertEqual(S.key_shape(d), S.key_shape(api), "CLI stdout must have the same dict shape as to_dict()")


class CheckB(Base):
    def assert_b(self, d: dict, state: Path) -> None:
        self.shape_ok(d)
        self.assertEqual(d["outcome"], "held", d)
        self.assertNotEqual(d["outcome"], "executed")
        self.assertEqual(d["control_plane"]["result"], "hold")
        self.assertIn("grant_revoked", d["control_plane"]["reasons"])
        self.assertEqual(d["native"]["disposition"], "held")
        self.assertIs(d["native"]["runtime_invoked"], False)
        self.assertEqual(d["native"]["runtime_invocations"], 0)
        self.assertIs(d["execution_claim"]["supported"], False)
        self.assertEqual(d["refusal"]["code"], "control_plane_hold")
        self.assertIn("grant_revoked", d["refusal"]["reasons"])
        self.assertTrue(d["refusal"]["explanation"])
        self.assertIn("revoked", d["refusal"]["explanation"].lower())
        self.assertFalse(S.db_path(state).exists(), "a hold must not create a SQLite database (so zero effect rows)")
        self.assertEqual(S.effect_rows(state), [])
        self.assertIsNone(d["evidence"]["replay"])
        self.assertEqual(d["evidence"]["replay_state"], "not_run")
        self.labels_ok(d)
        self.assertEqual(d["permitted_next_actions"], [])

    def test_revoked_authority_holds(self):
        root = S.require_stack(self)
        from refund_desk import process_refund

        with S.tempdir("f3-b-") as td:
            state = Path(td)
            with S.native_counters(root) as n:
                d = process_refund(S.make_case(S.CASE_B), S.make_config(root, state)).to_dict()
            self.assert_b(d, state)
            self.assertEqual((n["execute"], n["commit"]), (0, 0), "independent native counters must read 0")

    def test_revoked_authority_via_cli(self):
        root = S.require_stack(self)
        with S.tempdir("f3-b-cli-") as td:
            state = Path(td)
            p = S.run_cli(S.cli_args("process", S.CASE_B, state), root=root)
            self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
            self.assert_b(json.loads(p.stdout), state)


class CheckC(Base):
    def test_uncertain_outcome_present_repeat_and_reconcile(self):
        root = S.require_stack(self)
        from refund_desk import present, process_refund, reconcile_case

        with S.tempdir("f3-c-") as td:
            state = Path(td)
            case, cfg = S.make_case(S.CASE_C), S.make_config(root, state)
            with S.native_counters(root) as n:
                # 1. test-owned fixture yields a genuine F1 unknown (asserted inside) with one committed applied row, no acknowledgment
                u = S.f1_unknown_for_case_c(self, root, state)
                self.assertIs(u.native.acknowledged, False)
                self.assertEqual((n["execute"], n["commit"]), (1, 1))
                rows = S.effect_rows(state)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["state"], "applied")

                # 2. pure presentation of the F1 result
                d = present(u, S.CASE_C["case_id"]).to_dict()
                self.shape_ok(d)
                self.assertEqual(d["outcome"], "uncertain")
                self.assertIs(d["execution_claim"]["supported"], False)
                self.assertIs(d["effect_absence_established"], False)
                self.assertEqual(d["permitted_next_actions"], ["reconcile"])
                self.assertEqual(d["retry_permission"], "not_established")
                msg = d["message"].lower()
                self.assertIn("unknown", msg, "message must state the outcome is unknown")
                for bad in ("executed", "failed", "succeeded", "no effect"):
                    self.assertIsNone(re.search(r"\b" + re.escape(bad) + r"\b", msg), f"message must not say {bad!r}: {d['message']}")
                self.labels_ok(d)

                # 3. repeating process_refund in the same state dir is refused as prior uncertain dispatch
                d3 = process_refund(case, cfg).to_dict()
                self.shape_ok(d3)
                self.assertEqual(d3["outcome"], "uncertain", d3)
                self.assertEqual(d3["refusal"]["code"], "prior_uncertain_dispatch")
                self.assertEqual(d3["permitted_next_actions"], ["reconcile"])
                self.assertEqual((n["execute"], n["commit"]), (1, 1), "no additional native execute/commit")
                self.assertEqual(S.effect_rows(state), rows)
                self.assertEqual(len(S.effect_rows(state)), 1)

                # 4. reconcile never dispatches
                d4 = reconcile_case(case, cfg).to_dict()
                self.assert_reconciled(d4, state, rows)
                self.assertEqual((n["execute"], n["commit"]), (1, 1))

    def assert_reconciled(self, d: dict, state: Path, rows_before: list) -> None:
        self.shape_ok(d)
        self.assertEqual(d["outcome"], "executed", d)
        self.assertIs(d["execution_claim"]["supported"], True)
        self.assertIn("observed", d["execution_claim"]["basis"])
        self.assertEqual(d["native"]["observed_state"], "applied")
        self.assertIs(d["native"]["newly_executed"], False)
        self.assertEqual(d["native"]["runtime_invocations"], 0)
        self.assertIs(d["native"]["acknowledged"], False)
        self.assertEqual(S.effect_rows(state), rows_before, "effects row must be byte-identical after reconcile")
        self.assertEqual(d["permitted_next_actions"], [])
        self.assertEqual(d["retry_permission"], "not_established")

    def test_reconcile_via_cli(self):
        root = S.require_stack(self)
        with S.tempdir("f3-c-cli-") as td:
            state = Path(td)
            S.f1_unknown_for_case_c(self, root, state)
            rows = S.effect_rows(state)
            self.assertEqual(len(rows), 1)
            p = S.run_cli(S.cli_args("reconcile", S.CASE_C, state), root=root)
            self.assertEqual(p.returncode, 0, (p.stdout, p.stderr))
            self.assert_reconciled(json.loads(p.stdout), state, rows)

    def test_no_fault_option_exposed(self):
        """5. No option, flag or parameter on the public API or CLI injects a fault."""
        import inspect

        import refund_desk

        words = ("fault", "inject", "simulate")
        for name in ("RefundCase", "DeskConfig", "process_refund", "reconcile_case", "present"):
            for pname in inspect.signature(getattr(refund_desk, name)).parameters:
                self.assertFalse(any(w in pname.lower().replace("default", "") for w in words), f"{name} parameter {pname!r}")
        p = S.run_cli(["--help"], root=None)
        text = (p.stdout + p.stderr).lower()
        self.assertIn("--case-id", text, "expected the CLI usage text")
        self.assertFalse(any(w in text for w in words), text)


if __name__ == "__main__":
    unittest.main()
