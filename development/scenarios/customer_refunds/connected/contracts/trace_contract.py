"""O5-E-C connected synthetic refund trace contract.

Pure contract validation only: no grants, effect dispatch, settlement inference, or
substitution for the pinned component implementations.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

CONTRACT_VERSION = "o5-e-connected-refund-trace/1.0.0"
SOURCE_REVISIONS = {
    "action_manifest": "8d1572d4f926c968a8704cb912a6e9d49166f74a",
    "control_plane": "e66e5f163c5d5c112ff345a2f332b4c3893ee183",
    "execution_runtime": "da9f52900ee2596dab087ec6c249ba84915d2b13",
    "replay": "2069a0ba1398812c3a8669331a7d8b87c80c4a48",
    "evidence_pack": "87293cfcbe8dfa2368d5bf77019945ba8ef1ae71",
}

HOLD_REASONS = {
    "missing_grant",
    "altered_policy",
    "approval_withdrawn",
    "duplicate_intent",
    "unknown_delivery",
    "forged_receipt",
    "forged_settlement",
    "tenant_mismatch",
}


class ContractError(ValueError):
    pass


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"required_text:{path}")
    return value


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"required_object:{path}")
    return value


def _exact_keys(value: dict[str, Any], required: set[str], optional: set[str], path: str) -> None:
    missing = required - value.keys()
    if missing:
        raise ContractError(f"missing_keys:{path}:{','.join(sorted(missing))}")
    extra = value.keys() - required - optional
    if extra:
        raise ContractError(f"unknown_keys:{path}:{','.join(sorted(extra))}")


def _same(actual: Any, expected: Any, code: str) -> None:
    if actual != expected:
        raise ContractError(code)


def validate_trace(raw: dict[str, Any]) -> dict[str, Any]:
    trace = deepcopy(_object(raw, "trace"))
    _exact_keys(
        trace,
        {"contract_version", "trajectory_id", "tenant_id", "source_revisions", "request", "decision", "execution_attempt", "evidence", "transport", "settlement"},
        set(),
        "trace",
    )
    _same(trace["contract_version"], CONTRACT_VERSION, "contract_version_mismatch")
    _text(trace["trajectory_id"], "trajectory_id")
    tenant = _text(trace["tenant_id"], "tenant_id")
    _same(trace["source_revisions"], SOURCE_REVISIONS, "source_revision_mismatch")

    request = _object(trace["request"], "request")
    _exact_keys(request, {"request_id", "intent_id", "tenant_id", "policy_ref", "policy_version", "policy_digest", "approval_id"}, set(), "request")
    request_id = _text(request["request_id"], "request.request_id")
    intent_id = _text(request["intent_id"], "request.intent_id")
    _same(request["tenant_id"], tenant, "tenant_mismatch:request")
    _text(request["policy_ref"], "request.policy_ref")
    _text(request["policy_version"], "request.policy_version")
    policy_digest = _text(request["policy_digest"], "request.policy_digest")
    _text(request["approval_id"], "request.approval_id")

    decision = _object(trace["decision"], "decision")
    _exact_keys(decision, {"decision_id", "request_id", "intent_id", "tenant_id", "result", "reasons", "policy_digest", "grant_id", "approval_id", "approval_status"}, set(), "decision")
    decision_id = _text(decision["decision_id"], "decision.decision_id")
    _same(decision["request_id"], request_id, "request_identity_mismatch:decision")
    _same(decision["intent_id"], intent_id, "intent_identity_mismatch:decision")
    _same(decision["tenant_id"], tenant, "tenant_mismatch:decision")
    if decision["result"] not in {"HOLD", "REFUSED"}:
        raise ContractError("decision_must_hold_or_refuse")
    if not isinstance(decision["reasons"], list) or not decision["reasons"]:
        raise ContractError("decision_reasons_required")
    unknown = set(decision["reasons"]) - HOLD_REASONS
    if unknown:
        raise ContractError(f"unsupported_hold_reason:{','.join(sorted(unknown))}")
    _same(decision["policy_digest"], policy_digest, "altered_policy")
    if decision["grant_id"] is not None:
        _text(decision["grant_id"], "decision.grant_id")
    _same(decision["approval_id"], request["approval_id"], "approval_identity_mismatch")
    if decision["approval_status"] not in {"active", "withdrawn"}:
        raise ContractError("invalid_approval_status")

    attempt = _object(trace["execution_attempt"], "execution_attempt")
    _exact_keys(attempt, {"attempt_id", "effect_id", "decision_id", "request_id", "intent_id", "tenant_id", "state"}, set(), "execution_attempt")
    attempt_id = _text(attempt["attempt_id"], "execution_attempt.attempt_id")
    effect_id = _text(attempt["effect_id"], "execution_attempt.effect_id")
    _same(attempt["decision_id"], decision_id, "decision_identity_mismatch:execution_attempt")
    _same(attempt["request_id"], request_id, "request_identity_mismatch:execution_attempt")
    _same(attempt["intent_id"], intent_id, "intent_identity_mismatch:execution_attempt")
    _same(attempt["tenant_id"], tenant, "tenant_mismatch:execution_attempt")
    if attempt["state"] not in {"not_dispatched", "refused", "unknown_delivery"}:
        raise ContractError("invalid_execution_attempt_state")

    evidence = _object(trace["evidence"], "evidence")
    _exact_keys(evidence, {"evidence_id", "request_id", "decision_id", "attempt_id", "tenant_id", "state", "independent_effect_verification"}, set(), "evidence")
    _text(evidence["evidence_id"], "evidence.evidence_id")
    _same(evidence["request_id"], request_id, "request_identity_mismatch:evidence")
    _same(evidence["decision_id"], decision_id, "decision_identity_mismatch:evidence")
    _same(evidence["attempt_id"], attempt_id, "attempt_identity_mismatch:evidence")
    _same(evidence["tenant_id"], tenant, "tenant_mismatch:evidence")
    if evidence["state"] not in {"recorded", "incomplete"}:
        raise ContractError("invalid_evidence_state")
    if evidence["independent_effect_verification"] is not False:
        raise ContractError("independent_effect_verification_not_established")

    transport = _object(trace["transport"], "transport")
    _exact_keys(transport, {"receipt_id", "request_id", "attempt_id", "tenant_id", "delivery_state", "authenticity"}, set(), "transport")
    _text(transport["receipt_id"], "transport.receipt_id")
    _same(transport["request_id"], request_id, "request_identity_mismatch:transport")
    _same(transport["attempt_id"], attempt_id, "attempt_identity_mismatch:transport")
    _same(transport["tenant_id"], tenant, "tenant_mismatch:transport")
    if transport["delivery_state"] not in {"not_sent", "refused", "unknown"}:
        raise ContractError("invalid_delivery_state")
    if transport["authenticity"] not in {"unverified", "verified"}:
        raise ContractError("invalid_receipt_authenticity")
    if transport["authenticity"] == "unverified" and transport["delivery_state"] != "unknown":
        raise ContractError("forged_receipt")

    settlement = _object(trace["settlement"], "settlement")
    _exact_keys(settlement, {"observation_id", "request_id", "effect_id", "tenant_id", "state", "independent"}, set(), "settlement")
    _text(settlement["observation_id"], "settlement.observation_id")
    _same(settlement["request_id"], request_id, "request_identity_mismatch:settlement")
    _same(settlement["effect_id"], effect_id, "effect_identity_mismatch:settlement")
    _same(settlement["tenant_id"], tenant, "tenant_mismatch:settlement")
    if settlement["state"] != "not_observed" or settlement["independent"] is not False:
        raise ContractError("forged_settlement")

    reasons = set(decision["reasons"])
    if decision["grant_id"] is None and "missing_grant" not in reasons:
        raise ContractError("missing_grant_requires_hold_reason")
    if decision["approval_status"] == "withdrawn" and "approval_withdrawn" not in reasons:
        raise ContractError("withdrawn_approval_requires_hold_reason")
    if attempt["state"] == "unknown_delivery" and "unknown_delivery" not in reasons:
        raise ContractError("unknown_delivery_requires_hold_reason")
    if transport["delivery_state"] == "unknown" and "unknown_delivery" not in reasons:
        raise ContractError("unknown_transport_requires_hold_reason")

    # Cross-stage identities are references, not aliases: their own identifiers
    # must remain distinct to avoid promoting one stage's record into another.
    stage_ids = [request_id, decision_id, attempt_id, evidence["evidence_id"], transport["receipt_id"], settlement["observation_id"]]
    if len(stage_ids) != len(set(stage_ids)):
        raise ContractError("stage_identity_collision")

    return trace


def interface_projection(trace: dict[str, Any]) -> dict[str, Any]:
    """Return the frozen handoff fields for workers A and B after validation."""
    t = validate_trace(trace)
    return {
        "a_control_runtime": {
            "request": t["request"],
            "decision": t["decision"],
            "execution_attempt": t["execution_attempt"],
            "transport": t["transport"],
        },
        "b_replay_evidence": {
            "request_id": t["request"]["request_id"],
            "decision_id": t["decision"]["decision_id"],
            "attempt_id": t["execution_attempt"]["attempt_id"],
            "effect_id": t["execution_attempt"]["effect_id"],
            "evidence": t["evidence"],
            "transport_receipt_id": t["transport"]["receipt_id"],
            "settlement": t["settlement"],
        },
    }
