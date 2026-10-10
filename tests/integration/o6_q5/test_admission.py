"""Mutation controls for release-admission gate over the real pinned hub lock."""
from __future__ import annotations
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "development/acceptance/o6-q5/admission.py"
spec = importlib.util.spec_from_file_location("o6_q5_admission", SCRIPT)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

HUB = Path(os.environ["COGNOUS_O6_Q5_HUB_ROOT"]).resolve()
actual_sha = subprocess.check_output(["git", "-C", str(HUB), "rev-parse", "HEAD"], text=True).strip()
candidate = json.loads((ROOT / "development/acceptance/o6-q5/candidate.json").read_text())
lock = json.loads((HUB / "component-lock.json").read_text())


def failure(candidate_value=None, lock_value=None, sha=None):
    with pytest.raises(gate.CandidateInvalid):
        gate.check(
            candidate if candidate_value is None else candidate_value,
            lock if lock_value is None else lock_value,
            actual_sha if sha is None else sha,
        )


def test_real_hub_lock_and_candidate_are_verified_but_held():
    result = gate.check(candidate, lock, actual_sha)
    assert result["status"] == "hold"
    assert result["release_admission"] == "not_authorized"
    assert result["effects"] == "disabled"
    assert result["selection"] == "unchanged"
    assert result["reason"] == "operational_trust_not_established"


@pytest.mark.parametrize("key", ["moltbot_safe", "gax_imx_transport", "bitrep"])
def test_hub_selected_pin_drift_fails_closed(key):
    changed = copy.deepcopy(lock)
    field = "accepted_sha" if key == "moltbot_safe" else "sha"
    changed["components"][key][field] = "0" * 40
    failure(lock_value=changed)


def test_runtime_secondary_selected_pin_drift_fails_closed():
    changed = copy.deepcopy(lock)
    changed["components"]["moltbot_safe"]["core_interop_sha"] = "0" * 40
    failure(lock_value=changed)


@pytest.mark.parametrize("key", ["moltbot_safe", "gax_imx_transport", "bitrep"])
def test_candidate_substitution_fails_closed(key):
    changed = copy.deepcopy(candidate)
    changed["candidate"][key] = "f" * 40
    failure(candidate_value=changed)


def test_wrong_hub_sha_fails_closed():
    failure(sha="f" * 40)


def test_false_operational_attestation_fails_closed():
    changed = copy.deepcopy(candidate)
    changed["operational_trust"]["state"] = "qualified"
    failure(candidate_value=changed)


def test_injected_operator_evidence_fails_closed():
    changed = copy.deepcopy(candidate)
    changed["operational_trust"]["independent_operator_evidence"] = "operator-says-ready"
    failure(candidate_value=changed)


def test_release_selection_or_effect_activation_fails_closed():
    for field, value in (("release_selection", "candidate"), ("effects", "enabled")):
        changed = copy.deepcopy(candidate)
        changed[field] = value
        failure(candidate_value=changed)


def test_evidence_rewrite_fails_closed():
    changed = copy.deepcopy(candidate)
    changed["engineering_evidence"]["o6_q4"]["run_id"] = 1
    failure(candidate_value=changed)


def test_missing_source_lock_fails_closed():
    changed = copy.deepcopy(lock)
    changed.pop("components")
    failure(lock_value=changed)
