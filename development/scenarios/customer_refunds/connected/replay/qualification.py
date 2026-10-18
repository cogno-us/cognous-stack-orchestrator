"""O5-E-B connected refund Replay/Evidence Pack qualification.

Consumes only synthetic connected traces and invokes the exact pinned upstream
Replay ReconstructionBundle and Evidence Pack model/validator. This module does
not authorize or execute refunds and cannot establish settlement.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

REPLAY_REPOSITORY = "cogno-us/cognous-replay-bundle"
REPLAY_REVISION = "c8e665bd1936e4da90f6a324b486a320934c4bff"
EVIDENCE_PACK_REPOSITORY = "cogno-us/cognous-governance-evidence-pack"
EVIDENCE_PACK_REVISION = "cde3f1f1cf517d5663afb33ce88c123aae779757"
RECONSTRUCTION_VERSION = "0.2.0"
EVIDENCE_PACK_VERSION = "0.2.0"
PRODUCER_PROFILE = "cognous-refund-o5-e-b-connected-v1"

class QualificationError(ValueError):
    pass

class UpstreamUnavailable(RuntimeError):
    pass

@dataclass(frozen=True)
class UpstreamModules:
    ReconstructionBundle: Any
    EvidencePack: Any
    validate_evidence_pack: Any

def _git_head(root: pathlib.Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise UpstreamUnavailable(f"cannot_read_git_head:{root}") from exc

def _require_checkout(env_name: str, expected_revision: str) -> pathlib.Path:
    raw = os.environ.get(env_name)
    if not raw:
        raise UpstreamUnavailable(f"missing_required_checkout:{env_name}")
    root = pathlib.Path(raw).resolve()
    if not (root / "src").is_dir():
        raise UpstreamUnavailable(f"missing_upstream_src:{env_name}:{root}")
    actual = _git_head(root)
    if actual != expected_revision:
        raise UpstreamUnavailable(
            f"wrong_upstream_revision:{env_name}:expected={expected_revision}:actual={actual}"
        )
    return root

def load_upstreams() -> UpstreamModules:
    replay_root = _require_checkout("COGNOUS_REPLAY_ROOT", REPLAY_REVISION)
    evidence_root = _require_checkout("COGNOUS_EVIDENCE_PACK_ROOT", EVIDENCE_PACK_REVISION)
    for src in (replay_root / "src", evidence_root / "src"):
        value = str(src)
        if value not in sys.path:
            sys.path.insert(0, value)
    replay = importlib.import_module("agent_replay_bundle.reconstruction")
    models = importlib.import_module("agent_governance_evidence_pack.models")
    validator = importlib.import_module("agent_governance_evidence_pack.validator")
    return UpstreamModules(
        ReconstructionBundle=getattr(replay, "ReconstructionBundle"),
        EvidencePack=getattr(models, "EvidencePack"),
        validate_evidence_pack=getattr(validator, "validate_evidence_pack"),
    )

def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QualificationError(f"required_text:{path}")
    return value

def _provenance(event: dict[str, Any], path: str) -> dict[str, Any]:
    provenance = event.get("provenance")
    if not isinstance(provenance, dict):
        raise QualificationError(f"missing_provenance:{path}")
    _text(provenance.get("source_component"), f"{path}.provenance.source_component")
    _text(provenance.get("source_revision"), f"{path}.provenance.source_revision")
    _text(provenance.get("source_record_id"), f"{path}.provenance.source_record_id")
    return provenance

def validate_connected_trace(source: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(source, dict):
        raise QualificationError("trace_not_object")
    tenant_id = _text(source.get("tenant_id"), "tenant_id")
    correlation_id = _text(source.get("correlation_id"), "correlation_id")
    request_id = _text(source.get("request_id"), "request_id")
    _text(source.get("trace_id"), "trace_id")
    events = source.get("events")
    if not isinstance(events, list) or not events:
        raise QualificationError("events_required")

    allowed = {
        "request", "screening", "decision", "approval_withdrawal", "refusal",
        "runtime_attempt", "transport_receipt", "effect_observation",
        "settlement_observation",
    }
    seen_event_ids: set[str] = set()
    seen_source_record_ids: set[str] = set()
    seen_effect_ids: set[str] = set()
    seen_attempt_ids: set[str] = set()
    authority_withdrawn = False
    validated: list[dict[str, Any]] = []

    for sequence, raw in enumerate(events):
        if not isinstance(raw, dict):
            raise QualificationError(f"event_not_object:{sequence}")
        event = deepcopy(raw)
        event_id = _text(event.get("event_id"), f"events[{sequence}].event_id")
        if event_id in seen_event_ids:
            raise QualificationError(f"duplicate_event_id:{event_id}")
        seen_event_ids.add(event_id)
        if event.get("sequence") != sequence:
            raise QualificationError(f"non_deterministic_sequence:{event_id}")
        if event.get("tenant_id") != tenant_id:
            raise QualificationError(f"tenant_mismatch:{event_id}")
        if event.get("correlation_id") != correlation_id:
            raise QualificationError(f"correlation_mismatch:{event_id}")
        if event.get("request_id") != request_id:
            raise QualificationError(f"request_mismatch:{event_id}")

        kind = event.get("kind")
        if kind not in allowed:
            raise QualificationError(f"unsupported_kind:{event_id}:{kind}")
        provenance = _provenance(event, event_id)
        source_record_id = provenance["source_record_id"]
        if source_record_id in seen_source_record_ids:
            raise QualificationError(f"duplicate_source_record_id:{source_record_id}")
        seen_source_record_ids.add(source_record_id)

        if kind == "decision":
            _text(event.get("decision_id"), f"{event_id}.decision_id")
            if event.get("authority_state") not in {"hold", "refused", "withdrawn"}:
                raise QualificationError(f"decision_must_fail_closed:{event_id}")
        elif kind == "approval_withdrawal":
            _text(event.get("approval_id"), f"{event_id}.approval_id")
            if event.get("authority_state") != "withdrawn":
                raise QualificationError(f"withdrawal_state_invalid:{event_id}")
            authority_withdrawn = True
        elif kind == "refusal":
            _text(event.get("refusal_id"), f"{event_id}.refusal_id")
            if event.get("refusal_state") != "refused":
                raise QualificationError(f"refusal_state_invalid:{event_id}")
        elif kind == "runtime_attempt":
            effect_id = _text(event.get("effect_id"), f"{event_id}.effect_id")
            attempt_id = _text(event.get("attempt_id"), f"{event_id}.attempt_id")
            if effect_id in seen_effect_ids:
                raise QualificationError(f"duplicate_effect_id:{effect_id}")
            if attempt_id in seen_attempt_ids:
                raise QualificationError(f"duplicate_attempt_id:{attempt_id}")
            seen_effect_ids.add(effect_id)
            seen_attempt_ids.add(attempt_id)
            if event.get("execution_state") not in {"refused", "not_dispatched", "cancelled"}:
                raise QualificationError(f"runtime_attempt_not_fail_closed:{event_id}")
            if authority_withdrawn and event.get("execution_state") not in {"refused", "not_dispatched", "cancelled"}:
                raise QualificationError(f"execution_after_withdrawal:{event_id}")
        elif kind == "transport_receipt":
            _text(event.get("receipt_id"), f"{event_id}.receipt_id")
            if event.get("receipt_state") not in {"received", "not_sent", "cancelled"}:
                raise QualificationError(f"receipt_state_invalid:{event_id}")
            if "settlement_id" in event or event.get("settlement") in {"settled", "completed"}:
                raise QualificationError(f"receipt_cannot_assert_settlement:{event_id}")
        elif kind == "effect_observation":
            _text(event.get("observer_id"), f"{event_id}.observer_id")
            if event.get("observed_effect") not in {"not_observed", "unknown"}:
                raise QualificationError(f"effect_observation_out_of_scope:{event_id}")
        elif kind == "settlement_observation":
            _text(event.get("observer_id"), f"{event_id}.observer_id")
            if event.get("settlement") != "not_observed":
                raise QualificationError(f"false_settlement_claim:{event_id}")
            if event.get("independent") is not True:
                raise QualificationError(f"settlement_observer_not_independent:{event_id}")
            if "settlement_id" in event:
                raise QualificationError(f"settlement_identifier_without_observation:{event_id}")

        validated.append(event)
    return validated

def _reconstruction(source: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    records = []
    for event in events:
        records.append({
            "record_id": event["event_id"],
            "producer_profile_id": PRODUCER_PROFILE,
            "record_type": event["kind"],
            "source_sequence": event["sequence"],
            "source_path": f"events[{event['sequence']}]",
            "recorded_at": event.get("recorded_at"),
            "identifiers": {
                "tenant_id": source["tenant_id"],
                "correlation_id": source["correlation_id"],
                "request_id": source["request_id"],
            },
            "evidence_class": "producer_reported",
            "data": deepcopy(event),
        })
    return {
        "bundle_id": f"refund-o5-e-b:{source['trace_id']}",
        "bundle_version": RECONSTRUCTION_VERSION,
        "run_id": f"refund:{source['tenant_id']}:{source['correlation_id']}",
        "status": "reconstruction_complete",
        "generated_at": source.get("generated_at"),
        "producer_profiles": [{
            "profile_id": PRODUCER_PROFILE,
            "producer": "cognous-stack-orchestrator O5-E-B connected synthetic refund trace",
            "repository": "cogno-us/cognous-stack-orchestrator",
            "revision": "issue-57-worker-output",
            "format_name": "connected-refund-trace",
            "format_version": "provisional-o5-e-b-v1",
            "schema_ref": None,
            "notes": "Provisional issue-57 trace contract; requires Governor reconciliation with issue #58.",
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
            "destination_observation": "producer_reported",
            "independent_effect_verification": False,
            "notes": "Authorization, refusal, runtime attempt, transport receipt, effect observation and settlement observation remain distinct.",
        },
        "derivation": None,
        "integrity": [],
        "metadata": {
            "scenario": "connected_synthetic_customer_refund",
            "tenant_id": source["tenant_id"],
            "correlation_id": source["correlation_id"],
            "request_id": source["request_id"],
            "replay_revision": REPLAY_REVISION,
            "evidence_pack_revision": EVIDENCE_PACK_REVISION,
            "settlement": "not_observed",
            "independent_effect_verification": "not_performed",
        },
    }

def _pack(source: dict[str, Any], reconstruction: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_kind.setdefault(event["kind"], []).append(event)
    return {
        "pack_id": f"agep-refund-o5-e-b:{source['trace_id']}",
        "pack_version": EVIDENCE_PACK_VERSION,
        "title": "O5-E-B connected synthetic refund evidence qualification",
        "generated_at": source.get("generated_at") or "2026-10-09T20:00:00Z",
        "review_status": "draft",
        "agent_overview": {
            "agent_name": "Synthetic Refund Agent",
            "business_purpose": "Qualify connected trace evidence boundaries without moving funds.",
        },
        "deployment_context": {
            "environment": "sandbox",
            "deployment_name": "o5-e-b-connected-refund",
            "systems_touched": [],
            "data_domains": [],
            "notes": "Synthetic offline sandbox fixture only; no live processor, credentials, grants, payment effect or verified settlement.",
        },
        "tool_inventory": [],
        "action_inventory": [],
        "policy_controls": [],
        "blocked_actions": [],
        "reliance_summary": [],
        "replay_bundles": [{
            "bundle_id": reconstruction["bundle_id"],
            "run_id": reconstruction["run_id"],
            "status": reconstruction["status"],
            "generated_at": reconstruction.get("generated_at"),
            "signed": False,
            "redacted": False,
            "validation_status": "parsed_by_exact_pinned_replay_model",
            "evidence_reference": "metadata.o5_e_b_connected.reconstruction_bundle",
        }],
        "validation_summary": {
            "valid_bundle_count": 1,
            "invalid_bundle_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "summary": "Exact-pinned Replay/Evidence Pack interfaces executed; settlement remains not observed.",
        },
        "metadata": {
            "o5_e_b_connected": {
                "replay_revision": REPLAY_REVISION,
                "evidence_pack_revision": EVIDENCE_PACK_REVISION,
                "reconstruction_bundle": reconstruction,
                "trace_id": source["trace_id"],
                "source_nature": "synthetic_connected_trace",
                "tenant_id": source["tenant_id"],
                "correlation_id": source["correlation_id"],
                "request_id": source["request_id"],
                "event_refs_by_kind": {k: [e["event_id"] for e in v] for k, v in sorted(by_kind.items())},
                "settlement": "not_observed",
                "independent_effect_verification": False,
                "limitations": [
                    "synthetic_connected_trace_only",
                    "provisional_issue_57_trace_shape_pending_issue_58_reconciliation",
                    "no_real_funds",
                    "no_payment_credentials",
                    "no_institutional_grants",
                    "no_independently_verified_settlement",
                ],
            }
        },
    }

def qualify_connected_trace(source: dict[str, Any]) -> dict[str, Any]:
    upstream = load_upstreams()
    events = validate_connected_trace(source)
    reconstruction_model = upstream.ReconstructionBundle.model_validate(_reconstruction(source, events))
    reconstruction = reconstruction_model.model_dump(mode="json")
    pack_model = upstream.EvidencePack.model_validate(_pack(source, reconstruction, events))
    report = upstream.validate_evidence_pack(pack_model)
    if not report.valid:
        errors = [
            issue.code for issue in report.issues
            if getattr(issue.severity, "value", issue.severity) == "error"
        ]
        raise QualificationError("upstream_evidence_pack_validation_failed:" + ",".join(errors))
    return {
        "source_revisions": {"replay": REPLAY_REVISION, "evidence_pack": EVIDENCE_PACK_REVISION},
        "reconstruction": reconstruction,
        "evidence_pack": pack_model.model_dump(mode="json"),
        "evidence_pack_validation": report.model_dump(mode="json"),
        "boundary_summary": {
            "authorization": [e.get("authority_state") for e in events if e["kind"] in {"decision", "approval_withdrawal"}],
            "refusal": [e.get("refusal_state") for e in events if e["kind"] == "refusal"],
            "runtime_attempt": [e.get("execution_state") for e in events if e["kind"] == "runtime_attempt"],
            "transport_receipt": [e.get("receipt_state") for e in events if e["kind"] == "transport_receipt"],
            "effect_observation": [e.get("observed_effect") for e in events if e["kind"] == "effect_observation"],
            "settlement": [e.get("settlement") for e in events if e["kind"] == "settlement_observation"],
            "independent_effect_verification": False,
        },
    }
