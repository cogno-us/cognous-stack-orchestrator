"""VSLICE-C1 adapter: real Action Manifest producer -> real Control Plane consumer (Python API and CLI).

Development-only and fixture-scoped. The authority context and resolver state are synthetic and unauthenticated: they
are test fixtures, not issued authority. The contract exercised here is a CANDIDATE and is not adopted. The Hub #280
digest-basis defect is OPEN and is gated (the producer refuses on divergence), not fixed. Non-authorizing: ACCEPTED means
only that the Control Plane returned "authorized" under synthetic, unauthenticated authority; any gate failure, missing
authority or unknown verdict is HOLD / refusal, never production readiness. No effect path is ever used: only
BoundedAuthorizationWorkflow.decide() is called, never execute(), reconcile() or the `acp run` CLI.
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
from datetime import datetime, timezone
from typing import NamedTuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I omits the script dir
import runner  # noqa: E402

ENV_MANIFEST_ROOT = "COGNOUS_C1_ACTION_MANIFEST_ROOT"
ENV_CP_ROOT = "COGNOUS_C1_CONTROL_PLANE_ROOT"
CASE_AUTHORIZED = "c1_manifest_to_cp_authorized"
CASE_NO_AUTHORITY = "c1_manifest_to_cp_no_authority"
PINS = {
    "manifest": {"repository": "cogno-us/cognous-action-manifest", "sha": "fa170815ef96a54c233d0dd9da821b60debabf8b",
                 "tree": "3b0e3772e944aa668c8f4b879588c7cc3e2c32be"},
    "control_plane": {"repository": "cogno-us/cognous-control-plane", "sha": "484fdbd297235dd24148ddb0703f2055a31eabff",
                      "tree": "c182939882103015f12c5360fccf377c54e2c4f9"},
}
MANIFEST_RELATIVE_PATH = "examples/refund_integration_v1_1.manifest.json"
FROZEN = {
    "manifest_file_sha256": "789ad39596b9e1ef84a726a671883e1cb6b83343da3a31db0a1120906d68c074",
    "proposal_sha256": "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2",
    "authority_context_sha256": "87a231dda0756bf7e66a72f13e4fd655830640baa955e1b79b9654e1fd69ba32",
    "resolver_state_sha256": "075fb26f316311be9f3d4b3932e60191012f6370eb709b5b893f3a0c2d4913bd",
}
# `deny` is in the CP result type but is never assigned by decide() at the pinned revision; mapped for completeness only.
ADMISSION_MAP = {"authorized": "ACCEPTED", "hold": "REFUSED", "deny": "REFUSED"}
NOW = datetime(2026, 10, 5, 19, 0, tzinfo=timezone.utc)
EVIDENCE_SCHEMA = "cognous.orchestrator.c1-evidence/0-candidate"
FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "c1" / "fixtures"
FIXTURE_FILES = {"proposal": "proposal.tenant-alpha.json", "authority_context": "authority-context.tenant-alpha.json",
                 "resolver_state": "resolver-state.tenant-alpha.json"}


class SourceIdentityError(RuntimeError):
    """A component root is missing, not the pinned checkout, modified, or the imported module is not under it."""


class C1GateError(Exception):
    """Producer-side fail-closed gate failure."""


class _Evidence(dict):
    """Plain JSON-serialisable dict that also carries the function which refills it for a new run."""
    reset = sources_check = harness = None


class C1Context(NamedTuple):
    registry: runner.Registry
    evidence: dict
    workdir: pathlib.Path


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _obj_bytes(obj):
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _strict_loads(data):
    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate object member refused")
        return dict(items)
    return json.loads(data, object_pairs_hook=pairs)


LIMITS = {"status": "DEVELOPMENT_ONLY_FIXTURE_SCOPED", "authority_basis": "SYNTHETIC_UNAUTHENTICATED_RESOLVER",
          "decision_semantics_only": True, "not_institutional_authority": True, "not_independent_qualification": True,
          "not_general_interoperability": True, "hub_280_digest_basis": "OPEN", "effect_executed": False}
HERE = pathlib.Path(__file__).resolve().parent


def _git(root, *args):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "LC_ALL": "C"}
    try:
        done = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *args], cwd=tempfile.gettempdir(),
                              env=env, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceIdentityError("git failed for %s: %s" % (root, type(exc).__name__)) from None
    if done.returncode != 0:
        raise SourceIdentityError("%s is not a usable git checkout (git %s failed)" % (root, args[0]))
    return done.stdout.strip()


def _verify_source(key, root, env_name):
    """Check the pinned checkout is exactly the pinned commit with nothing modified, hidden, untracked or ignored."""
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
    if tags != {"H "}:  # assume-unchanged / skip-worktree / unmerged markers hide modifications
        raise SourceIdentityError("%s: git ls-files -v shows non-H tags %s" % (key, sorted(tags - {"H "})))
    if _git(root, "status", "--porcelain", "--ignored=matching", "--untracked-files=all") != "":
        raise SourceIdentityError("%s: checkout has modified, untracked or ignored files" % key)
    return root, {"repository": pin["repository"], "pinned_sha": pin["sha"], "observed_head": head, "pinned_tree": pin["tree"],
                  "observed_tree": tree, "tracked_files_clean": True, "ls_files_all_H": True, "status_ignored_clean": True}


def _check_modules(root, src_ev):
    """Every loaded module under <root>/src must be byte-identical (git blob hash) to HEAD; record them."""
    src = root / "src"
    blobs = {}
    for line in _git(root, "ls-tree", "-r", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        blobs[path] = meta.split()[2]
    mods = {}
    for name, mod in sorted(sys.modules.items()):
        file = getattr(mod, "__file__", None)
        if not file or src not in pathlib.Path(file).resolve().parents:
            continue
        data = pathlib.Path(file).resolve().read_bytes()
        blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
        rel = pathlib.Path(file).resolve().relative_to(root).as_posix()
        if blobs.get(rel) != blob:
            raise SourceIdentityError("module %s (%s) differs from the pinned git blob" % (name, rel))
        mods[name] = {"file": str(pathlib.Path(file).resolve()), "git_blob_sha": blob}
    src_ev["imported_modules"] = mods


def build(manifest_root=None, cp_root=None, *, manifest_file=None, proposal=None, authority_context=None,
          resolver_state=None, workdir=None):
    am_root, am_src = _verify_source("manifest", manifest_root, ENV_MANIFEST_ROOT)
    cp_root, cp_src = _verify_source("control_plane", cp_root, ENV_CP_ROOT)
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(cp_root / "src"), str(am_root / "src")]
    import agent_action_manifest as am_pkg
    from agent_action_manifest import models as am_models
    import agent_control_plane
    import agent_control_plane.bounded as bounded
    import agent_control_plane.cli_run as cli_run
    import pydantic
    for root, src_ev, pkg in ((am_root, am_src, am_pkg), (cp_root, cp_src, agent_control_plane)):
        if root not in pathlib.Path(pkg.__file__).resolve().parents:
            raise SourceIdentityError("%s imported from %s, not under %s" % (pkg.__name__, pkg.__file__, root))
        src_ev["imported_module_file"] = str(pathlib.Path(pkg.__file__).resolve())
        _check_modules(root, src_ev)

    manifest_path = pathlib.Path(manifest_file) if manifest_file is not None else am_root / MANIFEST_RELATIVE_PATH
    manifest_bytes = manifest_path.read_bytes()
    overrides = {"manifest_file": manifest_file, "proposal": proposal, "authority_context": authority_context,
                 "resolver_state": resolver_state}
    fixture_ev = {"manifest_file": {"mode": "frozen" if manifest_file is None else "test_override", "sha256": _sha(manifest_bytes),
                                    "sha256_of": "file_bytes",
                                    "relative_path": MANIFEST_RELATIVE_PATH if manifest_file is None else str(manifest_path)}}
    inputs = {}
    for name in ("proposal", "authority_context", "resolver_state"):
        if overrides[name] is None:
            data = (FIXTURE_DIR / FIXTURE_FILES[name]).read_bytes()  # read once: the verified bytes are the parsed bytes
            if _sha(data) != FROZEN[name + "_sha256"]:
                raise C1GateError("fixture %s sha256 differs from the frozen value" % name)
            inputs[name] = _strict_loads(data)
            fixture_ev[name] = {"mode": "frozen", "sha256": _sha(data), "sha256_of": "file_bytes"}
        else:
            inputs[name] = overrides[name]
            fixture_ev[name] = {"mode": "test_override", "sha256": _sha(_obj_bytes(overrides[name])),
                                "sha256_of": "canonical_reserialisation"}
    used = [n for n, o in overrides.items() if o is not None]
    work = pathlib.Path(workdir) if workdir is not None else pathlib.Path(tempfile.mkdtemp(prefix="c1-"))
    ev = _Evidence()

    def reset(case_id):
        ev.clear()
        ev.update({
            "schema": EVIDENCE_SCHEMA, "case_id": case_id, "mode": "test_override" if used else "frozen",
            "frozen_fixture": not used, "overridden_inputs": used, "limits": dict(LIMITS),
            "sources": {"manifest": copy.deepcopy(am_src), "control_plane": copy.deepcopy(cp_src)},
            "runtime": {"python": sys.version.split()[0], "pydantic": pydantic.VERSION},
            "fixtures": copy.deepcopy(fixture_ev),
            "digests": {"am_manifest_digest": None, "cp_manifest_commitment": None, "am_proposal_digest": None,
                        "proposal_mismatches": None},
            "gate": {"passed": False, "failure": None},
            "clock": {"now": NOW.isoformat(), "allow_test_time": True, "developer_only_override": True},
            "consumer_invocations": 0, "destination": None, "workdir": str(work)})
        if case_id == CASE_NO_AUTHORITY:
            ev["fixtures"]["authority_context"] = {"withheld": True}

    def gate(step, ok, message, kind="C1GateError"):
        if not ok:
            err = C1GateError(message)
            err.step, err.kind = step, kind
            raise err

    def producer(fixture):
        step = "manifest_bytes"
        try:
            data = manifest_path.read_bytes()
            gate(step, data == fixture, "manifest file bytes differ from the case fixture")
            if manifest_file is None:
                gate(step, _sha(data) == FROZEN["manifest_file_sha256"], "manifest file sha256 differs from the frozen value")
            step = "manifest_load"
            model = am_pkg.load_manifest(manifest_path)
            gate(step, manifest_path.read_bytes() == data, "manifest file changed while it was being loaded")
            step = "manifest_validate"
            gate(step, am_pkg.validate_manifest(model).valid is True, "Action Manifest validate_manifest reports invalid")
            step = "manifest_version"
            gate(step, model.manifest_version == "1.1", "manifest_version is %r, not '1.1'" % (model.manifest_version,))
            step = "digest_basis"
            raw = _strict_loads(data)
            gate(step, isinstance(raw, dict), "manifest is not a JSON object")
            am_digest, cp_digest = am_pkg.manifest_digest(model), bounded.commitment(raw)
            ev["digests"].update(am_manifest_digest=am_digest, cp_manifest_commitment=cp_digest)
            gate(step, am_digest == cp_digest, "digest basis divergence between Action Manifest and Control Plane (Hub #280, open, gated not fixed)")
            step = "proposal_model"
            prop_model = am_models.RuntimeActionProposalV12.model_validate(inputs["proposal"])
            step = "proposal_mismatches"
            mismatches = list(am_pkg.proposal_mismatches(model, prop_model))
            ev["digests"].update(am_proposal_digest=am_pkg.proposal_digest(prop_model), proposal_mismatches=mismatches)
            gate(step, mismatches == [], "proposal_mismatches: %s" % (mismatches,))
        except Exception as exc:  # any producer failure stops the edge; record where and why
            kind = getattr(exc, "kind", type(exc).__name__)
            ev["gate"] = {"passed": False, "failure": {"type": kind, "step": step, "message": str(exc)[:300]}}
            if isinstance(exc, C1GateError):
                raise
            raise C1GateError("%s at %s: %s" % (kind, step, str(exc)[:200])) from None
        ev["gate"] = {"passed": True, "failure": None}
        return data

    def make_call(with_authority):
        def call(data):
            ev["consumer_invocations"] += 1
            raw = _strict_loads(data)
            prop = bounded.TenantRuntimeProposal.model_validate(inputs["proposal"])
            unknown = sorted(set(inputs["resolver_state"]) - set(cli_run.RESOLVER_SECTIONS))
            if unknown:
                raise ValueError("resolver-state: unknown sections refused: %s" % unknown)
            sections = {n: {k: m.model_validate(v) for k, v in inputs["resolver_state"].get(n, {}).items()}
                        for n, m in cli_run.RESOLVER_SECTIONS.items()}
            contexts = {prop.authority_context_ref: inputs["authority_context"]} if with_authority else {}
            dest = work / "destination.json"  # one workdir per build; records.json keeps state, so do not share it across cases
            wf = bounded.BoundedAuthorizationWorkflow(
                manifest=raw, resolver=bounded.SyntheticResolver(contexts=contexts, **sections),
                destination=bounded.LocalRefundDestination(dest),
                records=bounded.BoundedRecordStore(work / "records.json", prop.run_id),
                allow_test_time=True, tenant_binding_generation=bounded.TENANT_GENERATION_STRICT)
            decision = wf.decide(prop, now=NOW)  # decision only: never execute() or reconcile()
            effects = json.loads(dest.read_text(encoding="utf-8") or "{}").get("effects", {}) if dest.exists() else {}
            ev["destination"] = {"path": str(dest), "effects": effects, "effect_count": len(effects)}
            return decision.model_dump(mode="json")
        return call

    ev.reset = reset
    ev.sources_check = lambda: [_check_modules(r, ev["sources"][k]) for k, r in (("manifest", am_root), ("control_plane", cp_root))]
    ev.harness = {"real_c1_sha256": _sha(pathlib.Path(__file__).read_bytes()),
                  "runner_sha256": _sha(pathlib.Path(runner.__file__).read_bytes()), "orchestrator_head": _orchestrator_head()}
    reset(None)
    registry = runner.Registry(
        producers={"action_manifest_c1": producer},
        consumers={"cp_authority_applicable": runner.Consumer(make_call(True), "result", ADMISSION_MAP),
                   "cp_authority_withheld": runner.Consumer(make_call(False), "result", ADMISSION_MAP)},
        cases={CASE_AUTHORIZED: ("action_manifest_c1", manifest_bytes, "cp_authority_applicable"),
               CASE_NO_AUTHORITY: ("action_manifest_c1", manifest_bytes, "cp_authority_withheld")},
        expectations={CASE_AUTHORIZED: "ACCEPTED", CASE_NO_AUTHORITY: "REFUSED"})
    return C1Context(registry, ev, work)


def _orchestrator_head():
    try:
        return _git(HERE, "rev-parse", "HEAD")
    except SourceIdentityError:
        return None


def run(case_id, ctx):
    if case_id not in ctx.registry.cases:
        raise KeyError(case_id)
    ev = ctx.evidence
    ev.reset(case_id)
    result = runner.run_case(case_id, ctx.registry)
    ev.sources_check()  # lazy imports during decide() must also match the pinned blobs
    ev["runner_result_sha256"] = _sha(runner.result_json(result).encode("utf-8"))
    ev["harness"] = dict(ev.harness)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one VSLICE-C1 case (development-only, fixture-scoped).")
    parser.add_argument("--case", required=True)
    parser.add_argument("--out")
    parser.add_argument("--evidence-out")
    args = parser.parse_args(argv)
    if args.case not in (CASE_AUTHORIZED, CASE_NO_AUTHORITY):
        print("refused: case id is not allowlisted", file=sys.stderr)
        return 2
    try:
        ctx = build()
    except (SourceIdentityError, C1GateError) as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 2
    result = run(args.case, ctx)
    text = runner.result_json(result)
    if args.out:
        pathlib.Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.evidence_out:
        pathlib.Path(args.evidence_out).write_text(json.dumps(ctx.evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
