"""O5-D-C qualification against exact pinned Replay and Evidence Pack sources."""

from __future__ import annotations

import importlib
import json
import os
import pathlib
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

REPLAY_REPOSITORY = "cogno-us/cognous-replay-bundle"
REPLAY_REVISION = "2069a0ba1398812c3a8669331a7d8b87c80c4a48"
EVIDENCE_PACK_REPOSITORY = "cogno-us/cognous-governance-evidence-pack"
EVIDENCE_PACK_REVISION = "87293cfcbe8dfa2368d5bf77019945ba8ef1ae71"
RECONSTRUCTION_VERSION = "0.2.0"
EVIDENCE_PACK_VERSION = "0.2.0"


class QualificationError(ValueError):
    """The synthetic trajectory violates the bounded qualification contract."""


class UpstreamUnavailable(RuntimeError):
    """A required exact-pinned upstream checkout is missing or at the wrong revision."""


@dataclass(frozen=True)
class UpstreamModules:
    ReconstructionBundle: Any
    EvidencePack: Any
    validate_evidence_pack: Any


def _git_head(root: pathlib.Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, stderr=subprocess.STDOUT
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
    evidence_models = importlib.import_module("agent_governance_evidence_pack.models")
    evidence_validator = importlib.import_module("agent_governance_evidence_pack.validator")
    return UpstreamModules(
        ReconstructionBundle=getattr(replay, "ReconstructionBundle"),
        EvidencePack=getattr(evidence_models, "EvidencePack"),
        validate_evidence_pack=getattr(evidence_validator, "validate_evidence_pack"),
    )


def _need_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QualificationError(f"required_text:{path}")
    return value


def _validate_trajectory(source: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(source, dict):
        raise QualificationError("trajectory_not_object")
    tenant_id = _need_text(source.get("tenant_id"), "tenant_id")
    request_id = _need_text(source.get("request_id"), "request_id")
    events = source.get("events")
    if not isinstance(events, list) or not events:
        raise QualificationError("events_required")

    allowed = {
        "intake", "authorization", "denial", "transport_receipt", "duplicate_suppressed",
        "runtime_refusal", "execution_reference", "settlement_status",
    }
    seen_ids: set[str] = set()
    validated: list[dict[str, Any]] = []
    for sequence, raw in enumerate(events):
        if not isinstance(raw, dict):
            raise QualificationError(f"event_not_object:{sequence}")
        event = deepcopy(raw)
        event_id = _need_text(event.get("event_id"), f"events[{sequence}].event_id")
        if event_id in seen_ids:
            raise QualificationError("duplicate_event_id")
        seen_ids.add(event_id)
        if event.get("sequence") != sequence:
            raise QualificationError(f"non_deterministic_sequence:{event_id}")
        if event.get("tenant_id") != tenant_id:
            raise QualificationError(f"tenant_mismatch:{event_id}")
        if event.get("request_id") != request_id:
            raise QualificationError(f"request_mismatch:{event_id}")
        kind = event.get("kind")
        if kind not in allowed:
            raise QualificationError(f"unsupported_kind:{event_id}:{kind}")
        if kind == "authorization":
            _need_text(event.get("decision_id"), f"{event_id}.decision_id")
            if event.get("authorization_state") not in {"held", "denied", "withdrawn"}:
                raise QualificationError(f"invalid_authorization_state:{event_id}")
        elif kind == "transport_receipt":
            _need_text(event.get("receipt_id"), f"{event_id}.receipt_id")
            if any(key in event for key in ("effect_id", "attempt_id", "settlement_id")):
                raise QualificationError(f"receipt_cannot_assert_effect_or_settlement:{event_id}")
        elif kind == "duplicate_suppressed":
            _need_text(event.get("duplicate_of_request_id"), f"{event_id}.duplicate_of_request_id")
            if any(key in event for key in ("effect_id", "attempt_id", "settlement_id")):
                raise QualificationError(f"duplicate_cannot_assert_effect_or_settlement:{event_id}")
        elif kind in {"runtime_refusal", "execution_reference"}:
            _need_text(event.get("effect_id"), f"{event_id}.effect_id")
            _need_text(event.get("attempt_id"), f"{event_id}.attempt_id")
            if event.get("simulation") is not True:
                raise QualificationError(f"execution_reference_must_be_simulated:{event_id}")
            expected = "refused" if kind == "runtime_refusal" else "intent_only"
            if event.get("execution_state") != expected:
                raise QualificationError(f"invalid_execution_state:{event_id}")
            if "settlement_id" in event:
                raise QualificationError(f"execution_reference_cannot_assert_settlement:{event_id}")
        elif kind == "settlement_status":
            if event.get("settlement") != "not_observed":
                raise QualificationError(f"settlement_evidence_out_of_scope:{event_id}")
            if any(key in event for key in ("effect_id", "attempt_id", "settlement_id")):
                raise QualificationError(f"settlement_reference_forbidden:{event_id}")
        validated.append(event)
    return validated


def _reconstruction(source: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    tenant_id = source["tenant_id"]
    request_id = source["request_id"]
    records = []
    for event in events:
        records.append(
            {
                "record_id": event["event_id"],
                "producer_profile_id": "cognous-refund-o5-d-c-synthetic-v1",
                "record_type": event["kind"],
                "source_sequence": event["sequence"],
                "source_path": f"events[{event['sequence']}]",
                "recorded_at": event.get("recorded_at"),
                "identifiers": {"tenant_id": tenant_id, "request_id": request_id},
                "evidence_class": "producer_reported",
                "data": deepcopy(event),
            }
        )
    return {
        "bundle_id": f"refund-o5-d-c:{source['trajectory_id']}",
        "bundle_version": RECONSTRUCTION_VERSION,
        "run_id": f"refund:{tenant_id}:{request_id}",
        "status": "reconstruction_complete",
        "generated_at": source.get("generated_at"),
        "producer_profiles": [
            {
                "profile_id": "cognous-refund-o5-d-c-synthetic-v1",
                "producer": "cognous-stack-orchestrator O5-D-C synthetic refund qualification",
                "repository": "cogno-us/cognous-stack-orchestrator",
                "revision": "issue-49-worker-fixture",
                "format_name": "refund-evidence-trajectory",
                "format_version": "1.0.0",
                "schema_ref": None,
                "notes": "Synthetic qualification only; no payment processor, credentials, grants, or settlement observation.",
            }
        ],
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
            "notes": "Receipt, authorization, execution reference, and settlement observation remain separate.",
        },
        "derivation": None,
        "integrity": [],
        "metadata": {
            "scenario": "synthetic_customer_refund",
            "tenant_id": tenant_id,
            "request_id": request_id,
            "replay_revision": REPLAY_REVISION,
            "evidence_pack_revision": EVIDENCE_PACK_REVISION,
            "settlement_observation": "not_performed",
            "independent_verification": "not_performed",
        },
    }


def _pack_dict(source: dict[str, Any], reconstruction: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    receipt_refs = [e["receipt_id"] for e in events if e["kind"] == "transport_receipt"]
    authorization_refs = [e["decision_id"] for e in events if e["kind"] == "authorization"]
    effect_refs = [
        {"effect_id": e["effect_id"], "attempt_id": e["attempt_id"], "state": e["execution_state"]}
        for e in events if e["kind"] in {"runtime_refusal", "execution_reference"}
    ]
    duplicates = [e["duplicate_of_request_id"] for e in events if e["kind"] == "duplicate_suppressed"]
    return {
        "pack_id": f"agep-refund-o5-d-c:{source['trajectory_id']}",
        "pack_version": EVIDENCE_PACK_VERSION,
        "title": "O5-D-C synthetic refund evidence qualification",
        "generated_at": source.get("generated_at") or "2026-10-09T19:00:00Z",
        "review_status": "draft",
        "agent_overview": {
            "agent_name": "Synthetic Refund Agent",
            "business_purpose": "Qualify evidence boundaries without moving funds.",
        },
        "deployment_context": {
            "environment": "sandbox",
            "deployment_name": "offline-o5-d-c",
            "systems_touched": [],
            "data_domains": [],
            "notes": "No live payment processor, credentials, institutional grants, or destination settlement observer.",
        },
        "tool_inventory": [],
        "action_inventory": [],
        "policy_controls": [],
        "blocked_actions": [],
        "reliance_summary": [],
        "replay_bundles": [
            {
                "bundle_id": reconstruction["bundle_id"],
                "run_id": reconstruction["run_id"],
                "status": reconstruction["status"],
                "generated_at": reconstruction.get("generated_at"),
                "signed": False,
                "redacted": False,
                "validation_status": "parsed_by_exact_pinned_replay_model",
                "evidence_reference": "metadata.o5_d_c_qualification.reconstruction_bundle",
            }
        ],
        "validation_summary": {
            "valid_bundle_count": 1,
            "invalid_bundle_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "summary": "Exact-pinned upstream parsers executed; no independent settlement or effect verification is claimed.",
        },
        "metadata": {
            "o5_d_c_qualification": {
                "replay_revision": REPLAY_REVISION,
                "evidence_pack_revision": EVIDENCE_PACK_REVISION,
                "reconstruction_bundle": reconstruction,
                "receipt_refs": receipt_refs,
                "authorization_refs": authorization_refs,
                "effect_refs": effect_refs,
                "duplicate_of_request_ids": duplicates,
                "settlement_observation": "not_performed",
                "independent_effect_verification": False,
                "receipt_semantics": "receipt_only_not_authorization_effect_or_settlement",
                "limitations": [
                    "synthetic_offline_qualification",
                    "no_real_funds",
                    "no_credentials",
                    "no_institutional_grants",
                    "no_destination_settlement_observer",
                    "does_not_exercise_manifest_reconstruction_transformer",
                ],
            }
        },
    }


def qualify_trajectory(source: dict[str, Any]) -> dict[str, Any]:
    upstream = load_upstreams()
    _need_text(source.get("trajectory_id") if isinstance(source, dict) else None, "trajectory_id")
    events = _validate_trajectory(source)
    reconstruction_input = _reconstruction(source, events)
    replay_model = upstream.ReconstructionBundle.model_validate(reconstruction_input)
    reconstruction = replay_model.model_dump(mode="json")

    pack_input = _pack_dict(source, reconstruction, events)
    pack = upstream.EvidencePack.model_validate(pack_input)
    report = upstream.validate_evidence_pack(pack)
    if not report.valid:
        codes = ",".join(issue.code for issue in report.issues if getattr(issue.severity, "value", issue.severity) == "error")
        raise QualificationError(f"upstream_evidence_pack_validation_failed:{codes}")

    return {
        "source_revisions": {
            "replay": REPLAY_REVISION,
            "evidence_pack": EVIDENCE_PACK_REVISION,
        },
        "reconstruction": reconstruction,
        "evidence_pack": pack.model_dump(mode="json"),
        "evidence_pack_validation": report.model_dump(mode="json"),
        "boundary_summary": {
            "receipts": [e["receipt_id"] for e in events if e["kind"] == "transport_receipt"],
            "authorization": [e.get("authorization_state") for e in events if e["kind"] == "authorization"],
            "effects": [e["execution_state"] for e in events if e["kind"] in {"runtime_refusal", "execution_reference"}],
            "duplicates_suppressed": sum(1 for e in events if e["kind"] == "duplicate_suppressed"),
            "settlement": "not_observed",
            "independent_effect_verification": False,
        },
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: qualification.py TRAJECTORY.json")
    source = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(qualify_trajectory(source), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
