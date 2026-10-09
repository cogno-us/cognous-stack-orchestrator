"""Deterministic synthetic refund trajectory reconstruction.

This module is development-only. It reconstructs supplied synthetic records; it
does not authorize a refund, dispatch an effect, contact a payment processor, or
verify settlement.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from copy import deepcopy
from typing import Any

REPLAY_REVISION = "2069a0ba1398812c3a8669331a7d8b87c80c4a48"
EVIDENCE_PACK_REVISION = "87293cfcbe8dfa2368d5bf77019945ba8ef1ae71"
RECONSTRUCTION_BUNDLE_VERSION = "0.2.0"
EVIDENCE_PACK_VERSION = "0.2.0"
CANONICALIZATION = "json-sort-keys-compact-utf8-no-nan"

_ALLOWED_KINDS = {
    "intake",
    "policy_screen",
    "hold",
    "denial",
    "approval_withdrawal",
    "duplicate_suppressed",
    "transport_receipt",
    "runtime_refusal",
    "execution_intent_accepted",
    "settlement_status",
}
_DECISION_KINDS = {"hold", "denial", "approval_withdrawal"}
_EFFECT_KINDS = {"runtime_refusal", "execution_intent_accepted"}


class ReplayContractError(ValueError):
    """Synthetic trajectory violates the bounded replay contract."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _need_text(event: dict[str, Any], name: str) -> str:
    value = event.get(name)
    if not isinstance(value, str) or not value:
        raise ReplayContractError(f"{event.get('event_id', '<unknown>')}: missing_{name}")
    return value


def _validate_event(event: Any, index: int, tenant_id: str, request_id: str) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ReplayContractError(f"event[{index}]: not_object")
    event = deepcopy(event)
    _need_text(event, "event_id")
    kind = _need_text(event, "kind")
    if kind not in _ALLOWED_KINDS:
        raise ReplayContractError(f"{event['event_id']}: unsupported_kind")
    if event.get("sequence") != index:
        raise ReplayContractError(f"{event['event_id']}: non_deterministic_sequence")
    if event.get("tenant_id") != tenant_id:
        raise ReplayContractError(f"{event['event_id']}: tenant_mismatch")
    if event.get("request_id") != request_id:
        raise ReplayContractError(f"{event['event_id']}: request_mismatch")
    _need_text(event, "recorded_at")
    source = event.get("source")
    if not isinstance(source, dict):
        raise ReplayContractError(f"{event['event_id']}: missing_source")
    if source.get("evidence_class") not in {
        "producer_reported",
        "locally_generated",
        "independently_checked",
    }:
        raise ReplayContractError(f"{event['event_id']}: invalid_evidence_class")
    _need_text(source, "reference")

    if kind == "transport_receipt":
        _need_text(event, "transport_id")
        if any(k in event for k in ("effect_id", "attempt_id", "settlement_id")):
            raise ReplayContractError(f"{event['event_id']}: transport_cannot_assert_effect")

    if kind in _DECISION_KINDS:
        _need_text(event, "decision_id")
        _need_text(event, "policy_version")

    if kind == "approval_withdrawal" and event.get("authority_state") != "withdrawn":
        raise ReplayContractError(f"{event['event_id']}: withdrawal_state_required")

    if kind == "duplicate_suppressed":
        _need_text(event, "duplicate_of_request_id")
        if event["duplicate_of_request_id"] == request_id:
            raise ReplayContractError(f"{event['event_id']}: duplicate_requires_prior_request")
        if any(k in event for k in ("effect_id", "attempt_id")):
            raise ReplayContractError(f"{event['event_id']}: duplicate_cannot_assert_effect")

    if kind in _EFFECT_KINDS:
        _need_text(event, "effect_id")
        _need_text(event, "attempt_id")
        if event.get("simulation") is not True:
            raise ReplayContractError(f"{event['event_id']}: effect_reference_must_be_simulated")
        if kind == "runtime_refusal" and event.get("execution_state") != "refused":
            raise ReplayContractError(f"{event['event_id']}: refusal_state_required")
        if kind == "execution_intent_accepted" and event.get("execution_state") != "intent_accepted":
            raise ReplayContractError(f"{event['event_id']}: intent_state_required")

    if kind == "settlement_status":
        # This bounded synthetic qualification never accepts positive settlement
        # evidence. A future operational profile must supply independently
        # authenticated destination observation under a separately reviewed task.
        if event.get("settlement") != "not_observed":
            raise ReplayContractError(f"{event['event_id']}: settlement_evidence_out_of_scope")
        if any(k in event for k in ("effect_id", "attempt_id", "settlement_id")):
            raise ReplayContractError(f"{event['event_id']}: settlement_reference_forbidden")

    return event


def reconstruct_trajectory(trajectory: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic reconstruction and review projection."""
    if not isinstance(trajectory, dict):
        raise ReplayContractError("trajectory_not_object")
    trajectory_id = _need_text(trajectory, "trajectory_id")
    tenant_id = _need_text(trajectory, "tenant_id")
    request_id = _need_text(trajectory, "request_id")
    events = trajectory.get("events")
    if not isinstance(events, list) or not events:
        raise ReplayContractError("events_required")

    validated = [_validate_event(e, i, tenant_id, request_id) for i, e in enumerate(events)]
    ids = [e["event_id"] for e in validated]
    if len(ids) != len(set(ids)):
        raise ReplayContractError("duplicate_event_id")
    if validated[0]["kind"] != "intake":
        raise ReplayContractError("first_event_must_be_intake")

    records = []
    decision_refs = []
    transport_refs = []
    effect_refs = []
    issuer_claims = []
    duplicate_refs = []

    for event in validated:
        kind = event["kind"]
        records.append({
            "record_id": event["event_id"],
            "producer_profile_id": "cognous-refund-synthetic-v1",
            "record_type": kind,
            "source_sequence": event["sequence"],
            "source_path": f"events[{event['sequence']}]",
            "recorded_at": event["recorded_at"],
            "identifiers": {
                "tenant_id": tenant_id,
                "request_id": request_id,
            },
            "evidence_class": event["source"]["evidence_class"],
            "data": deepcopy(event),
        })
        if kind == "intake" and "issuer_state" in event:
            issuer_claims.append({
                "state": event["issuer_state"],
                "source_reference": event["source"]["reference"],
                "evidence_class": event["source"]["evidence_class"],
            })
        if kind in _DECISION_KINDS:
            decision_refs.append({
                "decision_id": event["decision_id"],
                "decision": kind,
                "policy_version": event["policy_version"],
                "source_reference": event["source"]["reference"],
            })
        if kind == "transport_receipt":
            transport_refs.append({
                "transport_id": event["transport_id"],
                "source_reference": event["source"]["reference"],
                "meaning": "receipt_only_not_authorization_or_effect",
            })
        if kind in _EFFECT_KINDS:
            effect_refs.append({
                "effect_id": event["effect_id"],
                "attempt_id": event["attempt_id"],
                "execution_state": event["execution_state"],
                "simulation": True,
                "source_reference": event["source"]["reference"],
                "settlement": "not_observed",
            })
        if kind == "duplicate_suppressed":
            duplicate_refs.append({
                "duplicate_of_request_id": event["duplicate_of_request_id"],
                "source_reference": event["source"]["reference"],
                "effect_created": False,
            })

    final_decision = decision_refs[-1]["decision"] if decision_refs else "none_recorded"
    if any(e["kind"] == "runtime_refusal" for e in validated):
        effect_state = "refused"
    elif any(e["kind"] == "execution_intent_accepted" for e in validated):
        effect_state = "simulated_intent_accepted"
    else:
        effect_state = "none_recorded"

    core = {
        "bundle_id": f"refund-replay:{trajectory_id}",
        "bundle_version": RECONSTRUCTION_BUNDLE_VERSION,
        "run_id": f"refund:{tenant_id}:{request_id}",
        "status": "reconstruction_complete",
        "generated_at": trajectory.get("generated_at", "2026-10-09T19:00:00Z"),
        "producer_profiles": [{
            "profile_id": "cognous-refund-synthetic-v1",
            "producer": "cognous-stack-orchestrator synthetic refund fixture",
            "repository": "cogno-us/cognous-stack-orchestrator",
            "revision": "0aaaa11d1795e4e0cbf081826e9e1d1b3d5ca850",
            "format_name": "customer-refund-trajectory",
            "format_version": "1.0.0",
            "schema_ref": None,
            "notes": "Synthetic offline qualification only; no payment processor or institutional grant.",
        }],
        "records": records,
        "links": [],
        "commitments": [],
        "import_reports": [],
        "semantics": {
            "record_reconstruction": True,
            "policy_reevaluation": False,
            "model_reexecution": False,
            "external_effect_execution": False,
            "destination_observation": "not_performed",
            "independent_effect_verification": False,
            "notes": "Offline reconstruction only; authorization is not renewed and settlement is not verified.",
        },
        "derivation": None,
        "integrity": [],
        "metadata": {
            "scenario": "customer_refund",
            "trajectory_id": trajectory_id,
            "tenant_id": tenant_id,
            "request_id": request_id,
            "source_replay_revision": REPLAY_REVISION,
            "source_evidence_pack_revision": EVIDENCE_PACK_REVISION,
        },
    }
    core["metadata"]["content_digest"] = _digest(core)

    return {
        "reconstruction_bundle": core,
        "evidence_projection": {
            "projection_version": "refund-evidence-projection/1.0.0",
            "pack_version_target": EVIDENCE_PACK_VERSION,
            "review_status": "draft",
            "tenant_id": tenant_id,
            "request_id": request_id,
            "issuer_claims": issuer_claims,
            "transport_receipts": transport_refs,
            "decisions": decision_refs,
            "duplicate_suppressions": duplicate_refs,
            "effect_references": effect_refs,
            "effect_state": effect_state,
            "settlement_status": "not_observed",
            "settlement_evidence": [],
            "independent_verification": "not_performed",
            "limitations": [
                "synthetic_offline_fixture",
                "no_institutional_grant",
                "no_payment_dispatch",
                "no_destination_observation",
                "no_settlement_evidence",
            ],
        },
        "trajectory_summary": {
            "trajectory_id": trajectory_id,
            "final_decision": final_decision,
            "effect_state": effect_state,
            "settlement": "not_observed",
        },
        "compatibility": probe_upstream_contracts(core),
    }


def probe_upstream_contracts(reconstruction: dict[str, Any]) -> dict[str, Any]:
    """Best-effort local compatibility check without claiming unavailable validation.

    The scoped orchestrator CI intentionally has no third-party packages. If the
    pinned Replay package is present, validate the ReconstructionBundle model.
    Evidence Pack import requires a compatible manifest plus Replay artifact, so
    this worker records that dependency rather than manufacturing a pack.
    """
    replay = {
        "repository": "cogno-us/cognous-replay-bundle",
        "revision": REPLAY_REVISION,
        "contract": f"ReconstructionBundle/{RECONSTRUCTION_BUNDLE_VERSION}",
        "status": "not_executed_dependency_unavailable",
    }
    try:
        module = importlib.import_module("agent_replay_bundle")
        model = getattr(module, "ReconstructionBundle")
        model.model_validate(reconstruction)
        replay["status"] = "validated_with_installed_package"
    except ModuleNotFoundError:
        pass
    except Exception as exc:
        raise ReplayContractError(f"upstream_replay_validation_failed:{type(exc).__name__}") from exc

    evidence = {
        "repository": "cogno-us/cognous-governance-evidence-pack",
        "revision": EVIDENCE_PACK_REVISION,
        "contract": f"EvidencePack/{EVIDENCE_PACK_VERSION}",
        "status": "not_executed_requires_manifest_and_upstream_package",
        "meaning": "projection is review input only, not an EvidencePack validation result",
    }
    return {"replay": replay, "evidence_pack": evidence}
