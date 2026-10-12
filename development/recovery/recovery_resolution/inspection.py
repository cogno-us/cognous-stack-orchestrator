"""Optional read-only composition of native recovery inspection consumers."""
from __future__ import annotations

import json

COMPONENT_REVISIONS = {
    "runtime": "8e7d634cf0a22b6f3c1fc6d93afe92c7414fa243",
    "replay": "696e7bc2432fc7b5cf2d6e6c5f0b944b2d9a265f",
    "evidence_pack": "bc20a65c0452b85333f9b036853d77aad0b08964",
}
PRODUCER_PROFILE = "cognous-recovery-resolution/synthetic-0.1"
EXPORT_FORMAT = "cognous-recovery-inspection/synthetic-0.1"
RESULT_FORMAT = "cognous-recovery-inspection-chain/0.1"


class InspectionHold(ValueError):
    """An import/inspection HOLD, not a historical dispatch refusal."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__("HOLD: " + reason)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def inspect_recovery_export(snapshot, *, expected_identity, component_revisions):
    """Inspect a supplied Runtime export without database access or admission.

    Selection metadata is caller asserted. CI verifies loaded dependency sources;
    this function does not authenticate repository origin, actor, or destination.
    """
    try:
        if _json(component_revisions) != _json(COMPONENT_REVISIONS):
            raise InspectionHold("unsupported_component_revisions")
        source = json.loads(_json(snapshot))
        if not isinstance(source, dict) or source.get("profile") != PRODUCER_PROFILE or source.get("export_format") != EXPORT_FORMAT:
            raise InspectionHold("unsupported_producer_profile")
        from agent_replay_bundle.recovery_inspection import (
            import_recovery_inspection, validate_recovery_inspection,
        )
        from agent_governance_evidence_pack.recovery_inspection import (
            build_recovery_inspection_evidence, validate_recovery_inspection_evidence,
        )
        replay = import_recovery_inspection(source, runtime_revision=COMPONENT_REVISIONS["runtime"],
                                            expected_identity=expected_identity)
        validate_recovery_inspection(replay)
        evidence = build_recovery_inspection_evidence(replay, replay_revision=COMPONENT_REVISIONS["replay"],
                                                       expected_identity=expected_identity)
        validate_recovery_inspection_evidence(evidence)
        if _json(evidence["replay_inspection"]["source"]) != _json(source):
            raise InspectionHold("source_retention_mismatch")
        if _json(evidence["loss_report"]) != _json(replay["loss_report"]):
            raise InspectionHold("loss_report_mismatch")
        gaps = evidence["loss_report"]["unavailable_evidence"]
        status = "inspected_with_unavailable_evidence" if gaps else "inspected_retained_records"
        return {
            "format": RESULT_FORMAT,
            "inspection_status": status,
            "component_revisions": dict(COMPONENT_REVISIONS),
            "revision_assurance": "caller_selected_not_authenticated",
            "evidence": evidence,
            "limitations": ["read_only_supplied_snapshot", "synthetic_only", "no_retry_or_execution_authority",
                            "no_source_authentication", "no_independent_settlement_verification",
                            "no_fresh_destination_observation", "no_release_adoption"],
        }
    except InspectionHold:
        raise
    except ImportError as exc:
        raise InspectionHold("native_consumer_unavailable") from exc
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        # No raw source payload or detailed downstream exception is logged here.
        raise InspectionHold("invalid_or_inconsistent_inspection") from exc


def validate_inspection_chain(result):
    """Validate the entire retained chain through the actual native consumers."""
    try:
        evidence = result["evidence"]
        rebuilt = inspect_recovery_export(evidence["replay_inspection"]["source"],
            expected_identity=evidence["original_identity"], component_revisions=result["component_revisions"])
        if _json(result) != _json(rebuilt):
            raise InspectionHold("derived_chain_mismatch")
    except InspectionHold:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise InspectionHold("malformed_inspection_chain") from exc
