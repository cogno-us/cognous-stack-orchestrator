"""Probe Replay and the Evidence Pack importer with the run records the overlay produced (report only).

A runner, not a test (subprocess). Reads bundle directories (run-record.json, proposal.json, manifest.json), calls
`agent_replay_bundle.importers.import_bounded_workflow` under each stated Control Plane revision label, and passes an accepted
bundle to `agent_governance_evidence_pack.importer.build_evidence_pack_from_artifacts`.

    COGNOUS_REPLAY_SRC=<replay>/src COGNOUS_EVIDENCE_PACK_SRC=<pack>/src COGNOUS_CANDIDATE_CONTROL_PLANE_REVISION=<sha> \
        python tests/overlay/_replay_runner.py OUT.json BUNDLE_DIR [BUNDLE_DIR ...]

Replay selects its profile from the revision label it is given; the label is a claim by the caller, not something Replay derives
from the record. The probe therefore reports, per record, the outcome under every label Replay supports and under the candidate's
own revision (which Replay does not list).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, os.environ["COGNOUS_REPLAY_SRC"])
sys.path.insert(0, os.environ["COGNOUS_EVIDENCE_PACK_SRC"])
from agent_governance_evidence_pack import importer as pack  # noqa: E402
from agent_replay_bundle import importers as replay  # noqa: E402


def outcome(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def labels() -> dict[str, str]:
    supported = [replay.CONTROL_PLANE_REVISION, *replay.CONTROL_PLANE_SUPPORTED_V2_REVISIONS]
    out = {r[:8]: r for r in supported}
    out["candidate:" + os.environ["COGNOUS_CANDIDATE_CONTROL_PLANE_REVISION"][:8]] = os.environ["COGNOUS_CANDIDATE_CONTROL_PLANE_REVISION"]
    return out


def probe(bundle: pathlib.Path) -> dict:
    record = json.loads((bundle / "run-record.json").read_text())
    proposal = json.loads((bundle / "proposal.json").read_text())
    manifest = json.loads((bundle / "manifest.json").read_text())
    per_label, accepted_bundle = {}, None
    for name, rev in labels().items():
        try:
            built = replay.import_bounded_workflow(record, proposal=proposal, control_plane_revision=rev)
            per_label[name] = "accepted"
            # The Evidence Pack pairs each Replay bundle with the Replay revision of its own generation (P4 -> 9aab3f6c, programme 2 ->
            # 2a7963b1) and refuses a bundle whose generation does not match the installed Replay. The installed Replay is 2a7963b1, so the
            # bundle handed to the pack is the one built under the programme-2 label (CONTROL_PLANE_P2_REVISION), the label this Replay pairs
            # with; the P4-labelled bundle can no longer be imported by the pack. Replay's own per-label outcomes are still reported for all labels.
            if rev == replay.CONTROL_PLANE_P2_REVISION:
                accepted_bundle = (name, built)
        except Exception as exc:  # noqa: BLE001 - the probe records every outcome
            per_label[name] = outcome(exc)
    result: dict = {"replay_by_label": per_label, "accepted_under": [k for k, v in per_label.items() if v == "accepted"]}
    if accepted_bundle is not None:
        name, built = accepted_bundle
        dumped = json.loads(json.dumps(built.model_dump(mode="json"), default=str))
        text = json.dumps(dumped)
        result["replay_label_used_for_pack"] = name
        result["replay_findings_under_p4"] = sorted({f"{f.get('code')}:{f.get('path')}" for rep in dumped.get("import_reports", [])
                                                    for f in rep.get("findings", [])})
        result["retained"] = {
            "rule_revisions_rows": bool(record.get("rule_revisions")) and "adopt-1" in text,
            "rule_identity_on_decisions": "rule_identity" in text,
            "attempt_joins_rows": bool(record.get("attempt_joins")) and any(j.get("join_id", "x") in text for j in record.get("attempt_joins", [])),
            "check_events_deadline": '"deadline"' in text,
        }
        try:
            built_pack = pack.build_evidence_pack_from_artifacts(manifest, dumped)
            meta = built_pack.metadata.get("traceable_import", {}) if hasattr(built_pack, "metadata") else {}
            result["evidence_pack"] = {"outcome": "accepted", "freshness_block": "freshness_summary" in meta}
        except Exception as exc:  # noqa: BLE001
            result["evidence_pack"] = {"outcome": outcome(exc), "freshness_block": False}
    return result


def main() -> None:
    out = pathlib.Path(sys.argv[1])
    results = {}
    for raw in sys.argv[2:]:
        b = pathlib.Path(raw)
        results[f"{b.parent.name}/{b.name}"] = probe(b)
    out.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
