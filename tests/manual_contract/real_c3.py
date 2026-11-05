"""VSLICE-C3 harness: real Replay Bundle output -> native Governance Evidence Pack import and validation (Python API plus `main`).

Development-only and fixture-scoped; implements Hub #273 contract comment 6671327666 (frozen for development by 6671384213).
The chain is: frozen C2 producer (Control Plane decide() only) -> persisted Control Plane record -> Replay
`import_bounded_workflow()` -> ONE persisted ReconstructionBundle 0.2.0 -> Pack `import_manifest_reconstruction()` -> Pack
`validate_evidence_pack()`. No field is mapped, added, dropped, renamed, defaulted or rescored; the Pack's own importer and
validator are the only consumer logic. The authority context, resolver state and evidence signatures are synthetic and
unauthenticated (TEST-ONLY public Ed25519 key). Non-authorizing: IMPORTED / `valid=True` mean only that the Pack's native
importer accepted and re-derived a PARTIAL reconstruction of one synthetic Control Plane decision. They are not approval,
certification, completeness, authenticity, custody, freshness or proof of any external effect. The Pack's Replay pin is a
PROVISIONAL, UNQUALIFIED development row (CP-2). Hub #280 stays OPEN. Engineering Constitution adoption is UNVERIFIED.

Helpers are COPIED and generalised from the C2 adapter (D9); nothing private is imported from C1/C2. The one reused symbol is the
public `c2_producer.produce`, whose file hash is pinned. A native refusal is REFUSED_NATIVE, reported verbatim, and is distinct
from an AdapterError (measurement, fixture, producer or harness failure).
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
import c2_producer  # noqa: E402  (public C2 producer; stdlib-only at import time; its file hash is pinned below)

ENV = {"control_plane": "COGNOUS_C3_CONTROL_PLANE_ROOT", "replay_bundle": "COGNOUS_C3_REPLAY_BUNDLE_ROOT",
       "evidence_pack": "COGNOUS_C3_EVIDENCE_PACK_ROOT", "action_manifest": "COGNOUS_C3_ACTION_MANIFEST_ROOT"}
CASE_P1, CASE_N1, CASE_N3, CASE_N5 = ("c3_p1_replay_to_pack_partial", "c3_n1_ten_tenant_tamper",
                                      "c3_n3_partial_as_complete", "c3_n5_rev_wrong_revision")
EVIDENCE_SCHEMA = "cognous.orchestrator.c3-evidence/0-candidate"
PINS = {
    "control_plane": {"repository": "cogno-us/cognous-control-plane", "sha": "484fdbd297235dd24148ddb0703f2055a31eabff",
                      "tree": "c182939882103015f12c5360fccf377c54e2c4f9"},
    "replay_bundle": {"repository": "cogno-us/cognous-replay-bundle", "sha": "93a76e281fcae6a65d2cd1d35376f87442dafb95",
                      "tree": "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f"},
    "evidence_pack": {"repository": "cogno-us/cognous-governance-evidence-pack", "sha": "065150852cc2a8abeb748777bb69d72ccd0e03d8",
                      "tree": "fe428a89da2e74346648cdfe014462ddc8624c77"},
    "action_manifest": {"repository": "cogno-us/cognous-action-manifest", "sha": "fa170815ef96a54c233d0dd9da821b60debabf8b",
                        "tree": "3b0e3772e944aa668c8f4b879588c7cc3e2c32be"},
}
MANIFEST_RELATIVE_PATH = "examples/refund_integration_v1_1.manifest.json"
FROZEN = {
    "proposal_sha256": "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2",
    "manifest_file_sha256": "789ad39596b9e1ef84a726a671883e1cb6b83343da3a31db0a1120906d68c074",
    "c2_producer_sha256": "7c4f2595d7939e4a373586faafc0de86469dc03b791d893d7b27fb328a02a895",  # base fce552de file bytes
}
ORACLE = {
    "effect_id": "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8",
    "proposal_commitment": "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53",
    "manifest_digest": "sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac",
    "tenant_id": "tenant-alpha", "generation": "bounded-authorization-effect/0.3-strict-tenant",
    "rb_status": "reconstruction_partial", "rb_findings": [["B004", "warning"]],
    "pack_version": "0.2.0", "review_status": "draft",
    "transformation_version": "agep-manifest-reconstruction-import/0.3.10-strict-tenant-candidate",
    "validator": "agent_replay_bundle.importers.import_bounded_workflow",
    "n1_message": "pinned Replay semantic validation failed: decisions[0].binding.tenant_id conflicts with committed operation",
    "n3_message": "pinned Replay semantic validation failed unexpectedly: retained Replay status differs from accepted reconstruction",
    "n5_wrong_revision": "f63ce914504dd06813c4ccd199b0570dbd8dd427",
    "n5_message": "producer_profiles[0].revision for cogno-us/cognous-agent-control-plane conflicts with pinned supported revision",
}
HERE = pathlib.Path(__file__).resolve().parent
PROPOSAL_PATH = HERE / "c1" / "fixtures" / "proposal.tenant-alpha.json"
LIMITS = {  # contract section 9, L1-L19, carried verbatim in substance; none may be dropped or softened
    "status": "DEVELOPMENT_TESTED_NOT_INDEPENDENTLY_QUALIFIED_FIXTURE_SCOPED",
    "L1": "Replay is reconstruction_partial with exactly B004 (a decision-only run); never complete.",
    "L2": "Authority is synthetic and unauthenticated (test-only public Ed25519 key); authorization: authorized in the pack is a retained "
          "historical record, not current permission.",
    "L3": "Journal association is proposal-level only; event_decision_linkage NOT_ESTABLISHED; decision_id is null on all events.",
    "L4": "Zero executor attempts and zero destination effects; no effect is inferred and none is verified.",
    "L5": "The C1 original-record incompatibility with Replay is preserved.",
    "L6": "Lineage to C1/C2 is identity/proposal-level, not decision-exact.",
    "L7": "signed=false; no signature is verified; HMAC/digest is not issuer identity.",
    "L8": "No custody chain; embedded retention is not custody.",
    "L9": "No freshness; generated_at is uncompared.",
    "L10": "Provenance labels (CP/RB revision, generation, manifest revision) are caller-asserted; input_artifacts[*].trusted_revision is a "
           "field name, not a trust finding; the Pack's recorded Replay revision is the verifier's, not the producer's.",
    "L11": "Pack valid=True means internally consistent, not reviewer approval, compliance or audit.",
    "L12": "semantically_valid and valid_bundle_count=1 on a partial pack are not completeness.",
    "L13": "Tenant is verified by Replay only, not by the Pack (the Pack has no tenant field).",
    "L14": "Replay, redelivery and substitution are not defended.",
    "L15": "Hub #280 digest-basis divergence is OPEN.",
    "L16": "The Pack's Replay pin (its CP-2 row) is a PROVISIONAL DEVELOPMENT PIN, UNQUALIFIED, and not the Pack-selected pair.",
    "L17": "Developer-scope only: not independently qualified, not production, no certification or clearance (HOLD).",
    "L18": "Engineering Constitution adoption is UNVERIFIED.",
    "L19": "The Pack carries no hash of the raw Control Plane record: retained_sources holds only the manifest and the reconstruction bundle; "
           "CP-record to bundle linkage is per-run harness evidence only.",
    "decision_semantics_only": True, "effect_executed": False, "non_authorizing": True,
    "no_certification_clearance_or_production_readiness": "HOLD", "hub_280_digest_basis": "OPEN",
    "bundle_hash_semantics": "H1 = sha256 of the exact persisted bytes; H2 = the Pack's canonical-JSON sha256; never interchangeable",
    "uncompared_by_pack": ["bundle_id", "generated_at", "integrity", "derivation", "free metadata"],
    "known_limitations_not_oracles": ["tampered integrity/bundle_id/generated_at is accepted by the Pack", "substitution of a different "
                                      "valid bundle", "redelivery of an old bundle", "coherent re-identification with a recomputed pack_id"],
    "synthetic_key_scope": "public key bytes(range(32)) valid only in the producer test profile",
}


class AdapterError(Exception):
    """Measurement, fixture, producer or harness failure. Never a native Replay/Pack refusal."""


class SourceIdentityError(AdapterError):
    """A component root is missing, not the pinned checkout, modified, or an imported module is not the pinned blob."""


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _native(exc):
    return {"type": type(exc).__name__, "message": str(exc), "code": getattr(exc, "code", None)}


def _check(name, expected, observed):
    return {"name": name, "expected": expected, "observed": observed, "ok": expected == observed}


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


def _verify_git(key, root):
    """Exact commit and tree, top level, every ls-files tag H, nothing modified, hidden, untracked or ignored."""
    root = root if root is not None else os.environ.get(ENV[key])
    if not root or not os.path.isdir(root):
        raise SourceIdentityError("%s: root missing (set %s)" % (key, ENV[key]))
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
    """Every loaded module of `package` (and the extra prefixes) lies under root and equals its pinned git blob; required modules
    must be loaded, symlinks and gitlinks are refused, extra non-module files are blob-checked."""
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
_PACK_REQUIRED = ("agent_governance_evidence_pack.importer", "agent_governance_evidence_pack.validator",
                  "agent_governance_evidence_pack.loader")


def measure(roots=None):
    """Verify git identity of all four roots BEFORE touching sys.path, then import and verify the loaded modules."""
    if not sys.flags.isolated:
        raise AdapterError("run under `python -I -B`: the environment, cwd and script directory must not shape imports")
    roots = roots or {}
    verified, evidence = {}, {}
    for key in ("control_plane", "replay_bundle", "evidence_pack", "action_manifest"):
        verified[key], evidence[key] = _verify_git(key, roots.get(key))
    sys.dont_write_bytecode = True
    shadow = sys.modules.get("tests")  # the CP helper package is named `tests`: never let another tree's bind first
    if shadow is not None and verified["control_plane"] not in pathlib.Path(getattr(shadow, "__file__", None) or "/").resolve().parents:
        raise SourceIdentityError("a module named `tests` is already loaded from outside the pinned Control Plane tree")
    cp, rb, pack = verified["control_plane"], verified["replay_bundle"], verified["evidence_pack"]
    for entry in (str(pack / "src"), str(cp / "src"), str(cp), str(rb / "src")):
        if entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)
    import agent_control_plane
    import agent_control_plane.bounded as bounded
    import agent_replay_bundle
    from agent_replay_bundle import importers
    import agent_governance_evidence_pack
    from agent_governance_evidence_pack import importer as pack_importer, loader as pack_loader, validator as pack_validator
    for key, pkg in (("control_plane", agent_control_plane), ("replay_bundle", agent_replay_bundle),
                     ("evidence_pack", agent_governance_evidence_pack)):
        if verified[key] not in pathlib.Path(pkg.__file__).resolve().parents:
            raise SourceIdentityError("%s imported from %s, not under %s" % (pkg.__name__, pkg.__file__, verified[key]))
        evidence[key]["imported_module_file"] = str(pathlib.Path(pkg.__file__).resolve())
    _check_modules(cp, evidence["control_plane"], "agent_control_plane", _CP_TESTS, required=("agent_control_plane.bounded",))
    _check_modules(rb, evidence["replay_bundle"], "agent_replay_bundle", required=("agent_replay_bundle.importers",))
    _check_modules(pack, evidence["evidence_pack"], "agent_governance_evidence_pack", required=_PACK_REQUIRED)
    label = evidence["control_plane"]["observed_head"]
    if label != importers.CONTROL_PLANE_STRICT_TENANT_REVISION:  # consistency check only; the label itself is the measurement
        raise SourceIdentityError("measured Control Plane head differs from the Replay strict-tenant revision constant")
    if pack_importer.CP2_REPLAY_PIN != PINS["replay_bundle"]["sha"]:
        raise SourceIdentityError("the Pack's CP-2 Replay pin differs from the pinned Replay revision")
    return {"sources": evidence, "revision_label": label, "_roots": verified,
            "_modules": {"bounded": bounded, "importers": importers, "pack_importer": pack_importer, "pack_loader": pack_loader,
                         "pack_validator": pack_validator}}


def _recheck(measured, helpers=True):
    """Lazy imports during produce()/import must also equal the pinned blobs."""
    roots, src = measured["_roots"], measured["sources"]
    names = ("agent_control_plane.bounded",) + (("tests", "tests.test_bounded_authorization", "tests.test_runtime_authority") if helpers else ())
    _check_modules(roots["control_plane"], src["control_plane"], "agent_control_plane", _CP_TESTS, required=names,
                   extra_files=("tests/fixtures/refund_integration_v1_1.manifest.json",) if helpers else ())
    _check_modules(roots["replay_bundle"], src["replay_bundle"], "agent_replay_bundle", required=("agent_replay_bundle.importers",))
    _check_modules(roots["evidence_pack"], src["evidence_pack"], "agent_governance_evidence_pack", required=_PACK_REQUIRED)
    for key in ("control_plane", "replay_bundle", "evidence_pack", "action_manifest"):  # nothing in the run may dirty a pinned tree
        _verify_git(key, str(roots[key]))


def _public(measured):
    return {"sources": measured["sources"], "revision_label": measured["revision_label"], "revision_label_basis": "measured_git_head_and_tree"}


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


def _orchestrator_state():
    root = HERE.parent.parent
    try:
        head = _git(root, "rev-parse", "HEAD")
        dirty = _git(root, "status", "--porcelain", "--untracked-files=no") != ""
    except SourceIdentityError:
        head, dirty = None, None
    return {"head": head, "tracked_files_modified": dirty}


def _harness():
    producer = pathlib.Path(c2_producer.__file__)
    return {"real_c3_sha256": _sha(pathlib.Path(__file__).read_bytes()), "c2_producer_sha256": _sha(producer.read_bytes()),
            "orchestrator": _orchestrator_state()}


def _import_replay(importers, record_obj, proposal_obj, label):
    """The ONLY Replay call. Proposal always supplied, label always the measured one. Returns (bundle, None) or (None, native)."""
    if proposal_obj is None:
        raise AdapterError("proposal is mandatory")
    try:
        return importers.import_bounded_workflow(record_obj, proposal=proposal_obj, control_plane_revision=label), None
    except importers.ImportContractError as exc:
        return None, _native(exc)
    except Exception as exc:  # unknown failure class: neither a native refusal nor evidence
        raise AdapterError("unexpected Replay exception %s: %s" % (type(exc).__name__, str(exc)[:200])) from None


def _import_pack(P, manifest_obj, bundle_obj):
    """The ONLY Pack import call (deep copies in: the caller's objects are never touched). Returns (pack, None) or (None, native)."""
    try:
        return P["pack_importer"].import_manifest_reconstruction(copy.deepcopy(manifest_obj), copy.deepcopy(bundle_obj)), None
    except P["pack_importer"].ImportContractError as exc:
        return None, _native(exc)
    except Exception as exc:
        raise AdapterError("unexpected Pack exception %s: %s" % (type(exc).__name__, str(exc)[:200])) from None


def _fresh_workdir(workdir):
    work = pathlib.Path(workdir) if workdir is not None else pathlib.Path(tempfile.mkdtemp(prefix="c3-"))
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        raise AdapterError("workdir %s is not empty; a Control Plane record store would resume old state" % work)
    return work


def _serialise_bundle(bundle):
    """Serialise the native bundle ONCE. Persisted bytes (H1) are NOT the Pack's canonical bytes (H2): indent=2, sorted keys, trailing
    newline. Nothing is added, dropped, renamed, defaulted or rescored; bundle_id and generated_at are kept; no integrity entry is attached."""
    return (json.dumps(bundle.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _pack_view(pack, report):
    pd = pack.model_dump(mode="json")
    T = (pd.get("metadata") or {}).get("traceable_import") or {}
    issues = [{"severity": getattr(i.severity, "value", str(i.severity)), "code": i.code, "path": i.path, "message": i.message} for i in report.issues]
    return pd, T, {"valid": report.valid, "pack_id": report.pack_id, "errors": [i for i in issues if i["severity"] == "error"],
                   "warnings": [i for i in issues if i["severity"] == "warning"], "issues": issues,
                   "validation_summary": pd.get("validation_summary")}


def _prepare(roots, workdir):
    """Measure, read fixtures, run the frozen producer, import into Replay, persist the bundle once. Returns a context dict."""
    measured = measure(roots)
    P = measured["_modules"]
    if _sha(pathlib.Path(c2_producer.__file__).read_bytes()) != FROZEN["c2_producer_sha256"]:
        raise AdapterError("c2_producer.py differs from the pinned C2 file (C2 must stay unchanged)")
    prop_bytes, proposal = _read_fixture(PROPOSAL_PATH, FROZEN["proposal_sha256"], "proposal")
    man_bytes, manifest = _read_fixture(measured["_roots"]["action_manifest"] / MANIFEST_RELATIVE_PATH, FROZEN["manifest_file_sha256"], "manifest")
    work = _fresh_workdir(workdir)
    try:
        produced = c2_producer.produce(measured["_roots"]["control_plane"], work, copy.deepcopy(proposal))
    except AdapterError:
        raise
    except Exception as exc:
        raise AdapterError("producer failed: %s: %s" % (type(exc).__name__, str(exc)[:200])) from None
    rec_bytes = pathlib.Path(produced.record_path).read_bytes()  # persisted record: read ONCE
    try:
        record = _strict_loads(rec_bytes)  # parse the SAME buffer
        dest = _strict_loads(pathlib.Path(produced.destination_path).read_bytes())
    except (OSError, ValueError) as exc:
        raise AdapterError("persisted producer output is not strict JSON: %s" % exc) from None
    effects = dest.get("effects") if isinstance(dest, dict) else None
    bundle, refusal = _import_replay(P["importers"], record, copy.deepcopy(proposal), measured["revision_label"])
    if pathlib.Path(produced.record_path).read_bytes() != rec_bytes:
        raise AdapterError("persisted record file changed during import (the harness must never rewrite it)")
    ctx = {"measured": measured, "P": P, "work": work, "proposal": proposal, "prop_bytes": prop_bytes, "manifest": manifest,
           "man_bytes": man_bytes, "produced": produced, "rec_bytes": rec_bytes, "record": record, "effects": effects,
           "bundle": bundle, "replay_refusal": refusal, "dest_path": pathlib.Path(produced.destination_path)}
    if refusal is None:
        h1_bytes = _serialise_bundle(bundle)
        bundle_path = work / "reconstruction-bundle.json"
        bundle_path.write_bytes(h1_bytes)
        ctx.update(bundle_bytes=h1_bytes, bundle_path=bundle_path, bundle_obj=_strict_loads(h1_bytes), bundle_view=bundle)
    return ctx


def _base_evidence(case_id, ctx):
    m = ctx["measured"]
    return {"schema": EVIDENCE_SCHEMA, "case_id": case_id, "producer_config_id": c2_producer.CONFIG_ID, "sources": _public(m),
            "runtime": _runtime(), "producer": ctx["produced"].provenance, "limits": copy.deepcopy(LIMITS), "harness": _harness(),
            "workdir": str(ctx["work"]),
            "inputs": {"proposal": {"sha256": _sha(ctx["prop_bytes"]), "frozen_sha256": FROZEN["proposal_sha256"], "sha256_of": "file_bytes"},
                       "manifest": {"sha256": _sha(ctx["man_bytes"]), "frozen_sha256": FROZEN["manifest_file_sha256"], "sha256_of": "file_bytes",
                                    "source": "%s@%s" % (PINS["action_manifest"]["repository"], PINS["action_manifest"]["sha"])}}}


def _p1_from(ctx):
    P, m = ctx["P"], ctx["measured"]
    ev = _base_evidence(CASE_P1, ctx)
    rec_sha = _sha(ctx["rec_bytes"])
    ev["record"] = {"sha256": rec_sha, "size_bytes": len(ctx["rec_bytes"]), "path": str(ctx["produced"].record_path),
                    "sha256_of": "file_bytes", "per_run_not_frozen": True, "unchanged_after_import": True}
    ev["destination"] = {"path": str(ctx["dest_path"]), "effects": ctx["effects"], "effect_count": None if ctx["effects"] is None else len(ctx["effects"])}
    if ctx["replay_refusal"] is not None:
        ev["native_replay"] = {"outcome": "REFUSED_NATIVE", **ctx["replay_refusal"]}
        ev.update(outcome="REFUSED_NATIVE", status="FAIL", oracle={"checks": [_check("replay_imported", "IMPORTED", "REFUSED_NATIVE")], "all_ok": False})
        return ev
    bundle, bundle_obj, h1_bytes = ctx["bundle"], ctx["bundle_obj"], ctx["bundle_bytes"]
    findings = [[f.code, f.severity] for rep in bundle.import_reports for f in rep.findings]
    ev["native_replay"] = {"outcome": "IMPORTED", "status": bundle.status, "findings": findings, "bundle_version": bundle.bundle_version,
                           "bundle_id": bundle.bundle_id, "generated_at": str(bundle_obj.get("generated_at")), "integrity": bundle_obj.get("integrity"),
                           "record_types": sorted({r.record_type for r in bundle.records}),
                           "counts": {k: len(ctx["record"].get(k) or []) for k in ("attempts", "observations", "reconciliations", "closeouts")}}
    h1 = _sha(h1_bytes)
    on_disk = ctx["bundle_path"].read_bytes()
    h2 = P["pack_importer"].sha256(bundle_obj)
    pack, refusal = _import_pack(P, ctx["manifest"], bundle_obj)
    ev["bundle"] = {"path": str(ctx["bundle_path"]), "size_bytes": len(h1_bytes), "H1_sha256_persisted_bytes": h1,
                    "H2_pack_canonical_sha256": h2, "h1_and_h2_are_distinct_values": ("sha256:" + h1) != h2,
                    "persisted_bytes_equal_disk": on_disk == h1_bytes, "serialised_once": True, "integrity_attached": False}
    ev["raw_record_to_bundle_linkage"] = {"cp_record_sha256": rec_sha, "bundle_H1": h1, "carried_by_pack": False,
                                          "note": "L19: the Pack carries no hash of the raw Control Plane record; this linkage is harness evidence only"}
    if refusal is not None:
        ev["native_pack"] = {"outcome": "REFUSED_NATIVE", **refusal}
        ev.update(outcome="REFUSED_NATIVE", status="FAIL", oracle={"checks": [_check("pack_imported", "IMPORTED", "REFUSED_NATIVE")], "all_ok": False})
        return ev
    report = P["pack_validator"].validate_evidence_pack(pack)
    pd, T, view = _pack_view(pack, report)
    pack_path = ctx["work"] / "evidence-pack.json"
    P["pack_loader"].dump_evidence_pack(pack, pack_path)
    again, _ = _import_pack(P, ctx["manifest"], bundle_obj)
    rb0_signed = ((pd.get("replay_bundles") or [{}])[0]).get("signed")
    ev["native_pack"] = {"outcome": "IMPORTED", "pack_id": pd.get("pack_id"), "pack_version": pd.get("pack_version"),
                         "review_status": pd.get("review_status"), "validation": view, "pack_path": str(pack_path),
                         "pack_file_sha256": _sha(pack_path.read_bytes()), "pack_file_sha256_of": "file_bytes_as_written_by_native_dump",
                         "transformation_version": T.get("transformation_version"), "selected_revisions": T.get("selected_revisions"),
                         "replay_semantic_validation": T.get("replay_semantic_validation"),
                         "lifecycle_summary": {k: (T.get("lifecycle_summary") or {}).get(k) for k in (
                             "authorization", "current_permission", "execution_attempted", "destination_observed",
                             "independent_verification", "reconstruction_status")},
                         "replay_semantics": T.get("replay_semantics"), "reconstruction_completeness": T.get("reconstruction_completeness"),
                         "replay_bundles": pd.get("replay_bundles"), "input_artifacts": T.get("input_artifacts"),
                         "unresolved_issues": T.get("unresolved_issues"), "conversion_losses": T.get("conversion_losses"),
                         "retained_source_scope": T.get("retained_source_scope"), "pack_signed": rb0_signed}
    retained = (T.get("retained_sources") or {})
    decs = [r for r in (retained.get("reconstruction_bundle") or {}).get("records", []) if r.get("record_type") == "runtime_decision"]
    dd = (decs[0].get("data") if len(decs) == 1 else None) or {}
    bind = dd.get("binding") or {}
    cp_decision = ctx["produced"].decision
    ia = T.get("input_artifacts") or [{}, {}]
    lc = T.get("lifecycle_summary") or {}
    sem = T.get("replay_semantics") or {}
    rb0 = (pd.get("replay_bundles") or [{}])[0]
    checks = [
        _check("rb_status", ORACLE["rb_status"], bundle.status), _check("rb_findings", ORACLE["rb_findings"], findings),
        _check("rb_counts_zero", {k: 0 for k in ev["native_replay"]["counts"]}, ev["native_replay"]["counts"]),
        _check("rb_bundle_version", "0.2.0", bundle.bundle_version), _check("rb_integrity_empty_none_attached", [], bundle_obj.get("integrity")),
        _check("destination_effects", {}, ctx["effects"]),
        _check("pack_version", ORACLE["pack_version"], pd.get("pack_version")), _check("review_status_draft", ORACLE["review_status"], pd.get("review_status")),
        _check("transformation_version", ORACLE["transformation_version"], T.get("transformation_version")),
        _check("selected_revisions", {"manifest": PINS["action_manifest"]["sha"], "replay": PINS["replay_bundle"]["sha"],
                                      "control_plane": PINS["control_plane"]["sha"]}, T.get("selected_revisions")),
        _check("replay_semantic_validation", {"validator": ORACLE["validator"], "required_revision": PINS["replay_bundle"]["sha"],
                                              "status": "validated_partial"}, T.get("replay_semantic_validation")),
        _check("replay_bundles_status", "validated_partial", rb0.get("status")), _check("replay_bundles_signed", False, rb0.get("signed")),
        _check("replay_bundles_redacted", False, rb0.get("redacted")),
        _check("replay_bundles_validation_status", "semantically_valid", rb0.get("validation_status")),
        _check("reconstruction_completeness", "reconstruction_partial", T.get("reconstruction_completeness")),
        _check("lifecycle_authorization_historical", "authorized", lc.get("authorization")),
        _check("lifecycle_current_permission", "not_evaluated_from_historical_records", lc.get("current_permission")),
        _check("lifecycle_execution_attempted", "no", lc.get("execution_attempted")),
        _check("lifecycle_destination_observed", "unknown", lc.get("destination_observed")),
        _check("lifecycle_independent_verification", "unavailable", lc.get("independent_verification")),
        _check("lifecycle_reconstruction_status", "reconstruction_partial", lc.get("reconstruction_status")),
        _check("replay_semantics_flags", {"policy_reevaluation": False, "external_effect_execution": False, "destination_observation": "not_performed",
                                          "independent_effect_verification": False},
               {k: sem.get(k) for k in ("policy_reevaluation", "external_effect_execution", "destination_observation", "independent_effect_verification")}),
        _check("manifest_digest", ORACLE["manifest_digest"], ia[0].get("hash")), _check("manifest_artifact_role", "manifest", ia[0].get("artifact_role")),
        _check("pack_valid", True, view["valid"]), _check("pack_zero_errors", 0, len(view["errors"])),
        _check("pack_input_artifact_H2_equals_pack_canonical", h2, ia[1].get("hash")),
        _check("H2_recomputed_by_pack_helper", h2, P["pack_importer"].sha256(bundle_obj)),
        _check("retained_bundle_equals_persisted_bundle", bundle_obj, retained.get("reconstruction_bundle")),
        _check("retained_manifest_equals_manifest_fixture", ctx["manifest"], retained.get("manifest")),
        _check("retained_decision_id", cp_decision.get("decision_id"), dd.get("decision_id")),
        _check("retained_effect_id", ORACLE["effect_id"], dd.get("effect_id")),
        _check("retained_proposal_commitment", ORACLE["proposal_commitment"], bind.get("proposal_commitment")),
        _check("retained_tenant", ORACLE["tenant_id"], bind.get("tenant_id")),
        _check("retained_generation", ORACLE["generation"], bind.get("generation")),
        _check("pack_id_deterministic_for_identical_bundle", pd.get("pack_id"), None if again is None else again.pack_id),
        _check("persisted_bytes_equal_disk", True, ev["bundle"]["persisted_bytes_equal_disk"]),
        _check("h1_h2_distinct", True, ev["bundle"]["h1_and_h2_are_distinct_values"]),
        _check("h1_matches_independent_hash_of_bytes", hashlib.sha256(h1_bytes).hexdigest(), h1)]
    _recheck(m)
    ok = all(c["ok"] for c in checks)
    ev["oracle"] = {"checks": checks, "all_ok": ok}
    ev["implementation_observed_not_frozen"] = {"pack_warning_codes": [w["code"] for w in view["warnings"]],
                                                "pack_validation_summary": view["validation_summary"],
                                                "note": "warnings are template-field emptiness; neither a count nor the pack's own warning_count is evidence fidelity"}
    ev.update(outcome="IMPORTED", status="PASS" if ok else "FAIL", pack_valid_is_not_approval=True)
    return ev


def _negative(case_id, ctx, p1, mutate, mutation, expected_message):
    """One-mutation negative: original manifest and bundle preserved, only `mutate` applied to a deep copy, native refusal verbatim."""
    P = ctx["P"]
    ev = _base_evidence(case_id, ctx)
    ev["p1_precondition"] = {"outcome": p1["outcome"], "status": p1["status"], "record_sha256": p1["record"]["sha256"]}
    if p1["outcome"] != "IMPORTED" or p1["status"] != "PASS":
        ev.update(outcome="FAIL", status="FAIL", reason="negative precondition: the unmodified P1 case did not pass")
        return ev
    original = ctx["bundle_obj"]
    original_h2 = P["pack_importer"].sha256(original)
    mutated = copy.deepcopy(original)
    mutate(mutated)  # the ONLY change
    if mutated == original:
        raise AdapterError("%s: the mutation did not change the bundle" % case_id)
    effects_before = ctx["effects"]
    pack, refusal = _import_pack(P, ctx["manifest"], mutated)
    effects_after = _strict_loads(ctx["dest_path"].read_bytes()).get("effects")
    intact = ctx["bundle_path"].read_bytes() == ctx["bundle_bytes"] and P["pack_importer"].sha256(original) == original_h2
    ev["mutation"] = {**mutation, "original_bundle_H1_sha256": _sha(ctx["bundle_bytes"]), "original_bundle_H2_pack_canonical_sha256": original_h2,
                      "mutated_bundle_H2_pack_canonical_sha256": P["pack_importer"].sha256(mutated),
                      "mutated_hash_basis": "pack_canonical_reserialisation_of_test_mutation_not_persisted_bytes",
                      "manifest_supplied": True, "manifest_file_sha256": _sha(ctx["man_bytes"]), "original_unmodified_after_run": intact}
    ev["destination"] = {"effects_before": effects_before, "effects_after": effects_after, "no_effect": effects_before == effects_after == {}}
    if refusal is None:
        ev.update(native_pack={"outcome": "IMPORTED", "pack_id": pack.pack_id}, outcome="FAIL", status="FAIL",
                  reason="tampered bundle was imported; the frozen expectation was not met")
        return ev
    checks = [_check("exception_type", "ImportContractError", refusal["type"]), _check("message", expected_message, refusal["message"]),
              _check("code_is_none_native_has_no_code", None, refusal["code"]), _check("original_bundle_unmodified", True, intact),
              _check("no_destination_effect", True, ev["destination"]["no_effect"])]
    ok = all(c["ok"] for c in checks)
    _recheck(ctx["measured"])
    ev.update(native_pack={"outcome": "REFUSED_NATIVE", **refusal}, oracle={"checks": checks, "all_ok": ok},
              outcome="REFUSED_NATIVE" if ok else "FAIL", status="PASS" if ok else "FAIL")
    return ev


def _decision(bundle_obj):
    decs = [r for r in bundle_obj["records"] if r.get("record_type") == "runtime_decision"]
    if len(decs) != 1:
        raise AdapterError("the bundle does not hold exactly one runtime_decision record")
    return decs[0]


def _mut_n1(b):
    binding = _decision(b)["data"]["binding"]
    if binding.get("tenant_id") != ORACLE["tenant_id"]:
        raise AdapterError("N1-TEN precondition: the decision tenant is not %s" % ORACLE["tenant_id"])
    binding["tenant_id"] = "tenant-beta"


def _mut_n3a(b):
    if b.get("status") != ORACLE["rb_status"]:
        raise AdapterError("N3 precondition: the bundle status is not %s" % ORACLE["rb_status"])
    b["status"] = "reconstruction_complete"


def _mut_n3b(b):
    _mut_n3a(b)
    for rep in b["import_reports"]:
        rep["complete"] = True
        rep["findings"] = []


def _mut_n5(b):
    prof = b["producer_profiles"][0]
    if prof.get("revision") != PINS["control_plane"]["sha"]:
        raise AdapterError("N5-REV precondition: producer_profiles[0].revision is not the measured Control Plane head")
    prof["revision"] = ORACLE["n5_wrong_revision"]


def run_all(roots=None, workdir=None):
    """P1 then N1-TEN, N3 (status alone, and status plus complete import reports with findings cleared) and N5-REV in one measured run."""
    ctx = _prepare(roots, workdir)
    p1 = _p1_from(ctx)
    out = {CASE_P1: p1}
    if ctx["replay_refusal"] is None:
        out[CASE_N1] = _negative(CASE_N1, ctx, p1, _mut_n1, {"field_path": "records[runtime_decision].data.binding.tenant_id",
                                                              "from": ORACLE["tenant_id"], "to": "tenant-beta"}, ORACLE["n1_message"])
        n3a = _negative(CASE_N3, ctx, p1, _mut_n3a, {"field_path": "status", "from": ORACLE["rb_status"], "to": "reconstruction_complete",
                                                      "variant": "status_alone"}, ORACLE["n3_message"])
        n3b = _negative(CASE_N3, ctx, p1, _mut_n3b, {"field_path": "status+import_reports[*].complete+findings", "from": ORACLE["rb_status"],
                                                      "to": "reconstruction_complete, reports complete, findings cleared",
                                                      "variant": "status_and_reports_forged_complete"}, ORACLE["n3_message"])
        n3a["variant_b"] = n3b
        both = n3a["status"] == "PASS" and n3b["status"] == "PASS"
        n3a["status"] = "PASS" if both else "FAIL"
        n3a["outcome"] = "REFUSED_NATIVE" if both else "FAIL"
        out[CASE_N3] = n3a
        out[CASE_N5] = _negative(CASE_N5, ctx, p1, _mut_n5, {"field_path": "producer_profiles[0].revision", "from": PINS["control_plane"]["sha"],
                                                              "to": ORACLE["n5_wrong_revision"]}, ORACLE["n5_message"])
        _recheck(ctx["measured"])  # the whole run, early returns included, must leave every pinned tree and module untouched
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the VSLICE-C3 cases (development-only, fixture-scoped, non-authorizing).")
    parser.add_argument("--case", default="all", help="all or one of: %s" % ", ".join((CASE_P1, CASE_N1, CASE_N3, CASE_N5)))
    parser.add_argument("--out")
    parser.add_argument("--workdir")
    args = parser.parse_args(argv)
    if args.case != "all" and args.case not in (CASE_P1, CASE_N1, CASE_N3, CASE_N5):
        print("refused: case id is not allowlisted", file=sys.stderr)
        return 2
    try:
        results = run_all(workdir=args.workdir)
    except AdapterError as exc:
        print("adapter error: %s" % exc, file=sys.stderr)
        return 2
    chosen = results if args.case == "all" else {args.case: results[args.case]}
    text = json.dumps(chosen, indent=2, sort_keys=True, default=str) + "\n"
    if args.out:
        pathlib.Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0 if all(v["status"] == "PASS" for v in chosen.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
