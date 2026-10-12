"""Composed qualification using actual pinned Runtime, Replay and Evidence Pack."""
from copy import deepcopy
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import sqlite3
import subprocess
import sys
from unittest.mock import patch

import pytest
from agent_replay_bundle import recovery_inspection as replay
from agent_governance_evidence_pack import recovery_inspection as evidence

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "development/recovery/recovery_resolution/inspection.py"
override = os.environ.get("RECOVERY_ADAPTER_OVERRIDE")
spec = importlib.util.spec_from_file_location("recovery_chain", override or ADAPTER)
chain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chain)

REPLAY = Path(os.environ["COGNOUS_REPLAY_SOURCE"]).resolve()
EVIDENCE = Path(os.environ["COGNOUS_EVIDENCE_SOURCE"]).resolve()
for module, root, relative, digest in [
    (replay, REPLAY, "src/agent_replay_bundle/recovery_inspection.py", "00fb16918f55d9799cd693b300a41d2a44e80379"),
    (evidence, EVIDENCE, "src/agent_governance_evidence_pack/recovery_inspection.py", "f879203092d1f02d4d250e13eb934d070384f76b"),
]:
    path = Path(module.__file__).resolve()
    assert path == root / relative
    content = path.read_bytes().rstrip(b"\n") + b"\n"
    assert hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == digest

# These owning-repository helpers load and hash-check the actual Runtime modules.
fixtures = runpy.run_path(str(REPLAY / "tests/recovery_inspection_checks.py"))
IDENTITY = {"effect_id": "effect", "attempt_id": "attempt", "decision_id": "decision",
            "grant_id": "grant", "grant_revision": "r1"}


@pytest.fixture
def pair(tmp_path):
    return fixtures["ledger"].__wrapped__(tmp_path)


def inspect(source, revisions=None):
    return chain.inspect_recovery_export(source, expected_identity=IDENTITY,
        component_revisions=chain.COMPONENT_REVISIONS if revisions is None else revisions)


def logical_database(path):
    with closing(sqlite3.connect(path)) as connection:
        return list(connection.iterdump())


@pytest.mark.parametrize("scenario", ["unobserved", "unknown", "absent", "partial", "unknown_applied",
    "partial_applied", "conflict", "duplicate_after_conflict", "legacy"])
def test_native_chain_and_retained_artifacts(pair, scenario):
    append = fixtures["append"]
    if scenario == "legacy":
        pair[0].close_original_attempt(attempt_id="attempt", observation_state="applied",
            observation=fixtures["OrderingEvidence"](3, "synthetic:legacy"), observation_ref="synthetic:legacy")
    elif scenario in {"unknown_applied", "partial_applied"}:
        append(pair, state="unknown" if scenario == "unknown_applied" else "partial")
        append(pair, event_id="event-2", order=4, state="applied", final=True, complete_coverage=True)
    elif scenario in {"conflict", "duplicate_after_conflict"}:
        append(pair)
        append(pair, state="partial", order=4)
        if scenario == "duplicate_after_conflict":
            append(pair, event_id="event-3", order=5, state="applied", final=True, complete_coverage=True)
            pair[1].append(fixtures["observation"](), expected_revision=0, predecessor_digest=None)
    elif scenario != "unobserved":
        append(pair, state=scenario)
    source = fixtures["export"](pair)
    before_database = logical_database(pair[0].path)
    before = deepcopy(source)
    with patch("sqlite3.connect", side_effect=AssertionError("inspection opened SQLite")):
        result = inspect(source)
        assert result == inspect(source)
        chain.validate_inspection_chain(result)
    assert logical_database(pair[0].path) == before_database
    assert source == before
    retained = result["evidence"]["replay_inspection"]["source"]
    assert retained == source
    assert result["evidence"]["summary"]["retained_event_count"] == len(source["events"])
    assert result["evidence"]["loss_report"] == result["evidence"]["replay_inspection"]["loss_report"]
    assert result["evidence"]["assurance"]["settlement_verified"] is False
    assert result["evidence"]["assurance"]["retry_eligible"] is False
    if scenario in {"unknown_applied", "partial_applied"}:
        assert result["evidence"]["summary"]["producer_work_state"] == "resolved"
    if scenario in {"conflict", "duplicate_after_conflict", "legacy"}:
        assert result["inspection_status"] == "inspected_with_unavailable_evidence"
    else:
        assert result["inspection_status"] == "inspected_retained_records"
    if scenario in {"conflict", "duplicate_after_conflict"}:
        assert result["evidence"]["summary"]["producer_work_state"] == "conflict_review"
    if scenario in {"legacy", "unobserved"}:
        assert result["evidence"]["summary"]["producer_work_state"] == "awaiting_observation"
    output = os.environ.get("RECOVERY_INSPECTION_ARTIFACTS")
    if output:
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (scenario + ".json")).write_text(json.dumps(result, indent=2) + "\n")


@pytest.mark.parametrize("component", ["runtime", "replay", "evidence_pack"])
def test_revision_guard_holds(pair, component):
    changed = dict(chain.COMPONENT_REVISIONS, **{component: "main"})
    with pytest.raises(chain.InspectionHold, match="unsupported_component_revisions"):
        inspect(fixtures["export"](pair), changed)


def test_unavailable_payload_guard(pair):
    fixtures["append"](pair)
    fixtures["append"](pair, state="partial", order=4)
    result = inspect(fixtures["export"](pair))
    assert result["inspection_status"] == "inspected_with_unavailable_evidence"
    assert result["evidence"]["loss_report"]["unavailable_evidence"]


@pytest.mark.parametrize("change", ["profile", "format", "missing_identity", "wrong_identity", "missing_event",
    "duplicate_event", "predecessor", "digest", "projection", "provenance", "fake_tenant"])
def test_invalid_source_holds(pair, change):
    fixtures["append"](pair)
    source = fixtures["export"](pair)
    if change == "profile": source["profile"] = "unknown"
    elif change == "format": source["export_format"] = "unknown"
    elif change == "missing_identity": del source["original"]["grant_id"]
    elif change == "wrong_identity": source["original"]["effect_id"] = "other"
    elif change == "missing_event": source["events"] = []
    elif change == "duplicate_event": source["events"].append(deepcopy(source["events"][0]))
    elif change == "predecessor": source["events"][0]["body"]["predecessor_digest"] = "a"*64
    elif change == "digest": source["events"][0]["digest"] = "a"*64
    elif change == "projection": source["current"]["work_state"] = "resolved"
    elif change == "provenance": source["limitations"] = []
    elif change == "fake_tenant": source["tenant_id"] = "fabricated"
    with pytest.raises(chain.InspectionHold):
        inspect(source)


def test_generic_parse_success_is_not_native_integration(pair):
    from agent_replay_bundle.reconstruction import ReconstructionBundle
    fixtures["append"](pair)
    source = fixtures["export"](pair)
    generic = ReconstructionBundle.model_validate(source)
    assert generic.records == []
    assert inspect(source)["evidence"]["summary"]["retained_event_count"] == 1
    with pytest.raises(chain.InspectionHold):
        inspect(generic.model_dump(mode="json"))


@pytest.mark.parametrize("change", ["status", "loss", "settlement", "verification", "events", "pins"])
def test_changed_chain_rejected(pair, change):
    fixtures["append"](pair)
    fixtures["append"](pair, order=4, state="partial")
    result = inspect(fixtures["export"](pair))
    if change == "status": result["inspection_status"] = "inspected_retained_records"
    elif change == "loss": result["evidence"]["loss_report"] = {}
    elif change == "settlement": result["evidence"]["assurance"]["settlement_verified"] = True
    elif change == "verification": result["evidence"]["assurance"]["independent_verification"] = "verified"
    elif change == "events": result["evidence"]["replay_inspection"]["source"]["events"] = []
    elif change == "pins": result["component_revisions"]["evidence_pack"] = "main"
    with pytest.raises(chain.InspectionHold):
        chain.validate_inspection_chain(result)


@pytest.mark.parametrize("mutation", ["revision", "gap"])
def test_disposable_mutations(tmp_path, mutation):
    code = ADAPTER.read_text()
    if mutation == "revision":
        changed = code.replace('if _json(component_revisions) != _json(COMPONENT_REVISIONS):', 'if False:', 1)
        case = "test_revision_guard_holds"
    else:
        changed = code.replace('"inspected_with_unavailable_evidence" if gaps else "inspected_retained_records"',
                               '"inspected_retained_records"', 1)
        case = "test_unavailable_payload_guard"
    assert changed != code
    path = tmp_path / "inspection.py"
    path.write_text(code)
    env = dict(os.environ, RECOVERY_ADAPTER_OVERRIDE=str(path))
    env.pop("RECOVERY_INSPECTION_ARTIFACTS", None)
    command = [sys.executable, "-m", "pytest", "-q", str(Path(__file__).resolve()) + "::" + case]
    baseline = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    path.write_text(changed)
    for cache in tmp_path.rglob("__pycache__"):
        shutil.rmtree(cache)
    mutant = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert mutant.returncode == 1, mutant.stdout + mutant.stderr
    assert "failed" in mutant.stdout and case in mutant.stdout
