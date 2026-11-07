"""G3-REFUND: three frozen development checks (Hub #273 freeze comment 6711352677). DEVELOPMENT ONLY / SYNTHETIC / builder-lineage.

Run with  G3_STACK_ROOT=<assembled pinned roots> G3_REQUIRE=1 [G3_EVIDENCE_DIR=<dir>] python -m pytest -q tests/manual_contract/g3_refund
A skip is not a pass: G3_REQUIRE=1 turns a missing environment into a failure. Not independent qualification.
"""
import json
import os
import sys
import traceback
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g3_stages as G  # noqa: E402

ROOT_ENV = os.environ.get("G3_STACK_ROOT")
EVIDENCE = Path(os.environ["G3_EVIDENCE_DIR"]) if os.environ.get("G3_EVIDENCE_DIR") else None
EXECUTOR_KINDS = {"execution_envelope", "execution_result", "destination_attempt", "destination_effect"}


def _need() -> Path:
    keys = list(G.PINS)
    if ROOT_ENV and all((Path(ROOT_ENV) / k).is_dir() for k in keys):
        return Path(ROOT_ENV)
    if os.environ.get("G3_REQUIRE") == "1":
        pytest.fail("G3_REQUIRE=1 but G3_STACK_ROOT is not an assembled stack root")
    pytest.skip("G3_STACK_ROOT not set")


def keep(case: str, name: str, content) -> None:
    if EVIDENCE is None:
        return
    d = EVIDENCE / case
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(content if isinstance(content, bytes) else str(content).encode())


def guard(case, stage_name, fn):
    """COMPATIBILITY GATE: preserve the native refusal verbatim and fail loudly (no retry, no workaround)."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - recorded verbatim, then re-raised as the stage's precise blocker
        text = f"{stage_name}: {type(exc).__name__} code={getattr(exc, 'code', None)!r}\n{exc}\n{traceback.format_exc()}"
        keep(case, f"REFUSAL_{stage_name}.txt", text)
        pytest.fail("COMPATIBILITY GATE - native consumer refused at " + text[:1500])


@pytest.fixture(scope="module")
def stack():
    root = _need()
    identity = G.verify_pins(root)
    for sub in ("replay/src", "evidence_pack/src"):
        sys.path.insert(0, str(root / sub))
    os.environ["ODES_ALLOW_UNVERIFIED_REPLAY"] = "0"
    from agent_replay_bundle import importers as replay
    from agent_governance_evidence_pack import importer as pack
    for mod, key in ((replay, "replay"), (pack, "evidence_pack")):
        assert Path(mod.__file__).resolve().is_relative_to((root / key).resolve()), (key, mod.__file__)
    assert hasattr(replay, "_validate_operation_tenant"), "imported Replay lacks the tenant-binding correction"
    assert pack.CP2_REPLAY_CANDIDATES[G.PACK_PROFILE]["replay"] == G.PINS["replay"], "Pack lacks the opt-in candidate"
    manifest = json.loads((root / "manifest" / "examples" / "refund_integration_v1_1.manifest.json").read_text())
    return type("S", (), {"root": root, "replay": replay, "pack": pack, "manifest": manifest, "identity": identity})


@pytest.fixture(scope="module")
def valid(stack, tmp_path_factory):
    out = tmp_path_factory.mktemp("g3-valid")
    done = G.capture(stack.root, "valid", out)
    keep("capture_valid", "stdout.txt", done.stdout + "\n--- stderr ---\n" + done.stderr)
    assert done.returncode == 0, "COMPATIBILITY GATE: capture failed:\n" + done.stdout[-1500:] + done.stderr[-3000:]
    data, summary = G.load_capture(out)
    for n in data:
        keep("capture_valid", n, json.dumps(data[n], indent=1, sort_keys=True))
    keep("capture_valid", "capture_summary.json", json.dumps(summary, indent=1, sort_keys=True))
    return type("V", (), {"data": data, "summary": summary, "dir": out})


@pytest.fixture(scope="module")
def revoked(stack, tmp_path_factory):
    out = tmp_path_factory.mktemp("g3-revoked")
    done = G.capture(stack.root, "revoked", out)
    keep("capture_revoked", "stdout.txt", done.stdout + "\n--- stderr ---\n" + done.stderr)
    assert done.returncode == 0, "capture failed:\n" + done.stdout[-1500:] + done.stderr[-3000:]
    data, summary = G.load_capture(out)
    for n in data:
        keep("capture_revoked", n, json.dumps(data[n], indent=1, sort_keys=True))
    keep("capture_revoked", "capture_summary.json", json.dumps(summary, indent=1, sort_keys=True))
    return type("R", (), {"data": data, "summary": summary, "dir": out})


def _cp_runtime_rows(v, stages):
    s = v.summary
    stages.append(G.stage("G2 authority + CP decide()", "institutional-governance + control-plane", "EXECUTED", f"{s['decision_result']} {s['reasons']}",
                          revision=G.PINS["institutional_governance"], input_id=s["authority_id"] + "@" + s["grant_revision"], output_id=None,
                          source="synthetic fixture facts + IG lineage; CP decision is the authority", evidence="CP run record retained",
                          limitation="resolver authenticated=false; authorized = synthetic developer-mode decision"))


def test_check1_positive_complete_chain(stack, valid, tmp_path):
    case, root, s = "check1_positive_chain", stack.root, valid.summary
    stages = []
    # --- CP (G2) ---
    assert s["decision_result"] == "authorized" and s["reasons"] == [], s
    assert s["resolver_authenticated"] is False
    _cp_runtime_rows(valid, stages)
    # --- Runtime: one real local write, producer-reported ---
    export = valid.data["runtime_export.json"]
    assert s["runtime_run"] is True and s["runtime_status"] == "executed" and s["runtime_error"] in (None, ""), s
    assert len(s["effect_rows"]) == 1 and s["effect_rows"][0]["state"] == "applied" and s["effect_rows"][0]["effect_id"] == s["effect_id"]
    assert len(export["effects"]) == 1 and export["effects"][0]["effect_id"] == s["effect_id"] == export["execution_envelope"]["effect_id"]
    assert export["execution_result"]["status"] == "executed" and export["execution_result"]["newly_executed"] is True
    stages.append(G.stage("Runtime execute (one local INSERT)", "execution-runtime", "EXECUTED", "executed / applied (1 row)", revision=G.PINS["runtime"],
                          input_id=s["effect_id"], output_id="runtime_export.json " + G.sha256_file(valid.dir / "runtime_export.json")[:19],
                          source="producer-reported (Runtime export; repository_revision caller-asserted)", evidence="export + local SQLite read-back",
                          limitation="real isolated local write; NOT independently observed; database disposed after capture"))
    # --- Replay ---
    bundle = guard(case, "replay_import", lambda: G.replay_import(stack, valid.data["control_plane_run.json"], valid.data["proposal.json"], export))
    keep(case, "replay_bundle.json", json.dumps(bundle, indent=1, sort_keys=True, default=str))
    assert bundle["status"] == "reconstruction_complete", bundle["status"]
    stages.append(G.stage("Replay import", "replay-bundle", "EXECUTED", bundle["status"], revision=G.PINS["replay"], input_id="CP run + proposal + Runtime export",
                          output_id="bundle " + str(bundle.get("bundle_id")), source="Replay import over producer-reported records", evidence="complete",
                          limitation="destination observation is producer_reported; independent_effect_verification false"))
    # --- Pack ---
    pack = guard(case, "pack_import", lambda: G.pack_import(stack, bundle))
    trace = pack.metadata["traceable_import"]
    assert trace["replay_semantic_validation"]["status"] == "validated_complete", trace["replay_semantic_validation"]
    from agent_governance_evidence_pack.loader import dump_evidence_pack
    pack_path = tmp_path / "pack.json"
    dump_evidence_pack(pack, pack_path)
    keep(case, "pack.json", pack_path.read_bytes())
    stages.append(G.stage("Pack import (opt-in generation)", "governance-evidence-pack", "EXECUTED", "validated_complete", revision=G.PINS["evidence_pack"],
                          input_id=G.PACK_PROFILE, output_id=str(pack.pack_id) + " " + G.sha256_file(pack_path)[:19], source="Pack validator status is a producer string",
                          evidence="complete", limitation="independent verification unavailable"))
    # --- Verifier ---
    report_path = tmp_path / "report.json"
    done = G.run_verifier(root, pack_path, report_path)
    keep(case, "verifier_stdout.txt", done.stdout + "\n--- stderr ---\n" + done.stderr)
    assert done.returncode == 3, ("Verifier exit", done.returncode, done.stderr[-800:])
    report = json.loads(report_path.read_bytes())
    keep(case, "report.json", report_path.read_bytes())
    assert report["overall"] == "abstain" and set(report["execution_evidence"]["present"]) == EXECUTOR_KINDS and report["execution_evidence"]["absent"] == []
    report_hash = G.sha256_file(report_path)
    stages.append(G.stage("Verifier pack_cli", "verifier (ALPHA/HOLD)", "EXECUTED", "exit 3 / abstain; executor kinds present", revision=G.PINS["verifier"],
                          input_id="pack " + G.sha256_file(pack_path)[:19], output_id="report " + report_hash[:19], source="Verifier recomputation over one file",
                          evidence="present kinds are source-asserted", limitation="source identity never checkable; unsupported claims: " + str(len(report["unsupported_claims"]))))
    # --- G1 + G1b ---
    g1b_dir = tmp_path / "g1b"
    done, g1b = G.run_g1b(root, report_path, g1b_dir, (EVIDENCE / case / "g1b") if EVIDENCE else None)
    keep(case, "g1b_stdout.txt", done.stdout + "\n--- stderr ---\n" + done.stderr[-4000:])
    assert g1b and "error" not in g1b, ("G1b failed", done.returncode, (g1b or done.stdout)[:800] if isinstance(g1b, str) else g1b, done.stderr[-1500:])
    x = g1b["result"]
    assert report_path.read_bytes() and G.sha256_file(report_path) == report_hash  # the report bytes were not altered by the chain
    assert x["outcome"] == "PRESENT_PROVISIONAL", x
    assert x["mismatches"] == [] and x["facts"]["artifact_identity_matched"] is True
    assert x["facts"]["signature_valid_under_supplied_dev_snapshot"] is True and x["assurance"] == "issuer_signature_only"
    assert x["facts"]["registry_record_observed_provisional"] is True and x["report_declared_overall"] == "abstain"
    stages.append(G.stage("G1 attestation (ephemeral key) + G1b Registry", "evidence-attestation + evidence-registry", "EXECUTED",
                          f"{x['outcome']}; signature {x['assurance']}", revision=G.PINS["evidence_registry"], input_id="report " + report_hash[:19],
                          output_id="claim " + str(x["observation"]["claim_id"])[:14] + " evidence " + str(x["observation"]["evidence_id"])[:14],
                          source="G1 statement signed by an ephemeral synthetic key; commitments recomputed from retained bytes", evidence="reconstructed; provisional",
                          limitation="not chain-bound; disposable chain; no custody or finality"))
    md = G.render_observation(case, "valid synthetic root, complete chain", stages, [
        "- Synthetic authorization: CP `authorized` under the G2 synthetic root (resolver authenticated=false).",
        "- Actual isolated local write: 1 row `applied` in a unique SQLite file (now disposed) - PRODUCER-REPORTED, not independently observed.",
        "- Verifier: `abstain` (exit 3) - not an accepted execution verdict.",
        f"- Signature validity under synthetic trust: {x['facts']['signature_valid_under_supplied_dev_snapshot']} ({x['assurance']}).",
        f"- Provisional Registry inclusion: {x['outcome']} (disposable chain; no custody/finality).",
    ])
    keep(case, "final_observation.md", md)
    keep(case, "stages.json", json.dumps(stages, indent=1))
    assert "PRODUCER-REPORTED" in md and "abstain" in md


def test_check2_revoked_refusal_chain(stack, revoked):
    case, s = "check2_revoked_refusal", revoked.summary
    assert s["decision_result"] == "hold" and "grant_revoked" in s["reasons"], s
    assert s["resolver_authenticated"] is False and s["runtime_run"] is False
    assert s["effect_rows"] == []
    assert set(revoked.data) == {"control_plane_run.json", "proposal.json"}, sorted(revoked.data)  # no Runtime export or downstream artifacts exist
    not_run = [G.stage(n, c, "NOT RUN", "not invoked because CP returned hold", revision=None, limitation="no artifact generated") for n, c in (
        ("Runtime execute", "execution-runtime"), ("Replay import", "replay-bundle"), ("Pack import", "governance-evidence-pack"), ("Verifier", "verifier"),
        ("G1 attestation", "evidence-attestation"), ("G1b Registry", "evidence-registry"))]
    stages = [G.stage("G2 authority + CP decide()", "institutional-governance + control-plane", "EXECUTED", f"hold {s['reasons']}", revision=G.PINS["institutional_governance"],
                      input_id=s["authority_id"] + "@" + s["grant_revision"], source="synthetic fixture facts + IG lineage; CP decision is the authority",
                      evidence="CP run record retained", limitation="synthetic developer-mode; HOLD never bypassed")] + not_run
    md = G.render_observation(case, "revoked synthetic root, refusal chain", stages, ["- CP `hold` with `grant_revoked`; every downstream stage NOT RUN; no SQLite effect row; no Registry write."])
    keep(case, "final_observation.md", md)
    keep(case, "stages.json", json.dumps(stages, indent=1))


def test_check3_missing_execution_evidence(stack, valid, tmp_path):
    case = "check3_missing_execution_evidence"
    # reuse check 1's authorized CP record + proposal; the executor export is deliberately omitted; no new Runtime execution or effect
    bundle = guard(case, "replay_import", lambda: G.replay_import(stack, valid.data["control_plane_run.json"], valid.data["proposal.json"], None))
    keep(case, "replay_bundle.json", json.dumps(bundle, indent=1, sort_keys=True, default=str))
    assert bundle["status"] == "reconstruction_partial", bundle["status"]
    kinds = {r["record_type"] for r in bundle["records"]}
    assert not (kinds & EXECUTOR_KINDS), kinds & EXECUTOR_KINDS
    pack = guard(case, "pack_import", lambda: G.pack_import(stack, bundle))
    trace = pack.metadata["traceable_import"]
    assert trace["replay_semantic_validation"]["status"] == "validated_partial", trace["replay_semantic_validation"]
    from agent_governance_evidence_pack.loader import dump_evidence_pack
    pack_path = tmp_path / "pack.json"
    dump_evidence_pack(pack, pack_path)
    keep(case, "pack.json", pack_path.read_bytes())
    report_path = tmp_path / "report.json"
    done = G.run_verifier(stack.root, pack_path, report_path)
    keep(case, "verifier_stdout.txt", done.stdout + "\n--- stderr ---\n" + done.stderr)
    assert done.returncode == 3, ("Verifier exit", done.returncode, done.stderr[-800:])
    report = json.loads(report_path.read_bytes())
    keep(case, "report.json", report_path.read_bytes())
    assert report["overall"] == "abstain" and set(report["execution_evidence"]["absent"]) == EXECUTOR_KINDS and report["execution_evidence"]["present"] == []
    stages = [
        G.stage("G2 authority + CP decide()", "institutional-governance + control-plane", "EXECUTED", "authorized (reused CP record from check 1)", revision=G.PINS["institutional_governance"],
                source="synthetic", evidence="CP run record", limitation="synthetic developer-mode"),
        G.stage("Runtime execute", "execution-runtime", "NOT RUN", "no new execution; executor export deliberately omitted", limitation="no additional effect"),
        G.stage("Replay import", "replay-bundle", "EXECUTED", bundle["status"], revision=G.PINS["replay"], source="CP record only", evidence="executor kinds absent",
                limitation="zero executor records is not a measured zero execution"),
        G.stage("Pack import", "governance-evidence-pack", "EXECUTED", "validated_partial", revision=G.PINS["evidence_pack"], source="producer string", evidence="partial"),
        G.stage("Verifier", "verifier (ALPHA/HOLD)", "EXECUTED", "exit 3 / abstain; four executor kinds absent", revision=G.PINS["verifier"], source="Verifier recomputation",
                evidence="executor evidence absent", limitation="execution assurance NOT VERIFIED"),
        G.stage("G1 attestation", "evidence-attestation", "NOT RUN", "not invoked in this case"),
        G.stage("G1b Registry", "evidence-registry", "NOT RUN", "not invoked in this case; no Registry result invented"),
    ]
    md = G.render_observation(case, "authorized reconstruction with executor export omitted", stages, [
        "- Replay `reconstruction_partial`; Pack `validated_partial`; Verifier `abstain` with all four executor kinds absent.",
        "- Execution assurance: NOT VERIFIED. No fabricated execution evidence; no additional effect."])
    keep(case, "final_observation.md", md)
    keep(case, "stages.json", json.dumps(stages, indent=1))
