import importlib.util
import os
import pathlib
import sys
import unittest
from copy import deepcopy

ROOT = pathlib.Path(__file__).resolve().parents[5]
MODULE = ROOT / "development/scenarios/customer_refunds/connected/replay/qualification.py"
spec = importlib.util.spec_from_file_location("o5eb_connected_replay", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

def event(i, kind, **extra):
    base = {
        "event_id": f"evt-{i}",
        "kind": kind,
        "sequence": i,
        "recorded_at": f"2026-10-09T20:1{i}:00Z",
        "tenant_id": "merchant-demo",
        "correlation_id": "corr-o5-e-057",
        "request_id": "refund-req-057",
        "provenance": {
            "source_component": extra.pop("_source_component", "cognous-stack-orchestrator"),
            "source_revision": extra.pop("_source_revision", "synthetic-connected-input"),
            "source_record_id": extra.pop("_source_record_id", f"source-{i}"),
        },
    }
    base.update(extra)
    return base

def trace():
    return {
        "trace_id": "refund-connected-refused-057",
        "tenant_id": "merchant-demo",
        "correlation_id": "corr-o5-e-057",
        "request_id": "refund-req-057",
        "generated_at": "2026-10-09T20:19:00Z",
        "events": [
            event(0, "request"),
            event(1, "screening"),
            event(2, "decision", decision_id="decision-057", authority_state="hold"),
            event(3, "approval_withdrawal", approval_id="approval-057", authority_state="withdrawn"),
            event(4, "refusal", refusal_id="refusal-057", refusal_state="refused"),
            event(5, "runtime_attempt", effect_id="effect-057", attempt_id="attempt-057", execution_state="refused"),
            event(6, "transport_receipt", receipt_id="receipt-057", receipt_state="not_sent"),
            event(7, "effect_observation", observer_id="observer-effect-057", observed_effect="not_observed"),
            event(8, "settlement_observation", observer_id="observer-settlement-057", settlement="not_observed", independent=True),
        ],
    }

class ConnectedReplayQualificationTests(unittest.TestCase):
    def test_exact_pinned_upstreams_parse_connected_refused_trace(self):
        result = m.qualify_connected_trace(trace())
        self.assertEqual(result["source_revisions"]["replay"], m.REPLAY_REVISION)
        self.assertEqual(result["source_revisions"]["evidence_pack"], m.EVIDENCE_PACK_REVISION)
        self.assertTrue(result["evidence_pack_validation"]["valid"])
        self.assertEqual(result["evidence_pack"]["deployment_context"]["environment"], "sandbox")
        self.assertEqual(result["evidence_pack"]["metadata"]["o5_e_b_connected"]["source_nature"], "synthetic_connected_trace")
        b = result["boundary_summary"]
        self.assertEqual(b["authorization"], ["hold", "withdrawn"])
        self.assertEqual(b["refusal"], ["refused"])
        self.assertEqual(b["runtime_attempt"], ["refused"])
        self.assertEqual(b["transport_receipt"], ["not_sent"])
        self.assertEqual(b["effect_observation"], ["not_observed"])
        self.assertEqual(b["settlement"], ["not_observed"])
        self.assertFalse(b["independent_effect_verification"])
        semantics = result["reconstruction"]["semantics"]
        self.assertEqual(semantics["destination_observation"], "producer_reported")
        self.assertFalse(semantics["independent_effect_verification"])
        self.assertFalse(semantics["external_effect_execution"])

    def test_swapped_tenant_is_rejected(self):
        source = trace()
        source["events"][5]["tenant_id"] = "other-merchant"
        with self.assertRaisesRegex(m.QualificationError, "tenant_mismatch"):
            m.qualify_connected_trace(source)

    def test_missing_provenance_is_rejected(self):
        source = trace()
        del source["events"][6]["provenance"]
        with self.assertRaisesRegex(m.QualificationError, "missing_provenance"):
            m.qualify_connected_trace(source)

    def test_duplicate_event_identifier_is_rejected(self):
        source = trace()
        source["events"][6]["event_id"] = source["events"][5]["event_id"]
        with self.assertRaisesRegex(m.QualificationError, "duplicate_event_id"):
            m.qualify_connected_trace(source)

    def test_duplicate_source_record_identifier_is_rejected(self):
        source = trace()
        source["events"][6]["provenance"]["source_record_id"] = source["events"][5]["provenance"]["source_record_id"]
        with self.assertRaisesRegex(m.QualificationError, "duplicate_source_record_id"):
            m.qualify_connected_trace(source)

    def test_duplicate_effect_identifier_is_rejected(self):
        source = trace()
        source["events"].insert(6, event(6, "runtime_attempt", effect_id="effect-057", attempt_id="attempt-058", execution_state="refused"))
        for i, e in enumerate(source["events"]):
            e["sequence"] = i
            e["event_id"] = f"evt-{i}" if i != 6 else "evt-runtime-dup"
            e["provenance"]["source_record_id"] = f"source-{i}"
        with self.assertRaisesRegex(m.QualificationError, "duplicate_effect_id"):
            m.qualify_connected_trace(source)

    def test_duplicate_attempt_identifier_is_rejected(self):
        source = trace()
        source["events"].insert(6, event(6, "runtime_attempt", effect_id="effect-058", attempt_id="attempt-057", execution_state="refused"))
        for i, e in enumerate(source["events"]):
            e["sequence"] = i
            e["event_id"] = f"evt-{i}" if i != 6 else "evt-runtime-attempt-dup"
            e["provenance"]["source_record_id"] = f"source-{i}"
        with self.assertRaisesRegex(m.QualificationError, "duplicate_attempt_id"):
            m.qualify_connected_trace(source)

    def test_false_settlement_claim_is_rejected(self):
        source = trace()
        source["events"][8]["settlement"] = "settled"
        source["events"][8]["settlement_id"] = "fake-settlement-057"
        with self.assertRaisesRegex(m.QualificationError, "false_settlement_claim"):
            m.qualify_connected_trace(source)

    def test_non_independent_settlement_observer_is_rejected(self):
        source = trace()
        source["events"][8]["independent"] = False
        with self.assertRaisesRegex(m.QualificationError, "settlement_observer_not_independent"):
            m.qualify_connected_trace(source)

    def test_transport_receipt_cannot_claim_settlement(self):
        source = trace()
        source["events"][6]["settlement"] = "settled"
        with self.assertRaisesRegex(m.QualificationError, "receipt_cannot_assert_settlement"):
            m.qualify_connected_trace(source)

    def test_approval_withdrawal_stays_distinct_from_execution(self):
        result = m.qualify_connected_trace(trace())
        refs = result["evidence_pack"]["metadata"]["o5_e_b_connected"]["event_refs_by_kind"]
        self.assertEqual(refs["approval_withdrawal"], ["evt-3"])
        self.assertEqual(refs["runtime_attempt"], ["evt-5"])
        self.assertEqual(refs["settlement_observation"], ["evt-8"])

    def test_exact_upstream_checkout_is_required(self):
        old_replay = os.environ.pop("COGNOUS_REPLAY_ROOT", None)
        old_pack = os.environ.pop("COGNOUS_EVIDENCE_PACK_ROOT", None)
        try:
            with self.assertRaisesRegex(m.UpstreamUnavailable, "missing_required_checkout"):
                m.qualify_connected_trace(trace())
        finally:
            if old_replay is not None:
                os.environ["COGNOUS_REPLAY_ROOT"] = old_replay
            if old_pack is not None:
                os.environ["COGNOUS_EVIDENCE_PACK_ROOT"] = old_pack

if __name__ == "__main__":
    unittest.main()
