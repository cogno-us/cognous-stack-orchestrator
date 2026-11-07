"""S2-REFUND-RT-01 selected test battery (P, N1-N8). DEVELOPMENT ONLY, SYNTHETIC / NONPRODUCTION, UNQUALIFIED, builder-lineage evidence.

Chain under test, all native and unmodified: pinned Control Plane (strict-tenant, tenant-alpha) -> pinned Execution Runtime Route A (PinnedControlPlaneExecutor.execute,
isolated local SQLite) -> Runtime export_execution_artifacts output (persisted unmodified by s2_capture.py) -> Replay import_bounded_workflow(moltbot_export=<export>) ->
Evidence Pack import_manifest_reconstruction. Negatives are in-memory mutations of deep copies of ONE captured export; the persisted raw files are never changed.

Requires S2_STACK_ROOT: a directory holding control_plane (484fdbd2), runtime (f7a55e2a), replay (7eb7d76e, S2-CANDIDATE-2; 93a76e28 was S2-CANDIDATE-1), evidence_pack (06515085),
manifest (fa170815), each a checkout whose TRACKED files are unmodified (untracked files are not checked). S2_REQUIRE=1 turns a missing/unsuitable root into a failure (skips are not passes). Facts are separated by source: Manifest declaration, Control Plane
authorization, Runtime SQLite rows (export effects/attempts), Runtime export, Replay reconstruction, Pack summary. The export's repository_revision is CALLER-ASSERTED by the
capture script, and the Runtime does not persist the export: the harness does. An effect_id supplied by the Control Plane is not a Runtime authority decision.
"""
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT_ENV = os.environ.get("S2_STACK_ROOT")
# S2-CANDIDATE-3 (source_tuples.json): Pack = merge commit 1906c1fb of Pack PR #68 (explicit opt-in Replay candidate); Replay unchanged from S2-CANDIDATE-2. Superseded: tuple 2 (Pack 06515085, refused Replay 7eb7d76e).
# S2-CANDIDATE-2 (source_tuples.json): Replay = exact main merge commit 7eb7d76e of Replay PR #89 (tenant-binding correction). S2-CANDIDATE-1 used Replay 93a76e28.
PINS = {"control_plane": "484fdbd297235dd24148ddb0703f2055a31eabff", "runtime": "f7a55e2a8494801e49193f9f46935f0a971c248d",
        "replay": "7eb7d76eda10ca1ff997bb86853e903e57da625c", "evidence_pack": "1906c1fb1da4b96449565301c143d7a06b6a16bb",
        "manifest": "fa170815ef96a54c233d0dd9da821b60debabf8b"}
MANIFEST_REL = "examples/refund_integration_v1_1.manifest.json"
CP_LABEL = PINS["control_plane"]
GENERATED = "2026-11-07T00:00:00Z"
PACK_PROFILE = "cp2-replay-7eb7d76e-tenant-binding-dev-0.1"      # the ONLY way the Pack accepts Replay 7eb7d76e: replay_generation=PACK_PROFILE
PACK_TRANSFORMATION = "agep-manifest-reconstruction-import/0.3.11-strict-tenant-replay-7eb7d76e-dev-candidate"
ALPHA = "tenant-alpha"


def _git(root, *args):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "LC_ALL": "C"}
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env, timeout=60, check=True).stdout.strip()


def _need():
    if ROOT_ENV and all((Path(ROOT_ENV) / k).is_dir() for k in PINS):
        return Path(ROOT_ENV)
    if os.environ.get("S2_REQUIRE") == "1":
        pytest.fail("S2_REQUIRE=1 but S2_STACK_ROOT is not a stack root")
    pytest.skip("S2_STACK_ROOT not set")


@pytest.fixture(scope="module")
def stack():
    root = _need()
    identity = {}
    for key, pin in PINS.items():
        head = _git(root / key, "rev-parse", "HEAD")
        dirty = _git(root / key, "status", "--porcelain", "--untracked-files=no")
        assert head == pin, (key, head)
        assert dirty == "", (key, "tracked files modified")
        identity[key] = {"head": head, "tree": _git(root / key, "rev-parse", "HEAD^{tree}")}
    for sub in ("replay/src", "evidence_pack/src"):
        sys.path.insert(0, str(root / sub))
    os.environ["ODES_ALLOW_UNVERIFIED_REPLAY"] = "0"
    from agent_replay_bundle import importers as replay
    from agent_governance_evidence_pack import importer as pack
    from agent_governance_evidence_pack import validator as pack_validator
    for mod, key in ((replay, "replay"), (pack, "evidence_pack")):
        assert Path(mod.__file__).resolve().is_relative_to((root / key).resolve()), (key, mod.__file__)
    # Source identity of the IMPORTED Replay code (not just a SHA string): the checkout HEAD is the pin, it contains the remediation commit, and the loaded module has the correction.
    tuples = json.loads((HERE / "source_tuples.json").read_text())["tuple_3_current"]
    assert all(tuples[k] == PINS[k] for k in PINS), "source_tuples.json does not match the pins"
    assert subprocess.run(["git", "-C", str(root / "replay"), "merge-base", "--is-ancestor", tuples["replay_remediation_commit"], PINS["replay"]]).returncode == 0
    assert hasattr(replay, "_validate_operation_tenant"), "imported Replay lacks the tenant-binding correction"
    assert pack.CP2_REPLAY_PIN == "93a76e281fcae6a65d2cd1d35376f87442dafb95" and pack.CP2_REPLAY_CANDIDATES[PACK_PROFILE]["replay"] == PINS["replay"], "Pack lacks the opt-in candidate"
    assert tuples["pack_profile"] == PACK_PROFILE
    identity["imported_replay_file"] = str(Path(replay.__file__).resolve())
    manifest = json.loads((root / "manifest" / MANIFEST_REL).read_text())
    return type("S", (), {"root": root, "replay": replay, "pack": pack, "validator": pack_validator, "manifest": manifest, "identity": identity})


def _capture(stack, scenario, out):
    cp, rt = stack.root / "control_plane", stack.root / "runtime"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(cp / "src"), str(cp), str(rt)]), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-B", str(HERE / "s2_capture.py"), str(out), scenario], cwd=str(cp), env=env, capture_output=True, text=True, timeout=600)
    return done


def _load(out):
    names = ("control_plane_run.json", "proposal.json", "runtime_export.json")
    return [json.loads((out / n).read_text()) for n in names], {n: hashlib.sha256((out / n).read_bytes()).hexdigest() for n in names}


@pytest.fixture(scope="module")
def valid(stack, tmp_path_factory):
    out = tmp_path_factory.mktemp("s2-valid")
    done = _capture(stack, "valid", out)
    assert done.returncode == 0, "COMPATIBILITY GATE: capture failed:\n" + done.stdout[-1500:] + done.stderr[-3000:]
    (cp_run, proposal, export), hashes = _load(out)
    summary = json.loads((out / "capture_summary.json").read_text())
    return type("V", (), {"cp": cp_run, "proposal": proposal, "export": export, "hashes": hashes, "summary": summary, "dir": out})


def _replay(stack, v, export, label=CP_LABEL, cp=None):
    return stack.replay.import_bounded_workflow(copy.deepcopy(v.cp if cp is None else cp), proposal=copy.deepcopy(v.proposal), moltbot_export=export, control_plane_revision=label).model_dump(mode="json")


def _log(name, exc):
    print("REFUSAL", name, "| code=%r |" % getattr(exc, "code", None), str(exc)[:300])


def _pack(stack, bundle):
    """The explicit opt-in is always passed: tuple 3 has NO implicit profile selection."""
    return stack.pack.import_manifest_reconstruction(copy.deepcopy(stack.manifest), copy.deepcopy(bundle), generated_at=GENERATED, replay_generation=PACK_PROFILE)


def _pack_record(stack):
    return {"id": PACK_PROFILE, "replay_revision": PINS["replay"], "control_plane": PINS["control_plane"], "moltbot_safe": PINS["runtime"], "manifest": PINS["manifest"],
            "opt_in": "caller_declared"}


def _cli(stack, pack, tmp, command):
    """Existing supported interface: write the pack with the Pack's own dumper and run `agep <command>` (cli.main) in a subprocess with the pinned Replay and Pack on the path."""
    from agent_governance_evidence_pack.loader import dump_evidence_pack
    path = Path(tmp) / "pack.json"
    dump_evidence_pack(pack, path)
    code = "import sys; sys.argv = ['agep', %r, %r]; from agent_governance_evidence_pack.cli import main; main()" % (command, str(path))
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(stack.root / "evidence_pack" / "src"), str(stack.root / "replay" / "src")]), "PYTHONDONTWRITEBYTECODE": "1", "ODES_ALLOW_UNVERIFIED_REPLAY": "0"}
    done = subprocess.run([sys.executable, "-B", "-c", code], env=env, capture_output=True, text=True, timeout=300, cwd=str(tmp))
    return done.returncode, done.stdout, done.stderr


def _facts(t):
    keys_counts = ("control_plane_attempt_count", "executor_attempt_count", "attempt_transition_record_count", "destination_effect_count", "destination_effect_state_counts",
                   "effect_observation_count", "effect_observation_state_counts", "reconciliation_count", "reconciliation_state_counts", "execution_result_state_counts",
                   "acknowledgement_counts", "acknowledgement_sources", "destination_observation_counts", "distinct_effect_count", "coverage_denominators", "counting_rules")
    return {"derived_counts": {k: t["derived_counts"].get(k) for k in keys_counts}, "lifecycle_summary": t.get("lifecycle_summary"),
            "replay_semantic_validation": t.get("replay_semantic_validation"), "replay_semantics": t.get("replay_semantics"), "replay_generation": t.get("replay_generation"),
            "transformation_version": t.get("transformation_version"), "selected_revisions": t.get("selected_revisions"),
            "input_artifacts": [{k: a.get(k) for k in ("role", "trusted_revision")} for a in t.get("input_artifacts", [])],
            "independent_verification": sorted(set(map(str, _collect(t, "independent_verification")))),
            "evidence_levels": t.get("evidence_levels"), "control_evidence_levels": t.get("control_evidence_levels"),
            "executor_producer_contract": t.get("executor_producer_contract"), "lifecycle_record_kinds": sorted(t.get("lifecycle_records", {}))}


def _trace(pack):
    return pack.metadata["traceable_import"]


def _collect(node, key, found=None):
    found = [] if found is None else found
    if isinstance(node, dict):
        for k, val in node.items():
            if k == key:
                found.append(val)
            _collect(val, key, found)
    elif isinstance(node, list):
        for item in node:
            _collect(item, key, found)
    return found


def _kinds(bundle):
    return sorted({r["record_type"] for r in bundle["records"]})


def _reseal(stack, export, mutate):
    """Mutate execution_envelope.operation in a deep copy, then replace the OLD operation digest by the NEW canonical digest everywhere it occurs, so that no
    unrelated digest-mismatch refusal can fire. Uses Replay's own canonical digest function."""
    e = copy.deepcopy(export)
    old = stack.replay._sha256(e["execution_envelope"]["operation"])
    mutate(e["execution_envelope"]["operation"])
    new = stack.replay._sha256(e["execution_envelope"]["operation"])

    def walk(node):
        if isinstance(node, dict):
            for k, val in list(node.items()):
                node[k] = new if val == old else walk(val)
        elif isinstance(node, list):
            for i, val in enumerate(node):
                node[i] = new if val == old else walk(val)
        return node
    walk(e)
    return e, old, new


# ---------------------------------------------------------------------------------------------------------------- gate 1 (compatibility)
def test_g1_runtime_route_a_executes_once_under_the_strict_tenant_control_plane(stack, valid):
    s = valid.summary
    assert s["decision_result"] == "authorized" and s["result_status"] == "executed" and s["error"] in (None, ""), s
    assert s["tenant_id"] == ALPHA and valid.export["execution_envelope"]["operation"].get("tenant_id") == ALPHA
    assert len(valid.export["effects"]) == 1 and len(valid.export["attempts"]) == 1


# ---------------------------------------------------------------------------------------------------------------- P
def test_p_replay_native_positive_runtime_export_replay_complete(stack, valid):
    """ITERATION B (construction correction): the Replay-level part of P, split from the Pack part so a Pack identity-pin refusal cannot mask it."""
    ex = valid.export
    assert ex["repository"]["revision"] == PINS["runtime"] and ex["repository"]["revision_status"] in ("source_asserted", "unavailable")
    assert ex["execution_result"]["status"] == "executed" and ex["execution_result"]["acknowledged"] is True
    assert ex["execution_envelope"]["effect_id"] == valid.summary["effect_id"] == ex["effects"][0]["effect_id"]
    bundle = _replay(stack, valid, ex)
    assert bundle["status"] == "reconstruction_complete", bundle["status"]
    assert {"execution_envelope", "execution_result", "destination_attempt", "destination_effect"} <= set(_kinds(bundle)), _kinds(bundle)
    assert sum(1 for r in bundle["records"] if r["record_type"] == "destination_effect") == 1
    assert set(valid.hashes) == {"control_plane_run.json", "proposal.json", "runtime_export.json"}


def test_p_pack_native_positive_pack_counts(stack, valid, tmp_path):
    """P-pack under S2-CANDIDATE-3: complete Replay reconstruction -> Pack native import with the explicit opt-in; executor-side counts come from Runtime records."""
    bundle = _replay(stack, valid, valid.export)
    assert bundle["status"] == "reconstruction_complete"
    pack = _pack(stack, bundle)
    t = _trace(pack)
    assert t["replay_generation"] == _pack_record(stack) and t["transformation_version"] == PACK_TRANSFORMATION
    rsv = t["replay_semantic_validation"]
    assert rsv["status"] == "validated_complete" and rsv["required_revision"] == PINS["replay"]
    assert t["selected_revisions"]["replay"] == PINS["replay"] and t["input_artifacts"][1]["trusted_revision"] == PINS["replay"]
    report = stack.validator.validate_evidence_pack(pack)
    assert report.valid, [i for i in report.issues if i.severity.value == "error"]
    kinds = t["lifecycle_records"]
    assert {"destination_attempt", "destination_effect", "execution_result", "execution_envelope"} <= set(kinds)                    # executor-side (Runtime export)
    assert {"control_plane_attempt_transition", "effect_observation", "reconciliation"} <= set(kinds)                                # Control Plane-side, separate kinds
    ex = valid.export
    assert [r.get("attempt_id") for r in kinds["destination_attempt"]] == [a["attempt_id"] for a in ex["attempts"]]
    assert [r.get("effect_id") for r in kinds["destination_effect"]] == [e["effect_id"] for e in ex["effects"]]
    assert [r.get("operation_digest") for r in kinds["destination_effect"]] == [e["operation_digest"] for e in ex["effects"]]
    c = t["derived_counts"]
    assert c["executor_attempt_count"] >= 1 and c["destination_effect_count"] == 1, c
    assert c["execution_result_state_counts"], c
    assert c["control_plane_attempt_count"] >= 1                      # Control Plane evidence is counted separately from the executor records
    assert set(_collect(t, "independent_verification")) == {"unavailable"}, _collect(t, "independent_verification")
    rc, out, err = _cli(stack, pack, tmp_path, "summarize")
    print("P-PACK-FACTS", json.dumps(_facts(t), sort_keys=True, default=str))
    print("P-PACK-CLI-SUMMARIZE rc=%s\n%s%s" % (rc, out, err))
    assert rc == 0 and ("executor_attempt_count : %s" % c["executor_attempt_count"]) in out and ("destination_observed   : %s" % t["lifecycle_summary"]["destination_observed"]) in out, (rc, out, err)


# ---------------------------------------------------------------------------------------------------------------- N1
@pytest.mark.parametrize("case", ["operation_amount", "effect_operation_digest"])
def test_n1_operation_mismatch_is_refused(stack, valid, case):
    e = copy.deepcopy(valid.export)
    if case == "operation_amount":
        e["execution_envelope"]["operation"]["amount"] = e["execution_envelope"]["operation"]["amount"] + 1
    else:
        e["effects"][0]["operation_digest"] = "sha256:" + "0" * 64
    with pytest.raises(stack.replay.ImportContractError) as exc:
        _replay(stack, valid, e)
    _log("N1:" + case, exc.value)
    assert "operation" in str(exc.value) or "amount" in str(exc.value), str(exc.value)


# ---------------------------------------------------------------------------------------------------------------- N2 (stop gate 2)
def test_n2_control_reseal_without_tenant_change_is_accepted(stack, valid):
    """Control: the digest-reseal procedure itself must not cause a refusal (so a refusal in the next test is attributable to the tenant change)."""
    e, old, new = _reseal(stack, valid.export, lambda op: None)
    assert old == new
    assert _replay(stack, valid, e)["status"] == "reconstruction_complete"


@pytest.mark.parametrize("field,value", [("tenant_id", "tenant-beta")])
def test_n2_executor_side_tenant_mismatch_is_refused_by_a_tenant_check(stack, valid, field, value):
    """REQUIRED: REFUSE, and the refusal must name tenant binding (not a malformed/digest failure). All digests are recomputed consistently so only the tenant differs."""
    e, old, new = _reseal(stack, valid.export, lambda op: op.__setitem__(field, value))
    assert old != new
    try:
        bundle = _replay(stack, valid, e)
    except stack.replay.ImportContractError as exc:
        _log("N2", exc)
        assert exc.code == "binding_contract_mismatch" and "execution_envelope.operation.tenant_id" in str(exc), (exc.code, str(exc))
        assert "digest" not in str(exc), "refused for an unrelated digest reason: " + str(exc)
    else:
        pytest.fail("REPLAY ACCEPTED an executor-side tenant mismatch (status %s)" % bundle["status"])


# ITERATION 2 of N2 (separately identified; the iteration-1 test above is retained unchanged and its original failure is preserved). Iteration 1 resealed only the
# export; Replay then refused at control_plane.observations.destination_state.operation_digest because the Control Plane run record carries the committed operation digest
# of the ORIGINAL (tenant-alpha) operation. That is a real cross-record digest binding, but not a tenant-specific check. N2b also replaces the old digest inside an in-memory
# COPY of the Control Plane record, so that the export and the Control Plane record agree on the tenant-beta operation and only the proposal/binding still say tenant-alpha.
def test_n2b_executor_and_control_plane_digests_agree_on_a_foreign_tenant_but_proposal_and_binding_do_not(stack, valid):
    e, old, new = _reseal(stack, valid.export, lambda op: op.__setitem__("tenant_id", "tenant-beta"))
    assert old != new
    cp = copy.deepcopy(valid.cp)

    def walk(node):
        if isinstance(node, dict):
            for k, val in list(node.items()):
                node[k] = new if val == old else walk(val)
        elif isinstance(node, list):
            for i, val in enumerate(node):
                node[i] = new if val == old else walk(val)
        return node
    walk(cp)
    assert cp != valid.cp, "the Control Plane record did not contain the old operation digest"
    try:
        bundle = _replay(stack, valid, e, cp=cp)
    except stack.replay.ImportContractError as exc:
        _log("N2", exc)
        assert exc.code == "binding_contract_mismatch" and "execution_envelope.operation.tenant_id" in str(exc), (exc.code, str(exc))
        assert "digest" not in str(exc), "refused for an unrelated digest reason: " + str(exc)
    else:
        pytest.fail("REPLAY ACCEPTED an executor-side tenant mismatch (status %s)" % bundle["status"])


# ---------------------------------------------------------------------------------------------------------------- N3
def test_n3_unsupported_revision_and_undeclared_member_are_refused(stack, valid):
    e = copy.deepcopy(valid.export)
    e["repository"]["revision"] = "f63ce914504dd06813c4ccd199b0570dbd8dd427"
    with pytest.raises(stack.replay.ImportContractError) as exc:
        _replay(stack, valid, e)
    _log("N3:revision", exc.value)
    e = copy.deepcopy(valid.export)
    e["undeclared_member"] = {"x": 1}
    with pytest.raises(stack.replay.ImportContractError) as exc:
        _replay(stack, valid, e)
    _log("N3:undeclared_member", exc.value)


# ---------------------------------------------------------------------------------------------------------------- N4 / N5 / N6
@pytest.mark.parametrize("member", ["attempts", "attempt_events"])
def test_n4_missing_runtime_attempt_evidence_is_refused(stack, valid, member):
    e = copy.deepcopy(valid.export)
    e[member] = []
    with pytest.raises(stack.replay.ImportContractError) as exc:
        _replay(stack, valid, e)
    _log("N4:" + member, exc.value)


@pytest.mark.parametrize("case", ["null_observation", "effects_removed"])
def test_n5_missing_effect_evidence_is_refused(stack, valid, case):
    e = copy.deepcopy(valid.export)
    if case == "null_observation":
        e["execution_result"]["observation"] = None
    else:
        e["effects"] = []
    with pytest.raises(stack.replay.ImportContractError) as exc:
        _replay(stack, valid, e)
    _log("N5:" + case, exc.value)


@pytest.mark.parametrize("member", ["effects", "attempts"])
def test_n6_duplicate_evidence_rows_are_refused(stack, valid, member):
    e = copy.deepcopy(valid.export)
    e[member] = e[member] + [copy.deepcopy(e[member][0])]
    with pytest.raises(stack.replay.ImportContractError) as exc:
        _replay(stack, valid, e)
    _log("N6:" + member, exc.value)


# ---------------------------------------------------------------------------------------------------------------- N7
@pytest.fixture(scope="module")
def lost(stack, tmp_path_factory):
    out = tmp_path_factory.mktemp("s2-lost")
    done = _capture(stack, "lost_ack", out)
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-3000:]
    (cp_run, proposal, export), hashes = _load(out)
    return type("L", (), {"cp": cp_run, "proposal": proposal, "export": export, "hashes": hashes})


def test_n7_replay_lost_acknowledgment_stays_unacknowledged_without_false_success(stack, lost):
    """ITERATION C (construction correction): the frozen oracle expected result status 'unknown'. The Runtime's native lost-acknowledgment outcome is status 'reconciled'
    (follow-up observation of its own SQLite row) with acknowledged False and newly_executed False (Replay's own tests/test_current_generation.py SCENARIOS lost_ack ->
    'reconciled'; fixture PROVENANCE 'reconciled after a lost acknowledgement'). The uncertainty invariant is: never acknowledged, never newly executed."""
    r = lost.export["execution_result"]
    assert r["status"] == "reconciled" and r["acknowledged"] is False and r["newly_executed"] is False and r["attempted"] is True, r
    bundle = _replay(stack, lost, lost.export)
    res = [x for x in bundle["records"] if x["record_type"] == "execution_result"]
    assert len(res) == 1 and res[0]["data"]["acknowledged"] is False and res[0]["data"]["newly_executed"] is False
    print("N7-REPLAY", json.dumps({"bundle_status": bundle["status"], "result": {k: res[0]["data"].get(k) for k in ("status", "acknowledged", "observed_state", "newly_executed", "error")}}, sort_keys=True, default=str))


def test_n7_pack_lost_acknowledgment_representation(stack, lost, valid, tmp_path):
    """N7-pack under S2-CANDIDATE-3 (corrected native semantics: reconciled / acknowledged False / newly_executed False)."""
    r = lost.export["execution_result"]
    assert r["status"] == "reconciled" and r["acknowledged"] is False and r["newly_executed"] is False
    bundle = _replay(stack, lost, lost.export)
    pack = _pack(stack, bundle)
    t = _trace(pack)
    assert t["replay_generation"] == _pack_record(stack) and stack.validator.validate_evidence_pack(pack).valid
    res = t["lifecycle_records"]["execution_result"]
    assert len(res) == 1 and res[0]["status"] == "reconciled" and res[0]["acknowledged"] is False and res[0]["newly_executed"] is False
    c = t["derived_counts"]
    base = _trace(_pack(stack, _replay(stack, valid, valid.export)))["derived_counts"]       # P-pack counters for comparison
    assert c["destination_effect_count"] == 1 and c["executor_attempt_count"] == base["executor_attempt_count"], (c, base)   # no second attempt or effect was invented
    assert c["acknowledgement_counts"] != base["acknowledgement_counts"], "a lost acknowledgment must be distinguishable from a positive acknowledgment"
    print("N7-PACK-FACTS", json.dumps(_facts(t), sort_keys=True, default=str))
    print("N7-PACK-P-REFERENCE-COUNTS", json.dumps({k: base.get(k) for k in ("execution_result_state_counts", "acknowledgement_counts", "acknowledgement_sources", "reconciliation_count", "destination_effect_state_counts")}, sort_keys=True, default=str))
    print("N7-PACK-EXECUTION-RESULT", json.dumps(res[0], sort_keys=True, default=str))
    rc, out, err = _cli(stack, pack, tmp_path, "summarize")
    print("N7-PACK-CLI-SUMMARIZE rc=%s\n%s%s" % (rc, out, err))
    assert rc == 0


# ---------------------------------------------------------------------------------------------------------------- N8
def test_n8_replay_missing_export_is_partial_with_no_runtime_records(stack, valid):
    """ITERATION B: Replay-level part of N8."""
    bundle = _replay(stack, valid, None)
    assert bundle["status"] == "reconstruction_partial"
    assert not ({"execution_envelope", "execution_result", "destination_attempt", "destination_effect"} & set(_kinds(bundle))), _kinds(bundle)
    print("N8-REPLAY", json.dumps({"status": bundle["status"], "kinds": _kinds(bundle), "semantics": bundle.get("semantics"),
                                   "moltbot_safe_revision": (bundle.get("metadata") or {}).get("moltbot_safe_revision")}, sort_keys=True, default=str))


def test_n8_pack_missing_export_is_validated_partial_and_counts_are_recorded(stack, valid, tmp_path):
    """N8-pack under S2-CANDIDATE-3. Substantive assertions are unconditional (a missing key raises); descriptive fields are RECORDED, not pre-asserted."""
    bundle = _replay(stack, valid, None)
    assert bundle["status"] == "reconstruction_partial"
    pack = _pack(stack, bundle)
    t = _trace(pack)
    assert t["replay_generation"] == _pack_record(stack) and t["transformation_version"] == PACK_TRANSFORMATION
    assert t["replay_semantic_validation"]["status"] == "validated_partial"
    assert stack.validator.validate_evidence_pack(pack).valid
    c = t["derived_counts"]
    assert c["executor_attempt_count"] == 0 and c["destination_effect_count"] == 0 and c["execution_result_state_counts"] == {}, c
    kinds = t["lifecycle_records"]
    assert not ({"execution_result", "execution_envelope", "destination_attempt", "destination_effect", "executor_observation"} & set(kinds)), sorted(kinds)
    assert set(_collect(t, "independent_verification")) == {"unavailable"}
    assert any("separate namespaces" in str(rule) for rule in (c.get("counting_rules") or t.get("counting_rules") or []) ) or "separate namespaces" in json.dumps(t.get("counting_rules", c.get("counting_rules"))), "counting rules do not state the namespace separation"
    summary = t["lifecycle_summary"]
    assert "execution_attempted" in summary and "destination_observed" in summary             # present (value recorded below)
    print("N8-PACK-FACTS", json.dumps(_facts(t), sort_keys=True, default=str))
    rc, out, err = _cli(stack, pack, tmp_path, "summarize")
    print("N8-PACK-CLI-SUMMARIZE rc=%s\n%s%s" % (rc, out, err))
    assert rc == 0 and ("executor_attempt_count : 0") in out, (rc, out, err)
    rc2, out2, err2 = _cli(stack, pack, tmp_path, "validate")
    print("N8-PACK-CLI-VALIDATE rc=%s\n%s%s" % (rc2, out2, err2))
    assert rc2 == 0
