"""Additional F1 boundary tests (NOT part of the frozen A/B/C oracles; added after independent code review). DEVELOPMENT ONLY / SYNTHETIC.
Run: G3_STACK_ROOT=<assembled pinned stack> F1_REQUIRE=1 python3 -m unittest discover -s tests/adapters/refund_disposition -p 'test_f1_boundary.py' -v
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _fault_injection as F
import _support as S
from orchestration.adapters.refund_disposition import dispose as D
from orchestration.adapters.refund_disposition import dispose_refund, reconcile_refund


def count(state: Path, table: str) -> int:
    with sqlite3.connect(f"file:{S.db_path(state)}?mode=ro", uri=True) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class Boundary(unittest.TestCase):
    def test_exception_after_runtime_entered_is_unknown_not_failed_and_not_uninvoked(self):
        root = S.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="f1-x1-") as td:
            state = Path(td)
            with S.native_counters(root) as n, mock.patch.object(D, "map_runtime", side_effect=RuntimeError("post-dispatch adapter fault")):
                r = dispose_refund(S.make_request(root, state, correlation="f1-x1"))
            self.assertEqual(r.disposition, "unknown")
            self.assertTrue(r.runtime_invoked)
            self.assertEqual((r.runtime_invocations, n["execute"], n["commit"]), (1, 1, 1))
            self.assertEqual(len(S.effect_rows(state)), 1)  # the effect did commit
            self.assertIs(r.effect_absence_established, False)
            self.assertEqual(r.next_step, "reconcile_read_only")

    def test_runtime_raises_is_unknown_with_no_absence_claim(self):
        root = S.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="f1-x5-") as td:
            state = Path(td)
            with S.native_counters(root) as n:
                S_ = S.load_stack(root)
                with mock.patch.object(S_.engine_adapter.PinnedControlPlaneExecutor, "execute", side_effect=RuntimeError("runtime raised")):
                    r = dispose_refund(S.make_request(root, state, correlation="f1-x5"))
            self.assertEqual(r.disposition, "unknown")
            self.assertTrue(r.runtime_invoked)
            self.assertEqual(r.runtime_invocations, 1)
            self.assertIs(r.effect_absence_established, False)  # no row exists here, yet absence is still not claimed
            self.assertIsNotNone(r.native.effect_id)  # native facts established before dispatch are kept
            self.assertEqual(r.next_step, "reconcile_read_only")

    def test_dispose_after_unknown_is_refused_without_reentering_the_runtime(self):
        root = S.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="f1-x2-") as td:
            state = Path(td)
            with S.native_counters(root) as n:
                first = F.dispose_with_lost_ack_unavailable_observation(S.make_request(root, state, correlation="f1-x2"))
                self.assertEqual(first.disposition, "unknown")
                again = dispose_refund(S.make_request(root, state, correlation="f1-x2"))
            self.assertEqual(again.disposition, "refused")
            self.assertEqual(again.refusal.code, "prior_uncertain_dispatch")
            self.assertEqual(again.next_step, "reconcile_read_only")
            self.assertEqual((again.runtime_invocations, n["execute"], n["commit"]), (0, 1, 1))
            self.assertEqual(len(S.effect_rows(state)), 1)

    def test_reconcile_creates_nothing_and_writes_no_effect_or_attempt_rows(self):
        root = S.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="f1-x3-") as td:
            state = Path(td)
            missing = reconcile_refund(S.make_request(root, state, correlation="f1-x3"))
            self.assertEqual(missing.disposition, "refused")
            self.assertFalse(S.db_path(state).exists())
            F.dispose_with_lost_ack_unavailable_observation(S.make_request(root, state, correlation="f1-x3"))
            before = {t: count(state, t) for t in ("effects", "attempts", "attempt_events")}
            rec = reconcile_refund(S.make_request(root, state, correlation="f1-x3"))
            self.assertEqual(rec.disposition, "executed")
            self.assertEqual({t: count(state, t) for t in before}, before)

    def test_hold_on_suspended_authority_creates_no_database(self):
        root = S.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="f1-x4-") as td:
            state = Path(td)
            r = dispose_refund(S.make_request(root, state, bundle="root_lineage_suspended.json", correlation="f1-x4"))
            self.assertEqual(r.disposition, "held")
            self.assertFalse(S.db_path(state).exists())
            self.assertEqual(r.runtime_invocations, 0)


if __name__ == "__main__":
    unittest.main()
