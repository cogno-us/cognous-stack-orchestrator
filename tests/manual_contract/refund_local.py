"""One bounded, nonproduction refund demonstration adapter.

This is a NEW selected-case implementation, not a modification of the frozen
C1-C4 harness. It has no workflow or automatic trigger. Calls a file-only
synthetic destination. This source file has not been qualified as safe for any
payment provider, tenant-aware Runtime effect, or production request.

The Architect must separately authorize the first composed current-pin run.
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import sys
import tempfile

sys.dont_write_bytecode = True

import real_c4  # existing exact-source C4 gate, loader and native boundary helpers
import refund_producer

SCHEMA = "cognous.orchestrator.synthetic-refund/0-draft"
ODES_SHA = "1e2261289e8ff8e862b697f5c7afcf7007453787"
ODES_TREE = "e0589cfe6a4ce6c558b0d8644f446cd2898a1362"
SCENARIOS = (("authorized", "authorized"), ("grant_revoked", "hold"))


class RefundAdapterError(Exception):
    pass


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump(obj: object) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _load_odes(odes_root: pathlib.Path):
    """Fail closed unless a clean exact ODES checkout is loaded."""
    root = odes_root.resolve(strict=True)
    if real_c4._git(root, "rev-parse", "HEAD") != ODES_SHA:
        raise RefundAdapterError("ODES HEAD is not the pinned revision")
    if real_c4._git(root, "rev-parse", "HEAD^{tree}") != ODES_TREE:
        raise RefundAdapterError("ODES tree is not the pinned tree")
    if real_c4._git(root, "status", "--porcelain", "--untracked-files=no"):
        raise RefundAdapterError("ODES checkout has changed tracked files")
    for module in (root / "src" / "odes").rglob("*.py"):
        if module.is_symlink():
            raise RefundAdapterError("ODES symlink source refused")
    sys.path.insert(0, str(root / "src"))
    import odes
    if root not in pathlib.Path(odes.__file__).resolve().parents:
        raise RefundAdapterError("ODES package imported outside pinned checkout")
    return odes


def classify_native(decision: dict, record: dict, destination: dict, pack: dict, reliance: dict) -> dict:
    """Only native, retained observations can establish a *synthetic* outcome.

    Never promote a harness PASS or an acknowledgement alone to completed.
    ODES reliance is reported separately from CP and Pack evidence acceptance.
    """
    result = decision.get("result")
    binding = decision.get("binding")
    attempts = record.get("attempts") or []
    observations = record.get("observations") or []
    reconciliations = record.get("reconciliations") or []
    effects = destination.get("effects") or {}
    lifecycle = ((pack.get("metadata") or {}).get("traceable_import") or {}).get("lifecycle_summary") or {}
    decision_effect = decision.get("effect_id")
    if result == "hold":
        if binding is not None or attempts or effects:
            raise RefundAdapterError("HOLD has a binding, attempt or destination effect")
        standing = "HELD_NO_EFFECT"
    elif result == "authorized":
        if not isinstance(binding, dict) or not decision_effect:
            raise RefundAdapterError("authorized decision missing native binding or effect_id")
        good_attempt = any(x.get("effect_id") == decision_effect and x.get("status") == "acknowledged" for x in attempts)
        good_observation = any(
            x.get("effect_id") == decision_effect and x.get("state") == "applied" for x in observations
        )
        good_reconciliation = any(
            x.get("effect_id") == decision_effect and x.get("result") == "applied"
            and x.get("observation_accepted") is True for x in reconciliations
        )
        row = effects.get(decision_effect)
        if good_attempt and good_observation and good_reconciliation and isinstance(row, dict) and row.get("state") == "applied":
            standing = "SYNTHETIC_APPLIED_OBSERVED"
        else:
            standing = "AUTHORIZED_NOT_CONFIRMED_APPLIED"
    else:
        raise RefundAdapterError("unsupported Control Plane outcome")
    if result == "hold" and lifecycle.get("authorization") not in (None, "held"):
        raise RefundAdapterError("Pack disagrees with HOLD authorization")
    if result == "authorized" and lifecycle.get("authorization") not in (None, "authorized"):
        raise RefundAdapterError("Pack disagrees with native authorization")
    return {
        "decision": result,
        "effect_id": decision_effect,
        "synthetic_effect_standing": standing,
        "record_attempt_count": len(attempts),
        "record_observation_count": len(observations),
        "record_reconciliation_count": len(reconciliations),
        "local_destination_row_count": len(effects),
        "pack_lifecycle": lifecycle,
        "odes_recipient_reliance": (reliance.get("recipient_reliance_decision") or {}),
        "real_payment_effect": "NOT_ATTEMPTED",
        "independent_qualification": False,
    }


def prepare_local_synthetic(roots: dict[str, str], odes_root: str, *, workdir: str | None = None) -> dict:
    """Execute ONLY an explicitly invoked, bounded local synthetic scratch run.

    NOT used by a workflow and NOT invoked as part of this PR preparation.
    Python >=3.11 Linux, isolated (-I -B) process required.
    """
    if not sys.flags.isolated:
        raise RefundAdapterError("must run with python3 -I -B")
    if set(roots) != set(real_c4.BOUNDARIES):
        raise RefundAdapterError("four explicit source roots required; no default lock fallback")
    for k, v in roots.items():
        if not pathlib.Path(v).is_dir():
            raise RefundAdapterError("source checkout missing: " + k)
    # Source measurement occurs BEFORE any native call.
    ctx = real_c4._measure(roots)
    odes = _load_odes(pathlib.Path(odes_root))
    manifest_path = ctx["am_root"] / real_c4.MANIFEST_RELATIVE_PATH
    man_bytes, man_ok = real_c4._read_once(manifest_path, real_c4.FROZEN["manifest_file_sha256"], "manifest")
    prop_bytes, prop_ok = real_c4._read_once(real_c4.PROPOSAL_PATH, real_c4.FROZEN["proposal_sha256"], "proposal")
    gate, manifest, proposal = real_c4._am_gate(ctx, man_bytes, prop_bytes, man_ok, prop_ok)
    if not gate["passed"] or not isinstance(manifest, dict) or not isinstance(proposal, dict):
        raise RefundAdapterError("frozen Action Manifest gate did not pass")
    if workdir is not None:
        # Only NEW empty scratch directories under a temporary filesystem root.
        tmp_root = pathlib.Path(tempfile.gettempdir()).resolve()
        candidate = pathlib.Path(workdir).resolve()
        if tmp_root not in candidate.parents:
            raise RefundAdapterError("workdir must be below system tempdir")
        work = real_c4._fresh_workdir(candidate)
    else:
        work = real_c4._fresh_workdir()
    files = real_c4._Files(work)
    files.put("inputs/manifest.json", man_bytes)
    files.put("inputs/proposal.json", prop_bytes)
    result = {"schema": SCHEMA, "status": "DEVELOPER_OBSERVATION_UNQUALIFIED",
              "subject_sources": {k: v["sha"] for k, v in real_c4.PINS.items()},
              "odes_source": ODES_SHA, "synthetic_test_clock": str(refund_producer.NOW),
              "limitations": ["synthetic unauthenticated authority", "no payment integration",
                              "virtual test clock", "no Runtime effect", "partial Replay",
                              "no ODES-to-Pack edge", "no independently trusted ODES recipient policy"],
              "cases": {}}
    for scenario, expected in SCENARIOS:
        case_dir = work / scenario
        case_dir.mkdir()
        produced = refund_producer.produce(
            pathlib.Path(ctx["roots"]["control_plane"]), case_dir, copy.deepcopy(proposal), copy.deepcopy(manifest), scenario
        )
        decision = produced.decision
        if decision.get("result") != expected:
            raise RefundAdapterError("unexpected native CP decision for " + scenario)
        raw_record = produced.record_path.read_bytes()
        raw_dest = produced.destination_path.read_bytes()
        rec = real_c4._strict_loads(raw_record)
        dest = real_c4._strict_loads(raw_dest)
        files.put(scenario + "/cp-record.json", raw_record)
        files.put(scenario + "/destination.json", raw_dest)
        bundle, refused = real_c4._import_replay(
            ctx["P"]["importers"], rec, copy.deepcopy(proposal), ctx["revision_label"]
        )
        if refused is not None or bundle is None:
            raise RefundAdapterError("native Replay refused: " + str(refused))
        bundle_obj = bundle.model_dump(mode="json")
        files.put(scenario + "/replay-bundle.json", _dump(bundle_obj))
        pack, pack_refused = real_c4._import_pack(ctx["P"], manifest, bundle_obj)
        if pack_refused is not None or pack is None:
            raise RefundAdapterError("native Pack refused: " + str(pack_refused))
        report = ctx["P"]["pack_validator"].validate_evidence_pack(pack)
        pack_dict = pack.model_dump(mode="json")
        files.put(scenario + "/pack.json", _dump(pack_dict))
        files.put(scenario + "/pack-validation.json", _dump({
            "valid": report.valid, "issue_codes": [x.code for x in report.issues]
        }))
        package = odes.export_cognous_stack_package(copy.deepcopy(manifest), copy.deepcopy(bundle_obj))
        reliance = odes.evaluate_recipient_package(copy.deepcopy(package), {})
        files.put(scenario + "/odes-package.json", _dump(package))
        files.put(scenario + "/odes-reliance.json", _dump(reliance))
        native = classify_native(decision, rec, dest, pack_dict, reliance)
        native["replay_status"] = bundle.status
        native["pack_validation_valid"] = report.valid
        native["local_effect_call_trace"] = produced.provenance["calls"]
        native["local_effect_observation"] = produced.local_effect
        result["cases"][scenario] = native
    # It is never permitted for a held scenario to share the authorized effect ID.
    if result["cases"]["authorized"]["effect_id"] == result["cases"]["grant_revoked"]["effect_id"]:
        raise RefundAdapterError("two independent synthetic decisions shared an effect ID")
    files.put("source-observations.json", _dump(result))
    files.put("SHA256SUMS.json", _dump(files.hashes))
    real_c4._recheck(ctx)
    return {"workdir": str(work), "observations": result, "hashes": dict(files.hashes)}
