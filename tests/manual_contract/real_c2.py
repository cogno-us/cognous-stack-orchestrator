"""VSLICE-C2 adapter: Control Plane runtime-profile decision record -> native Replay Bundle import (Python API plus this module's `main`).

Development-only and fixture-scoped. The authority context, resolver state and evidence signatures are synthetic and
unauthenticated (TEST-ONLY public Ed25519 key). The contract exercised here is a CANDIDATE and is not adopted. Hub #280
(digest basis) stays OPEN. Non-authorizing: "IMPORTED" means only that Replay returned a native, PARTIAL reconstruction of
one synthetic Control Plane record; it is not complete replay, qualification, authenticity or effect proof. Only
BoundedAuthorizationWorkflow.decide() is ever called (inside c2_producer), never execute(), reconcile() or apply(). The persisted
record bytes are read once, hashed, parsed from the same buffer and never rewritten. A native Replay refusal is
REFUSED_NATIVE, reported verbatim and distinct from an AdapterError (measurement, fixture or producer failure).
"""
import argparse
import copy
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I omits the script dir
import real_c1  # noqa: E402  (reused: _sha, _obj_bytes, _git, _orchestrator_head, FIXTURE_DIR, FIXTURE_FILES)
import runner  # noqa: E402

ENV_CP_ROOT = "COGNOUS_C2_CONTROL_PLANE_ROOT"
ENV_RB_ROOT = "COGNOUS_C2_REPLAY_BUNDLE_ROOT"
CASE_P1, CASE_N1, CASE_N2 = "c2_p1_runtime_profile_partial", "c2_n1_stored_tenant_tamper", "c2_n2_c1_records_incompatible"
EVIDENCE_SCHEMA = "cognous.orchestrator.c2-evidence/0-candidate"
CONFIG_ID = "C2-CP-RUNTIME-PROFILE-STRICT-TENANT-DECIDE-ONLY"
PINS = {
    "control_plane": {"repository": "cogno-us/cognous-control-plane", "sha": "484fdbd297235dd24148ddb0703f2055a31eabff",
                      "tree": "c182939882103015f12c5360fccf377c54e2c4f9"},
    "replay_bundle": {"repository": "cogno-us/cognous-replay-bundle", "sha": "93a76e281fcae6a65d2cd1d35376f87442dafb95",
                      "tree": "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f"},
}
FROZEN = {
    "proposal_sha256": "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2",
    "c1_records_positive_sha256": "51e4d278b61134fda1db36b4fa82af7e4ad03df761f53c58941b8e9203b70e91",
    "c1_records_negative_sha256": "6a3e188088fe5fa2913ac5b085351175aa8db77e19d19420c8ed68d8a7b8e9cd",
}
ORACLE = {
    "effect_id": "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8",
    "proposal_commitment": "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53",
    "tenant_id": "tenant-alpha", "generation": "bounded-authorization-effect/0.3-strict-tenant",
    "result": "authorized", "reasons": [], "time_source": "test_override", "decided_at": "2026-10-05T19:00:00+00:00",
    "status": "reconstruction_partial", "findings": [["B004", "warning"]],
    "record_types": ["input_time_floors", "resolution_check", "resolution_check_event", "runtime_decision", "runtime_proposal"],
    "reason_vocabulary_version": "runtime-authority-reasons/0.1", "runtime_authority_profile": "runtime-authority/0.1",
    "resolution_inputs": 11, "resolution_checks": 1,
    "adapter_profile": "control-plane-strict-tenant-stack@484fdbd2",
    "n1_message": "decisions[0].binding.tenant_id conflicts with committed operation",
    "n2_message": "typed refusal profile: resolution journal missing",
}
N1_PATH = "decisions[0].binding.tenant_id"
HERE = pathlib.Path(__file__).resolve().parent
PROPOSAL_PATH = real_c1.FIXTURE_DIR / real_c1.FIXTURE_FILES["proposal"]
C1_RECORDS = {  # key -> (fixture path, frozen sha256, hosted run id, artifact id)
    "positive": (HERE / "c2" / "fixtures" / "c1-hosted-native-records.positive.json", FROZEN["c1_records_positive_sha256"], "42067811832", "13433583494"),
    "negative": (HERE / "c2" / "fixtures" / "c1-hosted-native-records.negative.json", FROZEN["c1_records_negative_sha256"], "42068362339", "13434638870"),
}
LIMITS = {  # frozen contract section 8 + section 14 keys, verbatim labels
    "status": "DEVELOPMENT_ONLY_FIXTURE_SCOPED", "authority_basis": "SYNTHETIC_UNAUTHENTICATED_RESOLVER",
    "time_source": "test_override", "clock": "caller_supplied_fixed_clock_developer_only",
    "decision_semantics_only": True, "effect_executed": False, "consistency_only": True,
    "no_key_or_attestation": True, "signature_key_basis": "TEST_ONLY_PUBLIC_SYNTHETIC_ED25519; signatures_prove_nothing_institutional",
    "no_authenticated_issuer": True, "not_authority_reevaluation": True, "not_proof_of_external_effect": True,
    "not_complete_history": "reconstruction_partial; B-codes verbatim", "replay_protection": "none",
    "tenant_generation": "proposal caller-supplied; hold binding null; effect_id does not hash tenant; strict label also accepts legacy; consistent forgery undetected except by external pin",
    "digest_basis": "RB raw dict vs CP model dump", "hub_280_digest_basis": "OPEN",
    "revision_label_caller_declared_in_RB": "measured by adapter from git HEAD/tree (R3)",
    "producer_revision_basis": "measured_source_pin_required; no_revision_or_profile_id_in_cp_record",
    "lineage": "identity_and_proposal_level_not_decision_exact",
    "correlation_id": "not persisted by CP and not independently checked by RB", "hold_bindings": "null",
    "private_cp_api_dependency": "_canonical_bytes (breaks silently on CP change; pin plus file-sha256 check mandatory)",
    "synthetic_key_scope": "public key bytes(range(32)) valid only in this test profile",
    "development_only_fixture_scoped": True, "not_independent_qualification": True, "not_institutional_authority": True,
    "not_general_interoperability": True, "non_authorizing": True,
    "no_certification_clearance_or_production_readiness": "HOLD",
}


class AdapterError(Exception):
    """Measurement, fixture or producer failure. Never a native Replay refusal and never a Control Plane hold."""


class SourceIdentityError(AdapterError):
    """A component root is missing, not the pinned checkout, modified, or an imported module is not the pinned blob."""


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _strict_loads(data):
    """Parse one buffer under the union of the pinned Control Plane and Replay refusal sets (needs measure() to have run):
    non-UTF-8, BOM, duplicate members, NaN/Infinity/overflow, lone surrogates, excess depth. Valid input parses as json.loads."""
    strict_json, ingress = sys.modules.get("agent_control_plane.strict_json"), sys.modules.get("agent_replay_bundle.ingress")
    if strict_json is None or ingress is None:
        raise AdapterError("strict loader requires the measured Control Plane and Replay modules")

    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate object member refused")
        return dict(items)

    def const(name):
        raise ValueError("non-finite number %s refused" % name)
    try:
        text = data.decode("utf-8")
        ingress.check_depth(text)
        strict_json.strict_loads(text)
        return json.loads(text, object_pairs_hook=pairs, parse_constant=const)
    except AdapterError:
        raise
    except Exception as exc:
        raise ValueError("%s: %s" % (type(exc).__name__, str(exc)[:200])) from None


def _git(root, *args):
    """Read-only git with no hooks, user config, optional locks (status must not write the index) or replace refs."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1"}
    try:
        done = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *args], cwd=tempfile.gettempdir(), env=env,
                              capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceIdentityError("git failed for %s: %s" % (root, type(exc).__name__)) from None
    if done.returncode != 0:
        raise SourceIdentityError("%s is not a usable git checkout (git %s failed)" % (root, args[0]))
    return done.stdout.strip()


def _verify_git(key, root, env_name):
    """Exact commit and tree, top level, every ls-files tag H, nothing modified, hidden, untracked or ignored."""
    root = root if root is not None else os.environ.get(env_name)
    if not root or not os.path.isdir(root):
        raise SourceIdentityError("%s: root missing (set %s)" % (key, env_name))
    root, pin = pathlib.Path(root).resolve(), PINS[key]
    head, tree = _git(root, "rev-parse", "HEAD"), _git(root, "rev-parse", "HEAD^{tree}")
    if _git(root, "rev-parse", "--show-toplevel") != str(root):
        raise SourceIdentityError("%s: %s is not the top level of a git checkout" % (key, root))
    if head != pin["sha"] or tree != pin["tree"]:
        raise SourceIdentityError("%s: HEAD/tree %s/%s != pin %s/%s" % (key, head, tree, pin["sha"], pin["tree"]))
    tags = {line[:2] for line in _git(root, "ls-files", "-v").splitlines()}
    if tags != {"H "}:
        raise SourceIdentityError("%s: git ls-files -v shows non-H tags %s" % (key, sorted(tags - {"H "})))
    if _git(root, "status", "--porcelain", "--ignored=matching", "--untracked-files=all") != "":
        raise SourceIdentityError("%s: checkout has modified, untracked or ignored files" % key)
    return root, {"repository": pin["repository"], "pinned_sha": pin["sha"], "observed_head": head, "pinned_tree": pin["tree"],
                  "observed_tree": tree, "tracked_files_clean": True, "ls_files_all_H": True, "status_ignored_clean": True}


def _check_modules(root, ev, package, extra_prefixes=(), required=(), extra_files=()):
    """Every loaded module of `package` (and tests.* for the Control Plane) lies under root and equals its pinned git blob.
    The required module names must be loaded, symlinks and gitlinks are refused, and extra non-module files are blob-checked."""
    blobs = {}
    for line in _git(root, "ls-tree", "-r", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        mode, _, blob = meta.split()
        if mode in ("120000", "160000"):
            raise SourceIdentityError("%s is a symlink or gitlink in the pinned tree" % path)
        blobs[path] = blob
    mods = {}
    for name, mod in sorted(sys.modules.items()):
        mine = name == package or name.startswith(package + ".") or any(name == p or name.startswith(p + ".") for p in extra_prefixes)
        file = getattr(mod, "__file__", None)
        if not file:
            if mine and getattr(mod, "__path__", None) and name in extra_prefixes:
                paths = [pathlib.Path(p).resolve() for p in mod.__path__]
                if not paths or any(root not in p.parents and p != root for p in paths):
                    raise SourceIdentityError("namespace package %s is not under %s" % (name, root))
            continue
        path = pathlib.Path(file).resolve()
        if mine and pathlib.Path(file) != path:
            raise SourceIdentityError("module %s is reached through a symlink" % name)
        if mine and root not in path.parents:
            raise SourceIdentityError("module %s imported from %s, not under %s" % (name, path, root))
        if root not in path.parents:
            continue
        data = path.read_bytes()
        blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
        rel = path.relative_to(root).as_posix()
        if blobs.get(rel) != blob:
            raise SourceIdentityError("module %s (%s) differs from the pinned git blob" % (name, rel))
        mods[name] = {"file": str(path), "git_blob_sha": blob, "sha256": _sha(data)}
    missing = sorted(set(required) - set(mods))
    if missing or not mods:
        raise SourceIdentityError("required modules not loaded from the pinned tree: %s" % (missing or "none loaded"))
    for rel in extra_files:
        data = (root / rel).read_bytes()
        if blobs.get(rel) != hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest():
            raise SourceIdentityError("%s differs from the pinned git blob" % rel)
        mods[rel] = {"file": str(root / rel), "git_blob_sha": blobs[rel], "sha256": _sha(data)}
    ev["imported_modules"] = mods


_CP_TESTS = ("tests",)


def measure(cp_root=None, rb_root=None):
    """Verify git identity of both roots BEFORE touching sys.path, then import and verify the loaded modules."""
    if not sys.flags.isolated:
        raise AdapterError("run under `python -I -B`: the environment, cwd and script directory must not shape imports")
    cp_root, cp_ev = _verify_git("control_plane", cp_root, ENV_CP_ROOT)
    rb_root, rb_ev = _verify_git("replay_bundle", rb_root, ENV_RB_ROOT)
    sys.dont_write_bytecode = True
    shadow = sys.modules.get("tests")  # the CP helper package is named `tests`: never let another tree's bind first
    if shadow is not None and cp_root not in pathlib.Path(getattr(shadow, "__file__", None) or "/").resolve().parents:
        raise SourceIdentityError("a module named `tests` is already loaded from outside the pinned Control Plane tree")
    for entry in (str(rb_root / "src"), str(cp_root), str(cp_root / "src")):
        if entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)
    import agent_control_plane
    import agent_control_plane.bounded as bounded
    from agent_replay_bundle import importers
    import agent_replay_bundle
    for root, ev, pkg in ((cp_root, cp_ev, agent_control_plane), (rb_root, rb_ev, agent_replay_bundle)):
        if root not in pathlib.Path(pkg.__file__).resolve().parents:
            raise SourceIdentityError("%s imported from %s, not under %s" % (pkg.__name__, pkg.__file__, root))
        ev["imported_module_file"] = str(pathlib.Path(pkg.__file__).resolve())
    _check_modules(cp_root, cp_ev, "agent_control_plane", _CP_TESTS, required=("agent_control_plane.bounded",))
    _check_modules(rb_root, rb_ev, "agent_replay_bundle", required=("agent_replay_bundle.importers",))
    label = cp_ev["observed_head"]
    if label != importers.CONTROL_PLANE_STRICT_TENANT_REVISION:  # consistency check only; the label itself is the measurement
        raise SourceIdentityError("measured Control Plane head differs from the Replay strict-tenant revision constant")
    return {"control_plane": cp_ev, "replay_bundle": rb_ev, "revision_label": label, "_roots": (cp_root, rb_root),
            "_modules": (bounded, importers)}


def _recheck(measured, helpers=True):
    """Lazy imports during produce()/import must also equal the pinned blobs (helpers=False: no producer ran, e.g. N2)."""
    cp_root, rb_root = measured["_roots"]
    names = ("agent_control_plane.bounded",) + (("tests", "tests.test_bounded_authorization", "tests.test_runtime_authority") if helpers else ())
    _check_modules(cp_root, measured["control_plane"], "agent_control_plane", _CP_TESTS, required=names,
                   extra_files=("tests/fixtures/refund_integration_v1_1.manifest.json",) if helpers else ())
    _check_modules(rb_root, measured["replay_bundle"], "agent_replay_bundle", required=("agent_replay_bundle.importers",))


def _public(measured):
    return {"control_plane": measured["control_plane"], "replay_bundle": measured["replay_bundle"],
            "revision_label": measured["revision_label"], "revision_label_basis": "measured_git_head_and_tree"}


def _read_fixture(path, expected_sha, what):
    try:
        data = pathlib.Path(path).read_bytes()  # read once: the verified bytes are the parsed bytes
    except OSError as exc:
        raise AdapterError("%s fixture unreadable: %s" % (what, type(exc).__name__)) from None
    if _sha(data) != expected_sha:
        raise AdapterError("%s fixture sha256 differs from the frozen value" % what)
    try:
        return data, _strict_loads(data)
    except ValueError as exc:
        raise AdapterError("%s fixture is not strict JSON: %s" % (what, exc)) from None


def _runtime():
    import importlib.metadata as md
    import pydantic
    out = {"python": sys.version.split()[0], "pydantic": pydantic.VERSION}
    try:
        out["cryptography"] = md.version("cryptography")
    except md.PackageNotFoundError:
        out["cryptography"] = None
    return out


def _harness():
    files = {"real_c2_sha256": pathlib.Path(__file__), "real_c1_sha256": pathlib.Path(real_c1.__file__),
             "runner_sha256": pathlib.Path(runner.__file__)}
    out = {k: _sha(p.read_bytes()) for k, p in files.items()}
    prod = sys.modules.get("c2_producer")
    if prod is not None:
        out["c2_producer_sha256"] = _sha(pathlib.Path(prod.__file__).read_bytes())
    out["orchestrator_head"] = real_c1._orchestrator_head()
    return out


def _native(exc):
    return {"type": type(exc).__name__, "message": str(exc), "code": getattr(exc, "code", None)}


def _import(importers, record_obj, proposal_obj, label):
    """The ONLY Replay call. Proposal always supplied, label always the measured one. Returns (bundle, None) or (None, native)."""
    if proposal_obj is None:
        raise AdapterError("proposal is mandatory (R4)")
    try:
        return importers.import_bounded_workflow(record_obj, proposal=proposal_obj, control_plane_revision=label), None
    except importers.ImportContractError as exc:
        return None, _native(exc)
    except Exception as exc:  # unknown failure class: neither a native refusal nor evidence
        raise AdapterError("unexpected Replay exception %s: %s" % (type(exc).__name__, str(exc)[:200])) from None


def _fresh_workdir(workdir):
    work = pathlib.Path(workdir) if workdir is not None else pathlib.Path(tempfile.mkdtemp(prefix="c2-"))
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        raise AdapterError("workdir %s is not empty; a Control Plane record store would resume old state" % work)
    return work


def _check(name, expected, observed):
    return {"name": name, "expected": expected, "observed": observed, "ok": expected == observed}


def _bundle_view(bundle, record_obj, has_check_events):
    decs = [r for r in bundle.records if r.record_type == "runtime_decision"]
    findings = [[f.code, f.severity] for rep in bundle.import_reports for f in rep.findings]
    return {"outcome": "IMPORTED", "status": bundle.status, "findings": findings,
            "record_types": sorted({r.record_type for r in bundle.records}),
            "counts": {k: len(record_obj.get(k) or []) for k in ("attempts", "observations", "reconciliations", "closeouts")},
            "has_check_events": has_check_events, "runtime_decision_records": len(decs),
            "import_reports": [{"adapter_profile": r.adapter_profile, "source_revision": r.source_revision, "rb_complete_flag": r.complete}
                               for r in bundle.import_reports]}, (decs[0].data if len(decs) == 1 else None)


def _p1(cp_root, rb_root, workdir):
    measured = measure(cp_root, rb_root)
    bounded, importers = measured["_modules"]
    prop_bytes, proposal = _read_fixture(PROPOSAL_PATH, FROZEN["proposal_sha256"], "proposal")
    c1_bytes, c1_rec = _read_fixture(C1_RECORDS["positive"][0], C1_RECORDS["positive"][1], "C1 positive records")
    work = _fresh_workdir(workdir)
    import c2_producer
    try:
        produced = c2_producer.produce(measured["_roots"][0], work, copy.deepcopy(proposal))
    except AdapterError:
        raise
    except Exception as exc:
        raise AdapterError("producer failed: %s: %s" % (type(exc).__name__, str(exc)[:200])) from None
    rec_bytes = pathlib.Path(produced.record_path).read_bytes()  # persisted bytes: read ONCE
    rec_sha = _sha(rec_bytes)
    try:
        record = _strict_loads(rec_bytes)  # parse the SAME buffer
    except ValueError as exc:
        raise AdapterError("persisted record is not strict JSON: %s" % exc) from None
    try:
        dest = _strict_loads(pathlib.Path(produced.destination_path).read_bytes())
        effects = dest.get("effects") if isinstance(dest, dict) else None
    except (OSError, ValueError):
        effects = None
    check_events = record.get("check_events")
    has_ce = isinstance(check_events, list) and bool(check_events)
    persisted = copy.deepcopy(record["decisions"][0])
    bundle, refusal = _import(importers, record, proposal, measured["revision_label"])
    unchanged = pathlib.Path(produced.record_path).read_bytes() == rec_bytes  # verification re-read only; hash/parse used the first buffer
    if not unchanged:
        raise AdapterError("persisted record file changed during import (adapter must never rewrite it)")
    _recheck(measured)
    ev = {"schema": EVIDENCE_SCHEMA, "case_id": CASE_P1, "producer_config_id": CONFIG_ID, "sources": _public(measured),
          "runtime": _runtime(), "producer": produced.provenance,
          "clock": {"now": ORACLE["decided_at"], "allow_test_time": True, "developer_only_override": True,
                    "clock_patch": produced.provenance.get("clock_patch")},
          "inputs": {"proposal": {"sha256": _sha(prop_bytes), "sha256_of": "file_bytes", "frozen_sha256": FROZEN["proposal_sha256"]}},
          "record": {"sha256": rec_sha, "size_bytes": len(rec_bytes), "path": str(produced.record_path), "sha256_of": "file_bytes",
                     "unchanged_after_import": unchanged, "per_run_not_frozen": True},
          "native_cp_decision": produced.decision,
          "destination": {"path": str(produced.destination_path), "effects": effects, "effect_count": None if effects is None else len(effects)},
          "limits": dict(LIMITS), "harness": _harness(), "workdir": str(work)}
    c1_dec = c1_rec["decisions"][0]
    if refusal is not None:
        ev["native_replay"] = {"outcome": "REFUSED_NATIVE", **refusal}
        ev.update(outcome="REFUSED_NATIVE", status="FAIL", oracle={"checks": [_check("replay_imported", "IMPORTED", "REFUSED_NATIVE")], "all_ok": False})
        return ev, record, proposal, measured, rec_sha
    view, dec = _bundle_view(bundle, record, has_ce)
    ev["native_replay"] = view
    d = dec or {}
    bind = d.get("binding") or {}
    events = check_events if has_ce else []
    checks = [
        _check("rb_status", ORACLE["status"], view["status"]), _check("rb_findings", ORACLE["findings"], view["findings"]),
        _check("rb_import_report", [{"adapter_profile": ORACLE["adapter_profile"], "source_revision": measured["revision_label"], "rb_complete_flag": False}],
               view["import_reports"]),
        _check("record_types", ORACLE["record_types"], view["record_types"]),
        _check("one_runtime_decision_record", 1, view["runtime_decision_records"]),
        _check("decision_result", ORACLE["result"], d.get("result")), _check("decision_reasons", ORACLE["reasons"], d.get("reasons")),
        _check("time_source", ORACLE["time_source"], d.get("time_source")), _check("decided_at", ORACLE["decided_at"], d.get("decided_at")),
        _check("tenant_id", ORACLE["tenant_id"], bind.get("tenant_id")), _check("generation", ORACLE["generation"], bind.get("generation")),
        _check("effect_id", ORACLE["effect_id"], d.get("effect_id")),
        _check("proposal_commitment", ORACLE["proposal_commitment"], bind.get("proposal_commitment")),
        _check("attempts_observations_reconciliations_closeouts", {k: 0 for k in view["counts"]}, view["counts"]),
        _check("destination_effects", {}, effects),
        _check("reason_vocabulary_version", ORACLE["reason_vocabulary_version"], d.get("reason_vocabulary_version")),
        _check("runtime_authority_profile", ORACLE["runtime_authority_profile"], (bind.get("runtime_authority") or {}).get("profile")),
        _check("check_events_present", True, has_ce),
        _check("check_events_decision_id_observed_null", True, bool(events) and all("decision_id" in e and e["decision_id"] is None for e in events)),
        _check("check_events_proposal_commitment", True, bool(events) and all(e.get("proposal_commitment") == ORACLE["proposal_commitment"] for e in events)),
        _check("check_events_vocabulary", True, bool(events) and all(e.get("reason_vocabulary_version") for e in events)),
        _check("resolution_inputs", ORACLE["resolution_inputs"], len(d.get("resolution_inputs") or [])),
        _check("resolution_checks", ORACLE["resolution_checks"], len(record.get("resolution_checks") or [])),
        _check("decision_id_differs_from_c1", True, d.get("decision_id") != c1_dec.get("decision_id")),
        _check("producer_decision_equals_persisted", True, produced.decision == persisted),
        _check("record_file_unchanged_after_import", True, unchanged)]
    same = lambda a, b: a == b  # noqa: E731
    c1b = c1_dec.get("binding") or {}
    ev["lineage"] = {
        "level": "identity_and_proposal_level_not_decision_exact", "c1_records_sha256": _sha(c1_bytes),
        "equal": {"effect_id": same(d.get("effect_id"), c1_dec.get("effect_id")),
                  "proposal_commitment": same(bind.get("proposal_commitment"), c1b.get("proposal_commitment")),
                  "tenant_id": same(bind.get("tenant_id"), c1b.get("tenant_id")), "generation": same(bind.get("generation"), c1b.get("generation")),
                  "result": same(d.get("result"), c1_dec.get("result")), "run_id": same(record.get("run_id"), c1_rec.get("run_id")),
                  "decided_at": same(d.get("decided_at"), c1_dec.get("decided_at")), "time_source": same(d.get("time_source"), c1_dec.get("time_source")),
                  "proposal_fixture": True},
        "new": {"decision_id_differs": d.get("decision_id") != c1_dec.get("decision_id"), "check_events_present": has_ce,
                "c1_check_events_present": "check_events" in c1_rec, "binding_runtime_authority": "runtime_authority" in bind,
                "c1_binding_runtime_authority": "runtime_authority" in c1b, "reason_vocabulary_version": d.get("reason_vocabulary_version"),
                "record_sha256_differs": rec_sha != _sha(c1_bytes)},
        "forbidden_claims": ["same decision", "C1 record accepted by RB"]}
    ok = all(c["ok"] for c in checks)
    ev["oracle"] = {"checks": checks, "all_ok": ok}
    ev["frozen_oracle_deviations"] = [{
        "contract_section": "freeze §14 'P1 journal assertions' (Hub #273 comment 6665220369)",
        "frozen_text": "every check_events entry's decision_id equals decisions[0].decision_id",
        "observed": {"event_decision_ids": sorted({str(e.get("decision_id")) for e in events}), "event_count": len(events),
                     "event_check_ids_distinct": len({e.get("check_id") for e in events}),
                     "events_check_id_equals_resolution_check_id": any(e.get("check_id") == (record.get("resolution_checks") or [{}])[0].get("check_id") for e in events)},
        "handling": "frozen text NOT silently replaced: the observed value is asserted instead (all null); a frozen-literal test is kept as an expected failure",
        "identity_binding_asserted_instead": "every check_event proposal_commitment equals the decision's proposal commitment",
        "disposition": "contract amendment requested from the Architect"}]
    ev.update(outcome="IMPORTED", status="PASS" if ok else "FAIL")
    return ev, record, proposal, measured, rec_sha


def run_p1(cp_root=None, rb_root=None, workdir=None):
    return _p1(cp_root, rb_root, workdir)[0]


def run_n1(cp_root=None, rb_root=None, workdir=None):
    p1, record, proposal, measured, rec_sha = _p1(cp_root, rb_root, workdir)
    _, importers = measured["_modules"]
    ev = {"schema": EVIDENCE_SCHEMA, "case_id": CASE_N1, "sources": p1["sources"], "runtime": p1["runtime"], "producer": p1["producer"],
          "limits": dict(LIMITS), "harness": p1["harness"], "inputs": p1["inputs"],
          "p1_precondition": {"outcome": p1["outcome"], "status": p1["status"], "record_sha256": rec_sha}}
    if p1["outcome"] != "IMPORTED":
        ev.update(outcome="FAIL", status="FAIL", reason="N1 precondition: the unmodified P1 record was not imported")
        return ev
    mutated = copy.deepcopy(record)
    binding = mutated["decisions"][0]["binding"]
    if binding.get("tenant_id") != ORACLE["tenant_id"]:
        raise AdapterError("N1 precondition: decisions[0].binding.tenant_id is not %s" % ORACLE["tenant_id"])
    binding["tenant_id"] = "tenant-beta"  # the ONLY change
    bundle, refusal = _import(importers, mutated, copy.deepcopy(proposal), p1["sources"]["revision_label"])
    _recheck(measured)
    ev["mutation"] = {"field_path": N1_PATH, "from": ORACLE["tenant_id"], "to": "tenant-beta", "original_record_sha256": rec_sha,
                      "mutated_input_sha256": _sha(real_c1._obj_bytes(mutated)), "sha256_of": "canonical_reserialisation_of_test_mutation",
                      "proposal_supplied": True, "proposal_sha256": p1["inputs"]["proposal"]["sha256"]}
    if refusal is None:
        ev.update(native_replay={"outcome": "IMPORTED", "status": bundle.status}, outcome="FAIL", status="FAIL",
                  reason="tampered record was imported; expectation not met")
        return ev
    ok = refusal["type"] == "ImportContractError" and refusal["message"] == ORACLE["n1_message"]
    ev.update(native_replay={"outcome": "REFUSED_NATIVE", **refusal}, outcome="REFUSED_NATIVE" if ok else "FAIL",
              tenant_check_reached=refusal["message"] == ORACLE["n1_message"],
              oracle={"checks": [_check("exception_type", "ImportContractError", refusal["type"]),
                                 _check("message", ORACLE["n1_message"], refusal["message"])], "all_ok": ok},
              status="PASS" if ok else "FAIL")
    return ev


def run_n2(cp_root=None, rb_root=None):
    measured = measure(cp_root, rb_root)
    _, importers = measured["_modules"]
    _, proposal = _read_fixture(PROPOSAL_PATH, FROZEN["proposal_sha256"], "proposal")
    items, all_ok = {}, True
    for key, (path, sha, run_id, artifact_id) in C1_RECORDS.items():
        data, rec = _read_fixture(path, sha, "C1 %s records" % key)
        bundle, refusal = _import(importers, rec, copy.deepcopy(proposal), measured["revision_label"])  # never another label
        ok = refusal is not None and refusal["type"] == "ImportContractError" and refusal["message"] == ORACLE["n2_message"]
        all_ok &= ok
        items[key] = {"records_sha256": _sha(data), "sha256_of": "file_bytes", "hosted_run_id": run_id, "hosted_artifact_id": artifact_id,
                      "native_replay": ({"outcome": "REFUSED_NATIVE", **refusal} if refusal else {"outcome": "IMPORTED", "status": bundle.status}),
                      "ok": ok}
    _recheck(measured, helpers=False)
    return {"schema": EVIDENCE_SCHEMA, "case_id": CASE_N2, "sources": _public(measured), "runtime": _runtime(), "records": items,
            "expected_message": ORACLE["n2_message"], "label_policy": "measured genuine label only; never retried under another label",
            "limits": dict(LIMITS), "harness": _harness(), "outcome": "REFUSED_NATIVE" if all_ok else "FAIL",
            "status": "PASS" if all_ok else "FAIL"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one VSLICE-C2 case (development-only, fixture-scoped, non-authorizing).")
    parser.add_argument("--case", required=True)
    parser.add_argument("--out")
    parser.add_argument("--workdir")
    args = parser.parse_args(argv)
    cases = {CASE_P1: run_p1, CASE_N1: run_n1, CASE_N2: None}
    if args.case not in cases:
        print("refused: case id is not allowlisted", file=sys.stderr)
        return 2
    try:
        ev = run_n2() if args.case == CASE_N2 else cases[args.case](workdir=args.workdir)
    except AdapterError as exc:
        print("adapter error: %s" % exc, file=sys.stderr)
        return 2
    text = json.dumps(ev, indent=2, sort_keys=True, default=str) + "\n"
    if args.out:
        pathlib.Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0 if ev["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
