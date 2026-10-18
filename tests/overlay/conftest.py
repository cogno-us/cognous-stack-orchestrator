"""Opt-in candidate-component overlay: shared setup.

Nothing here runs in the orchestrator's default CI. The overlay needs checkouts named by environment variables; without them every
test is skipped (set COGNOUS_OVERLAY_REQUIRE=1 to turn a missing variable into a failure, as the workflow does).

Required:  COGNOUS_OVERLAY_ACTION_MANIFEST, COGNOUS_OVERLAY_CONTROL_PLANE, COGNOUS_OVERLAY_RUNTIME,
           COGNOUS_OVERLAY_VERIFIER, COGNOUS_OVERLAY_ODES   (paths to git checkouts; the candidate revisions)
Optional:  COGNOUS_OVERLAY_BASELINE_CONTROL_PLANE / _RUNTIME  (the programme-2 starting revisions: default-path byte comparison)
           COGNOUS_OVERLAY_PIN_CONTROL_PLANE / _RUNTIME        (the orchestrator's own pins: report-only comparison)
           COGNOUS_OVERLAY_REPORT_DIR                          (where overlay-report.json and the bundles are kept)
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

HERE = pathlib.Path(__file__).resolve().parent
REQUIRED = {
    "action_manifest": "COGNOUS_OVERLAY_ACTION_MANIFEST",
    "control_plane": "COGNOUS_OVERLAY_CONTROL_PLANE",
    "runtime": "COGNOUS_OVERLAY_RUNTIME",
    "verifier": "COGNOUS_OVERLAY_VERIFIER",
    "odes": "COGNOUS_OVERLAY_ODES",
}
OPTIONAL = {
    "baseline_control_plane": "COGNOUS_OVERLAY_BASELINE_CONTROL_PLANE",
    "baseline_runtime": "COGNOUS_OVERLAY_BASELINE_RUNTIME",
    "pin_control_plane": "COGNOUS_OVERLAY_PIN_CONTROL_PLANE",
    "pin_runtime": "COGNOUS_OVERLAY_PIN_RUNTIME",
}
REPORT: dict = {"claim": "synthetic, report-only; no authority, no effect, not release evidence; issue #30 HOLD unchanged",
                "sections": {}}


def head(path: str) -> str:
    return subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True).strip()


class Overlay:
    def __init__(self) -> None:
        self.paths = {k: os.environ[v] for k, v in REQUIRED.items()}
        self.optional = {k: os.environ[v] for k, v in OPTIONAL.items() if os.environ.get(v)}
        self.heads = {k: head(p) for k, p in {**self.paths, **self.optional}.items()}
        base = os.environ.get("COGNOUS_OVERLAY_REPORT_DIR")
        self.out = pathlib.Path(base) if base else pathlib.Path(tempfile.mkdtemp(prefix="cognous-overlay-"))
        self.out.mkdir(parents=True, exist_ok=True)
        REPORT["heads"] = self.heads

    def run_runner(self, script: str, *args: str, control_plane: str | None = None, runtime: str | None = None) -> None:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "COGNOUS_ACTION_MANIFEST_SRC": self.paths["action_manifest"],
            "COGNOUS_CONTROL_PLANE_SRC": control_plane or self.paths["control_plane"],
            "COGNOUS_EXECUTION_RUNTIME_ROOT": runtime or self.paths["runtime"],
        }
        proc = subprocess.run([sys.executable, "-I", str(HERE / script), *args], env=env, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise AssertionError(f"{script} failed ({proc.returncode}):\n{proc.stdout[-2000:]}\n{proc.stderr[-4000:]}")


@pytest.fixture(scope="session")
def overlay() -> Overlay:
    missing = [v for v in REQUIRED.values() if not os.environ.get(v)]
    if missing:
        if os.environ.get("COGNOUS_OVERLAY_REQUIRE") == "1":
            pytest.fail(f"overlay variables missing: {missing}")
        pytest.skip(f"candidate overlay not configured (needs {', '.join(missing)}); opt-in only")
    return Overlay()


@pytest.fixture(scope="session")
def candidate_handoff(overlay: Overlay) -> pathlib.Path:
    out = overlay.out / "candidate-handoff"
    overlay.run_runner("_handoff_runner.py", str(out))
    return out


@pytest.fixture(scope="session")
def candidate_journal(overlay: Overlay) -> pathlib.Path:
    out = overlay.out / "candidate-journal"
    overlay.run_runner("_journal_runner.py", str(out))
    return out


@pytest.fixture(scope="session")
def candidate_destinations(overlay: Overlay) -> pathlib.Path:
    out = overlay.out / "candidate-destinations"
    overlay.run_runner("_destination_runner.py", str(out))
    return out


@pytest.fixture(scope="session")
def baseline(overlay: Overlay):
    cp, rt = overlay.optional.get("baseline_control_plane"), overlay.optional.get("baseline_runtime")
    if not (cp and rt):
        if os.environ.get("COGNOUS_OVERLAY_REQUIRE") == "1":
            pytest.fail("baseline revisions required but not supplied")
        pytest.skip("programme-2 baseline revisions not supplied")
    handoff, journal = overlay.out / "baseline-handoff", overlay.out / "baseline-journal"
    overlay.run_runner("_handoff_runner.py", str(handoff), control_plane=cp, runtime=rt)
    overlay.run_runner("_journal_runner.py", str(journal), "off", control_plane=cp, runtime=rt)
    return {"handoff": handoff, "journal": journal}


@pytest.fixture(scope="session")
def pinned(overlay: Overlay):
    cp, rt = overlay.optional.get("pin_control_plane"), overlay.optional.get("pin_runtime")
    if not (cp and rt):
        if os.environ.get("COGNOUS_OVERLAY_REQUIRE") == "1":
            pytest.fail("orchestrator pin checkouts required but not supplied")
        pytest.skip("orchestrator pin checkouts not supplied")
    out = overlay.out / "pinned-handoff"
    overlay.run_runner("_handoff_runner.py", str(out), control_plane=cp, runtime=rt)
    return out


@pytest.fixture(scope="session", autouse=True)
def _write_report():
    yield
    if REPORT["sections"]:
        base = os.environ.get("COGNOUS_OVERLAY_REPORT_DIR")
        if base:
            path = pathlib.Path(base) / "overlay-report.json"
            path.write_text(json.dumps(REPORT, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")


def section(name: str, data) -> None:
    REPORT["sections"][name] = data


@pytest.fixture(scope="session")
def replay_probe(overlay: Overlay, candidate_handoff, candidate_journal):
    """Replay and Evidence Pack outcomes for the overlay's own records (optional checkouts COGNOUS_OVERLAY_REPLAY / _EVIDENCE_PACK)."""
    replay, pack = os.environ.get("COGNOUS_OVERLAY_REPLAY"), os.environ.get("COGNOUS_OVERLAY_EVIDENCE_PACK")
    if not (replay and pack):
        if os.environ.get("COGNOUS_OVERLAY_REQUIRE") == "1":
            pytest.fail("COGNOUS_OVERLAY_REPLAY and COGNOUS_OVERLAY_EVIDENCE_PACK are required")
        pytest.skip("Replay / Evidence Pack checkouts not supplied")
    overlay.heads["replay"], overlay.heads["evidence_pack"] = head(replay), head(pack)
    out = overlay.out / "replay-probe.json"
    bundles = [candidate_handoff / "applied", candidate_handoff / "held_no_grant"] + [
        candidate_journal / s / "applied" for s in ("off", "identity", "freshness", "rule_revision", "full")]
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "COGNOUS_REPLAY_SRC": str(pathlib.Path(replay) / "src"),
           "COGNOUS_EVIDENCE_PACK_SRC": str(pathlib.Path(pack) / "src"),
           "COGNOUS_CANDIDATE_CONTROL_PLANE_REVISION": overlay.heads["control_plane"]}
    proc = subprocess.run([sys.executable, "-I", str(HERE / "_replay_runner.py"), str(out), *map(str, bundles)], env=env,
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise AssertionError(f"_replay_runner failed:\n{proc.stdout[-1500:]}\n{proc.stderr[-3000:]}")
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def assurance(overlay: Overlay, candidate_handoff, candidate_journal):
    out = overlay.out / "assurance.json"
    bundles = [candidate_handoff / "applied", candidate_journal / "off/applied", candidate_journal / "full/applied"]
    overlay.run_runner("_assurance_runner.py", str(out), *map(str, bundles))
    return json.loads(out.read_text(encoding="utf-8"))
