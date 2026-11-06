"""VSLICE-C4 coordinator: Action Manifest gate -> Control Plane -> Replay Bundle -> Governance Evidence Pack (Python API plus `main`).

Development-only and fixture-scoped; implements the C4 v0.1 development contract (Hub #273 comment 6674059997, frozen for
development by the Architect decision A1-A9). One coordinator invocation drives, in one process on the same bytes:
AM native gate on the manifest bytes -> Control Plane decide() only (c4_producer, scenario `authorized` or `grant_revoked`) ->
persisted CP record -> Replay import_bounded_workflow -> ONE persisted ReconstructionBundle 0.2.0 -> Pack import and validation.
N2 mutates one field of a deep copy of the N1 bundle and expects the Pack's native structural refusal.

Non-authorizing. Every boundary keeps its native outcome verbatim and its own orchestration class; a downstream ACCEPTED import of a
held decision is evidence import only, never acceptance of the action. PASS means only that observations equal the frozen oracle.
Authority, resolver state and evidence signatures are synthetic and unauthenticated (TEST-ONLY public key). Developer scope: no
qualification, no certification or clearance (HOLD), no production use. The Action Manifest component produces no proposal and no
output a later component consumes (L20): its edge is a native gate plus pass-through of the same validated bytes.

Helpers are COPIED and generalised from the C1 and C3 adapters; nothing underscore-private is imported from them. Reused public
symbols: real_c3.measure / AdapterError / SourceIdentityError / LIMITS (read as data) and c4_producer.produce.
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
import uuid

sys.dont_write_bytecode = True  # never write .pyc into the pinned checkouts: their cleanliness is part of the source gate
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I omits the script dir
import c2_producer  # noqa: E402  (file hash pinned below; C2 must stay unchanged)
import c4_producer  # noqa: E402
import real_c3  # noqa: E402  (public measure / error classes / LIMITS-as-data only)

SCHEMA = "cognous.orchestrator.c4-evidence/0-candidate"
CASE_P1, CASE_N1, CASE_N2 = "c4_p1_authorized_chain", "c4_n1_hold_revoked_grant", "c4_n2_flip_hold_to_authorized"
CASES = (CASE_P1, CASE_N1, CASE_N2)
ENV = {"action_manifest": "COGNOUS_C4_ACTION_MANIFEST_ROOT", "control_plane": "COGNOUS_C4_CONTROL_PLANE_ROOT",
       "replay_bundle": "COGNOUS_C4_REPLAY_BUNDLE_ROOT", "evidence_pack": "COGNOUS_C4_EVIDENCE_PACK_ROOT"}
PINS = {
    "action_manifest": {"repository": "cogno-us/cognous-action-manifest", "sha": "fa170815ef96a54c233d0dd9da821b60debabf8b",
                        "tree": "3b0e3772e944aa668c8f4b879588c7cc3e2c32be"},
    "control_plane": {"repository": "cogno-us/cognous-control-plane", "sha": "484fdbd297235dd24148ddb0703f2055a31eabff",
                      "tree": "c182939882103015f12c5360fccf377c54e2c4f9"},
    "replay_bundle": {"repository": "cogno-us/cognous-replay-bundle", "sha": "93a76e281fcae6a65d2cd1d35376f87442dafb95",
                      "tree": "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f"},
    "evidence_pack": {"repository": "cogno-us/cognous-governance-evidence-pack", "sha": "065150852cc2a8abeb748777bb69d72ccd0e03d8",
                      "tree": "fe428a89da2e74346648cdfe014462ddc8624c77"},
}
MANIFEST_RELATIVE_PATH = "examples/refund_integration_v1_1.manifest.json"
FROZEN = {
    "manifest_file_sha256": "789ad39596b9e1ef84a726a671883e1cb6b83343da3a31db0a1120906d68c074",
    "manifest_digest": "sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac",
    "proposal_sha256": "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2",
    "proposal_commitment": "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53",
    "c2_producer_sha256": "7c4f2595d7939e4a373586faafc0de86469dc03b791d893d7b27fb328a02a895",
    "real_c3_sha256": "c92883af328f5127a395571887a72ceffccdfbe4d6c983d5c62ff9a21d64c31b",  # base aff43bdd file bytes: its public measure() runs first
    "effect_id_authorized": "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8",
    "effect_id_hold": "sha256:d0e4afe09cdf3a52aa3b530b822411b1dff35031973660fbbf9b707415f18465",
    "action_id": "urn:cognous:action:refund-issue-routine-v1", "tenant_id": "tenant-alpha",
    "generation": "bounded-authorization-effect/0.3-strict-tenant", "authority_profile": "runtime-authority/0.1",
    "reason_vocabulary_version": "runtime-authority-reasons/0.1", "decided_at": "2026-10-05T19:00:00+00:00",
    "pack_version": "0.2.0", "review_status": "draft",
    "transformation_version": "agep-manifest-reconstruction-import/0.3.10-strict-tenant-candidate",
    "validator": "agent_replay_bundle.importers.import_bounded_workflow",
}
ZERO_COUNT_KEYS = ("control_plane_attempt_count", "executor_attempt_count", "attempt_transition_record_count", "destination_effect_count",
                   "effect_observation_count", "reconciliation_count")
RB_RECORD_TYPES = ["input_time_floors", "resolution_check", "resolution_check_event", "runtime_decision", "runtime_proposal"]
HERE = pathlib.Path(__file__).resolve().parent
PROPOSAL_PATH = HERE / "c1" / "fixtures" / "proposal.tenant-alpha.json"
BOUNDARIES = ("action_manifest", "control_plane", "replay_bundle", "evidence_pack")
EXPECTED_OPEN_ADVERSE = {
    "n2_scope": "N2 is a Pack structural refusal (an authorized decision must carry a binding); Replay does not refuse the flip and this is not "
                "a general anti-forgery guarantee. A coordinated flip is refused differently and is not exercised here.",
}

_C3 = real_c3.LIMITS  # read as data: L1-L19 are carried verbatim, never reworded
LIMITS = copy.deepcopy({k: v for k, v in _C3.items()})
assert all(("L%d" % i) in LIMITS for i in range(1, 20)), "real_c3.LIMITS must carry L1-L19"
LIMITS.update({
    "L20": "The Action Manifest component produces no proposal and no output a later component consumes; the proposal is a hand-authored "
           "hash-pinned fixture and AM only validates/binds.",
    "L21": "C4's CP decision comes from the profile-enabled configuration, not the C1 configuration; C1 hosted runs relate to C4 at identity "
           "level only and are not the C4 decision.",
    "L22": "For a hold, Replay does not bind the supplied proposal, tenant, action or correlation to the record and the Pack's EvidencePack "
           "model has no first-class tenant field; refusal continuity is checked natively only for manifest id/version/digest (Pack) and is "
           "otherwise orchestrator-extracted.",
    "L23": "effect_id differs by verdict.",
    "L24": "run-1 is a literal, not a run identity; no native per-run end-to-end identity exists.",
    "L25": "NOT_ATTEMPTED, REFUSED and held as orchestration labels are not component statuses and prove no absence of effect beyond "
           "decide()-only plus observed {}.",
    "L26": "The hold scenario is a synthetic grant-status input variation on test-only helpers, not a real revocation event.",
    "L27": "The producer configuration id is persisted by no component; deny and effect-time refusal paths are unexercised.",
    "scenario_qualifications": {
        "P1": "L1 is exactly B004; the lifecycle authorization reads authorized (historical, not current permission).",
        "N1_HOLD": "Replay status is reconstruction_partial (never complete) with findings {B004, B005}; the lifecycle authorization reads held; "
                   "L13 is narrowed by L22 (for a hold neither Replay nor the Pack verifies tenant). Downstream ACCEPTED means evidence "
                   "imported, never acceptance of the action.",
        "N2_FLIP": "Pack structural refusal only (L22 applies); Replay does not refuse the flip.",
    },
    "chain_verdict_semantics": "earliest non-ACCEPTED boundary; PASS means observations equal the frozen oracle, never authorization",
    "values_not_golden": ["decision_id", "check_id", "bundle_id", "generated_at", "pack_id", "cp_record_sha256", "bundle_h1_sha256",
                          "bundle_h2_pack_canonical_sha256", "pack_file_sha256", "coordinator_invocation_uuid", "github_run_id"],
})
KNOWN_NOT_EXECUTED = [
    "N3-GATE (deferred: the freeze does not pin the mutated byte; not implemented here)", "CP deny path (never emitted by decide())",
    "effect-time refusal via a real executor", "C1 hosted records through Replay (incompatible, identity-level only)",
    "coordinated hold-to-authorized flip", "revocation or stale replay, partial failure, real executor export", "signatures, custody, freshness",
    "replay/redelivery defence", "complete reconstruction", "agep CLI cross-check", "Pack execution gates"]
AdapterError, SourceIdentityError = real_c3.AdapterError, real_c3.SourceIdentityError


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _native(exc):
    return {"type": type(exc).__name__, "message": str(exc), "code": getattr(exc, "code", None)}


def _check(name, expected, observed):
    return {"name": name, "expected": expected, "observed": observed, "ok": expected == observed}


def _dump_bytes(obj):
    """Bundle serialisation exactly as C3: indent 2, sorted keys, trailing newline; no integrity entry, nothing added or dropped."""
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _strict_loads(data):
    """Parse one buffer under the union of the pinned Control Plane and Replay refusal sets (needs measure() first)."""
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
    """Read-only git with no hooks, user config, optional locks or replace refs."""
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


def _check_am_modules(root, ev):
    """Every loaded agent_action_manifest module lies under root, is not a symlink and equals its pinned git blob."""
    blobs = {}
    for line in _git(root, "ls-tree", "-r", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        mode, _, blob = meta.split()
        if mode in ("120000", "160000"):
            raise SourceIdentityError("%s is a symlink or gitlink in the pinned tree" % path)
        blobs[path] = blob
    mods = {}
    for name, mod in sorted(sys.modules.items()):
        if not (name == "agent_action_manifest" or name.startswith("agent_action_manifest.")):
            continue
        file = getattr(mod, "__file__", None)
        if not file:
            continue
        path = pathlib.Path(file).resolve()
        if pathlib.Path(file) != path:
            raise SourceIdentityError("module %s is reached through a symlink" % name)
        if root not in path.parents:
            raise SourceIdentityError("module %s imported from %s, not under %s" % (name, path, root))
        data = path.read_bytes()
        blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
        rel = path.relative_to(root).as_posix()
        if blobs.get(rel) != blob:
            raise SourceIdentityError("module %s (%s) differs from the pinned git blob" % (name, rel))
        mods[name] = {"file": str(path), "git_blob_sha": blob, "sha256": _sha(data)}
    missing = sorted({"agent_action_manifest.loader", "agent_action_manifest.binding", "agent_action_manifest.models"} - set(mods))
    if missing:
        raise SourceIdentityError("required Action Manifest modules not loaded from the pinned tree: %s" % missing)
    ev["imported_modules"] = mods


def _measure(roots):
    """Public real_c3.measure on explicit roots (git identity of all four + CP/RB/Pack module blobs), then the AM import-by-path check."""
    if not sys.flags.isolated:
        raise AdapterError("run under `python -I -B`: the environment, cwd and script directory must not shape imports")
    measured = real_c3.measure({k: roots[k] for k in BOUNDARIES})
    am_root = pathlib.Path(measured["_roots"]["action_manifest"])
    entry = str(am_root / "src")
    if entry in sys.path:
        sys.path.remove(entry)
    sys.path.insert(0, entry)
    import agent_action_manifest as am_pkg
    from agent_action_manifest import models as am_models
    if am_root not in pathlib.Path(am_pkg.__file__).resolve().parents:
        raise SourceIdentityError("agent_action_manifest imported from %s, not under %s" % (am_pkg.__file__, am_root))
    sources = copy.deepcopy(measured["sources"])
    sources["action_manifest"]["imported_module_file"] = str(pathlib.Path(am_pkg.__file__).resolve())
    _check_am_modules(am_root, sources["action_manifest"])
    return {"measured": measured, "roots": measured["_roots"], "sources": sources, "revision_label": measured["revision_label"],
            "P": measured["_modules"], "am": am_pkg, "am_models": am_models, "am_root": am_root, "input_roots": {k: roots[k] for k in BOUNDARIES}}


def _recheck(ctx):
    """Lazy imports and the run itself must leave every pinned tree and loaded module equal to its pin (re-measure, public API)."""
    real_c3.measure(ctx["input_roots"])
    _check_am_modules(ctx["am_root"], {})


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
    root = HERE.parent.parent
    try:
        head, dirty = _git(root, "rev-parse", "HEAD"), _git(root, "status", "--porcelain", "--untracked-files=no") != ""
    except SourceIdentityError:
        head, dirty = None, None
    h = {"orchestrator": {"head": head, "tracked_files_modified": dirty}}
    for key, mod in (("real_c4", sys.modules[__name__]), ("c4_producer", c4_producer), ("c2_producer", c2_producer), ("real_c3", real_c3)):
        h[key + "_sha256"] = _sha(pathlib.Path(mod.__file__).read_bytes())
    return h


def _harness_run_ref(invocation):
    env = os.environ.get
    return {"coordinator_invocation_uuid": invocation, "github_run_id": env("GITHUB_RUN_ID"), "github_run_attempt": env("GITHUB_RUN_ATTEMPT"),
            "github_sha": env("GITHUB_SHA")}


# ---------------------------------------------------------------- inputs and the AM native gate
def _read_once(path, expected_sha, what):
    try:
        data = pathlib.Path(path).read_bytes()  # read ONCE: the hashed bytes are the parsed bytes and the persisted bytes
    except OSError as exc:
        raise AdapterError("%s fixture unreadable: %s" % (what, type(exc).__name__)) from None
    return data, _sha(data) == expected_sha


class _GateStop(Exception):
    def __init__(self, klass, step, message, native=None):
        super().__init__(message)
        self.klass, self.step, self.native = klass, step, native


def _am_gate(ctx, man_bytes, prop_bytes, man_hash_ok, prop_hash_ok):
    """AM native gate on the SAME buffer that is hashed, persisted and passed on. Never raises for a gate outcome: returns a record.
    BLOCKED = precondition/gate stopped the chain (orchestrator verdict); FAILED = AM load error. Returns (record, manifest_obj, proposal)."""
    am, models, bounded = ctx["am"], ctx["am_models"], ctx["P"]["bounded"]
    rec = {"passed": False, "class": "BLOCKED", "step": None, "failure": None, "valid": None, "manifest_version": None,
           "manifest_digest": None, "cp_manifest_commitment": None, "proposal_digest": None, "proposal_mismatches": None,
           "manifest_file_sha256": _sha(man_bytes), "proposal_file_sha256": _sha(prop_bytes), "native_exception": None}
    raw = proposal = None
    step = "manifest_bytes"
    try:
        if not man_hash_ok:
            raise _GateStop("BLOCKED", step, "manifest file sha256 differs from the frozen value")
        if not prop_hash_ok:
            raise _GateStop("BLOCKED", "proposal_bytes", "proposal file sha256 differs from the frozen value")
        step = "manifest_parse"
        try:
            raw, proposal = _strict_loads(man_bytes), _strict_loads(prop_bytes)
        except ValueError as exc:
            raise _GateStop("FAILED", step, "input is not strict JSON: %s" % exc) from None
        if not isinstance(raw, dict) or not isinstance(proposal, dict):
            raise _GateStop("FAILED", step, "manifest and proposal must be JSON objects")
        step = "manifest_load"
        try:
            model = am.load_manifest_json(copy.deepcopy(raw))  # the dict parsed from the SAME buffer
        except am.ManifestLoadError as exc:
            raise _GateStop("FAILED", step, str(exc)[:300], _native(exc)) from None
        step = "manifest_validate"
        rec["valid"] = am.validate_manifest(model).valid
        if rec["valid"] is not True:
            raise _GateStop("BLOCKED", step, "Action Manifest validate_manifest reports invalid")
        step = "manifest_version"
        rec["manifest_version"] = model.manifest_version
        if model.manifest_version != "1.1":
            raise _GateStop("BLOCKED", step, "manifest_version is %r, not '1.1'" % (model.manifest_version,))
        step = "manifest_digest"
        rec["manifest_digest"], rec["cp_manifest_commitment"] = am.manifest_digest(model), bounded.commitment(raw)
        if rec["manifest_digest"] != FROZEN["manifest_digest"]:
            raise _GateStop("BLOCKED", step, "manifest_digest differs from the frozen value")
        if rec["manifest_digest"] != rec["cp_manifest_commitment"]:
            raise _GateStop("BLOCKED", step, "digest basis divergence between Action Manifest and Control Plane (Hub #280, open, gated not fixed)")
        step = "proposal_model"
        try:
            prop_model = models.RuntimeActionProposalV12.model_validate(proposal)
        except Exception as exc:
            raise _GateStop("FAILED", step, "proposal does not validate as RuntimeActionProposalV12: %s" % type(exc).__name__) from None
        step = "proposal_digest"
        rec["proposal_digest"] = am.proposal_digest(prop_model)
        if rec["proposal_digest"] != FROZEN["proposal_commitment"]:
            raise _GateStop("BLOCKED", step, "proposal_digest differs from the frozen value")
        step = "proposal_mismatches"
        rec["proposal_mismatches"] = list(am.proposal_mismatches(model, prop_model))
        if rec["proposal_mismatches"] != []:
            raise _GateStop("BLOCKED", step, "proposal_mismatches: %s" % (rec["proposal_mismatches"],))
    except _GateStop as stop:
        rec.update(passed=False, **{"class": stop.klass}, step=stop.step, failure=str(stop)[:300], native_exception=stop.native)
        return rec, None, None
    rec.update(passed=True, step="proposal_mismatches")
    rec["class"] = "ACCEPTED"
    return rec, raw, proposal


# ---------------------------------------------------------------- native component calls
def _import_replay(importers, record_obj, proposal_obj, label):
    """The ONLY Replay call. Returns (bundle, None) or (None, native). Only ImportContractError is a native refusal."""
    try:
        return importers.import_bounded_workflow(record_obj, proposal=proposal_obj, control_plane_revision=label), None
    except importers.ImportContractError as exc:
        return None, _native(exc)
    except Exception as exc:  # unknown failure class: neither a native refusal nor evidence
        raise AdapterError("unexpected Replay exception %s: %s" % (type(exc).__name__, str(exc)[:200])) from None


def _import_pack(P, manifest_obj, bundle_obj):
    """The ONLY Pack import call (deep copies in). Returns (pack, None) or (None, native)."""
    try:
        return P["pack_importer"].import_manifest_reconstruction(copy.deepcopy(manifest_obj), copy.deepcopy(bundle_obj)), None
    except P["pack_importer"].ImportContractError as exc:
        return None, _native(exc)
    except Exception as exc:
        raise AdapterError("unexpected Pack exception %s: %s" % (type(exc).__name__, str(exc)[:200])) from None


def _pack_view(pack, report):
    pd = pack.model_dump(mode="json")
    T = (pd.get("metadata") or {}).get("traceable_import") or {}
    issues = [{"severity": getattr(i.severity, "value", str(i.severity)), "code": i.code, "path": i.path, "message": i.message} for i in report.issues]
    return pd, T, {"valid": report.valid, "pack_id": report.pack_id, "errors": [i for i in issues if i["severity"] == "error"],
                   "warnings": [i for i in issues if i["severity"] == "warning"], "issues": issues,
                   "validation_summary": pd.get("validation_summary")}


def _fresh_workdir(workdir):
    work = pathlib.Path(workdir) if workdir is not None else pathlib.Path(tempfile.mkdtemp(prefix="c4-"))
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        raise AdapterError("workdir %s is not empty; a Control Plane record store would resume old state" % work)
    return work


class _Files:
    """Persist bytes once, read the file back once to prove it equals what was hashed, and keep relative path -> sha256."""

    def __init__(self, work):
        self.work, self.hashes = work, {}

    def put(self, rel, data):
        path = self.work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if path.read_bytes() != data:
            raise AdapterError("persisted file %s differs from the bytes written" % rel)
        self.hashes[rel] = _sha(data)
        return path


def _boundary(name, **kw):
    out = {"boundary": name, "native_outcome": None, "native_result": None, "native_status": None, "native_exception": None,
           "orchestration_class": "NOT_EXECUTED", "input_sha256": None, "output_sha256": None, "retains_upstream_refusal": False,
           "carried_authorization_state": None}
    out.update(kw)
    return out


def _not_executed(name, reason):
    return _boundary(name, reason=reason)


def _chain_verdict(boundaries):
    for b in boundaries:
        if b["orchestration_class"] != "ACCEPTED":
            return {"class": b["orchestration_class"], "boundary": b["boundary"]}
    return {"class": "ACCEPTED", "boundary": None}


def _decisions(bundle_obj):
    return [r for r in bundle_obj.get("records", []) if r.get("record_type") == "runtime_decision"]


def _auth_state(result):
    return {"authorized": "authorized", "hold": "held"}.get(result)


# ---------------------------------------------------------------- one scenario chain
def _chain(scenario, case_id, sdir, shared):
    """AM boundary result is shared; CP -> RB -> Pack run here with the gated, already-validated manifest object."""
    ctx, gate, files, label = shared["ctx"], shared["gate"], shared["files"], shared["label"]
    P = ctx["P"]
    ev = {"schema": SCHEMA, "case_id": case_id, "scenario": scenario, "native": {"replay": None, "pack": None}}
    am_b = _boundary("action_manifest", native_outcome="valid=%s; proposal_mismatches=%s" % (gate["valid"], gate["proposal_mismatches"]),
                     native_result={k: gate[k] for k in ("valid", "manifest_version", "manifest_digest", "proposal_digest", "proposal_mismatches")},
                     native_exception=gate["native_exception"], orchestration_class=gate["class"], input_sha256=gate["manifest_file_sha256"],
                     output_sha256=gate["manifest_file_sha256"] if gate["passed"] else None, failure=gate["failure"], step=gate["step"])
    out = {"ev": ev, "bundle_obj": None, "record": None, "bundle_bytes": None, "dest_effects": None, "produced": None}
    ev["boundaries"] = [am_b] + [_not_executed(b, "upstream boundary action_manifest %s" % gate["class"]) for b in BOUNDARIES[1:]]
    if not gate["passed"]:
        ev["gate_stopped_chain"] = True
        return out
    man_obj, proposal = shared["manifest_obj"], shared["proposal"]
    man_sha, prop_sha = gate["manifest_file_sha256"], gate["proposal_file_sha256"]
    try:
        produced = c4_producer.produce(ctx["roots"]["control_plane"], sdir / "producer", copy.deepcopy(proposal), man_obj, scenario)
    except Exception as exc:
        raise AdapterError("producer failed: %s: %s" % (type(exc).__name__, str(exc)[:200])) from None
    if man_obj != _strict_loads(shared["man_bytes"]):
        raise AdapterError("the validated manifest object changed during the Control Plane call")
    rec_bytes = pathlib.Path(produced.record_path).read_bytes()  # persisted record: read ONCE
    dest_bytes = pathlib.Path(produced.destination_path).read_bytes()
    try:
        record, dest = _strict_loads(rec_bytes), _strict_loads(dest_bytes)  # parse the SAME buffers
    except ValueError as exc:
        raise AdapterError("persisted producer output is not strict JSON: %s" % exc) from None
    rel = sdir.name
    files.put(rel + "/cp-record.json", rec_bytes)
    files.put(rel + "/destination.json", dest_bytes)
    effects = dest.get("effects") if isinstance(dest, dict) else None
    rec_sha = _sha(rec_bytes)
    decision = produced.decision
    result = decision.get("result")
    cp_class = {"authorized": "ACCEPTED", "hold": "REFUSED_NATIVE", "deny": "REFUSED_NATIVE"}.get(result, "FAILED")
    held = result == "hold"
    cp_b = _boundary("control_plane", native_outcome=result, orchestration_class=cp_class, input_sha256=man_sha, output_sha256=rec_sha,
                     input_extra_sha256={"manifest_file": man_sha, "proposal_file": prop_sha},
                     native_result={"result": result, "reasons": decision.get("reasons"), "decision_id": decision.get("decision_id"),
                                    "effect_id": decision.get("effect_id"), "binding_present": decision.get("binding") is not None,
                                    "operation_horizon": decision.get("operation_horizon")},
                     carried_authorization_state=_auth_state(result))
    ev["boundaries"][1] = cp_b
    out.update(record=record, dest_effects=effects, produced=produced, rec_sha=rec_sha)
    ev["destination"] = {"path": str(produced.destination_path), "effects": effects, "effect_count": None if effects is None else len(effects)}
    if cp_class == "FAILED" or (cp_class == "REFUSED_NATIVE" and not held):
        return out  # no native verdict this chain defines downstream observation for: later boundaries stay NOT_EXECUTED
    bundle, refusal = _import_replay(P["importers"], record, copy.deepcopy(proposal), label)
    if pathlib.Path(produced.record_path).read_bytes() != rec_bytes:
        raise AdapterError("persisted record file changed during import (the harness must never rewrite it)")
    rb_b = _boundary("replay_bundle", input_sha256=rec_sha, retains_upstream_refusal=held)
    ev["boundaries"][2] = rb_b
    if refusal is not None:
        rb_b.update(native_outcome="REFUSED_NATIVE", native_exception=refusal, orchestration_class="REFUSED_NATIVE")
        ev["native"]["replay"] = {"outcome": "REFUSED_NATIVE", **refusal}
        return out
    h1_bytes = _dump_bytes(bundle.model_dump(mode="json"))  # serialised ONCE
    files.put(rel + "/reconstruction-bundle.json", h1_bytes)
    bundle_obj = _strict_loads(h1_bytes)
    h1 = _sha(h1_bytes)
    findings = [[f.code, f.severity] for rep in bundle.import_reports for f in rep.findings]
    decs = _decisions(bundle_obj)
    rb_result = ((decs[0].get("data") or {}).get("result")) if len(decs) == 1 else None
    ev["native"]["replay"] = {"outcome": "IMPORTED", "status": bundle.status, "findings": findings,
                              "findings_detail": [{"code": f.code, "severity": f.severity, "message": getattr(f, "message", None)}
                                                  for rep in bundle.import_reports for f in rep.findings],
                              "bundle_version": bundle.bundle_version, "bundle_id": bundle.bundle_id,
                              "generated_at": str(bundle_obj.get("generated_at")), "integrity": bundle_obj.get("integrity"),
                              "record_types": sorted({r.record_type for r in bundle.records}),
                              "counts": {k: len(record.get(k) or []) for k in ("attempts", "observations", "reconciliations", "closeouts")}}
    rb_b.update(native_outcome="IMPORTED", native_status=bundle.status, orchestration_class="ACCEPTED", output_sha256=h1,
                native_result={"findings": findings, "record_types": ev["native"]["replay"]["record_types"], "runtime_decision_result": rb_result},
                carried_authorization_state=_auth_state(rb_result))
    out.update(bundle_obj=bundle_obj, bundle_bytes=h1_bytes, h1=h1)
    h2 = P["pack_importer"].sha256(bundle_obj)
    out["h2"] = h2
    ev["bundle"] = {"path": str(sdir / "reconstruction-bundle.json"), "size_bytes": len(h1_bytes), "H1_sha256_persisted_bytes": h1,
                    "H2_pack_canonical_sha256": h2, "h1_and_h2_are_distinct_values": ("sha256:" + h1) != h2,
                    "serialised_once": True, "integrity_attached": False}
    ev["raw_record_to_bundle_linkage"] = {"cp_record_sha256": rec_sha, "bundle_H1": h1, "carried_by_pack": False,
                                          "note": "L19: the Pack carries no hash of the raw Control Plane record; this linkage is harness evidence only"}
    pack, refusal = _import_pack(P, shared["manifest_obj"], bundle_obj)
    pk_b = _boundary("evidence_pack", input_sha256=h1, retains_upstream_refusal=held)
    ev["boundaries"][3] = pk_b
    if refusal is not None:
        pk_b.update(native_outcome="REFUSED_NATIVE", native_exception=refusal, orchestration_class="REFUSED_NATIVE")
        ev["native"]["pack"] = {"outcome": "REFUSED_NATIVE", **refusal}
        return out
    try:
        report = P["pack_validator"].validate_evidence_pack(pack)
    except Exception as exc:
        raise AdapterError("Pack validate_evidence_pack raised %s: %s" % (type(exc).__name__, str(exc)[:300])) from None
    pd, T, view = _pack_view(pack, report)
    pack_path = sdir / "evidence-pack.json"
    try:
        P["pack_loader"].dump_evidence_pack(pack, pack_path)
    except Exception as exc:
        raise AdapterError("Pack dump_evidence_pack raised %s: %s" % (type(exc).__name__, str(exc)[:300])) from None
    pack_bytes = pack_path.read_bytes()
    files.hashes[rel + "/evidence-pack.json"] = _sha(pack_bytes)  # native dump: hashed as written
    files.put(rel + "/pack-validation-report.json", _dump_bytes(view))
    again, _ = _import_pack(P, shared["manifest_obj"], bundle_obj)  # determinism OBSERVATION on identical input; never a retry of a refusal
    lc = T.get("lifecycle_summary") or {}
    ev["native"]["pack"] = {
        "outcome": "IMPORTED", "pack_id": pd.get("pack_id"), "pack_version": pd.get("pack_version"), "review_status": pd.get("review_status"),
        "validation": view, "pack_path": str(pack_path), "pack_file_sha256": _sha(pack_bytes), "pack_file_sha256_of": "file_bytes_as_written_by_native_dump",
        "transformation_version": T.get("transformation_version"), "selected_revisions": T.get("selected_revisions"),
        "replay_semantic_validation": T.get("replay_semantic_validation"),
        "lifecycle_summary": {k: lc.get(k) for k in ("authorization", "current_permission", "execution_attempted", "destination_observed",
                                                     "independent_verification", "reconstruction_status")},
        "replay_semantics": T.get("replay_semantics"), "reconstruction_completeness": T.get("reconstruction_completeness"),
        "replay_bundles": pd.get("replay_bundles"), "input_artifacts": T.get("input_artifacts"), "derived_counts": T.get("derived_counts"),
        "unresolved_issues": T.get("unresolved_issues"), "conversion_losses": T.get("conversion_losses"),
        "retained_source_scope": T.get("retained_source_scope"), "pack_id_deterministic": None if again is None else again.pack_id == pd.get("pack_id")}
    pk_b.update(native_outcome="IMPORTED", native_status="valid=%s" % view["valid"], orchestration_class="ACCEPTED", output_sha256=_sha(pack_bytes),
                native_result={"valid": view["valid"], "errors": len(view["errors"]), "warnings": len(view["warnings"]), "pack_id": pd.get("pack_id")},
                carried_authorization_state=lc.get("authorization") if lc.get("authorization") in ("authorized", "held") else None)
    out.update(pack_dump=pd, T=T, view=view, pack_sha=_sha(pack_bytes), again=again)
    return out


# ---------------------------------------------------------------- oracles
def _gate_checks(gate):
    return [_check("am_gate_passed", True, gate["passed"]), _check("am_validate_manifest_valid", True, gate["valid"]),
            _check("am_manifest_file_sha256", FROZEN["manifest_file_sha256"], gate["manifest_file_sha256"]),
            _check("am_proposal_file_sha256", FROZEN["proposal_sha256"], gate["proposal_file_sha256"]),
            _check("am_manifest_digest", FROZEN["manifest_digest"], gate["manifest_digest"]),
            _check("am_proposal_digest", FROZEN["proposal_commitment"], gate["proposal_digest"]),
            _check("am_proposal_mismatches_empty", [], gate["proposal_mismatches"])]


def _cp_common(out, scenario):
    prod, record, ev = out["produced"], out["record"], out["ev"]
    d = prod.decision
    ce = record.get("check_events") or []
    prov = prod.provenance
    return [_check("cp_operation_horizon_proposal_commitment", FROZEN["proposal_commitment"], (d.get("operation_horizon") or {}).get("proposal_commitment")),
            _check("cp_reason_vocabulary_version", FROZEN["reason_vocabulary_version"], d.get("reason_vocabulary_version")),
            _check("cp_time_source", "test_override", d.get("time_source")), _check("cp_decided_at", FROZEN["decided_at"], d.get("decided_at")),
            _check("cp_check_events_count", 13, len(ce)), _check("cp_check_events_decision_id_all_null", [None] * len(ce), [e.get("decision_id") for e in ce]),
            _check("cp_check_events_proposal_commitment", [FROZEN["proposal_commitment"]] * len(ce), [e.get("proposal_commitment") for e in ce]),
            _check("cp_record_zero_attempts_observations_reconciliations_closeouts", {k: 0 for k in ("attempts", "observations", "reconciliations", "closeouts")},
                   {k: len(record.get(k) or []) for k in ("attempts", "observations", "reconciliations", "closeouts")}),
            _check("cp_record_decision_id_equals_returned", d.get("decision_id"), ((record.get("decisions") or [{}])[0]).get("decision_id")),
            _check("producer_calls_decide_only", ["decide"], prov.get("calls")), _check("producer_scenario", scenario, prov.get("scenario")),
            _check("producer_manifest_equals_cp_repo_copy", True, prov.get("manifest_equals_cp_repo_copy")),
            _check("destination_effects", {}, out["dest_effects"]), _check("record_sha256_matches_persisted_copy", _sha(prod.record_path.read_bytes()), out["rec_sha"])]


def _pack_common(out, shared):
    T, pd, view, ev = out["T"], out["pack_dump"], out["view"], out["ev"]
    lc, sem, ia = T.get("lifecycle_summary") or {}, T.get("replay_semantics") or {}, T.get("input_artifacts") or [{}, {}]
    dc = T.get("derived_counts") or {}
    retained = T.get("retained_sources") or {}
    rb0 = (pd.get("replay_bundles") or [{}])[0]
    rdec = [r for r in (retained.get("reconstruction_bundle") or {}).get("records", []) if r.get("record_type") == "runtime_decision"]
    dd = (rdec[0].get("data") if len(rdec) == 1 else None) or {}
    zero = {k: dc.get(k) for k in ZERO_COUNT_KEYS}
    return dd, [
        _check("pack_derived_counts_zero", {k: 0 for k in ZERO_COUNT_KEYS}, zero),
        _check("pack_derived_counts_are_int_not_bool", {k: True for k in ZERO_COUNT_KEYS},
               {k: (type(dc.get(k)) is int) for k in ZERO_COUNT_KEYS}),
        _check("pack_version", FROZEN["pack_version"], pd.get("pack_version")), _check("review_status_draft", FROZEN["review_status"], pd.get("review_status")),
        _check("transformation_version", FROZEN["transformation_version"], T.get("transformation_version")),
        _check("selected_revisions", {"manifest": PINS["action_manifest"]["sha"], "replay": PINS["replay_bundle"]["sha"],
                                      "control_plane": PINS["control_plane"]["sha"]}, T.get("selected_revisions")),
        _check("replay_semantic_validation", {"validator": FROZEN["validator"], "required_revision": PINS["replay_bundle"]["sha"],
                                              "status": "validated_partial"}, T.get("replay_semantic_validation")),
        _check("replay_bundles_status", "validated_partial", rb0.get("status")), _check("replay_bundles_signed", False, rb0.get("signed")),
        _check("replay_bundles_redacted", False, rb0.get("redacted")),
        _check("replay_bundles_validation_status", "semantically_valid", rb0.get("validation_status")),
        _check("reconstruction_completeness", "reconstruction_partial", T.get("reconstruction_completeness")),
        _check("lifecycle_current_permission", "not_evaluated_from_historical_records", lc.get("current_permission")),
        _check("lifecycle_execution_attempted", "no", lc.get("execution_attempted")),
        _check("lifecycle_destination_observed", "unknown", lc.get("destination_observed")),
        _check("lifecycle_independent_verification", "unavailable", lc.get("independent_verification")),
        _check("lifecycle_reconstruction_status", "reconstruction_partial", lc.get("reconstruction_status")),
        _check("replay_semantics_flags", {"policy_reevaluation": False, "external_effect_execution": False, "destination_observation": "not_performed",
                                          "independent_effect_verification": False},
               {k: sem.get(k) for k in ("policy_reevaluation", "external_effect_execution", "destination_observation", "independent_effect_verification")}),
        _check("manifest_input_artifact_digest", FROZEN["manifest_digest"], ia[0].get("hash")), _check("manifest_artifact_role", "manifest", ia[0].get("artifact_role")),
        _check("pack_valid", True, view["valid"]), _check("pack_zero_errors", 0, len(view["errors"])),
        _check("pack_input_artifact_H2_equals_pack_canonical", out["h2"], ia[1].get("hash")),
        _check("retained_bundle_equals_persisted_bundle", out["bundle_obj"], retained.get("reconstruction_bundle")),
        _check("retained_manifest_equals_manifest_object", shared["manifest_obj"], retained.get("manifest")),
        _check("retained_decision_id", out["produced"].decision.get("decision_id"), dd.get("decision_id")),
        _check("pack_id_deterministic_for_identical_bundle", pd.get("pack_id"), None if out["again"] is None else out["again"].pack_id),
        _check("h1_h2_distinct", True, (out["ev"].get("bundle") or {}).get("h1_and_h2_are_distinct_values")),
        _check("h1_matches_independent_hash_of_bytes", hashlib.sha256(out["bundle_bytes"]).hexdigest(), out["h1"])]


def _rb_checks(out, findings_check):
    b, rp = out["bundle_obj"], out["ev"]["native"]["replay"]
    return [_check("rb_status", "reconstruction_partial", rp["status"]), findings_check,
            _check("rb_record_types", RB_RECORD_TYPES, rp["record_types"]), _check("rb_bundle_version", "0.2.0", rp["bundle_version"]),
            _check("rb_integrity_empty_none_attached", [], b.get("integrity")),
            _check("rb_counts_zero", {k: 0 for k in rp["counts"]}, rp["counts"])]


def _p1_checks(out, shared):
    d = out["produced"].decision
    bind = d.get("binding") or {}
    dd, pk = _pack_common(out, shared)
    lc = out["T"].get("lifecycle_summary") or {}
    cp = [_check("cp_result", "authorized", d.get("result")), _check("cp_reasons", [], d.get("reasons")),
          _check("cp_effect_id", FROZEN["effect_id_authorized"], d.get("effect_id")),
          _check("cp_binding_manifest_digest", FROZEN["manifest_digest"], bind.get("manifest_digest")),
          _check("cp_binding_proposal_commitment", FROZEN["proposal_commitment"], bind.get("proposal_commitment")),
          _check("cp_binding_tenant", FROZEN["tenant_id"], bind.get("tenant_id")), _check("cp_binding_action_id", FROZEN["action_id"], bind.get("action_id")),
          _check("cp_binding_generation", FROZEN["generation"], bind.get("generation")),
          _check("cp_binding_runtime_authority_profile", FROZEN["authority_profile"], (bind.get("runtime_authority") or {}).get("profile")),
          _check("producer_scenario_mutation_none", None, out["produced"].provenance.get("scenario_mutation"))]
    chain = [_check("pack_retained_decision_result", "authorized", dd.get("result")), _check("pack_retained_effect_id", FROZEN["effect_id_authorized"], dd.get("effect_id")),
             _check("pack_retained_proposal_commitment", FROZEN["proposal_commitment"], (dd.get("binding") or {}).get("proposal_commitment")),
             _check("pack_retained_tenant", FROZEN["tenant_id"], (dd.get("binding") or {}).get("tenant_id")),
             _check("pack_retained_action_id", FROZEN["action_id"], (dd.get("binding") or {}).get("action_id")),
             _check("pack_retained_generation", FROZEN["generation"], (dd.get("binding") or {}).get("generation")),
             _check("lifecycle_authorization_historical", "authorized", lc.get("authorization"))]
    return _cp_common(out, "authorized") + cp + _rb_checks(out, _check("rb_findings_exactly_B004_warning", [["B004", "warning"]], out["ev"]["native"]["replay"]["findings"])) + pk + chain + [
        _check("chain_verdict_accepted", {"class": "ACCEPTED", "boundary": None}, _chain_verdict(out["ev"]["boundaries"]))]


def _n1_checks(out, shared):
    d = out["produced"].decision
    dd, pk = _pack_common(out, shared)
    T = out["T"]
    lc, dc = T.get("lifecycle_summary") or {}, T.get("derived_counts") or {}
    bdec = _decisions(out["bundle_obj"])
    bres = (bdec[0].get("data") or {}).get("result") if len(bdec) == 1 else None
    cp = [_check("cp_result", "hold", d.get("result")), _check("cp_reasons", ["grant_revoked"], d.get("reasons")),
          _check("cp_binding_null", None, d.get("binding")), _check("cp_effect_id", FROZEN["effect_id_hold"], d.get("effect_id")),
          _check("producer_scenario_mutation", "grant_status=revoked", out["produced"].provenance.get("scenario_mutation"))]
    rb_extra = [_check("rb_no_B002_B006", [], sorted({f[0] for f in out["ev"]["native"]["replay"]["findings"]} & {"B002", "B006"}))]
    held = [_check("lifecycle_authorization_held", "held", lc.get("authorization")),
            _check("pack_authorization_held_count", 1, dc.get("authorization_held_count")),
            _check("pack_authorization_granted_count", 0, dc.get("authorization_granted_count")),
            _check("bundle_runtime_decision_result_hold", "hold", bres), _check("pack_retained_runtime_decision_result_hold", "hold", dd.get("result")),
            _check("pack_retained_binding_null", None, dd.get("binding")),
            _check("pack_retained_effect_id_hold", FROZEN["effect_id_hold"], dd.get("effect_id")),
            _check("downstream_boundaries_retain_refusal_and_hold",
                   [(True, "held"), (True, "held")], [(b["retains_upstream_refusal"], b["carried_authorization_state"]) for b in out["ev"]["boundaries"][2:]]),
            _check("downstream_boundaries_accepted_as_imports", ["ACCEPTED", "ACCEPTED"], [b["orchestration_class"] for b in out["ev"]["boundaries"][2:]]),
            _check("chain_verdict_refused_native_at_control_plane", {"class": "REFUSED_NATIVE", "boundary": "control_plane"}, _chain_verdict(out["ev"]["boundaries"]))]
    return _cp_common(out, "grant_revoked") + cp + _rb_checks(out, _check("rb_findings_code_set_B004_B005", ["B004", "B005"], sorted({f[0] for f in out["ev"]["native"]["replay"]["findings"]}))) + rb_extra + pk + held


# ---------------------------------------------------------------- identity, crosswalk, shared evidence parts
def _row(name, value, loc, persisted_by, verified_by, cls, stability, **extra):
    return {"name": name, "value": value, "native_location": loc, "persisted_by": persisted_by, "verified_by": verified_by,
            "class": cls, "stability": stability, **extra}


def _exact_if(value, observed, with_cls="EXACT"):
    return with_cls if value is not None and all(o == value for o in observed) and observed else "NOT CARRIED"


def _crosswalk(out, shared, scenario):
    d, record, held = out["produced"].decision, out["record"], scenario == "grant_revoked"
    bundle_obj, T = out.get("bundle_obj"), out.get("T") or {}
    bind = d.get("binding") or {}
    rt = [r for r in (bundle_obj or {}).get("records", []) if r.get("record_type") == "runtime_proposal"]
    rprop = (rt[0].get("data") if len(rt) == 1 else None) or {}
    retained = (T.get("retained_sources") or {}).get("reconstruction_bundle") or {}
    rdec = [r for r in retained.get("records", []) if r.get("record_type") == "runtime_decision"]
    pdd = (rdec[0].get("data") if rdec else None) or {}
    bdec = (_decisions(bundle_obj)[0].get("data") if bundle_obj and _decisions(bundle_obj) else None) or {}
    pc = FROZEN["proposal_commitment"]
    native_verify = ("none: RB does not bind the supplied proposal to a hold record (L22); orchestrator extraction" if held else
                     "native: RB importers.py:271-300; Pack importer.py:1037-1049")
    ia = T.get("input_artifacts") or [{}]
    prof = ((bundle_obj or {}).get("producer_profiles") or [{}])[0]
    rows = [
        _row("manifest_file_sha256", shared["gate"]["manifest_file_sha256"], "inputs/am-manifest.json (file bytes)", "orchestrator only",
             "orchestrator extraction (frozen literal; AM gate on the same buffer)", "NOT CARRIED", "stable"),
        _row("manifest_digest", FROZEN["manifest_digest"], "evidence-pack.json metadata.traceable_import.input_artifacts[0].hash; cp-record decisions[0].binding.manifest_digest (authorized only)",
             "Pack (and CP for authorized)", "native: AM manifest_digest; Pack importer.py:1037-1049", _exact_if(FROZEN["manifest_digest"], [ia[0].get("hash")]), "stable"),
        _row("proposal_file_sha256", shared["gate"]["proposal_file_sha256"], "inputs/proposal.json (file bytes)", "orchestrator only",
             "orchestrator extraction", "NOT CARRIED", "stable"),
        _row("proposal_commitment", pc, "cp-record decisions[0].operation_horizon.proposal_commitment; check_events[*].proposal_commitment; bundle runtime_decision/runtime_proposal; Pack retained_sources",
             "CP, RB, Pack", native_verify, _exact_if(pc, [(d.get("operation_horizon") or {}).get("proposal_commitment"), (pdd.get("operation_horizon") or {}).get("proposal_commitment", pc)]),
             "stable (constant across verdicts)"),
        _row("action_id", FROZEN["action_id"], "cp-record decisions[0].binding.action_id (authorized only); bundle runtime_proposal record",
             "CP (authorized), RB runtime_proposal", native_verify, "EXACT" if (bind.get("action_id") == FROZEN["action_id"] or rprop.get("action_id") == FROZEN["action_id"]) else "NOT CARRIED", "stable",
             observed_in_binding=bind.get("action_id"), observed_in_runtime_proposal=rprop.get("action_id")),
        _row("tenant_id", FROZEN["tenant_id"], "cp-record decisions[0].binding.tenant_id (authorized only); bundle runtime_proposal record; no Pack tenant field",
             "CP (authorized), RB runtime_proposal", "native: RB (authorized only); none for a hold (L22); Pack has no tenant field (L13)",
             "EXACT" if (bind.get("tenant_id") == FROZEN["tenant_id"] or rprop.get("tenant_id") == FROZEN["tenant_id"]) else "NOT CARRIED", "stable",
             observed_in_binding=bind.get("tenant_id"), observed_in_runtime_proposal=rprop.get("tenant_id")),
        _row("effect_id", d.get("effect_id"), "cp-record decisions[0].effect_id; bundle runtime_decision.data.effect_id; Pack retained_sources",
             "CP, RB, Pack", "native: RB (authorized only)" if not held else "orchestrator extraction",
             _exact_if(d.get("effect_id"), [bdec.get("effect_id"), pdd.get("effect_id")]), "verdict-dependent (L23)"),
        _row("decision_id", d.get("decision_id"), "cp-record decisions[0].decision_id; bundle runtime_decision.data.decision_id; Pack retained_sources",
             "CP, RB, Pack", "orchestrator extraction", _exact_if(d.get("decision_id"), [bdec.get("decision_id"), pdd.get("decision_id")]), "per-run"),
        _row("correlation_id", rprop.get("correlation_id"), "bundle runtime_proposal record only (not persisted by CP)", "RB runtime_proposal",
             "bound only via proposal_commitment, authorized decisions only", "ID-LEVEL", "proposal field; not an end-to-end identity"),
        _row("NOT LINKED: check_id <-> decision_id", {"check_ids": sorted({e.get("check_id") for e in record.get("check_events") or []}),
                                                       "check_events_decision_id": sorted({str(e.get("decision_id")) for e in record.get("check_events") or []})},
             "cp-record check_events[*] vs decisions[0]", "CP", "none (decision_id is null on all 13 events; amendment 6667028276)", "NOT CARRIED", "per-run", not_linked=True),
        _row("NOT LINKED: raw CP record hash <-> bundle (L19)", {"cp_record_sha256": out["rec_sha"], "bundle_h1": out.get("h1")}, "none", "orchestrator only", "none",
             "NOT CARRIED", "per-run", not_linked=True),
        _row("NOT LINKED: H1 persisted bundle bytes <-> H2 Pack canonical hash", {"h1": out.get("h1"), "h2": out.get("h2")}, "evidence-pack.json input_artifacts[1].hash is H2",
             "Pack (H2 only)", "none; distinct values by construction", "NOT CARRIED", "per-run", not_linked=True),
        _row("NOT LINKED: effect_id across verdicts", {"observed_verdict": d.get("result"), "observed": d.get("effect_id"),
                                                       "other_verdict_frozen": FROZEN["effect_id_hold" if not held else "effect_id_authorized"]},
             "cp-record decisions[0].effect_id", "CP", "none (effect_id differs by verdict, L23)", "NOT CARRIED", "verdict-dependent", not_linked=True),
        _row("proposal <-> decision linkage (NOT LINKED for a hold)", {"verdict": d.get("result"), "binding_present": bool(bind)}, "none for a hold", "none",
             "none (L22)" if held else "native for authorized: RB importers.py:271-300", "NOT CARRIED" if held else "EXACT", "scenario", not_linked=held),
        _row("NOT LINKED: producer config id", c4_producer.CONFIG_ID, "none (persisted by no component, L27)", "orchestrator provenance only", "none", "NOT CARRIED", "stable", not_linked=True),
        _row("NOT LINKED: CP repository-name label drift", {"bundle_producer_profile_repository": prof.get("repository"),
                                                              "measured": PINS["control_plane"]["repository"]},
             "bundle producer_profiles[0]", "RB (caller-asserted label)", "none (labels are caller-asserted, L10)", "NOT CARRIED", "stable", not_linked=True),
        _row("NOT LINKED: C1 record <-> C4 record", None, "none", "none", "none (identity-level only; forbidden claims: same decision, C1 record accepted by RB)",
             "NOT CARRIED", "stable", not_linked=True),
        _row("run_id literal", record.get("run_id"), "cp-record run_id", "CP", "none (a literal, not a run identity, L24)", "NOT CARRIED", "constant literal", not_linked=True),
    ]
    return rows


def _identity(out, shared, scenario, invocation):
    d = out["produced"].decision
    bundle_obj = out.get("bundle_obj") or {}
    pack_id = out["T"] and out["pack_dump"].get("pack_id")
    return {"stable": {"action_id": shared["proposal"].get("action_id"), "proposal_commitment": (d.get("operation_horizon") or {}).get("proposal_commitment"),
                       "manifest_digest": shared["gate"]["manifest_digest"], "tenant_id": shared["proposal"].get("tenant_id")},
            "effect_id": d.get("effect_id"),
            "per_run": {"decision_id": d.get("decision_id"), "bundle_id": bundle_obj.get("bundle_id"), "generated_at": bundle_obj.get("generated_at"),
                        "pack_id": pack_id, "cp_record_sha256": out["rec_sha"], "bundle_h1_sha256": out.get("h1"),
                        "bundle_h2_pack_canonical_sha256": out.get("h2"), "pack_file_sha256": out.get("pack_sha")},
            "harness_run_ref": _harness_run_ref(invocation),
            "note": "no native end-to-end run/correlation identity exists (A6); harness_run_ref is orchestrator-only"}


def _common_evidence(case_id, shared):
    ctx = shared["ctx"]
    g = shared["gate"]
    return {"sources": {"sources": ctx["sources"], "revision_label": ctx["revision_label"], "revision_label_basis": "measured_git_head_and_tree"},
            "runtime": _runtime(), "limits": copy.deepcopy(LIMITS), "harness": shared["harness"], "workdir": str(shared["work"]),
            "producer_config_id": c4_producer.CONFIG_ID, "am_gate": g,
            "inputs": {"manifest": {"sha256": g["manifest_file_sha256"], "frozen_sha256": FROZEN["manifest_file_sha256"], "sha256_of": "file_bytes",
                                    "size_bytes": len(shared["man_bytes"]), "path": "inputs/am-manifest.json",
                                    "source": "%s@%s" % (PINS["action_manifest"]["repository"], PINS["action_manifest"]["sha"])},
                       "proposal": {"sha256": g["proposal_file_sha256"], "frozen_sha256": FROZEN["proposal_sha256"], "sha256_of": "file_bytes",
                                    "size_bytes": len(shared["prop_bytes"]), "path": "inputs/proposal.json"}},
            "known_not_executed": list(KNOWN_NOT_EXECUTED), "adverse_retained": copy.deepcopy(EXPECTED_OPEN_ADVERSE)}


def _finish(ev, shared, checks, prefixes):
    ok = all(c["ok"] for c in checks)
    ev["oracle"] = {"checks": checks, "all_ok": ok}
    ev["files"] = {k: v for k, v in sorted(shared["files"].hashes.items()) if k.startswith(prefixes)}
    ev["chain_verdict"] = _chain_verdict(ev["boundaries"])
    ev["chain_verdict_text"] = "%s@%s" % (ev["chain_verdict"]["class"], ev["chain_verdict"]["boundary"]) if ev["chain_verdict"]["boundary"] else "ACCEPTED"
    return ok


def _scenario_case(case_id, scenario, shared, sub, checker):
    sdir = shared["work"] / sub
    sdir.mkdir()
    out = _chain(scenario, case_id, sdir, shared)
    ev = out["ev"]
    ev.update(_common_evidence(case_id, shared))
    if out["produced"] is None or out["bundle_obj"] is None or "pack_dump" not in out:
        blocked = not shared["gate"]["passed"]
        checks = _gate_checks(shared["gate"]) + [_check("chain_completed_all_four_boundaries", True, False)]
        ev["identity"] = {"harness_run_ref": _harness_run_ref(shared["invocation"])}
        ev["crosswalk"], ev["destination"] = [], ev.get("destination")
        _finish(ev, shared, checks, ("inputs/", sub + "/"))
        ev["status"] = ("BLOCKED" if shared["gate"]["class"] == "BLOCKED" else "FAIL") if blocked else "FAIL"
        return out
    ev["producer"] = out["produced"].provenance
    ev["identity"] = _identity(out, shared, scenario, shared["invocation"])
    ev["crosswalk"] = _crosswalk(out, shared, scenario)
    ev["record"] = {"sha256": out["rec_sha"], "size_bytes": None, "path": str(out["produced"].record_path), "sha256_of": "file_bytes",
                    "per_run_not_frozen": True}
    ev["record"]["size_bytes"] = len(pathlib.Path(out["produced"].record_path).read_bytes())
    ev["record"]["unchanged_after_import"] = _sha(pathlib.Path(out["produced"].record_path).read_bytes()) == out["rec_sha"]
    _recheck(shared["ctx"])
    checks = _gate_checks(shared["gate"]) + checker(out, shared) + [_check("record_unchanged_after_import", True, ev["record"]["unchanged_after_import"])]
    ok = _finish(ev, shared, checks, ("inputs/", sub + "/"))
    ev["status"] = "PASS" if ok else "FAIL"
    return out


def _n2_case(shared, n1):
    ev = {"schema": SCHEMA, "case_id": CASE_N2, "scenario": "flip_of_n1", "native": {"replay": None, "pack": None}}
    ev.update(_common_evidence(CASE_N2, shared))
    reason = "derived from N1 retained bundle"
    ev["boundaries"] = [_not_executed(b, reason) for b in BOUNDARIES[:3]]
    ok_pre = n1["ev"]["status"] == "PASS" and n1["bundle_obj"] is not None
    if not ok_pre:
        ev["boundaries"].append(_not_executed("evidence_pack", "N1 precondition not met"))
        ev["identity"] = {"harness_run_ref": _harness_run_ref(shared["invocation"])}
        ev["crosswalk"] = []
        _finish(ev, shared, [_check("n1_precondition_passed", True, False)], ("inputs/", "n2/"))
        ev["chain_verdict"], ev["chain_verdict_text"] = {"class": "BLOCKED", "boundary": "n1_precondition"}, "BLOCKED@n1_precondition"
        ev["status"] = "BLOCKED"
        return ev
    P = shared["ctx"]["P"]
    original = n1["bundle_obj"]
    original_h2 = P["pack_importer"].sha256(original)
    mutated = copy.deepcopy(original)
    decs = _decisions(mutated)
    if len(decs) != 1 or (decs[0].get("data") or {}).get("result") != "hold":
        raise AdapterError("N2 precondition: the N1 bundle does not hold exactly one runtime_decision with result hold")
    decs[0]["data"]["result"] = "authorized"  # the ONLY change
    mut_bytes = _dump_bytes(mutated)
    shared["files"].put("n2/mutated-bundle.json", mut_bytes)
    mutated_obj = _strict_loads(mut_bytes)
    n1_decision_id = ((n1["record"].get("decisions") or [{}])[0]).get("decision_id")  # from the retained N1 CP record bytes
    expected_message = "decision %s is authorized but has no binding" % n1_decision_id
    pack, refusal = _import_pack(P, shared["manifest_obj"], mutated_obj)
    n1_bundle_path = shared["work"] / "n1" / "reconstruction-bundle.json"
    intact = n1_bundle_path.read_bytes() == n1["bundle_bytes"] and P["pack_importer"].sha256(original) == original_h2
    dest_after = _strict_loads((shared["work"] / "n1" / "destination.json").read_bytes()).get("effects")
    pk_b = _boundary("evidence_pack", input_sha256=_sha(mut_bytes), retains_upstream_refusal=True, carried_authorization_state=None)
    ev["boundaries"].append(pk_b)
    ev["mutation"] = {"field_path": "records[runtime_decision].data.result", "from": "hold", "to": "authorized", "original_bundle_H1_sha256": n1["h1"],
                      "original_bundle_H2_pack_canonical_sha256": original_h2, "mutated_bundle_file_sha256": _sha(mut_bytes),
                      "mutated_bundle_H2_pack_canonical_sha256": P["pack_importer"].sha256(mutated_obj),
                      "mutated_hash_basis": "bytes of the mutated deep copy dumped by the same serialiser; not a product of any component",
                      "manifest_supplied": True, "manifest_file_sha256": shared["gate"]["manifest_file_sha256"], "original_unmodified_after_run": intact,
                      "expected_message_source": "decisions[0].decision_id of the retained N1 CP record"}
    ev["destination"] = {"effects_before": n1["dest_effects"], "effects_after": dest_after, "no_effect": n1["dest_effects"] == dest_after == {}}
    if refusal is None:
        pk_b.update(native_outcome="IMPORTED", native_status="pack_id=%s" % pack.pack_id, orchestration_class="ACCEPTED")
        ev["native"]["pack"] = {"outcome": "IMPORTED", "pack_id": pack.pack_id}
        refusal = {"type": None, "message": None, "code": None}
    else:
        pk_b.update(native_outcome="REFUSED_NATIVE", native_exception=refusal, orchestration_class="REFUSED_NATIVE")
        ev["native"]["pack"] = {"outcome": "REFUSED_NATIVE", **refusal}
    checks = [_check("n1_precondition_passed", True, ok_pre), _check("exception_type", "ImportContractError", refusal["type"]),
              _check("message", expected_message, refusal["message"]), _check("code_is_none_native_has_no_code", None, refusal["code"]),
              _check("only_one_field_changed", True, [_mut_path_equal(original, mutated)] == [True]),
              _check("original_bundle_unmodified", True, intact), _check("no_destination_effect", True, ev["destination"]["no_effect"]),
              _check("chain_verdict_refused_native_at_evidence_pack", {"class": "REFUSED_NATIVE", "boundary": "evidence_pack"}, _chain_verdict(ev["boundaries"][3:]))]
    ev["identity"] = {"harness_run_ref": _harness_run_ref(shared["invocation"]), "n1_decision_id": n1_decision_id}
    ev["crosswalk"] = []
    _recheck(shared["ctx"])
    ok = _finish(ev, shared, checks, ("inputs/", "n2/"))
    ev["chain_verdict"] = _chain_verdict(ev["boundaries"][3:])  # only the Pack boundary is exercised; others are derived, not re-run
    ev["chain_verdict_text"] = "%s@%s" % (ev["chain_verdict"]["class"], ev["chain_verdict"]["boundary"])
    ev["status"] = "PASS" if ok else "FAIL"
    return ev


def _mut_path_equal(original, mutated):
    """True when mutated differs from original only at runtime_decision.data.result (hold -> authorized)."""
    probe = copy.deepcopy(mutated)
    _decisions(probe)[0]["data"]["result"] = "hold"
    return probe == original and mutated != original


def run_all(roots=None, workdir=None, *, manifest_path=None, proposal_path=None):
    """Measure sources, read inputs once, run the AM gate once, then P1, N1-HOLD and N2-FLIP in one coordinator invocation."""
    if roots is None:
        roots = {k: os.environ.get(v) for k, v in ENV.items()}
    for k in BOUNDARIES:
        if not roots.get(k) or not os.path.isdir(str(roots[k])):
            raise SourceIdentityError("%s: root missing (set %s)" % (k, ENV[k]))
    if _sha((pathlib.Path(__file__).resolve().parent / "real_c3.py").read_bytes()) != FROZEN["real_c3_sha256"]:  # checked BEFORE its measure() is executed
        raise AdapterError("real_c3.py differs from the pinned C3 file (C3 must stay unchanged)")
    ctx = _measure(roots)
    if _sha(pathlib.Path(c2_producer.__file__).read_bytes()) != FROZEN["c2_producer_sha256"]:
        raise AdapterError("c2_producer.py differs from the pinned C2 file (C2 must stay unchanged)")
    man_path = pathlib.Path(manifest_path) if manifest_path is not None else ctx["am_root"] / MANIFEST_RELATIVE_PATH
    prop_path = pathlib.Path(proposal_path) if proposal_path is not None else PROPOSAL_PATH
    man_bytes, man_ok = _read_once(man_path, FROZEN["manifest_file_sha256"], "manifest")
    prop_bytes, prop_ok = _read_once(prop_path, FROZEN["proposal_sha256"], "proposal")
    work = _fresh_workdir(workdir)
    files = _Files(work)
    files.put("inputs/am-manifest.json", man_bytes)
    files.put("inputs/proposal.json", prop_bytes)
    gate, manifest_obj, proposal = _am_gate(ctx, man_bytes, prop_bytes, man_ok, prop_ok)
    shared = {"ctx": ctx, "gate": gate, "files": files, "work": work, "label": ctx["revision_label"], "manifest_obj": manifest_obj,
              "proposal": proposal, "man_bytes": man_bytes, "prop_bytes": prop_bytes, "harness": _harness(), "invocation": str(uuid.uuid4())}
    p1 = _scenario_case(CASE_P1, "authorized", shared, "p1", _p1_checks)
    n1 = _scenario_case(CASE_N1, "grant_revoked", shared, "n1", _n1_checks)
    n2 = _n2_case(shared, n1)
    _recheck(ctx)
    return {CASE_P1: p1["ev"], CASE_N1: n1["ev"], CASE_N2: n2}


def _summary(results):
    return ["%s: chain %s, status %s" % (cid, ev["chain_verdict_text"], ev["status"]) for cid, ev in results.items()]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the VSLICE-C4 cases (development-only, fixture-scoped, non-authorizing).")
    parser.add_argument("--case", default="all", help="all or one of: %s" % ", ".join(CASES))
    parser.add_argument("--out")
    parser.add_argument("--workdir")
    args = parser.parse_args(argv)
    if args.case != "all" and args.case not in CASES:
        print("refused: case id is not allowlisted", file=sys.stderr)
        return 2
    try:
        results = run_all(workdir=args.workdir)
    except AdapterError as exc:
        print("adapter error: %s" % exc, file=sys.stderr)
        return 2
    chosen = results if args.case == "all" else {args.case: results[args.case]}
    for line in _summary(chosen):  # chain verdict first in every summary
        print(line, file=sys.stderr)
    text = json.dumps(chosen, indent=2, sort_keys=True, default=str) + "\n"
    if args.out:
        pathlib.Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0 if all(v["status"] == "PASS" for v in chosen.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
