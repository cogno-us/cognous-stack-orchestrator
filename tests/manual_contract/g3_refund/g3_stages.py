"""G3-REFUND stage runner (DEVELOPMENT ONLY / SYNTHETIC). Thin composition of existing native component interfaces; no new framework."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "source_manifest.json").read_text())
PINS = {k: v["commit"] for k, v in MANIFEST["components"].items()}
PACK_PROFILE = MANIFEST["replay_generation"]
CP_LABEL = PINS["control_plane"]
GENERATED = "2026-11-07T00:00:00Z"
NONCLAIMS = [
    "authorization is SYNTHETIC developer-mode (resolver authenticated=false; identity/mandate flags are fixture assertions)",
    "the Runtime write is a REAL local SQLite INSERT, but the effect evidence is PRODUCER-REPORTED, not independently observed",
    "the Verifier is ALPHA/HOLD and abstains; it never accepts a Pack",
    "the signature is valid only under a synthetic ephemeral snapshot and is not chain-bound",
    "Registry inclusion is PROVISIONAL on a disposable local chain: no durable custody, no consensus finality",
    "no independent qualification, no production authority, no ODES/GAX, no source-lock change",
]


def sha256_file(path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(root, *args):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "LC_ALL": "C"}
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env, timeout=60, check=True).stdout.strip()


def verify_pins(root: Path) -> dict:
    identity = {}
    for key, pin in PINS.items():
        assert git(root / key, "rev-parse", "HEAD") == pin, (key, "not the pinned commit")
        assert git(root / key, "status", "--porcelain", "--untracked-files=no") == "", (key, "tracked files modified")
        identity[key] = {"head": pin, "tree": git(root / key, "rev-parse", "HEAD^{tree}")}
    return identity


def stage(name, component, status, outcome, *, revision=None, input_id=None, output_id=None, source="", evidence="", limitation=""):
    """One row of the final observation. status in EXECUTED | NOT RUN | UNKNOWN | REFUSED."""
    assert status in ("EXECUTED", "NOT RUN", "UNKNOWN", "REFUSED")
    return {"stage": name, "component": component, "revision": revision, "input_identity": input_id, "output_identity": output_id,
            "status": status, "outcome": outcome, "assertion_source": source, "evidence_availability": evidence, "limitation": limitation}


def capture(root: Path, scenario: str, out: Path):
    cp, rt = root / "control_plane", root / "runtime"
    env = {**os.environ, "G3_STACK_ROOT": str(root), "PYTHONPATH": os.pathsep.join([str(cp / "src"), str(rt)]), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-B", str(HERE / "g3_capture.py"), str(out), scenario], cwd=str(cp), env=env, capture_output=True, text=True, timeout=600)


def load_capture(out: Path):
    names = ("control_plane_run.json", "proposal.json", "runtime_export.json")
    data = {n: json.loads((out / n).read_text()) for n in names if (out / n).exists()}
    return data, json.loads((out / "capture_summary.json").read_text())


def replay_import(stack, cp_run, proposal, export):
    return stack.replay.import_bounded_workflow(copy.deepcopy(cp_run), proposal=copy.deepcopy(proposal), moltbot_export=export,
                                                control_plane_revision=CP_LABEL).model_dump(mode="json")


def pack_import(stack, bundle):
    """The explicit opt-in Replay generation is always passed."""
    return stack.pack.import_manifest_reconstruction(copy.deepcopy(stack.manifest), copy.deepcopy(bundle), generated_at=GENERATED, replay_generation=PACK_PROFILE)


def run_verifier(root: Path, pack_path: Path, report_path: Path):
    env = {**os.environ, "PYTHONPATH": str(root / "verifier" / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-B", "-m", "cognous_verify.pack_cli", str(pack_path), "--out", str(report_path)], env=env, capture_output=True, text=True,
                          timeout=300, cwd=str(report_path.parent))
    return done


def run_g1b(root: Path, report_path: Path, workdir: Path, evidence_dir: Path | None):
    env = {**os.environ, "G3_REGISTRY_ROOT": str(root / "evidence_registry"), "PYTHON": sys.executable, "BITREP_ROOT": str(root / "evidence_attestation"),
           "G1_ROOT": str(root / "evidence_attestation"), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(["node", str(HERE / "g1b_run.mjs"), str(report_path), str(workdir), PINS["verifier"], str(evidence_dir) if evidence_dir else "-"],
                          env=env, capture_output=True, text=True, timeout=600, cwd=str(root / "evidence_registry" / "chain"))
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("G3_G1B_RESULT ")), None)
    return done, (json.loads(line[len("G3_G1B_RESULT "):]) if line else None)


def render_observation(case: str, title: str, stages: list[dict], summary_lines: list[str]) -> str:
    rows = ["| stage | component@rev | status | outcome | input -> output identity | assertion source | evidence | limitation |", "|---|---|---|---|---|---|---|---|"]
    for s in stages:
        rows.append("| {stage} | {component}@{rev} | **{status}** | {outcome} | {i} -> {o} | {source} | {evidence} | {limitation} |".format(
            rev=(s["revision"] or "")[:12], i=s["input_identity"], o=s["output_identity"], source=s["assertion_source"], evidence=s["evidence_availability"],
            **{k: s[k] for k in ("stage", "component", "status", "outcome", "limitation")}))
    return "\n".join([f"# G3 final development observation - {case}: {title}", "", "DEVELOPMENT ONLY / SYNTHETIC. Not a single SUCCESS verdict; the facts below are separate.", "",
                      *summary_lines, "", *rows, "", "## Nonclaims", *[f"- {n}" for n in NONCLAIMS], ""])
