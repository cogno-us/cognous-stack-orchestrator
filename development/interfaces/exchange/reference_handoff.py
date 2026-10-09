"""Read-only Cognous Governed Exchange reference handoff.

Maps an already-produced exchange evidence record into an orchestrator
reference envelope. It does not deliver messages, dispatch effects, verify
producer claims, or authorize any action.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

SOURCE_REPOSITORY = "cogno-us/cognous-governed-exchange"
SOURCE_REVISION = "a1cbc7b28f702283b0e4f3192bb43e4a9e618ebf"
SOURCE_PROFILE_PATH = "experiments/governed_message_transport/profile.md"
SOURCE_IMPLEMENTATION_PATH = "experiments/governed_message_transport/transport.py"
SOURCE_TEST_PATH = "tests/test_governed_message_transport.py"

TRANSPORT_PROFILE = "urn:cognous:profiles:governed-message-transport:0.1.0"
TRANSPORT_VERSION = "0.1.0"
HANDOFF_PROFILE = "urn:cognous:orchestrator:exchange-reference-handoff:0.1.0"

KNOWN_ACK_KINDS = {
    "DURABLE_RECEIPT": "receipt_only",
    "DURABLE_RECEIPT_UNRESOLVED": "receipt_unresolved",
    "TERMINAL_REJECTION": "transport_rejection_only",
}


class ExchangeHandoffError(ValueError):
    """Malformed or unsupported source evidence."""


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExchangeHandoffError(f"{field}_required")
    return value


def _optional_ref(value: Any, namespace: str) -> dict[str, Any]:
    if value is None:
        return {"namespace": namespace, "id": None, "status": "unknown"}
    if not isinstance(value, str) or not value:
        return {"namespace": namespace, "id": None, "status": "invalid"}
    return {"namespace": namespace, "id": value, "status": "reported_reference"}


def _map_attempt(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ExchangeHandoffError("invalid_delivery_attempt")
    attempt_id = _required_text(row.get("transport_attempt_id"), "transport_attempt_id")
    retry = row.get("retry_of_transport_attempt_id")
    ack_id = row.get("acknowledgement_id")
    return {
        "namespace": "exchange.transport.delivery_attempt",
        "id": attempt_id,
        "status": row.get("state") if isinstance(row.get("state"), str) else "unknown",
        "ordinal": row.get("ordinal") if type(row.get("ordinal")) is int else None,
        "retry_of": (
            {"namespace": "exchange.transport.delivery_attempt", "id": retry}
            if isinstance(retry, str) and retry else None
        ),
        "acknowledgement_ref": (
            {"namespace": "exchange.transport.acknowledgement", "id": ack_id}
            if isinstance(ack_id, str) and ack_id else None
        ),
        "failure_reason": row.get("reason") if isinstance(row.get("reason"), str) else None,
    }


def _map_ack(row: Any, side: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ExchangeHandoffError("invalid_acknowledgement")
    ack_id = _required_text(row.get("acknowledgement_id"), "acknowledgement_id")
    attempt_id = _required_text(row.get("transport_attempt_id"), "ack_transport_attempt_id")
    kind = row.get("kind")
    return {
        "namespace": "exchange.transport.acknowledgement",
        "id": ack_id,
        "side": side,
        "kind": kind if isinstance(kind, str) and kind else "UNKNOWN",
        "status": KNOWN_ACK_KINDS.get(kind, "unknown"),
        "delivery_attempt_ref": {
            "namespace": "exchange.transport.delivery_attempt",
            "id": attempt_id,
        },
        "authorization": "not_established",
        "effect": "not_established",
        "independent_verification": "not_established",
    }


def map_exchange_evidence(
    evidence: dict[str, Any],
    *,
    source_revision: str = SOURCE_REVISION,
) -> dict[str, Any]:
    """Map an Exchange evidence record into a read-only reference envelope."""
    if source_revision != SOURCE_REVISION:
        raise ExchangeHandoffError("unsupported_exchange_revision")
    if not isinstance(evidence, dict):
        raise ExchangeHandoffError("evidence_object_required")
    if evidence.get("transport_profile") != TRANSPORT_PROFILE:
        raise ExchangeHandoffError("unsupported_transport_profile")
    if evidence.get("transport_version") != TRANSPORT_VERSION:
        raise ExchangeHandoffError("unsupported_transport_version")

    message_id = _required_text(evidence.get("message_id"), "message_id")
    attempts_raw = evidence.get("delivery_attempts")
    sender_acks_raw = evidence.get("sender_acknowledgements")
    recipient_acks_raw = evidence.get("recipient_acknowledgements")
    if not isinstance(attempts_raw, list):
        raise ExchangeHandoffError("delivery_attempts_list_required")
    if not isinstance(sender_acks_raw, list):
        raise ExchangeHandoffError("sender_acknowledgements_list_required")
    if not isinstance(recipient_acks_raw, list):
        raise ExchangeHandoffError("recipient_acknowledgements_list_required")

    producer_refs = evidence.get("producer_refs")
    if producer_refs is None:
        producer_refs = {}
    if not isinstance(producer_refs, dict):
        raise ExchangeHandoffError("producer_refs_object_required")

    processing = evidence.get("recipient_processing_status")
    if not isinstance(processing, str) or not processing:
        processing = "unknown"
    outbox = evidence.get("outbox_state")
    if not isinstance(outbox, str) or not outbox:
        outbox = "unknown"

    return {
        "handoff_profile": HANDOFF_PROFILE,
        "handoff_mode": "read_only_reference_mapping",
        "source": {
            "repository": SOURCE_REPOSITORY,
            "revision": SOURCE_REVISION,
            "profile_path": SOURCE_PROFILE_PATH,
            "implementation_path": SOURCE_IMPLEMENTATION_PATH,
            "test_path": SOURCE_TEST_PATH,
        },
        "message_ref": {
            "namespace": "exchange.governed_message",
            "id": message_id,
            "status": "reported_reference",
            "content_commitment": deepcopy(evidence.get("content_commitment")),
        },
        "delivery_attempt_refs": [_map_attempt(row) for row in attempts_raw],
        "acknowledgement_refs": {
            "sender": [_map_ack(row, "sender") for row in sender_acks_raw],
            "recipient": [_map_ack(row, "recipient") for row in recipient_acks_raw],
        },
        "recipient_processing_status": processing,
        "transport_state": outbox,
        "producer_refs": {
            "decision": _optional_ref(
                producer_refs.get("decision_id"), "control_plane.decision"
            ),
            "effect": _optional_ref(
                producer_refs.get("effect_id"), "execution.effect"
            ),
            "executor_attempt": _optional_ref(
                producer_refs.get("executor_attempt_id"),
                "execution.executor_attempt",
            ),
            "source_reported": deepcopy(producer_refs),
        },
        "assurance": {
            "receipt": (
                "reported"
                if sender_acks_raw or recipient_acks_raw or evidence.get("inbox_received_at")
                else "unknown"
            ),
            "authorization": "not_established",
            "dispatch_authority": "not_established",
            "effect_occurrence": "not_established",
            "effect_verification": "not_established",
            "source_authenticity": "not_established",
        },
        "boundary": {
            "transport_is_not_authorization": True,
            "acknowledgement_is_not_authorization": True,
            "refusal_is_not_authorization": True,
            "producer_reference_is_not_verification": True,
            "no_transport_dispatch_performed": True,
        },
    }
