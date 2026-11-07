"""VNEXT-S3-CONTRACT-VALIDATION-01: bounded native Verifier contract-validation harness.

DEVELOPMENT ONLY / SYNTHETIC / NONPRODUCTION / UNQUALIFIED / builder-lineage / non-authorizing / HOLD.
Not independent qualification. Expectations live in s3_oracle.json, frozen before execution.

The harness runs the Verifier's own native entry point (cognous_verify.cli:main) in a subprocess
against byte-preserved S2 Control Plane records and minimal isolated mutated copies. It does not
reimplement any Verifier check. Required environment:

    S3_VERIFIER_ROOT  checkout of cogno-us/cognous-open-control-stack-verifier at the pinned revision
    S3_MANIFEST_ROOT  checkout of cogno-us/cognous-action-manifest at the pinned revision
    S3_EVIDENCE_DIR   (optional) directory to retain raw per-test evidence
    S3_REQUIRE=1      turn a missing/unsuitable root into a failure (a skip is not a pass)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ORACLE = json.loads((HERE / "s3_oracle.json").read_text(encoding="utf-8"))
S2_INPUTS = HERE.parent / "s2_runtime" / "evidence" / "raw_supplementary_capture"
MANIFEST_REL = Path("examples") / "refund_integration_v1_1.manifest.json"
FIXED_TIME = ORACLE["fixed_report_time"]
OVERALL = ORACLE["exit_to_overall"]
RUNNER = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from cognous_verify.cli import main; sys.exit(main(sys.argv[2:]))"
)
_P1_CACHE: dict = {}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> str:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/tmp")}
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def _root(name: str) -> Path:
    value = os.environ.get(name)
    if value and Path(value).is_dir():
        return Path(value).resolve()
    if os.environ.get("S3_REQUIRE") == "1":
        pytest.fail(f"S3_REQUIRE=1 but {name} is not a directory")
    pytest.skip(f"{name} not set")


@pytest.fixture(scope="session")
def env():
    verifier = _root("S3_VERIFIER_ROOT")
    manifest_root = _root("S3_MANIFEST_ROOT")
    return {
        "verifier": verifier,
        "src": verifier / "src",
        "manifest": manifest_root / MANIFEST_REL,
        "manifest_root": manifest_root,
        "evidence": Path(os.environ["S3_EVIDENCE_DIR"]) if os.environ.get("S3_EVIDENCE_DIR") else None,
    }


def run_verifier(env, args, cwd):
    """Run the native entry point once. Returns exit status, stdout, stderr and the parsed report."""
    out = cwd / "report.json"
    argv = [sys.executable, "-I", "-B", "-c", RUNNER, str(env["src"]), *args]
    if "--out" not in args and "--version" not in args:
        argv += ["--out", str(out)]
    argv += ["--generated-at", FIXED_TIME]
    proc = subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "")}
    )
    report = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    return {"exit": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "report": report,
            "argv_tail": [a if not a.startswith("/") else Path(a).name for a in args]}


def retain(env, name, result, mutation, inputs):
    """Retain raw evidence for one test: mutation, input hashes, exit, stdout/stderr, report."""
    verdicts = {}
    if result["report"]:
        verdicts = {c["check_id"]: c["verdict"] for c in result["report"]["checks"]}
    meta = {
        "test": name,
        "verifier_revision": ORACLE["sources"]["verifier_revision"],
        "mutation": mutation,
        "input_sha256": {p.name: _sha(p) for p in inputs},
        "exit": result["exit"],
        "overall": OVERALL[str(result["exit"])] if str(result["exit"]) in OVERALL else "ERROR",
        "check_verdicts": verdicts,
        "report_sha256": hashlib.sha256(json.dumps(result["report"], sort_keys=True).encode()).hexdigest()
        if result["report"] else None,
    }
    if env["evidence"]:
        d = env["evidence"] / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
        (d / "stdout.txt").write_text(result["stdout"])
        (d / "stderr.txt").write_text(result["stderr"])
        if result["report"]:
            (d / "report.json").write_text(json.dumps(result["report"], indent=1, sort_keys=True) + "\n")
        for p in inputs:
            if p.parent not in (S2_INPUTS, env["manifest"].parent):  # retain only mutated copies
                (d / ("input_" + p.name)).write_bytes(p.read_bytes())
    return meta


def checks_of(result):
    assert result["report"] is not None, f"no report written: exit {result['exit']} {result['stderr']!r}"
    return {c["check_id"]: c for c in result["report"]["checks"]}


def finding(checks, check_id, code, locator_suffix):
    hits = [f for f in checks[check_id]["findings"] if f["code"] == code and f["locator"].endswith(locator_suffix)]
    assert hits, f"{check_id}: no finding {code} at *{locator_suffix}: {checks[check_id]['findings']}"


def all_confirmed(checks, ids):
    for i in ids:
        assert checks[i]["verdict"] == "confirmed", (i, checks[i]["verdict"], checks[i]["findings"])


def no_refuted(checks):
    bad = [i for i, c in checks.items() if c["verdict"] == "refuted"]
    assert not bad, f"unexpected refuted checks: {bad}"


def mutated_json(src: Path, dst: Path, edit):
    """Structured edit of a retained record; the unedited serialization must round-trip byte-exactly."""
    raw = src.read_bytes()
    obj = json.loads(raw)
    assert (json.dumps(obj, indent=1, sort_keys=True) + "\n").encode() == raw, "serialization does not round-trip"
    edit(obj)
    dst.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return dst


@pytest.fixture()
def originals_unchanged():
    yield
    for name in ("control_plane_run.json", "proposal.json", "runtime_export.json"):
        assert _sha(S2_INPUTS / name) == ORACLE["input_sha256"][name], f"original {name} changed"


def base_args(env, rec=None, proposal=None, manifest=None):
    a = [str(rec or S2_INPUTS / "control_plane_run.json")]
    a += ["--proposal", str(proposal or S2_INPUTS / "proposal.json")] if proposal is not False else []
    a += ["--manifest", str(manifest or env["manifest"])] if manifest is not False else []
    return a


# --------------------------------------------------------------------------- G0 source identity
def test_g0_source_identity(env):
    sources = ORACLE["sources"]
    assert _git(env["verifier"], "rev-parse", "HEAD") == sources["verifier_revision"]
    assert _git(env["verifier"], "status", "--porcelain", "--untracked-files=all") == ""
    assert _git(env["manifest_root"], "rev-parse", "HEAD") == sources["manifest_revision"]
    assert _git(env["manifest_root"], "status", "--porcelain", "--untracked-files=all") == ""
    probe = subprocess.run(
        [sys.executable, "-I", "-B", "-c",
         "import sys; sys.path.insert(0, sys.argv[1]); import cognous_verify, cognous_verify.cli as c; "
         "print(cognous_verify.__file__); print(c.main.__module__ + ':' + c.main.__name__)", str(env["src"])],
        capture_output=True, text=True, check=True, env={"PATH": os.environ.get("PATH", "")}).stdout.split("\n")
    assert Path(probe[0]).resolve().is_relative_to(env["src"].resolve())
    assert probe[1] == "cognous_verify.cli:main"
    for name in ("control_plane_run.json", "proposal.json", "runtime_export.json"):
        assert _sha(S2_INPUTS / name) == ORACLE["input_sha256"][name]
    assert _sha(env["manifest"]) == ORACLE["input_sha256"]["refund_integration_v1_1.manifest.json"]
    repo = HERE.parents[2]
    subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", sources["orchestrator_base"], "HEAD"], check=True)


# --------------------------------------------------------------------------- P1 / N6
def _p1(env, tmp_path_factory):
    if "r" not in _P1_CACHE:
        cwd = tmp_path_factory.mktemp("p1")
        r = run_verifier(env, base_args(env), cwd)
        _P1_CACHE["r"] = r
        _P1_CACHE["meta"] = retain(env, "test_p1_unchanged_s2_record_abstains_with_substantive_commitment_checks", r,
                                   "none (byte-identical originals)",
                                   [S2_INPUTS / "control_plane_run.json", S2_INPUTS / "proposal.json", env["manifest"]])
    return _P1_CACHE["r"]


def test_p1_unchanged_s2_record_abstains_with_substantive_commitment_checks(env, tmp_path_factory, originals_unchanged):
    r = _p1(env, tmp_path_factory)
    checks = checks_of(r)
    assert r["exit"] == 3
    assert set(checks) == set(ORACLE["p1_confirmed_checks"]) | set(ORACLE["ledger_checks"])
    all_confirmed(checks, ORACLE["p1_confirmed_checks"])
    for i in ORACLE["ledger_checks"]:
        assert checks[i]["verdict"] == "could_not_check"
        assert checks[i]["could_not_check_reason"] == "input_absent"
        assert checks[i]["extensions"]["x-reason"] == "input_absent:destination_ledger"
    assert r["report"]["summary"] == {"checks": 32, "confirmed": 25, "could_not_check": 7, "refuted": 0}
    assert r["report"]["scope"]["tiers_run"] == ["V1", "V2", "V4"]
    assert r["report"]["scope"]["semantic_quality"] == "not_assessed"
    assert not [i for i in checks if i.startswith("v3.")]
    assert "tier V3 (witness re-derivation) not run" in r["stdout"]
    assert r["stderr"] == ""
    ids = {n["id"] for n in r["report"]["does_not_prove"]}
    assert set(ORACLE["required_nonclaim_ids"]) <= ids
    no_refuted(checks)


def test_n6_partial_evidence_boundary(env, tmp_path_factory, originals_unchanged):
    r = _p1(env, tmp_path_factory)  # identical input, source and configuration as P1
    checks = checks_of(r)
    assert r["exit"] == 3 and OVERALL[str(r["exit"])] == "ABSTAIN"
    for i in ORACLE["ledger_checks"]:
        assert checks[i]["verdict"] == "could_not_check"
        assert checks[i]["extensions"]["x-reason"] == "input_absent:destination_ledger"
    no_refuted(checks)
    assert r["exit"] != 0  # absence of refutation is not an accept


# --------------------------------------------------------------------------- negatives
def test_n1_proposal_commitment_mutation(env, tmp_path, originals_unchanged):
    prop = mutated_json(S2_INPUTS / "proposal.json", tmp_path / "proposal.json", lambda p: p.__setitem__("amount", 51.0))
    r = run_verifier(env, base_args(env, proposal=prop), tmp_path)
    retain(env, "test_n1_proposal_commitment_mutation", r, "mutated proposal.json: amount 50.0 -> 51.0",
           [S2_INPUTS / "control_plane_run.json", prop, env["manifest"]])
    c = checks_of(r)
    assert r["exit"] == 1
    assert c["v2.identity.proposal-commitment"]["verdict"] == "refuted"
    finding(c, "v2.identity.proposal-commitment", "proposal_commitment_mismatch", ".decisions[0].operation_horizon.proposal_commitment")
    all_confirmed(c, ["v1.wire.strict-parse", "v1.structure", "v1.structure.proposal-export",
                      "v2.identity.payload-commitment", "v2.identity.manifest-digest"])


def test_n2_effect_identity_mutation(env, tmp_path, originals_unchanged):
    def edit(rec):
        e = rec["decisions"][0]["effect_id"]
        rec["decisions"][0]["effect_id"] = e[:-1] + ("0" if e[-1] != "0" else "1")
    rec = mutated_json(S2_INPUTS / "control_plane_run.json", tmp_path / "control_plane_run.json", edit)
    r = run_verifier(env, base_args(env, rec=rec), tmp_path)
    retain(env, "test_n2_effect_identity_mutation", r, "mutated control_plane_run.json: decisions[0].effect_id last digit",
           [rec, S2_INPUTS / "proposal.json", env["manifest"]])
    c = checks_of(r)
    assert r["exit"] == 1
    assert c["v2.identity.effect-id"]["verdict"] == "refuted"
    finding(c, "v2.identity.effect-id", "invalid_effect_identity", ".decisions[0].effect_id")
    all_confirmed(c, ["v1.wire.strict-parse", "v1.structure"])


def test_n3a_payload_commitment_mutation(env, tmp_path, originals_unchanged):
    def edit(p):
        assert p["payload"]["refund_reason"] == "duplicate"
        p["payload"]["refund_reason"] = "fraudulent"
    prop = mutated_json(S2_INPUTS / "proposal.json", tmp_path / "proposal.json", edit)
    r = run_verifier(env, base_args(env, proposal=prop), tmp_path)
    retain(env, "test_n3a_payload_commitment_mutation", r, "mutated proposal.json: payload.refund_reason duplicate -> fraudulent",
           [S2_INPUTS / "control_plane_run.json", prop, env["manifest"]])
    c = checks_of(r)
    assert r["exit"] == 1
    finding(c, "v2.identity.payload-commitment", "payload_commitment_mismatch", ".proposals[0].payload_commitment")
    finding(c, "v2.identity.proposal-commitment", "proposal_commitment_mismatch", ".decisions[0].operation_horizon.proposal_commitment")
    all_confirmed(c, ["v1.structure.proposal-export", "v2.identity.manifest-digest"])


def test_n3b_manifest_binding_mutation(env, tmp_path, originals_unchanged):
    text = env["manifest"].read_text(encoding="utf-8")
    old = '"owner": "cognous-integration-pilot"'
    assert text.count(old) == 1
    man = tmp_path / env["manifest"].name
    man.write_text(text.replace(old, '"owner": "cognous-integration-pilot-x"'), encoding="utf-8")
    r = run_verifier(env, base_args(env, manifest=man), tmp_path)
    retain(env, "test_n3b_manifest_binding_mutation", r, "mutated manifest copy: owner suffix -x",
           [S2_INPUTS / "control_plane_run.json", S2_INPUTS / "proposal.json", man])
    c = checks_of(r)
    assert r["exit"] == 1
    assert c["v2.identity.manifest-digest"]["verdict"] == "refuted"
    finding(c, "v2.identity.manifest-digest", "manifest_digest_mismatch", ".proposals[0].manifest_digest")
    finding(c, "v2.identity.manifest-digest", "manifest_input_commitment_mismatch", ".decisions[0].resolution_inputs[0].record_commitment")
    assert not [f for f in c["v2.identity.manifest-digest"]["findings"] if f["code"] == "manifest_identity_mismatch"]
    all_confirmed(c, ["v1.structure.manifest", "v2.identity.proposal-commitment", "v2.identity.payload-commitment"])
    assert _sha(env["manifest"]) == ORACLE["input_sha256"]["refund_integration_v1_1.manifest.json"]


def test_n4a_missing_proposal_export(env, tmp_path, originals_unchanged):
    r = run_verifier(env, base_args(env, proposal=False), tmp_path)
    retain(env, "test_n4a_missing_proposal_export", r, "invocation omits --proposal",
           [S2_INPUTS / "control_plane_run.json", env["manifest"]])
    c = checks_of(r)
    assert r["exit"] == 3
    for i in ORACLE["identity_checks"]:
        assert c[i]["verdict"] == "could_not_check", i
        assert c[i]["could_not_check_reason"] == "input_absent"
        assert c[i]["extensions"]["x-reason"] == "input_absent:proposal_export"
    for i in ORACLE["ledger_checks"]:
        assert c[i]["verdict"] == "could_not_check"
    assert "v1.structure.proposal-export" not in c
    all_confirmed(c, ["v1.wire.strict-parse", "v1.structure", "v1.structure.manifest"])
    no_refuted(c)


def test_n4b_missing_run_record_argument(env, tmp_path, originals_unchanged):
    r = run_verifier(env, ["--manifest", str(env["manifest"]), "--out", str(tmp_path / "report.json")], tmp_path)
    retain(env, "test_n4b_missing_run_record_argument", r, "invocation supplies no run record",
           [env["manifest"]])
    assert r["exit"] == 2
    assert r["report"] is None and r["stdout"] == ""
    assert "run_record" in r["stderr"]


def test_n5_unsupported_generation(env, tmp_path, originals_unchanged):
    def edit(rec):
        rec["decisions"][0]["binding"]["generation"] = "bounded-authorization-effect/9.9-unsupported"
    rec = mutated_json(S2_INPUTS / "control_plane_run.json", tmp_path / "control_plane_run.json", edit)
    r = run_verifier(env, base_args(env, rec=rec), tmp_path)
    retain(env, "test_n5_unsupported_generation", r, "mutated control_plane_run.json: binding.generation unsupported value",
           [rec, S2_INPUTS / "proposal.json", env["manifest"]])
    c = checks_of(r)
    assert r["exit"] == 1
    assert c["v1.structure"]["verdict"] == "refuted"
    hits = [f for f in c["v1.structure"]["findings"] if f["code"] == "unknown_enum_value" and f["locator"].endswith(".binding.generation")]
    assert hits, c["v1.structure"]["findings"]
    assert c["v2.identity.proposal-commitment"]["verdict"] == "could_not_check"
    assert c["v2.identity.proposal-commitment"]["extensions"]["x-reason"] == "tier_unavailable:structure_refuted"


@pytest.mark.skip(reason="NOT EXECUTED - UNSUPPORTED NATIVE CONTRACT: the Verifier defines no Replay/Evidence Pack input role or document kind and none is retained; no adapter invented")
def test_n7_replay_or_pack_input():
    raise AssertionError("not executed")


def test_n7b_non_journal_s2_artifact_is_unsupported_document(env, tmp_path, originals_unchanged):
    exp = S2_INPUTS / "runtime_export.json"
    r = run_verifier(env, [str(exp)], tmp_path)
    retain(env, "test_n7b_non_journal_s2_artifact_is_unsupported_document", r,
           "retained runtime_export.json supplied as the run record (not Replay/Pack)", [exp])
    c = checks_of(r)
    assert r["exit"] == 3
    all_confirmed(c, ["v1.wire.strict-parse"])
    assert c["v1.structure"]["verdict"] == "could_not_check"
    assert c["v1.structure"]["could_not_check_reason"] == "not_applicable_to_input"
    assert c["v1.structure"]["extensions"]["x-reason"].startswith("unsupported_document")
    assert not [i for i in c if i.startswith("v2.identity.") and c[i]["verdict"] == "confirmed"]
    no_refuted(c)


def test_n8_self_consistent_forgery_characterization(env, tmp_path, originals_unchanged):
    raw_p = (S2_INPUTS / "proposal.json").read_bytes()
    raw_r = (S2_INPUTS / "control_plane_run.json").read_text(encoding="utf-8")
    prop = json.loads(raw_p)
    rec = json.loads(raw_r)
    forged = dict(prop, correlation_id="forged-correlation-s3-n8")
    helper = (
        "import sys, json; sys.path.insert(0, sys.argv[1]); "
        "from cognous_verify import wire, generation; from cognous_verify.canon import commitment; "
        "old = wire.parse(open(sys.argv[2], 'rb').read()); new = wire.parse(open(sys.argv[3], 'rb').read()); "
        "g, rev = sys.argv[4], sys.argv[5]; "
        "print(json.dumps([commitment(old), commitment(new), "
        "generation.effect_identity(commitment(old), g, rev, generation.STRICT), "
        "generation.effect_identity(commitment(new), g, rev, generation.STRICT)]))"
    )
    fp = tmp_path / "proposal.json"
    fp.write_text(json.dumps(forged, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    b = rec["decisions"][0]["binding"]
    out = subprocess.run(
        [sys.executable, "-I", "-B", "-c", helper, str(env["src"]), str(S2_INPUTS / "proposal.json"), str(fp),
         b["grant_id"], b["grant_revision"]],
        capture_output=True, text=True, check=True, env={"PATH": os.environ.get("PATH", "")}).stdout
    old_pc, new_pc, old_eid, new_eid = json.loads(out)
    assert old_pc == rec["decisions"][0]["operation_horizon"]["proposal_commitment"]  # sanity: native recompute matches record
    assert old_eid == rec["decisions"][0]["effect_id"]
    sealed = raw_r.replace(old_pc, new_pc).replace(old_eid, new_eid)
    assert old_pc not in sealed and old_eid not in sealed
    fr = tmp_path / "control_plane_run.json"
    fr.write_text(sealed, encoding="utf-8")
    r = run_verifier(env, base_args(env, rec=fr, proposal=fp), tmp_path)
    retain(env, "test_n8_self_consistent_forgery_characterization", r,
           "mutated: proposal.correlation_id; proposal commitment + effect id recomputed with native functions and replaced throughout the record",
           [fr, fp, env["manifest"]])
    c = checks_of(r)
    assert r["exit"] == 3, "outcome B: forged set not self-consistent under the harness reseal"
    all_confirmed(c, ["v1.structure"] + ORACLE["identity_checks"])
    no_refuted(c)
    assert "self_consistent_forgery_not_detected" in {n["id"] for n in r["report"]["does_not_prove"]}
