"""Exactly three Architect-approved focused cases, run against the pinned native components.

Local synthetic scratch only; no payment effect; not a qualification. Required environment (explicit, no defaults):
COGNOUS_C4_ACTION_MANIFEST_ROOT, COGNOUS_C4_CONTROL_PLANE_ROOT, COGNOUS_C4_REPLAY_BUNDLE_ROOT,
COGNOUS_C4_EVIDENCE_PACK_ROOT, COGNOUS_REFUND_ODES_ROOT. A missing root FAILS (never skips).
Run: python3 -I -B .github/scripts/run_unittest_no_skips.py tests/manual_contract/refund_local_focused
"""
import json
import os
import pathlib
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import refund_local  # noqa: E402

ENV = {
    "action_manifest": "COGNOUS_C4_ACTION_MANIFEST_ROOT",
    "control_plane": "COGNOUS_C4_CONTROL_PLANE_ROOT",
    "replay_bundle": "COGNOUS_C4_REPLAY_BUNDLE_ROOT",
    "evidence_pack": "COGNOUS_C4_EVIDENCE_PACK_ROOT",
}


class RefundLocalFocused(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [v for v in (*ENV.values(), "COGNOUS_REFUND_ODES_ROOT") if not os.environ.get(v)]
        if missing:
            raise AssertionError("required environment roots missing: " + ", ".join(missing))
        cls.out = refund_local.prepare_local_synthetic(
            {k: os.environ[v] for k, v in ENV.items()}, os.environ["COGNOUS_REFUND_ODES_ROOT"])
        cls.work = pathlib.Path(cls.out["workdir"])
        cls.cases = cls.out["observations"]["cases"]

    def _dest(self, scenario):
        return json.loads((self.work / scenario / "destination.json").read_text())

    def _rec(self, scenario):
        return json.loads((self.work / scenario / "cp-record.json").read_text())

    def test_01_authorized_synthetic_refund(self):
        c = self.cases["authorized"]
        rec, dest = self._rec("authorized"), self._dest("authorized")
        self.assertEqual(c["decision"], "authorized")
        self.assertEqual(c["local_effect_call_trace"], ["decide", "execute", "reconcile"])
        eid = c["effect_id"]
        self.assertEqual([a["status"] for a in rec["attempts"]], ["attempted", "acknowledged"])  # one attempt id, two transitions
        self.assertEqual(len({a["attempt_id"] for a in rec["attempts"]}), 1)
        self.assertIsInstance(c["binding"], dict)
        self.assertTrue(any(o["effect_id"] == eid and o["state"] == "applied" for o in rec["observations"]))
        self.assertTrue(any(r["effect_id"] == eid and r["result"] == "applied" and r["observation_accepted"] is True
                            for r in rec["reconciliations"]))
        self.assertEqual(list(dest["effects"]), [eid])
        self.assertEqual(dest["effects"][eid]["state"], "applied")
        self.assertEqual(c["synthetic_effect_standing"], "SYNTHETIC_APPLIED_OBSERVED")
        self.assertEqual(c["real_payment_effect"], "NOT_ATTEMPTED")
        self.assertIs(c["independent_qualification"], False)

    def test_02_held_refund_has_no_effect(self):
        c = self.cases["grant_revoked"]
        rec, dest = self._rec("grant_revoked"), self._dest("grant_revoked")
        self.assertEqual(c["decision"], "hold")
        self.assertIsNone(c["binding"])
        self.assertEqual(c["local_effect_call_trace"], ["decide"])  # execute() observed as never called
        for key in ("attempts", "observations", "reconciliations"):
            self.assertEqual(rec.get(key) or [], [])
        self.assertEqual(dest.get("effects") or {}, {})
        self.assertEqual(c["synthetic_effect_standing"], "HELD_NO_EFFECT")
        self.assertNotEqual(c["effect_id"], self.cases["authorized"]["effect_id"])
        # held evidence retained downstream (per-hop assertions already enforced by check_propagation)
        self.assertEqual(c["pack_lifecycle"]["authorization"], "held")
        self.assertEqual(c["replay_status"], "reconstruction_partial")

    def test_03_truthful_evidence_propagation(self):
        for name, c in self.cases.items():
            self.assertEqual(c["replay_status"], "reconstruction_partial", name)  # partial stays partial
            self.assertIs(c["pack_validation_valid"], True, name)
            self.assertEqual(c["pack_lifecycle"]["reconstruction_status"], "reconstruction_partial", name)
            self.assertEqual(c["odes_recipient_reliance"]["status"], "fail", name)  # no trusted inputs -> final reliance FAIL
        # acknowledgement alone is never completion
        rec, dest = self._rec("authorized"), self._dest("authorized")
        c = self.cases["authorized"]
        no_row = refund_local.classify_native(
            {"result": "authorized", "binding": {"x": 1}, "effect_id": c["effect_id"]},
            {"attempts": rec["attempts"], "observations": [], "reconciliations": []}, {"effects": {}},
            {"metadata": {"traceable_import": {"lifecycle_summary": {"authorization": "authorized"}}}}, {})
        self.assertEqual(no_row["synthetic_effect_standing"], "AUTHORIZED_NOT_CONFIRMED_APPLIED")
        # ODES acceptance of structure is not authorization: the held case still reads held, never authorized
        self.assertEqual(self.cases["grant_revoked"]["decision"], "hold")
        # no ODES -> Pack edge: no stored Pack mentions the ODES package digest
        for scenario in ("authorized", "grant_revoked"):
            pkg = json.loads((self.work / scenario / "odes-package.json").read_text())
            self.assertNotIn(pkg["package_digest"], (self.work / scenario / "pack.json").read_text())


if __name__ == "__main__":
    unittest.main()
