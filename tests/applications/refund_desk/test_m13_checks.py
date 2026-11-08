"""Refund Desk (F3) M1-3 developer CHECKS A-D on the real pinned local native stack (Amendment M3, Issue #157): evidence.replay_note.

DEVELOPMENT ONLY / SYNTHETIC / test-owner developer checks, NOT independent qualification.
Expected notes are obtained by calling PUBLIC F1 directly (test-owned), never by hard-coding a diagnosis; where F1 reports import_failed the note must
be non-null and forwarded verbatim.

Run: F3_STACK_ROOT=<assembled pinned stack> F3_REQUIRE=1 python -m unittest discover -s tests/applications/refund_desk -p 'test_m13_checks.py' -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_refund_desk_m12_support", Path(__file__).with_name("_m12_support.py"))
M = sys.modules.get("_refund_desk_m12_support") or importlib.util.module_from_spec(_spec)
sys.modules["_refund_desk_m12_support"] = M
if not hasattr(M, "HIGH"):
    _spec.loader.exec_module(M)
S = M.S


def f1_direct(spec, root, state, twice=False):
    """Public F1 called directly on an independent fresh state directory; returns the list of F1 results."""
    from orchestration.adapters.refund_disposition import dispose_refund

    req = M.build_f1_request(spec, root, state)
    out = [dispose_refund(req)]
    if twice:
        out.append(dispose_refund(req))
    return out


class Base(unittest.TestCase):
    def note_ok(self, d, f1r):
        self.assertIn("replay_note", d["evidence"])
        self.assertEqual(d["evidence"]["replay_note"], f1r.evidence.replay_note, "verbatim F1 replay_note (or null)")
        self.assertEqual(d["evidence"]["replay_state"], f1r.evidence.replay_state)
        if f1r.evidence.replay_state == "import_failed":
            self.assertTrue(d["evidence"]["replay_note"], "import_failed must carry F1's explanation")
            self.assertIsNone(d["evidence"]["replay"])
            self.assertEqual(d["outcome"], "executed", "a Replay import failure is not an execution failure")
        json.dumps(d)


class CheckAB(Base):
    def _scenario(self, spec, profile_id, requested):
        root = S.require_stack(self)
        from refund_desk import process_refund

        with S.tempdir("m13-f1-") as t1, S.tempdir("m13-app-") as t2:
            first_f1, repeat_f1 = f1_direct(spec, root, Path(t1), twice=True)
            state = Path(t2)
            with S.native_counters(root) as n:
                d1 = process_refund(M.make_case(spec), S.make_config(root, state)).to_dict()
                rows = S.effect_rows(state)
                commits_after_first = n["commit"]
                self.assertEqual((n["execute"], n["commit"]), (1, 1))
                d2 = process_refund(M.make_case(spec), S.make_config(root, state)).to_dict()
                self.assertEqual(n["commit"], 1)
                self.assertEqual(n["commit"] - commits_after_first, 0, "no additional commit")
            # A: initial
            self.assertEqual(d1["outcome"], "executed")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["state"], "applied")
            self.note_ok(d1, first_f1)
            self.assertEqual(d1["profile"], M.IDENTITY[profile_id])
            self.assertEqual(d1["requested_profile"], requested)
            # B: repeat
            self.assertEqual(d2["outcome"], "executed")
            self.assertIs(d2["native"]["newly_executed"], False)
            self.assertEqual(S.effect_rows(state), rows)
            self.assertEqual(d2["effect"]["effect_id"], d1["effect"]["effect_id"])
            self.note_ok(d2, repeat_f1)
            self.assertEqual(d2["profile"], d1["profile"])
            self.assertEqual(d2["retry_permission"], "not_established")
            self.assertIs(d2["execution_claim"]["supported"], True)
            return d1, d2

    def test_ab_routine_profile_initial_and_repeat(self):
        d1, d2 = self._scenario(M.A1, M.ROUTINE, None)
        # documented observation, asserted only as consistency with F1 (see Issue #157): record it for the PR evidence
        print("\nM13-EVIDENCE routine repeat:", json.dumps({"replay_state": d2["evidence"]["replay_state"], "replay_note": d2["evidence"]["replay_note"]}))

    def test_d_high_profile_initial_and_repeat(self):
        d1, d2 = self._scenario(M.A2, M.HIGH, M.HIGH)
        print("\nM13-EVIDENCE high repeat:", json.dumps({"replay_state": d2["evidence"]["replay_state"], "replay_note": d2["evidence"]["replay_note"]}))

    def test_cli_repeat_shows_note(self):
        root = S.require_stack(self)
        with S.tempdir("m13-cli-f1-") as t1, S.tempdir("m13-cli-") as t2:
            _, repeat_f1 = f1_direct(M.A1, root, Path(t1), twice=True)
            for _ in range(2):
                p = S.run_cli(M.cli_args("process", M.A1, Path(t2)), root=root)
                self.assertEqual(p.returncode, 0, (p.stdout, p.stderr))
            d = json.loads(p.stdout)
            self.note_ok(d, repeat_f1)


class CheckC(Base):
    def test_uncertain_and_read_only_reconcile_forward_f1_notes(self):
        root = S.require_stack(self)
        from orchestration.adapters.refund_disposition import reconcile_refund
        from refund_desk import present, process_refund, reconcile_case

        spec = M.CASE_C_HIGH
        with S.tempdir("m13-c-") as td:
            state = Path(td)
            case, cfg = M.make_case(spec), S.make_config(root, state)
            with S.native_counters(root) as n:
                u = M.f1_unknown_high(self, root, state)
                rows = S.effect_rows(state)
                d = present(u, spec["case_id"]).to_dict()
                self.assertEqual(d["outcome"], "uncertain")
                self.note_ok(d, u)
                self.assertEqual(d["retry_permission"], "not_established")
                self.assertIs(d["effect_absence_established"], False)
                d3 = process_refund(case, cfg).to_dict()  # refused prior_uncertain_dispatch -> uncertain, no redispatch
                self.assertEqual(d3["outcome"], "uncertain")
                self.assertIn("replay_note", d3["evidence"])
                self.assertEqual((n["execute"], n["commit"]), (1, 1), "no automatic redispatch")
                f1_rec = reconcile_refund(M.build_f1_request(spec, root, state))
                d4 = reconcile_case(case, cfg).to_dict()
                self.note_ok(d4, f1_rec)
                self.assertEqual(d4["retry_permission"], "not_established")
                self.assertEqual((n["execute"], n["commit"]), (1, 1))
                self.assertEqual(S.effect_rows(state), rows)


class Negatives(Base):
    def test_presentation_is_read_only_and_does_not_touch_source_files(self):
        root = S.require_stack(self)
        from refund_desk import present

        with S.tempdir("m13-n-") as td:
            state = Path(td)
            f1r = f1_direct(M.A1, root, state)[0]
            files = [Path(x.path) for x in f1r.evidence.source if getattr(x, "path", None)]
            before = {str(p): S.sha256_file(p) for p in files if p.exists()}
            with S.native_counters(root) as n:
                a = present(f1r, M.A1["case_id"]).to_dict()
                b = present(f1r, M.A1["case_id"]).to_dict()
                self.assertEqual((n["execute"], n["commit"]), (0, 0), "presentation causes no Runtime/commit")
            self.assertEqual(a, b)
            self.assertEqual({str(p): S.sha256_file(p) for p in files if p.exists()}, before)
            self.assertEqual(len(S.effect_rows(state)), 1)


if __name__ == "__main__":
    unittest.main()
