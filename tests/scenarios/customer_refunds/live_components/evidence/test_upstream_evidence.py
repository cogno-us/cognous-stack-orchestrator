import importlib.util
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[5]
MODULE = ROOT / "development/scenarios/customer_refunds/live_components/evidence/qualification.py"
spec = importlib.util.spec_from_file_location("o5dc_evidence", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def trajectory():
    return {
        "trajectory_id": "refund-refusal-duplicate-execution-ref-v1",
        "tenant_id": "merchant-demo",
        "request_id": "refund-req-049",
        "generated_at": "2026-10-09T19:58:00Z",
        "events": [
            {"event_id": "e0", "kind": "intake", "sequence": 0, "recorded_at": "2026-10-09T19:58:00Z", "tenant_id": "merchant-demo", "request_id": "refund-req-049"},
            {"event_id": "e1", "kind": "authorization", "sequence": 1, "recorded_at": "2026-10-09T19:58:01Z", "tenant_id": "merchant-demo", "request_id": "refund-req-049", "decision_id": "decision-049", "authorization_state": "withdrawn"},
            {"event_id": "e2", "kind": "transport_receipt", "sequence": 2, "recorded_at": "2026-10-09T19:58:02Z", "tenant_id": "merchant-demo", "request_id": "refund-req-049", "receipt_id": "receipt-049"},
            {"event_id": "e3", "kind": "duplicate_suppressed", "sequence": 3, "recorded_at": "2026-10-09T19:58:03Z", "tenant_id": "merchant-demo", "request_id": "refund-req-049", "duplicate_of_request_id": "refund-req-048"},
            {"event_id": "e4", "kind": "runtime_refusal", "sequence": 4, "recorded_at": "2026-10-09T19:58:04Z", "tenant_id": "merchant-demo", "request_id": "refund-req-049", "effect_id": "effect-sim-049", "attempt_id": "attempt-sim-049", "execution_state": "refused", "simulation": True},
            {"event_id": "e5", "kind": "settlement_status", "sequence": 5, "recorded_at": "2026-10-09T19:58:05Z", "tenant_id": "merchant-demo", "request_id": "refund-req-049", "settlement": "not_observed"},
        ],
    }


class UpstreamEvidenceQualificationTests(unittest.TestCase):
    def test_exact_pinned_upstreams_parse_refusal_duplicate_and_references(self):
        result = m.qualify_trajectory(trajectory())
        self.assertEqual(result["source_revisions"]["replay"], m.REPLAY_REVISION)
        self.assertEqual(result["source_revisions"]["evidence_pack"], m.EVIDENCE_PACK_REVISION)
        self.assertTrue(result["evidence_pack_validation"]["valid"])
        self.assertEqual(result["boundary_summary"]["authorization"], ["withdrawn"])
        self.assertEqual(result["boundary_summary"]["effects"], ["refused"])
        self.assertEqual(result["boundary_summary"]["duplicates_suppressed"], 1)
        self.assertEqual(result["boundary_summary"]["settlement"], "not_observed")
        self.assertFalse(result["boundary_summary"]["independent_effect_verification"])

    def test_execution_reference_is_not_settlement(self):
        source = trajectory()
        source["trajectory_id"] = "refund-execution-reference-v1"
        source["events"][4]["kind"] = "execution_reference"
        source["events"][4]["execution_state"] = "intent_only"
        result = m.qualify_trajectory(source)
        self.assertEqual(result["boundary_summary"]["effects"], ["intent_only"])
        self.assertEqual(result["boundary_summary"]["settlement"], "not_observed")
        trace = result["evidence_pack"]["metadata"]["o5_d_c_qualification"]
        self.assertEqual(trace["receipt_semantics"], "receipt_only_not_authorization_effect_or_settlement")
        self.assertFalse(trace["independent_effect_verification"])

    def test_receipt_cannot_be_promoted_to_effect(self):
        source = trajectory()
        source["events"][2]["effect_id"] = "invented-effect"
        with self.assertRaisesRegex(m.QualificationError, "receipt_cannot_assert_effect_or_settlement"):
            m.qualify_trajectory(source)

    def test_duplicate_cannot_create_effect_reference(self):
        source = trajectory()
        source["events"][3]["attempt_id"] = "invented-attempt"
        with self.assertRaisesRegex(m.QualificationError, "duplicate_cannot_assert_effect_or_settlement"):
            m.qualify_trajectory(source)

    def test_positive_settlement_claim_is_rejected(self):
        source = trajectory()
        source["events"][5]["settlement"] = "settled"
        with self.assertRaisesRegex(m.QualificationError, "settlement_evidence_out_of_scope"):
            m.qualify_trajectory(source)

    def test_cross_tenant_event_is_rejected(self):
        source = trajectory()
        source["events"][4]["tenant_id"] = "other-tenant"
        with self.assertRaisesRegex(m.QualificationError, "tenant_mismatch"):
            m.qualify_trajectory(source)

    def test_upstream_checkout_is_required_not_optional(self):
        old_replay = os.environ.pop("COGNOUS_REPLAY_ROOT", None)
        old_pack = os.environ.pop("COGNOUS_EVIDENCE_PACK_ROOT", None)
        try:
            with self.assertRaisesRegex(m.UpstreamUnavailable, "missing_required_checkout"):
                m.qualify_trajectory(trajectory())
        finally:
            if old_replay is not None:
                os.environ["COGNOUS_REPLAY_ROOT"] = old_replay
            if old_pack is not None:
                os.environ["COGNOUS_EVIDENCE_PACK_ROOT"] = old_pack


if __name__ == "__main__":
    unittest.main()
