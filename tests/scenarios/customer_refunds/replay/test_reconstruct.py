import copy
import importlib.util
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]
MODULE_PATH = ROOT / "development/scenarios/customer_refunds/replay/reconstruct.py"
FIXTURE_PATH = ROOT / "development/scenarios/customer_refunds/replay/fixture.json"

spec = importlib.util.spec_from_file_location("refund_replay", MODULE_PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class RefundReplayTests(unittest.TestCase):
    def test_denied_withdrawn_trajectory_is_deterministic_and_non_effecting(self):
        source = fixture()
        first = m.reconstruct_trajectory(source)
        second = m.reconstruct_trajectory(copy.deepcopy(source))
        self.assertEqual(first, second)

        summary = first["trajectory_summary"]
        self.assertEqual(summary["final_decision"], "denial")
        self.assertEqual(summary["effect_state"], "refused")
        self.assertEqual(summary["settlement"], "not_observed")

        bundle = first["reconstruction_bundle"]
        self.assertEqual(bundle["bundle_version"], "0.2.0")
        self.assertFalse(bundle["semantics"]["external_effect_execution"])
        self.assertEqual(bundle["semantics"]["destination_observation"], "not_performed")
        self.assertFalse(bundle["semantics"]["independent_effect_verification"])

        projection = first["evidence_projection"]
        self.assertEqual(projection["review_status"], "draft")
        self.assertEqual(projection["settlement_status"], "not_observed")
        self.assertEqual(projection["settlement_evidence"], [])
        self.assertEqual(projection["independent_verification"], "not_performed")
        self.assertEqual(projection["effect_references"][0]["execution_state"], "refused")
        self.assertTrue(projection["effect_references"][0]["simulation"])
        self.assertFalse(projection["duplicate_suppressions"][0]["effect_created"])

    def test_transport_receipt_stays_separate_from_effect(self):
        result = m.reconstruct_trajectory(fixture())
        receipts = result["evidence_projection"]["transport_receipts"]
        self.assertEqual(receipts[0]["meaning"], "receipt_only_not_authorization_or_effect")
        self.assertNotIn("effect_id", receipts[0])
        self.assertEqual(result["evidence_projection"]["settlement_evidence"], [])

    def test_simulated_accepted_intent_does_not_become_settlement(self):
        source = fixture()
        source["trajectory_id"] = "refund-simulated-intent-v1"
        source["events"] = source["events"][:4]
        source["events"].extend([
            {
                "event_id": "evt-004",
                "kind": "execution_intent_accepted",
                "sequence": 4,
                "recorded_at": "2026-10-09T19:00:04Z",
                "tenant_id": "merchant-demo",
                "request_id": "refund-req-001",
                "effect_id": "effect-sim-accepted-001",
                "attempt_id": "attempt-sim-accepted-001",
                "execution_state": "intent_accepted",
                "simulation": True,
                "source": {
                    "evidence_class": "producer_reported",
                    "reference": "fixture:runtime:intent-accepted",
                },
            },
            {
                "event_id": "evt-005",
                "kind": "settlement_status",
                "sequence": 5,
                "recorded_at": "2026-10-09T19:00:05Z",
                "tenant_id": "merchant-demo",
                "request_id": "refund-req-001",
                "settlement": "not_observed",
                "source": {
                    "evidence_class": "locally_generated",
                    "reference": "fixture:settlement:not-observed",
                },
            },
        ])
        result = m.reconstruct_trajectory(source)
        self.assertEqual(result["trajectory_summary"]["effect_state"], "simulated_intent_accepted")
        self.assertEqual(result["trajectory_summary"]["settlement"], "not_observed")
        self.assertEqual(result["evidence_projection"]["settlement_evidence"], [])
        effect = result["evidence_projection"]["effect_references"][0]
        self.assertTrue(effect["simulation"])
        self.assertEqual(effect["settlement"], "not_observed")

    def test_issuer_transport_decision_and_effect_namespaces_remain_distinct(self):
        projection = m.reconstruct_trajectory(fixture())["evidence_projection"]
        self.assertEqual(projection["issuer_claims"][0]["state"], "verified_issuer_only")
        self.assertIn("transport_id", projection["transport_receipts"][0])
        self.assertIn("decision_id", projection["decisions"][0])
        self.assertIn("effect_id", projection["effect_references"][0])
        self.assertNotIn("decision_id", projection["transport_receipts"][0])
        self.assertNotIn("transport_id", projection["decisions"][0])
        self.assertNotIn("settlement_id", projection["effect_references"][0])

    def test_negative_transport_effect_promotion_fails_closed(self):
        source = fixture()
        source["events"][3]["effect_id"] = "invented-effect"
        with self.assertRaisesRegex(m.ReplayContractError, "transport_cannot_assert_effect"):
            m.reconstruct_trajectory(source)

    def test_negative_positive_settlement_claim_fails_closed(self):
        source = fixture()
        source["events"][-1]["settlement"] = "settled"
        with self.assertRaisesRegex(m.ReplayContractError, "settlement_evidence_out_of_scope"):
            m.reconstruct_trajectory(source)

    def test_negative_unsimulated_effect_reference_fails_closed(self):
        source = fixture()
        source["events"][7]["simulation"] = False
        with self.assertRaisesRegex(m.ReplayContractError, "effect_reference_must_be_simulated"):
            m.reconstruct_trajectory(source)

    def test_negative_cross_tenant_event_fails_closed(self):
        source = fixture()
        source["events"][5]["tenant_id"] = "other-tenant"
        with self.assertRaisesRegex(m.ReplayContractError, "tenant_mismatch"):
            m.reconstruct_trajectory(source)

    def test_negative_sequence_reordering_fails_closed(self):
        source = fixture()
        source["events"][2]["sequence"] = 3
        with self.assertRaisesRegex(m.ReplayContractError, "non_deterministic_sequence"):
            m.reconstruct_trajectory(source)

    def test_compatibility_status_is_truthful_without_upstream_packages(self):
        compat = m.reconstruct_trajectory(fixture())["compatibility"]
        self.assertEqual(compat["replay"]["revision"], m.REPLAY_REVISION)
        self.assertIn(
            compat["replay"]["status"],
            {"not_executed_dependency_unavailable", "validated_with_installed_package"},
        )
        self.assertEqual(
            compat["evidence_pack"]["status"],
            "not_executed_requires_manifest_and_upstream_package",
        )


if __name__ == "__main__":
    unittest.main()
