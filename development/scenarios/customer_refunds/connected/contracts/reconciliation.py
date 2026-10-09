"""Issue #58: reconcile the *actual* O5-E-A and O5-E-B trace interfaces.

Read-only structural contract. This is NOT a producer, issuer verifier, grant
resolver, payment executor, or a replacement for either pinned upstream.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from trace_contract import ContractError


def reconcile_handoff(*, decision: Any, observation: dict[str, Any], effect_rows: list,
                      attempt_rows: list, runtime_result: Any = None) -> dict[str, Any]:
    """Project PR #60's objects without creating an absent attempt/claim/grant."""
    result = getattr(decision, "result", None)
    if result not in {"hold", "authorized", "denied"}:
        raise ContractError("unknown_control_plane_decision")
    decision_id = getattr(decision, "decision_id", None)
    effect_id = getattr(decision, "effect_id", None)
    if not isinstance(decision_id, str) or not decision_id:
        raise ContractError("missing_decision_id")
    if not isinstance(effect_id, str) or not effect_id:
        raise ContractError("missing_effect_id")
    if observation.get("effect_id") != effect_id:
        raise ContractError("effect_observation_identity_mismatch")
    state = observation.get("state")
    if state not in {"absent", "unknown", "committed", "executed"}:
        raise ContractError("unsupported_effect_observation")
    if result != "authorized":
        if getattr(decision, "binding", None) is not None:
            raise ContractError("non_authorized_binding")
        if effect_rows or attempt_rows:
            raise ContractError("effect_or_attempt_after_hold")
        if state != "absent":
            raise ContractError("effect_not_absent_after_hold")
        if runtime_result is not None:
            raise ContractError("runtime_result_without_authority")
        attempt_id = None
        execution_state = "not_dispatched"
    else:
        if getattr(decision, "binding", None) is None:
            raise ContractError("authorized_without_binding")
        attempt_id = getattr(runtime_result, "attempt_id", None) if runtime_result is not None else None
        attempted = getattr(runtime_result, "attempted", None) if runtime_result is not None else None
        if attempted is False and attempt_id is not None:
            raise ContractError("attempt_id_from_non_attempt")
        if attempted is True and not attempt_id:
            raise ContractError("missing_real_attempt_id")
        if attempt_id is not None and not any(r.get("attempt_id") == attempt_id for r in attempt_rows):
            raise ContractError("attempt_not_in_destination")
        execution_state = getattr(runtime_result, "status", None) if runtime_result is not None else "not_dispatched"
    return {
        "decision_id": decision_id,
        "effect_id": effect_id,
        "decision_state": result,
        "decision_reasons": list(getattr(decision, "reasons", ()) or ()),
        "attempt_id": attempt_id,
        "execution_state": execution_state,
        "effect_observation": state,
        "settlement": "not_observed",
        "merchant_authority": "not_established",
        "issuer_verification": "not_established",
    }


KINDS = ("request", "screening", "decision", "approval_withdrawal", "refusal",
         "runtime_attempt", "transport_receipt", "effect_observation",
         "settlement_observation")


def reconcile_replay_trace(source: dict[str, Any]) -> dict[str, Any]:
    """Verify PR #61's observed event vocabulary, lineage and provenance.

    This checks structural attribution only, not cryptographic issuer identity.
    PR #61's synthetic runtime_attempt is NOT equated to PR #60's absent
    runtime attempt from the missing-grant HOLD case.
    """
    if not isinstance(source, dict):
        raise ContractError("trace_not_object")
    tenant = source.get("tenant_id")
    request = source.get("request_id")
    correlation = source.get("correlation_id")
    if not all(isinstance(x, str) and x for x in (tenant, request, correlation, source.get("trace_id"))):
        raise ContractError("missing_trace_identity")
    events = source.get("events")
    if not isinstance(events, list) or not events:
        raise ContractError("missing_events")
    seen_event, seen_source, seen_attempt, seen_effect = set(), set(), set(), set()
    by_kind = Counter()
    stages = {}
    for seq, event in enumerate(events):
        if not isinstance(event, dict):
            raise ContractError("event_not_object")
        eid = event.get("event_id")
        kind = event.get("kind")
        if not isinstance(eid, str) or not eid or eid in seen_event:
            raise ContractError("duplicate_or_missing_event_id")
        seen_event.add(eid)
        if event.get("sequence") != seq:
            raise ContractError("bad_sequence")
        if kind not in KINDS:
            raise ContractError("unknown_event_kind")
        for field, value in (("tenant_id", tenant), ("request_id", request), ("correlation_id", correlation)):
            if event.get(field) != value:
                raise ContractError(f"{field}_mismatch")
        prov = event.get("provenance")
        if not isinstance(prov, dict) or not all(
            isinstance(prov.get(k), str) and prov[k] for k in
            ("source_component", "source_revision", "source_record_id")
        ):
            raise ContractError("missing_provenance")
        record_id = prov["source_record_id"]
        if record_id in seen_source:
            raise ContractError("duplicate_source_record_id")
        seen_source.add(record_id)
        by_kind[kind] += 1
        if kind == "decision":
            if event.get("authority_state") not in {"hold", "refused", "withdrawn"}:
                raise ContractError("decision_not_fail_closed")
            stages["decision_id"] = event.get("decision_id")
            if not stages["decision_id"]:
                raise ContractError("missing_decision_id")
        elif kind == "approval_withdrawal":
            if event.get("authority_state") != "withdrawn" or not event.get("approval_id"):
                raise ContractError("invalid_withdrawal")
        elif kind == "refusal":
            if event.get("refusal_state") != "refused" or not event.get("refusal_id"):
                raise ContractError("invalid_refusal")
        elif kind == "runtime_attempt":
            effect, attempt = event.get("effect_id"), event.get("attempt_id")
            if not effect or not attempt or effect in seen_effect or attempt in seen_attempt:
                raise ContractError("duplicate_or_missing_runtime_identity")
            seen_effect.add(effect); seen_attempt.add(attempt)
            if event.get("execution_state") not in {"refused", "not_dispatched", "cancelled"}:
                raise ContractError("unsupported_runtime_state")
        elif kind == "transport_receipt":
            if not event.get("receipt_id") or event.get("receipt_state") not in {"received", "not_sent", "cancelled"}:
                raise ContractError("invalid_receipt")
            if "settlement_id" in event or event.get("settlement") in {"settled", "completed"}:
                raise ContractError("receipt_claims_settlement")
        elif kind == "effect_observation":
            if not event.get("observer_id") or event.get("observed_effect") not in {"not_observed", "unknown"}:
                raise ContractError("invalid_effect_observation")
        elif kind == "settlement_observation":
            if not event.get("observer_id") or event.get("settlement") != "not_observed" or event.get("independent") is not True or "settlement_id" in event:
                raise ContractError("unfounded_settlement")
    if by_kind["decision"] != 1 or by_kind["settlement_observation"] != 1:
        raise ContractError("incomplete_decision_or_settlement_observation")
    return {
        "trace_id": source["trace_id"], "request_id": request,
        "tenant_id": tenant, "correlation_id": correlation,
        "event_counts": dict(by_kind),
        "source_provenance": "producer_reported_not_issuer_verified",
        "institutional_grant": "not_established",
        "independent_effect_verification": False,
        "settlement": "not_observed",
    }


def compare_connected_boundaries(handoff: dict[str, Any], replay: dict[str, Any]) -> dict[str, Any]:
    """Do not claim a common execution from independently authored fixtures."""
    if handoff.get("decision_state") == "hold" and handoff.get("attempt_id") is None:
        if replay.get("event_counts", {}).get("runtime_attempt", 0):
            return {"compatible_semantics": True, "same_trajectory_proven": False,
                    "reason": "synthetic_replay_attempt_not_linked_to_hold_handoff"}
    return {"compatible_semantics": True, "same_trajectory_proven": False,
            "reason": "source_generated_correlation_not_yet_demonstrated"}
