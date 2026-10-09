import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
PATH = ROOT / "development" / "interfaces" / "exchange" / "reference_handoff.py"
SPEC = importlib.util.spec_from_file_location("exchange_reference_handoff", PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def sample():
    return {
        "transport_profile": module.TRANSPORT_PROFILE,
        "transport_version": module.TRANSPORT_VERSION,
        "message_id": "msg-1",
        "content_commitment": "sha256:" + "1" * 64,
        "outbox_state": "DELIVERED",
        "inbox_received_at": "2026-10-06T12:00:00Z",
        "recipient_processing_status": "retained",
        "delivery_attempts": [
            {
                "transport_attempt_id": "delivery-1",
                "ordinal": 1,
                "state": "ACKNOWLEDGED",
                "retry_of_transport_attempt_id": None,
                "acknowledgement_id": "ack-1",
                "reason": None,
            }
        ],
        "sender_acknowledgements": [
            {
                "acknowledgement_id": "ack-1",
                "transport_attempt_id": "delivery-1",
                "kind": "DURABLE_RECEIPT",
            }
        ],
        "recipient_acknowledgements": [
            {
                "acknowledgement_id": "ack-1",
                "transport_attempt_id": "delivery-1",
                "kind": "DURABLE_RECEIPT",
            }
        ],
        "producer_refs": {
            "decision_id": "decision-7",
            "effect_id": "effect-9",
            "executor_attempt_id": "executor-attempt-3",
        },
        "namespace_rule": (
            "transport_attempt_id is transport-owned; decision_id, effect_id and "
            "executor_attempt_id are linked only when returned by the recipient producer"
        ),
    }


class ExchangeReferenceHandoffTests(unittest.TestCase):
    def test_preserves_separate_reference_namespaces(self):
        got = module.map_exchange_evidence(sample())
        self.assertEqual(got["message_ref"]["id"], "msg-1")
        self.assertEqual(got["delivery_attempt_refs"][0]["id"], "delivery-1")
        self.assertEqual(got["acknowledgement_refs"]["sender"][0]["id"], "ack-1")
        self.assertEqual(got["producer_refs"]["decision"]["id"], "decision-7")
        self.assertEqual(got["producer_refs"]["effect"]["id"], "effect-9")
        self.assertEqual(got["producer_refs"]["executor_attempt"]["id"], "executor-attempt-3")
        namespaces = {
            got["message_ref"]["namespace"],
            got["delivery_attempt_refs"][0]["namespace"],
            got["acknowledgement_refs"]["sender"][0]["namespace"],
            got["producer_refs"]["decision"]["namespace"],
            got["producer_refs"]["effect"]["namespace"],
            got["producer_refs"]["executor_attempt"]["namespace"],
        }
        self.assertEqual(len(namespaces), 6)

    def test_lost_ack_is_unresolved_not_effect_or_authorization(self):
        item = sample()
        item["outbox_state"] = "PENDING_RETRY"
        item["sender_acknowledgements"] = []
        item["recipient_acknowledgements"] = []
        item["delivery_attempts"][0]["state"] = "PENDING_RETRY"
        item["delivery_attempts"][0]["acknowledgement_id"] = None
        item["producer_refs"] = {"effect_id": "effect-9"}
        got = module.map_exchange_evidence(item)
        self.assertEqual(got["transport_state"], "PENDING_RETRY")
        self.assertEqual(got["assurance"]["receipt"], "reported")
        self.assertEqual(got["assurance"]["authorization"], "not_established")
        self.assertEqual(got["assurance"]["effect_occurrence"], "not_established")
        self.assertEqual(got["producer_refs"]["effect"]["status"], "reported_reference")

    def test_duplicate_suppressed_attempts_remain_distinct_transport_attempts(self):
        item = sample()
        item["delivery_attempts"].append(
            {
                "transport_attempt_id": "delivery-2",
                "ordinal": 2,
                "state": "ACKNOWLEDGED",
                "retry_of_transport_attempt_id": "delivery-1",
                "acknowledgement_id": "ack-2",
                "reason": "duplicate_suppressed",
            }
        )
        item["sender_acknowledgements"].append(
            {
                "acknowledgement_id": "ack-2",
                "transport_attempt_id": "delivery-2",
                "kind": "DURABLE_RECEIPT",
            }
        )
        got = module.map_exchange_evidence(item)
        self.assertEqual(
            [x["id"] for x in got["delivery_attempt_refs"]],
            ["delivery-1", "delivery-2"],
        )
        self.assertEqual(got["delivery_attempt_refs"][1]["retry_of"]["id"], "delivery-1")
        self.assertEqual(got["message_ref"]["id"], "msg-1")
        self.assertEqual(got["assurance"]["authorization"], "not_established")

    def test_unknown_effect_and_executor_attempt_are_explicit(self):
        item = sample()
        item["producer_refs"] = {"decision_id": "decision-7"}
        got = module.map_exchange_evidence(item)
        self.assertEqual(got["producer_refs"]["decision"]["status"], "reported_reference")
        self.assertEqual(got["producer_refs"]["effect"]["status"], "unknown")
        self.assertIsNone(got["producer_refs"]["effect"]["id"])
        self.assertEqual(got["producer_refs"]["executor_attempt"]["status"], "unknown")
        self.assertEqual(got["assurance"]["effect_verification"], "not_established")

    def test_terminal_rejection_is_transport_refusal_not_authorization(self):
        item = sample()
        item["sender_acknowledgements"][0]["kind"] = "TERMINAL_REJECTION"
        item["recipient_acknowledgements"][0]["kind"] = "TERMINAL_REJECTION"
        item["producer_refs"] = {}
        got = module.map_exchange_evidence(item)
        ack = got["acknowledgement_refs"]["sender"][0]
        self.assertEqual(ack["status"], "transport_rejection_only")
        self.assertEqual(ack["authorization"], "not_established")
        self.assertTrue(got["boundary"]["refusal_is_not_authorization"])
        self.assertEqual(got["assurance"]["authorization"], "not_established")

    def test_informational_refuse_cannot_become_authorization(self):
        item = sample()
        item["message_type"] = "REFUSE"
        item["producer_refs"] = {"decision_id": "refusal-decision"}
        got = module.map_exchange_evidence(item)
        self.assertEqual(got["producer_refs"]["decision"]["id"], "refusal-decision")
        self.assertEqual(got["assurance"]["authorization"], "not_established")
        self.assertTrue(got["boundary"]["refusal_is_not_authorization"])

    def test_durable_receipt_ack_is_receipt_only(self):
        got = module.map_exchange_evidence(sample())
        ack = got["acknowledgement_refs"]["recipient"][0]
        self.assertEqual(ack["status"], "receipt_only")
        self.assertEqual(ack["authorization"], "not_established")
        self.assertEqual(ack["effect"], "not_established")
        self.assertEqual(ack["independent_verification"], "not_established")

    def test_unresolved_receipt_is_explicit_failure_state(self):
        item = sample()
        item["recipient_processing_status"] = "unresolved_after_durable_receipt"
        item["recipient_acknowledgements"][0]["kind"] = "DURABLE_RECEIPT_UNRESOLVED"
        got = module.map_exchange_evidence(item)
        self.assertEqual(got["recipient_processing_status"], "unresolved_after_durable_receipt")
        self.assertEqual(
            got["acknowledgement_refs"]["recipient"][0]["status"],
            "receipt_unresolved",
        )
        self.assertEqual(got["assurance"]["effect_occurrence"], "not_established")

    def test_unsupported_source_revision_fails_closed(self):
        with self.assertRaisesRegex(
            module.ExchangeHandoffError, "unsupported_exchange_revision"
        ):
            module.map_exchange_evidence(sample(), source_revision="main")

    def test_malformed_or_unknown_reference_is_not_fabricated(self):
        item = sample()
        item["producer_refs"] = {
            "decision_id": "",
            "effect_id": None,
            "executor_attempt_id": 42,
        }
        got = module.map_exchange_evidence(item)
        self.assertEqual(got["producer_refs"]["decision"]["status"], "invalid")
        self.assertEqual(got["producer_refs"]["effect"]["status"], "unknown")
        self.assertEqual(got["producer_refs"]["executor_attempt"]["status"], "invalid")
        self.assertEqual(got["assurance"]["authorization"], "not_established")


if __name__ == "__main__":
    unittest.main()
