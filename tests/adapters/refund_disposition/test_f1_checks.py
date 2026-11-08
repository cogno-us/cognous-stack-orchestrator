"""F1 developer checks A, B, C against the oracles frozen in orchestration/adapters/refund_disposition/ORACLES.md (commit d4e6eb6).
DEVELOPMENT ONLY / SYNTHETIC / builder-lineage developer tests; NOT independent qualification.

Run: G3_STACK_ROOT=<assembled pinned stack> F1_REQUIRE=1 python -m unittest discover -s tests/adapters/refund_disposition -p 'test_f1_checks.py' -v
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _support as S
from orchestration.adapters.refund_disposition import dispose_refund, reconcile_refund


def labels_ok(tc: unittest.TestCase, r) -> None:
    tc.assertTrue(r.labels.synthetic_authority)
    tc.assertIs(r.labels.authenticated, False)
    tc.assertEqual(r.labels.evidence_basis, "producer_reported")
    tc.assertTrue(r.labels.nonproduction)
    tc.assertTrue(r.labels.non_authorizing)
    tc.assertEqual(r.labels.retry_permission, "not_established")
    tc.assertIs(r.effect_absence_established, False)
    tc.assertTrue(r.cleanup.ok, r.cleanup)
    tc.assertIsNotNone(r.cleanup.scratch_path)
    tc.assertFalse(Path(r.cleanup.scratch_path).exists())


class CheckA(unittest.TestCase):
    def test_authorized_one_effect_and_idempotent_repeat(self):
        root = S.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="f1-a-") as td:
            state = Path(td)
            with S.native_counters(root) as n:
                r1 = dispose_refund(S.make_request(root, state, correlation="f1-check-a"))
                self.assertEqual(r1.disposition, "executed", r1)
                self.assertEqual((r1.native.cp_result, r1.native.cp_reasons), ("authorized", ()))
                self.assertEqual((r1.native.runtime_status, r1.native.newly_executed, r1.native.acknowledged), ("executed", True, True))
                self.assertEqual((r1.runtime_invocations, n["execute"], n["commit"]), (1, 1, 1))
                rows = S.effect_rows(state)
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["state"], rows[0]["amount"], rows[0]["unit"]), ("applied", 50.0, "USD"))
                self.assertEqual(rows[0]["effect_id"], r1.native.effect_id)
                cp = json.loads(Path(next(f for f in r1.evidence.source if f.kind == "cp_run_record").path).read_text())
                authorized = [d for d in cp["decisions"] if d["result"] == "authorized"]
                self.assertEqual([d["effect_id"] for d in authorized], [rows[0]["effect_id"]])  # CP record, row and result agree independently
                self.assertEqual(r1.next_step, "none")
                labels_ok(self, r1)
                # Replay reference is resolvable and truthful
                self.assertEqual(r1.evidence.replay_state, "imported", r1.evidence)
                ref = r1.evidence.replay
                self.assertTrue(Path(ref.path).is_file())
                self.assertEqual(ref.sha256, S.sha256_file(ref.path))
                bundle = json.loads(Path(ref.path).read_text())
                self.assertEqual(bundle["status"], "reconstruction_complete")
                self.assertEqual(ref.detail["status"], "reconstruction_complete")
                self.assertIn(r1.native.effect_id, json.dumps(bundle))
                self.assertTrue(any(rec.get("record_type") == "execution_result" for rec in bundle["records"]), "Replay holds executor records")
                self.assertTrue(any(f.kind == "cp_run_record" and f.sha256 == S.sha256_file(f.path) for f in r1.evidence.source))
                before = rows
                # repetition: same request, same state dir -> no second effect
                r2 = dispose_refund(S.make_request(root, state, correlation="f1-check-a"))
                after = S.effect_rows(state)
                self.assertEqual(len(after), 1)
                self.assertEqual(after, before)
                self.assertEqual(r2.native.effect_id, r1.native.effect_id)
                self.assertIs(r2.native.newly_executed, False)
                self.assertEqual(r2.native.runtime_status, "reconciled")
                self.assertEqual(n["commit"], 1)
                self.assertEqual(r2.disposition, "executed")
                self.assertEqual(n["execute"], 2)  # the repeat re-enters the Runtime once; the destination's native idempotency absorbs it
                labels_ok(self, r2)


class CheckB(unittest.TestCase):
    def test_revoked_authority_holds_without_runtime(self):
        root = S.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="f1-b-") as td:
            state = Path(td)
            with S.native_counters(root) as n:
                r = dispose_refund(S.make_request(root, state, bundle="root_lineage_revoked.json", correlation="f1-check-b"))
            self.assertEqual(r.disposition, "held", r)
            self.assertEqual(r.native.cp_result, "hold")
            self.assertIn("grant_revoked", r.native.cp_reasons)
            self.assertIs(r.runtime_invoked, False)
            self.assertEqual(r.runtime_invocations, 0)
            self.assertEqual((n["execute"], n["commit"]), (0, 0))
            self.assertEqual(S.effect_rows(state), [])
            self.assertEqual(S.grant_rows(state), [])
            self.assertFalse(S.db_path(state).exists())  # stronger than the oracle: a hold does not even create the destination database
            self.assertEqual(r.evidence.replay_state, "not_run")
            self.assertIsNone(r.evidence.replay)
            produced = [x.name for x in (state / "evidence").glob("**/*.json")] if (state / "evidence").exists() else []
            self.assertFalse([x for x in produced if x.startswith(("replay_bundle", "runtime_export"))], produced)
            self.assertTrue(any(f.kind == "cp_run_record" and f.sha256 == S.sha256_file(f.path) for f in r.evidence.source))
            self.assertEqual(r.next_step, "resolve_authority_hold")
            self.assertEqual(r.refusal.source, "control_plane")
            labels_ok(self, r)


class CheckC(unittest.TestCase):
    def test_post_commit_lost_ack_with_unavailable_observation_is_unknown_then_effect_free_reconcile(self):
        root = S.require_stack(self)
        with tempfile.TemporaryDirectory(prefix="f1-c-") as td:
            state = Path(td)
            with S.native_counters(root) as n:
                r = dispose_refund(S.make_request(root, state, correlation="f1-check-c", dev_fault="lost_ack_observation_unavailable"))
                self.assertEqual(r.disposition, "unknown", r)
                self.assertEqual(r.native.runtime_status, "unknown")
                self.assertIs(r.native.acknowledged, False)
                self.assertEqual((n["execute"], n["commit"], r.runtime_invocations), (1, 1, 1))  # no automatic retry
                rows = S.effect_rows(state)
                self.assertEqual(len(rows), 1)  # the effect DID commit
                self.assertEqual(rows[0]["state"], "applied")
                self.assertIs(r.effect_absence_established, False)
                self.assertNotEqual(r.native.observed_state, "absent")
                self.assertNotIn(r.disposition, ("executed", "failed", "held"))
                self.assertEqual(r.next_step, "reconcile_read_only")
                labels_ok(self, r)
                rec = reconcile_refund(S.make_request(root, state, correlation="f1-check-c"))
                self.assertEqual(rec.disposition, "executed", rec)
                self.assertEqual(rec.native.runtime_status, "observed")
                self.assertEqual(rec.native.observed_state, "applied")
                self.assertIs(rec.native.newly_executed, False)
                self.assertEqual(rec.mode, "reconcile")
                self.assertEqual((n["execute"], n["commit"], rec.runtime_invocations), (1, 1, 0))  # reconciliation dispatched nothing
                self.assertEqual(S.effect_rows(state), rows)  # observed state preserved byte-for-byte
                self.assertEqual(rec.labels.retry_permission, "not_established")
                labels_ok(self, rec)


if __name__ == "__main__":
    unittest.main()
