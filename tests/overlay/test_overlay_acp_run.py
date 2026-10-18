"""`acp run` (public Control Plane command) records through cognous-verify and the ODES validators.

`acp run` takes the Control Plane's own example inputs (examples/acp_run), so the orchestrator contributes no input here; what it
adds is the cross-check: a record produced by the public command, with its own control-plane local destination ledger, is read by
the independent verifier and by the ODES contracts. Synthetic only; the command contacts no network.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

from conftest import section
from test_overlay_verifier import FIXED, acp, assert_report_denominators, odes, tally, verify  # noqa: F401  (odes is a fixture)

CASES = {"authorized": 0, "held": 1}  # case -> acp run exit code (0 applied, 1 held)


@pytest.mark.parametrize("case", sorted(CASES))
def test_acp_run_record_through_validate_run_verifier_and_odes(overlay, odes, case):
    examples = pathlib.Path(overlay.paths["control_plane"]) / "examples" / "acp_run"
    work = overlay.out / "acp-run" / case
    shutil.rmtree(work, ignore_errors=True)  # acp run refuses a non-empty store or output directory
    work.mkdir(parents=True)
    run = acp(overlay, "run", "--manifest", str(examples / "manifest.json"), "--proposal", str(examples / case / "proposal.json"),
              "--authority-context", str(examples / case / "authority-context.json"),
              "--resolver-state", str(examples / case / "resolver-state.json"),
              "--store-dir", str(work / "store"), "--out-dir", str(work / "out"), "--now", "2026-10-05T19:00:00Z", "--format", "json")
    assert run.returncode == CASES[case], run.stdout + run.stderr
    record = work / "out" / "bounded-run-record.json"
    assert record.exists()
    validated = acp(overlay, "validate-run", str(work / "out" / "run-record.json"))
    assert validated.returncode == 0, validated.stdout + validated.stderr

    bundle = work / "bundle"
    bundle.mkdir()
    (bundle / "run-record.json").write_bytes(record.read_bytes())
    (bundle / "proposal.json").write_bytes((examples / case / "proposal.json").read_bytes())
    (bundle / "manifest.json").write_bytes((examples / "manifest.json").read_bytes())
    ledger = work / "store" / "destination.json"
    code, report, out = verify(overlay, bundle, ledger=ledger)
    assert code in (0, 3), f"cognous-verify exit {code} on a real `acp run` record (FINDING):\n{out}"
    assert odes["verification-report"].validate(report) == []
    assert_report_denominators(report)
    assert report["summary"]["refuted"] == 0

    doc = dict(json.loads(record.read_text()), contract="control-plane-journal", contract_version="0.1.0-draft", producer="control-plane")
    violations = odes["control-plane-journal"].validate(doc)
    assert violations == [], [f"{v.code} {v.path}" for v in violations]
    section(f"acp_run_{case}", {"acp_run_exit": run.returncode, "validate_run_exit": validated.returncode, "verifier_exit": code,
                                **tally(report), "odes_journal_violations": 0})
