"""Exactly three Architect-selected focused synthetic-refund tests.

These exercise native-field interpretation with controlled fixtures. They do NOT
prove that a current-pin composed source run has succeeded; first native run
requires a separate Architect decision.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from refund_local import RefundAdapterError, classify_native


def _pack(authorization, attempted):
    return {"metadata": {"traceable_import": {"lifecycle_summary": {
        "authorization": authorization,
        "execution_attempted": attempted,
        "reconstruction_status": "reconstruction_partial",
    }}}}


class RefundLocalFocusedTests(unittest.TestCase):
    def test_01_authorized_synthetic_completed_requires_observation_reconcile_and_row(self):
        decision = {"result": "authorized", "effect_id": "e-a", "binding": {"tenant_id": "tenant-alpha"}}
        record = {
            "attempts": [{"effect_id": "e-a", "status": "acknowledged"}],
            "observations": [{"effect_id": "e-a", "state": "applied"}],
            "reconciliations": [{"effect_id": "e-a", "result": "applied", "observation_accepted": True}],
        }
        result = classify_native(decision, record, {"effects": {"e-a": {"state": "applied"}}},
                                 _pack("authorized", "yes"),
                                 {"recipient_reliance_decision": {"status": "fail"}})
        self.assertEqual(result["synthetic_effect_standing"], "SYNTHETIC_APPLIED_OBSERVED")
        self.assertEqual(result["local_destination_row_count"], 1)
        self.assertEqual(result["real_payment_effect"], "NOT_ATTEMPTED")

    def test_02_hold_prohibits_local_effect_and_records_no_execution(self):
        decision = {"result": "hold", "effect_id": "e-h", "binding": None}
        result = classify_native(
            decision, {"attempts": [], "observations": [], "reconciliations": []},
            {"effects": {}}, _pack("held", "no"),
            {"recipient_reliance_decision": {"status": "fail"}},
        )
        self.assertEqual(result["synthetic_effect_standing"], "HELD_NO_EFFECT")
        self.assertEqual(result["record_attempt_count"], 0)
        with self.assertRaises(RefundAdapterError):
            classify_native(decision, {"attempts": [{"effect_id": "e-h"}]},
                            {"effects": {}}, _pack("held", "no"), {})

    def test_03_acknowledgement_alone_never_promotes_to_completed_or_reliance(self):
        decision = {"result": "authorized", "effect_id": "e-a", "binding": {"tenant_id": "tenant-alpha"}}
        result = classify_native(
            decision,
            {"attempts": [{"effect_id": "e-a", "status": "acknowledged"}],
             "observations": [], "reconciliations": []},
            {"effects": {}}, _pack("authorized", "yes"),
            {"recipient_reliance_decision": {"status": "fail", "reasons": ["missing recipient trust"]}},
        )
        self.assertEqual(result["synthetic_effect_standing"], "AUTHORIZED_NOT_CONFIRMED_APPLIED")
        self.assertEqual(result["odes_recipient_reliance"]["status"], "fail")
        self.assertEqual(result["pack_lifecycle"]["reconstruction_status"], "reconstruction_partial")


if __name__ == "__main__":
    unittest.main()
