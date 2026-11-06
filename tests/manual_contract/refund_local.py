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
import os
import pathlib
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script dir; sibling harness modules live here

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


def _odes_clean(root: pathlib.Path) -> None:
    if real_c4._git(root, "rev-parse", "HEAD") != ODES_SHA:
        raise RefundAdapterError("ODES HEAD is not the pinned revision")
    if real_c4._git(root, "rev-parse", "HEAD^{tree}") != ODES_TREE:
        raise RefundAdapterError("ODES tree is not the pinned tree")
    if real_c4._git(root, "status", "--porcelain", "--untracked-files=all", "--ignored=matching"):
        raise RefundAdapterError("ODES checkout has changed, untracked or ignored files")
    if any(line[:2] != "H " for line in real_c4._git(root, "ls-files", "-v").splitlines()):
        raise RefundAdapterError("ODES checkout has assume-unchanged or skip-worktree files")


def _load_odes(odes_root: pathlib.Path):
    """Fail closed unless a clean exact ODES checkout is loaded; every loaded odes module is blob-checked."""
    root = odes_root.resolve(strict=True)
    _odes_clean(root)
    for module in (root / "src" / "odes").rglob("*.py"):
        if module.is_symlink():
            raise RefundAdapterError("ODES symlink source refused")
    sys.path.insert(0, str(root / "src"))
    import odes
    if root not in pathlib.Path(odes.__file__).resolve().parents:
        raise RefundAdapterError("ODES package imported outside pinned checkout")
    for name, mod in sorted(sys.modules.items()):
        if name == "odes" or name.startswith("odes."):
            path = pathlib.Path(mod.__file__).resolve()
            if root not in path.parents:
                raise RefundAdapterError("ODES module outside pinned checkout: " + name)
            rel = path.relative_to(root).as_posix()
            data = path.read_bytes()
            if hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != real_c4._git(root, "rev-parse", "HEAD:" + rel):
                raise RefundAdapterError("ODES module differs from its pinned blob: " + rel)
    return odes


def _confine_workdir(workdir, source_dirs):
    """Return a fresh scratch dir strictly below the system tempdir and disjoint from every source checkout."""
    tmp_root = pathlib.Path(tempfile.gettempdir()).resolve()
    if len(tmp_root.parts) < 2:
        raise RefundAdapterError("system tempdir is a filesystem root")
    if workdir is None:
        candidate = pathlib.Path(tempfile.mkdtemp(prefix="refund-local-")).resolve()
    else:
        candidate = pathlib.Path(workdir).resolve()
    if tmp_root not in candidate.parents:
        raise RefundAdapterError("workdir must be strictly below the system tempdir")
    for src in source_dirs:
        src = pathlib.Path(src).resolve()
        if candidate == src or src in candidate.parents or candidate in src.parents:
            raise RefundAdapterError("workdir overlaps a source checkout")
    return real_c4._fresh_workdir(candidate)


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
    if not lifecycle:
        raise RefundAdapterError("Pack lifecycle summary missing")
    if result == "hold":
        if binding is not None or attempts or observations or reconciliations or effects:
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
        row_ok = len(effects) == 1 and isinstance(row, dict) and row.get("state") == "applied" and row.get("effect_id") == decision_effect
        if good_attempt and good_observation and good_reconciliation and row_ok:
            standing = "SYNTHETIC_APPLIED_OBSERVED"
        else:
            standing = "AUTHORIZED_NOT_CONFIRMED_APPLIED"
    else:
        raise RefundAdapterError("unsupported Control Plane outcome")
    if result == "hold" and lifecycle.get("authorization") != "held":
        raise RefundAdapterError("Pack disagrees with HOLD authorization")
    if result == "authorized" and lifecycle.get("authorization") != "authorized":
        raise RefundAdapterError("Pack disagrees with native authorization")
    return {
        "decision": result,
        "effect_id": decision_effect,
        "binding": binding,
        "synthetic_effect_standing": standing,
        "standing_basis": "native CP attempt+observation+reconciliation AND local destination row; producer-retained, not independent",
        "record_attempt_count": len(attempts),
        "record_observation_count": len(observations),
        "record_reconciliation_count": len(reconciliations),
        "local_destination_row_count": len(effects),
        "pack_lifecycle": lifecycle,
        "odes_recipient_reliance": (reliance.get("recipient_reliance_decision") or {}),
        "real_payment_effect": "NOT_ATTEMPTED",
        "independent_qualification": False,
    }


def check_propagation(scenario, rec, bundle_obj, pack_dict, report, package, reliance, raw_texts):
    """Per-hop assertions that native state survives Replay -> Pack and Replay -> ODES unchanged and never improves."""
    held = scenario == "grant_revoked"
    bad = []

    def need(cond, msg):
        if not cond:
            bad.append(msg)

    types = [x.get("record_type") for x in bundle_obj.get("records", [])]
    n = types.count
    need(bundle_obj.get("status") == "reconstruction_partial", "Replay status is not partial")
    sem = bundle_obj.get("semantics") or {}
    need(sem.get("destination_observation") == "not_performed" and sem.get("external_effect_execution") is False
         and sem.get("independent_effect_verification") is False, "Replay semantics claim more than recorded events")
    for t in ("destination_effect", "destination_attempt", "execution_result"):
        need(n(t) == 0, "Replay carries executor/destination record " + t)
    need(n("effect_observation") == len(rec.get("observations") or []), "Replay effect_observation count != CP record")
    need(n("reconciliation") == len(rec.get("reconciliations") or []), "Replay reconciliation count != CP record")
    md = ((pack_dict.get("metadata") or {}).get("traceable_import") or {})
    dc, lc = md.get("derived_counts") or {}, md.get("lifecycle_summary") or {}
    need(dc.get("destination_effect_count") == 0 and dc.get("executor_attempt_count") == 0, "Pack counts a destination/executor effect")
    need(dc.get("effect_observation_count") == n("effect_observation") and dc.get("reconciliation_count") == n("reconciliation"),
         "Pack observation/reconciliation counts differ from Replay")
    need(dc.get("control_plane_attempt_count") == len({x.get("attempt_id") for x in rec.get("attempts") or []}), "Pack attempt count != CP record")
    need(dc.get("authorization_granted_count") == (0 if held else 1) and dc.get("authorization_held_count") == (1 if held else 0)
         and dc.get("authorization_denied_count") == 0, "Pack authorization counts wrong")
    need(lc.get("authorization") == ("held" if held else "authorized"), "Pack authorization lifecycle wrong")
    need(lc.get("execution_attempted") == ("no" if held else "yes"), "Pack execution_attempted wrong")
    need(lc.get("destination_observed") == ("unknown" if held else "applied"), "Pack destination_observed wrong")
    need(lc.get("reconstruction_status") == "reconstruction_partial", "Pack improved reconstruction status")
    need(lc.get("independent_verification") == "unavailable", "Pack claims independent verification")
    need([x.get("status") for x in pack_dict.get("replay_bundles", [])] == ["validated_partial"], "Pack replay bundle status not validated_partial")
    need(report.valid is True, "Pack validation report not valid")
    prov = package.get("provenance") or {}
    rv = prov.get("replay_validation") or {}
    need(rv.get("status") == "reconstruction_partial", "ODES package improved reconstruction status")
    codes = [x.get("code") for x in rv.get("findings", [])]
    need(codes == (["B005", "B004"] if held else ["B004"]), "ODES carried findings differ: %r" % (codes,))
    need((package.get("record") or {}).get("decision_type") == ("agent_action_held" if held else "agent_action_authorized"), "ODES decision_type wrong")
    ef = prov.get("execution_facts") or {}
    need(not ef.get("destination_effects") and not ef.get("executor_observations"), "ODES carries destination/executor facts")
    for layer in ("schema_validity", "replay_semantic_consistency", "package_content_integrity"):
        need((reliance.get(layer) or {}).get("status") == "pass", "ODES layer not pass: " + layer)
    for layer in ("consumption_conditions", "integrity_authentication_checks", "historical_authority_assertions", "authority_status_and_freshness"):
        need((reliance.get(layer) or {}).get("status") != "pass", "ODES layer unexpectedly pass: " + layer)
    need((reliance.get("recipient_reliance_decision") or {}).get("status") == "fail", "ODES final reliance is not FAIL")
    need(all("grant_effect_counts" not in t for t in raw_texts), "destination-only grant_effect_counts reached downstream evidence")
    need(not package.get("package_digest") or package["package_digest"] not in json.dumps(pack_dict), "Pack references the ODES package digest (ODES-to-Pack edge)")
    if bad:
        raise RefundAdapterError("propagation check failed for %s: %s" % (scenario, "; ".join(bad)))


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
    here = pathlib.Path(real_c4.__file__).resolve().parent
    for name, key in (("real_c3.py", "real_c3_sha256"), ("c2_producer.py", "c2_producer_sha256")):
        if _hash((here / name).read_bytes()) != real_c4.FROZEN[key]:
            raise RefundAdapterError(name + " differs from the frozen harness file")
    # Source measurement occurs BEFORE any native call.
    ctx = real_c4._measure(roots)
    odes = _load_odes(pathlib.Path(odes_root))
    manifest_path = ctx["am_root"] / real_c4.MANIFEST_RELATIVE_PATH
    man_bytes, man_ok = real_c4._read_once(manifest_path, real_c4.FROZEN["manifest_file_sha256"], "manifest")
    prop_bytes, prop_ok = real_c4._read_once(real_c4.PROPOSAL_PATH, real_c4.FROZEN["proposal_sha256"], "proposal")
    gate, manifest, proposal = real_c4._am_gate(ctx, man_bytes, prop_bytes, man_ok, prop_ok)
    if not gate["passed"] or not isinstance(manifest, dict) or not isinstance(proposal, dict):
        raise RefundAdapterError("frozen Action Manifest gate did not pass")
    work = _confine_workdir(workdir, [*roots.values(), odes_root])
    files = real_c4._Files(work)
    files.put("inputs/manifest.json", man_bytes)
    files.put("inputs/proposal.json", prop_bytes)
    result = {"schema": SCHEMA, "status": "DEVELOPER_OBSERVATION_UNQUALIFIED",
              "subject_sources": {k: v["sha"] for k, v in real_c4.PINS.items()},
              "odes_source": ODES_SHA, "synthetic_test_clock": str(refund_producer.NOW),
              "limitations": ["synthetic unauthenticated authority", "no payment integration",
                              "virtual test clock", "no Runtime effect", "partial Replay",
                              "no ODES-to-Pack edge", "no independently trusted ODES recipient policy (empty policy; N5b exposure unresolved)",
                              "destination row and grant_effect_counts never reach Replay, Pack or ODES",
                              "acknowledgement and CP-observed applied state are producer-retained, not independent",
                              "ODES acceptance of structure is not authorization; machine_role and authority_valid_at_decision are self-asserted",
                              "ODES package created_at is wall-clock, so package hashes are not reproducible"],
              "harness": {**real_c4._harness(), "refund_local_sha256": _hash(pathlib.Path(__file__).read_bytes()),
                          "refund_producer_sha256": _hash(pathlib.Path(refund_producer.__file__).read_bytes())},
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
        try:
            package = odes.export_cognous_stack_package(copy.deepcopy(manifest), copy.deepcopy(bundle_obj))
            reliance = odes.evaluate_recipient_package(copy.deepcopy(package), {})
        except Exception as exc:  # native ODES refusal is reported, never swallowed
            raise RefundAdapterError("native ODES refused (%s): %s" % (type(exc).__name__, exc)) from None
        files.put(scenario + "/odes-package.json", _dump(package))
        files.put(scenario + "/odes-reliance.json", _dump(reliance))
        check_propagation(scenario, rec, bundle_obj, pack_dict, report, package, reliance,
                          [raw_record.decode(), json.dumps(bundle_obj), json.dumps(pack_dict), json.dumps(package)])
        native = classify_native(decision, rec, dest, pack_dict, reliance)
        native["replay_status"] = bundle.status
        native["pack_validation_valid"] = report.valid
        native["local_effect_call_trace"] = list(produced.provenance["calls"])
        native["local_effect_observation"] = produced.local_effect
        result["cases"][scenario] = native
    # It is never permitted for a held scenario to share the authorized effect ID.
    if result["cases"]["authorized"]["effect_id"] == result["cases"]["grant_revoked"]["effect_id"]:
        raise RefundAdapterError("two independent synthetic decisions shared an effect ID")
    real_c4._recheck(ctx)  # source trees unchanged after all native calls, BEFORE the observation files are written
    _odes_clean(pathlib.Path(odes_root).resolve(strict=True))
    files.put("source-observations.json", _dump(result))
    files.put("SHA256SUMS.json", _dump(files.hashes))
    return {"workdir": str(work), "observations": result, "hashes": dict(files.hashes)}
