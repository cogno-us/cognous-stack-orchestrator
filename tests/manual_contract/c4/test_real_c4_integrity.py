"""Integrity tests for the VSLICE-C4 coordinator (real_c4) and producer (c4_producer): source identity of all four roots, fixture
integrity, byte preservation, limitations, claim promotion, no-effect, static guards, scope containment, API shape. Companion to
test_real_c4.py (functional / native oracle observations), which this file does not duplicate.

DRAFT. Expectations come ONLY from the frozen literals restated below (Hub #273 C4 contract 6674059997, frozen for development by the
Architect decision A1-A9; the C3 contract 6671327666 section 9 for L1-L19) and from this file's own independent observations (files
read from disk, this file's own native Replay/Pack calls, spies on the real component calls). They are never read back from harness
output; harness evidence is only compared AGAINST them. stdlib unittest only; run with `python -I -B`. The four component roots come
from the COGNOUS_C4_* environment variables and are REQUIRED (the run fails, it does not skip). Pinned roots are only read: every
mutation is made on a clone.

A green run means the C4 coordinator preserved bytes, identity and limitations on a synthetic fixture and ran decide() only. It is not
qualification, authenticity, effect proof, approval or acceptance of anything.
"""
import sys

sys.dont_write_bytecode = True  # never write .pyc into the pinned checkouts: their cleanliness is part of the source gate

import ast
import builtins
import contextlib
import copy
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
MANUAL = HERE.parent
REPO = MANUAL.parent.parent
sys.path.insert(0, str(MANUAL))
import real_c3  # noqa: E402  (public C3 surface only; must not import any component at module import time)
import real_c4  # noqa: E402
import c4_producer  # noqa: E402

ENVS = {"action_manifest": "COGNOUS_C4_ACTION_MANIFEST_ROOT", "control_plane": "COGNOUS_C4_CONTROL_PLANE_ROOT",
        "replay_bundle": "COGNOUS_C4_REPLAY_BUNDLE_ROOT", "evidence_pack": "COGNOUS_C4_EVIDENCE_PACK_ROOT"}
KEYS = tuple(ENVS)
BASE = "aff43bdd4e9540537e6d53f326848f7a37e57b8d"  # orchestrator base commit of this slice
CASE_P1, CASE_N1, CASE_N2 = "c4_p1_authorized_chain", "c4_n1_hold_revoked_grant", "c4_n2_flip_hold_to_authorized"
CASES = (CASE_P1, CASE_N1, CASE_N2)
EVIDENCE_SCHEMA = "cognous.orchestrator.c4-evidence/0-candidate"

# ---- frozen literals (C4 contract sections 2, 6, 8, 9; C3 contract section 2) ----
PINS = {
    "action_manifest": ("cogno-us/cognous-action-manifest", "fa170815ef96a54c233d0dd9da821b60debabf8b", "3b0e3772e944aa668c8f4b879588c7cc3e2c32be"),
    "control_plane": ("cogno-us/cognous-control-plane", "484fdbd297235dd24148ddb0703f2055a31eabff", "c182939882103015f12c5360fccf377c54e2c4f9"),
    "replay_bundle": ("cogno-us/cognous-replay-bundle", "93a76e281fcae6a65d2cd1d35376f87442dafb95", "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f"),
    "evidence_pack": ("cogno-us/cognous-governance-evidence-pack", "065150852cc2a8abeb748777bb69d72ccd0e03d8", "fe428a89da2e74346648cdfe014462ddc8624c77"),
}
CP_SHA = PINS["control_plane"][1]
PROPOSAL_SHA = "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2"
MANIFEST_FILE_SHA = "789ad39596b9e1ef84a726a671883e1cb6b83343da3a31db0a1120906d68c074"
MANIFEST_DIGEST = "sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac"
PROPOSAL_COMMITMENT = "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53"
EFFECT_AUTHORIZED = "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8"
EFFECT_HOLD = "sha256:d0e4afe09cdf3a52aa3b530b822411b1dff35031973660fbbf9b707415f18465"
C2_PRODUCER_SHA = "7c4f2595d7939e4a373586faafc0de86469dc03b791d893d7b27fb328a02a895"
MANIFEST_REL = "examples/refund_integration_v1_1.manifest.json"
CP_MANIFEST_REL = "tests/fixtures/refund_integration_v1_1.manifest.json"
PROPOSAL_PATH = MANUAL / "c1" / "fixtures" / "proposal.tenant-alpha.json"
TRACKED_FILE = {  # one tracked file per root that the harness loads or reads
    "action_manifest": MANIFEST_REL, "control_plane": "src/agent_control_plane/bounded.py",
    "replay_bundle": "src/agent_replay_bundle/importers.py", "evidence_pack": "src/agent_governance_evidence_pack/importer.py"}
AM_MODULE_FILE = "src/agent_action_manifest/binding.py"
CP_HELPER_FILES = ("tests/test_bounded_authorization.py", "tests/test_runtime_authority.py", "tests/__init__.py")
COMPONENT_PREFIXES = ("agent_action_manifest", "agent_control_plane", "agent_replay_bundle", "agent_governance_evidence_pack")

# ---- C3 contract section 9: L1-L19 key phrases (compared lower-case); the C4 limits must carry the C3 text unchanged ----
LIMIT_PHRASES = {
    1: ("reconstruction_partial", "b004", "never complete"),
    2: ("synthetic", "unauthenticated", "test-only public ed25519 key", "not current permission"),
    3: ("proposal-level only", "event_decision_linkage not_established", "decision_id is null"),
    4: ("zero executor attempts", "zero destination effects", "none is verified"),
    5: ("original-record incompatibility", "preserved"),
    6: ("identity/proposal-level", "not decision-exact"),
    7: ("signed=false", "no signature is verified", "not issuer identity"),
    8: ("no custody chain", "not custody"),
    9: ("no freshness", "generated_at is uncompared"),
    10: ("caller-asserted", "field name, not a trust finding", "pack constants", "nothing verifies where the supplied", "verifier's, not the producer's"),
    11: ("valid=true", "not reviewer approval", "compliance or audit"),
    12: ("semantically_valid", "valid_bundle_count=1", "not completeness"),
    13: ("verified by replay only", "not by the pack"),
    14: ("not defended",),
    15: ("hub #280", "open"),
    16: ("provisional", "unqualified"),
    17: ("not independently qualified", "not production", "hold"),
    18: ("constitution", "unverified"),
    19: ("no hash of the raw control plane record", "retained_sources", "reconstruction bundle", "harness evidence only"),
}
# ---- C4 contract section 16: L20-L27 key phrases (compared lower-case, hyphens/underscores folded) ----
NEW_LIMIT_PHRASES = {
    20: ("no proposal", "hand-authored", "hash-pinned", "validates"),
    21: ("profile-enabled", "c1", "identity level"),
    22: ("hold", "does not bind", "proposal", "tenant", "first-class tenant field"),
    23: ("effect_id", "verdict"),
    24: ("run-1", "literal", "not a run identity"),
    25: ("not_attempted", "refused", "held", "not component statuses", "decide()"),
    26: ("synthetic", "grant", "not a real revocation"),
    27: ("producer configuration id", "persisted by no component", "deny"),
}
LIMIT_FLAGS = {"decision_semantics_only": True, "effect_executed": False, "non_authorizing": True,
               "no_certification_clearance_or_production_readiness": "HOLD", "hub_280_digest_basis": "OPEN"}
# positive claims that may appear ONLY inside a negated limitation text (never as a value elsewhere in the evidence)
FORBIDDEN_CLAIMS = (r"complete reconstruction", r"fully reconstructed", r"reconstruction_complete(?!ness)", r"\bauthenticated authority",
                    r"\bverified execution", r"\bexecution verified", r"\bcertified\b", r"\bapproved\b", r"production[ -]ready",
                    r"\bindependently qualified", r"\bcompliant\b", r"\bcleared for\b", r"\bclearance granted",
                    r"\bsecurity clearance\b", r"\bqualification (?:passed|complete)", r"\bis authorized to\b")
NEGATION = re.compile(r"\b(not|no|never|neither|nor|without)\b|\bun[a-z]+", re.I)

SHARED = {}
ROOTS = {}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def strict_loads(data):
    def pairs(items):
        keys = [k for k, _ in items]
        assert len(keys) == len(set(keys)), "duplicate key"
        return dict(items)

    def bad(c):
        raise AssertionError("non-finite constant " + c)
    return json.loads(data, object_pairs_hook=pairs, parse_constant=bad)


def h2_of(obj):
    """The Pack's canonical-JSON hash, restated independently of the Pack helper (importer.canonical_bytes)."""
    return "sha256:" + sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))


def bare(value):
    return value[len("sha256:"):] if isinstance(value, str) and value.startswith("sha256:") else value


GITENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent", "GIT_CONFIG_GLOBAL": "/dev/null",
          "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}


def git(*args, cwd=None, text=True):
    done = subprocess.run(["git", "-c", "advice.detachedHead=false", *args], check=True, capture_output=True, text=text, env=GITENV, cwd=cwd)
    return done.stdout


def tree_signature(root):
    """Hash of every file and directory name (+file bytes) below root, excluding .git: the pinned trees must be unchanged by a run."""
    h = hashlib.sha256()
    for p in sorted(pathlib.Path(root).rglob("*")):
        rel = p.relative_to(root)
        if ".git" in rel.parts:
            continue
        h.update(rel.as_posix().encode() + (b"\0" + p.read_bytes() if p.is_file() else b"/") + b"\0")
    return h.hexdigest()


def setUpModule():
    if not sys.flags.isolated:
        raise AssertionError("run under `python -I -B`")
    missing = [n for n in ENVS.values() if not os.environ.get(n)]
    if missing:
        raise AssertionError("required environment variable(s) not set: %s (point them at the pinned checkouts)" % ", ".join(missing))
    for key, name in ENVS.items():
        ROOTS[key] = pathlib.Path(os.environ[name]).resolve()
        if not ROOTS[key].is_dir():
            raise AssertionError("checkout root is not a directory: %s" % ROOTS[key])


def parsed_proposal():
    return strict_loads(PROPOSAL_PATH.read_bytes())


def walk(obj, path=()):
    """Yield (path, scalar) for every scalar in a JSON-like object."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, path + (i,))
    else:
        yield path, obj


def diff_paths(a, b, path=()):
    """Every path at which two JSON-like objects differ (missing keys / list lengths count as one path each)."""
    if type(a) is not type(b):
        return [path]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(path + (k,))
            else:
                out += diff_paths(a[k], b[k], path + (k,))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [path]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, path + (i,))
        return out
    return [] if a == b else [path]


def flat_strings(obj):
    return [v for _, v in walk(obj) if isinstance(v, str)]


def pin_triplet(pin):
    if isinstance(pin, dict):
        repo = pin.get("repository", pin.get("repo"))
        return (repo, pin.get("sha"), pin.get("tree"))
    return tuple(pin)


# ------------------------------------------------------------------------------------------------------------------------------
class Shared:
    """ONE full run_all() with spies on the REAL AM gate, producer, Replay import, Pack import, CP effect methods, every file write and
    every read the coordinator makes of the persisted inputs."""

    def __init__(self):
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="c4i-")) / "w"
        P = real_c3.measure(dict(ROOTS))["_modules"]  # modules are cached: the spies below patch the objects the run will use
        self.IMP, self.PI, self.bounded = P["importers"], P["pack_importer"], P["bounded"]
        sys.path.insert(0, str(ROOTS["action_manifest"] / "src"))  # same entry the coordinator inserts; AM was git-verified by measure()
        import agent_action_manifest as am
        self.am = am
        bundle_cls = sys.modules["agent_replay_bundle.reconstruction"].ReconstructionBundle
        self.bundle_cls = bundle_cls
        self.before = {k: tree_signature(r) for k, r in ROOTS.items()}
        self.events, self.am_calls, self.produce, self.replay, self.pack = [], [], [], [], []
        self.writes, self.reads, self.opens, self.dumps = [], [], [], []
        self.decide_calls = 0
        self.forbidden_calls = []
        outer = self
        manifest_path = str(ROOTS["action_manifest"] / MANIFEST_REL)
        real_replay, real_pack, real_produce = self.IMP.import_bounded_workflow, self.PI.import_manifest_reconstruction, c4_producer.produce
        real_dump, real_wb, real_wt, real_open = bundle_cls.model_dump, pathlib.Path.write_bytes, pathlib.Path.write_text, builtins.open
        real_rb, real_rt = pathlib.Path.read_bytes, pathlib.Path.read_text
        real_copyfile, real_copy2, real_decide = shutil.copyfile, shutil.copy2, self.bounded.BoundedAuthorizationWorkflow.decide

        def who():
            """Module name of the CALLER of the spy that called who() (frame 0 = who, 1 = the spy, 2 = the spy's caller)."""
            return sys._getframe(2).f_globals.get("__name__")

        def replay_spy(record, *a, **kw):
            internal = who() != "real_c4"
            outer.events.append(("replay_internal" if internal else "replay",))
            try:
                bundle = real_replay(record, *a, **kw)
            except BaseException as exc:
                if not internal:
                    outer.replay.append({"record": copy.deepcopy(record), "args": a, "kwargs": copy.deepcopy(kw), "bundle": None, "raised": exc})
                raise
            if not internal:
                outer.replay.append({"record": copy.deepcopy(record), "args": a, "kwargs": copy.deepcopy(kw), "bundle": bundle,
                                     "native_dump": real_dump(bundle, mode="json"), "raised": None})
            return bundle

        def pack_spy(manifest, bundle, *a, **kw):
            internal = who() != "real_c4"
            outer.events.append(("pack_internal" if internal else "pack",))
            rec = {"manifest": copy.deepcopy(manifest), "bundle": copy.deepcopy(bundle), "extra": (a, kw), "raised": None, "result": None}
            try:
                rec["result"] = real_pack(manifest, bundle, *a, **kw)
            except BaseException as exc:
                rec["raised"] = exc
                if not internal:
                    outer.pack.append(rec)
                raise
            if not internal:
                outer.pack.append(rec)
            return rec["result"]

        def produce_spy(cp_root, workdir, proposal_obj, manifest_obj, scenario, *a, **kw):
            outer.events.append(("produce", scenario))
            outer.produce.append({"cp_root": str(cp_root), "workdir": str(workdir), "proposal": copy.deepcopy(proposal_obj),
                                  "manifest": copy.deepcopy(manifest_obj), "scenario": scenario, "extra": (a, kw)})
            return real_produce(cp_root, workdir, proposal_obj, manifest_obj, scenario, *a, **kw)

        def decide_spy(self_, *a, **kw):
            outer.decide_calls += 1
            outer.events.append(("decide",))
            return real_decide(self_, *a, **kw)

        def dump_spy(self_, *a, **kw):
            if who() in ("real_c4", "c4_producer"):
                outer.dumps.append((a, dict(kw)))
            return real_dump(self_, *a, **kw)

        def wb_spy(self_, data):
            outer.writes.append((str(self_), bytes(data), who()))
            return real_wb(self_, data)

        def wt_spy(self_, data, *a, **kw):
            outer.writes.append((str(self_), None, who()))
            return real_wt(self_, data, *a, **kw)

        def copy_spy(real):
            def spy(src, dst, *a, **kw):
                outer.writes.append((str(dst), None, who()))
                return real(src, dst, *a, **kw)
            return spy

        def open_spy(file, mode="r", *a, **kw):
            if isinstance(file, (str, os.PathLike)):
                m = str(mode)
                if any(c in m for c in "wax+"):
                    outer.opens.append((str(file), who()))
                else:
                    outer.reads.append((os.path.abspath(str(file)), who(), len(outer.events)))
            return real_open(file, mode, *a, **kw)

        def rb_spy(self_):
            outer.reads.append((os.path.abspath(str(self_)), who(), len(outer.events)))
            return real_rb(self_)

        def rt_spy(self_, *a, **kw):
            outer.reads.append((os.path.abspath(str(self_)), who(), len(outer.events)))
            return real_rt(self_, *a, **kw)

        def forbid(name):
            def spy(*a, **kw):
                outer.forbidden_calls.append(name)
                raise AssertionError("%s() must never be called by the C4 chain" % name)
            return spy

        def am_wrap(name):
            real = getattr(am, name)

            def spy(*a, **kw):
                outer.events.append(("am", name))
                out = real(*a, **kw)
                outer.am_calls.append({"name": name, "args": copy.deepcopy(a), "kwargs": copy.deepcopy(kw), "result": copy.deepcopy(out) if isinstance(out, (str, list, dict)) else out})
                return out
            return spy

        self.manifest_path = manifest_path
        patches = [mock.patch.object(self.IMP, "import_bounded_workflow", replay_spy), mock.patch.object(self.PI, "import_manifest_reconstruction", pack_spy),
                   mock.patch.object(c4_producer, "produce", produce_spy), mock.patch.object(bundle_cls, "model_dump", dump_spy),
                   mock.patch.object(self.bounded.BoundedAuthorizationWorkflow, "decide", decide_spy),
                   mock.patch.object(self.bounded.BoundedAuthorizationWorkflow, "execute", forbid("execute")),
                   mock.patch.object(self.bounded.BoundedAuthorizationWorkflow, "reconcile", forbid("reconcile")),
                   mock.patch.object(self.bounded.LocalRefundDestination, "apply", forbid("apply")),
                   mock.patch.object(pathlib.Path, "write_bytes", wb_spy), mock.patch.object(pathlib.Path, "write_text", wt_spy),
                   mock.patch.object(pathlib.Path, "read_bytes", rb_spy), mock.patch.object(pathlib.Path, "read_text", rt_spy),
                   mock.patch.object(shutil, "copyfile", copy_spy(real_copyfile)), mock.patch.object(shutil, "copy2", copy_spy(real_copy2)),
                   mock.patch.object(builtins, "open", open_spy)]
        patches += [mock.patch.object(am, n, am_wrap(n)) for n in ("load_manifest_json", "validate_manifest", "manifest_digest", "proposal_digest", "proposal_mismatches")]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            self.results = real_c4.run_all(dict(ROOTS), self.work)
        self.after = {k: tree_signature(r) for k, r in ROOTS.items()}
        self.git_status = {k: git("-C", str(r), "status", "--porcelain", "--ignored=matching", "--untracked-files=all") for k, r in ROOTS.items()}

    # ---- retained files, re-read from disk ----
    def path(self, *parts):
        return self.work.joinpath(*parts)

    def bytes_of(self, *parts):
        return self.path(*parts).read_bytes()

    def json_of(self, *parts):
        return strict_loads(self.bytes_of(*parts))

    def reads_of(self, target, modules=("real_c4", "c4_producer")):
        target = os.path.abspath(str(target))
        return [r for r in self.reads if r[0] == target and r[1] in modules]

    def event_positions(self, kind):
        return [i for i, e in enumerate(self.events) if e[0] == kind]

    def writes_to(self, target):
        return [w for w in self.writes if w[0] == str(target)]


def shared():
    if "run" not in SHARED:
        SHARED["run"] = Shared()
    return SHARED["run"]


# ------------------------------------------------------------------------------------------------------------------------------
PROBE = r"""
import sys, json, os
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import real_c4, c4_producer
roots = json.loads(sys.argv[2])
work = sys.argv[3]
run_kwargs = json.loads(sys.argv[4])
PREFIXES = ("agent_action_manifest", "agent_control_plane", "agent_replay_bundle", "agent_governance_evidence_pack")
calls = {"produce": 0}
real_produce = c4_producer.produce
def counting(*a, **kw):
    calls["produce"] += 1
    return real_produce(*a, **kw)
c4_producer.produce = counting
before_path = list(sys.path)
out = {"clean_at_import": not any(m.startswith(PREFIXES) for m in sys.modules), "raised": None, "statuses": None, "calls": calls}
try:
    __PRE__
    res = real_c4.run_all(roots, work, **run_kwargs)
    out["statuses"] = {k: v["status"] for k, v in res.items()}
    out["failures"] = {k: (v.get("am_gate") or {}).get("failure") for k, v in res.items()}
except BaseException as e:
    out["raised"] = [type(e).__name__, [c.__name__ for c in type(e).__mro__], str(e)[:600]]
out["component_modules"] = sorted(m for m in sys.modules if m.startswith(PREFIXES))
out["tests_pkg_loaded"] = "tests" in sys.modules
out["path_added"] = [p for p in sys.path if p not in before_path]
out["work_exists"] = os.path.isdir(work)
print(json.dumps(out))
"""

PRODUCER_PROBE = r"""
import sys, json, os, pathlib, tempfile, copy
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import real_c3, c4_producer
roots = json.loads(sys.argv[2])
scenario_arg, manifest_variant = json.loads(sys.argv[3])
P = real_c3.measure(roots)["_modules"]
B = P["bounded"]
decide = {"n": 0}
real_decide = B.BoundedAuthorizationWorkflow.decide
def spy(self, *a, **kw):
    decide["n"] += 1
    return real_decide(self, *a, **kw)
B.BoundedAuthorizationWorkflow.decide = spy
proposal = json.loads(pathlib.Path(sys.argv[4]).read_text())
cp = pathlib.Path(roots["control_plane"])
manifest = json.loads((cp / "tests" / "fixtures" / "refund_integration_v1_1.manifest.json").read_text())
if manifest_variant == "altered":
    manifest["manifest_version"] = "9.9"
elif manifest_variant == "not_a_dict":
    manifest = json.dumps(manifest)
work = pathlib.Path(tempfile.mkdtemp(prefix="c4p-")) / "w"
work.mkdir()
out = {"raised": None, "decide_calls": 0, "work_entries": None}
try:
    res = c4_producer.produce(cp, work, proposal, manifest, scenario_arg)
    out["result"] = res.decision.get("result")
except BaseException as e:
    out["raised"] = [type(e).__name__, [c.__name__ for c in type(e).__mro__], str(e)[:300]]
out["decide_calls"] = decide["n"]
out["work_entries"] = sorted(p.name for p in work.iterdir())
print(json.dumps(out))
"""


def run_probe(roots, pre="pass", tree=MANUAL, env=None, work=None, run_kwargs=None):
    work = work or (pathlib.Path(tempfile.mkdtemp(prefix="c4probe-")) / "w")
    argv = [sys.executable, "-I", "-B", "-c", PROBE.replace("__PRE__", pre), str(tree), json.dumps({k: str(v) for k, v in roots.items()}), str(work),
            json.dumps(run_kwargs or {})]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=900, cwd=tempfile.gettempdir(),
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **(env or {})})
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    out["work"] = work
    return out


def run_producer_probe(scenario, manifest_variant):
    argv = [sys.executable, "-I", "-B", "-c", PRODUCER_PROBE, str(MANUAL), json.dumps({k: str(v) for k, v in ROOTS.items()}),
            json.dumps([scenario, manifest_variant]), str(PROPOSAL_PATH)]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=tempfile.gettempdir(), env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def make_tree(dst):
    """Copy of the manual_contract directory (harness, producers, runner, fixtures) for alteration tests."""
    shutil.copytree(MANUAL, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "test_*.py"))
    return pathlib.Path(dst)


class CloneMixin:
    """Fresh clones of the pinned roots in a private tempdir (the pinned roots themselves are never written)."""

    @classmethod
    def make_good_clones(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="c4i-src-")).resolve()
        cls.good = {}
        for key in KEYS:
            dst = cls.tmp / ("good-" + key)
            git("clone", "-q", "--no-hardlinks", str(ROOTS[key]), str(dst))
            git("-C", str(dst), "checkout", "-q", "--detach", PINS[key][1])
            cls.good[key] = dst
        cls.counter = 0

    @classmethod
    def drop_clones(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def clone(self, key, label):
        type(self).counter += 1
        dst = self.tmp / ("%s-%s-%d" % (key, label, self.counter))
        git("clone", "-q", "--no-hardlinks", str(self.good[key]), str(dst))
        git("-C", str(dst), "checkout", "-q", "--detach", PINS[key][1])
        return dst

    def roots_with(self, key, path):
        roots = dict(self.good)
        roots[key] = path
        return roots


# ------------------------------------------------------------------------------------------------------------------------------
class SourceIdentityTests(CloneMixin, unittest.TestCase):
    """Fresh interpreters (python -I -B): no component is imported, the producer is not called and no clone path is added to sys.path
    when ANY of the four source gates fails."""

    @classmethod
    def setUpClass(cls):
        cls.make_good_clones()

    @classmethod
    def tearDownClass(cls):
        cls.drop_clones()

    def refused(self, key, bad, pattern, *, expect_key=True, roots=None):
        out = run_probe(roots or self.roots_with(key, bad))
        self.assertTrue(out["clean_at_import"], "importing real_c4 must not import component code")
        self.assertIsNotNone(out["raised"], "source gate accepted a bad %s root: %s" % (key, bad))
        self.assertEqual(out["raised"][0], "SourceIdentityError", out)
        self.assertIn("AdapterError", out["raised"][1])
        self.assertRegex(out["raised"][2], pattern)
        if expect_key:
            self.assertIn(key, out["raised"][2])
        self.assertEqual(out["component_modules"], [], "no component module may be imported after a failed source gate (%s)" % key)
        self.assertEqual(out["calls"]["produce"], 0, "the producer must not run after a failed source gate")
        self.assertFalse(out["tests_pkg_loaded"])
        self.assertEqual([p for p in out["path_added"] if "c4i-src" in p], [], "no clone path may be added to sys.path after a failed gate")
        self.assertFalse(out["work_exists"], "no workdir after a failed source gate")

    def test_positive_control_clean_clones_pass_all_three_cases(self):
        out = run_probe(self.good)
        self.assertIsNone(out["raised"], out)
        self.assertTrue(out["clean_at_import"])
        self.assertEqual(sorted(out["statuses"]), sorted(CASES))
        self.assertEqual(set(out["statuses"].values()), {"PASS"})
        self.assertEqual(out["calls"]["produce"], 2, "exactly one producer call each for P1 and N1; N2 derives from the retained N1 bundle")
        self.assertTrue(out["component_modules"], "a passing measurement does import the components")

    def test_untracked_file_refused_in_each_root(self):
        for key in KEYS:
            with self.subTest(root=key):
                bad = self.clone(key, "untracked")
                (bad / "stray.txt").write_text("x\n")
                self.refused(key, bad, "modified, untracked or ignored")

    def test_ignored_file_refused_in_each_root(self):
        for key in KEYS:
            with self.subTest(root=key):
                bad = self.clone(key, "ignored")
                (bad / ".git" / "info" / "exclude").write_text("hidden-ignored.txt\n")
                (bad / "hidden-ignored.txt").write_text("x\n")
                self.refused(key, bad, "modified, untracked or ignored")

    def test_modified_tracked_file_refused_in_each_root(self):
        for key in KEYS:
            with self.subTest(root=key):
                bad = self.clone(key, "modified")
                target = bad / TRACKED_FILE[key]
                target.write_bytes(target.read_bytes() + b"\n")
                self.refused(key, bad, "modified, untracked or ignored")

    def test_staged_modification_refused_in_each_root(self):
        for key in KEYS:
            with self.subTest(root=key):
                bad = self.clone(key, "staged")
                target = bad / TRACKED_FILE[key]
                target.write_bytes(target.read_bytes() + b"\n")
                git("-C", str(bad), "add", TRACKED_FILE[key])
                self.refused(key, bad, "modified, untracked or ignored")

    def test_modified_action_manifest_module_file_refused(self):
        bad = self.clone("action_manifest", "ammod")
        target = bad / AM_MODULE_FILE
        self.assertTrue(target.is_file(), "the pinned AM package module the gate imports")
        target.write_bytes(target.read_bytes() + b"\n# tampered\n")
        self.refused("action_manifest", bad, "modified, untracked or ignored")

    def test_modified_control_plane_test_helper_files_each_refused(self):
        for rel in CP_HELPER_FILES:
            with self.subTest(helper=rel):
                bad = self.clone("control_plane", "helper")
                target = bad / rel
                self.assertTrue(target.is_file(), rel)
                target.write_bytes(target.read_bytes() + b"\n# tampered\n")
                self.refused("control_plane", bad, "modified, untracked or ignored")

    def test_skip_worktree_hidden_modification_refused_in_each_root_and_helpers(self):
        targets = [(k, TRACKED_FILE[k]) for k in KEYS] + [("action_manifest", AM_MODULE_FILE), ("control_plane", CP_HELPER_FILES[0])]
        for key, rel in targets:
            with self.subTest(root=key, file=rel):
                bad = self.clone(key, "skipwt")
                target = bad / rel
                target.write_bytes(target.read_bytes() + b"\n# hidden tamper\n")
                git("-C", str(bad), "update-index", "--skip-worktree", rel)
                self.assertEqual(git("-C", str(bad), "status", "--porcelain"), "", "precondition: git status is blind to the edit")
                self.refused(key, bad, "non-H tags")

    def test_assume_unchanged_hidden_modification_refused_in_each_root(self):
        for key in KEYS:
            with self.subTest(root=key):
                bad = self.clone(key, "assume")
                target = bad / TRACKED_FILE[key]
                target.write_bytes(target.read_bytes() + b"\n# hidden tamper\n")
                git("-C", str(bad), "update-index", "--assume-unchanged", TRACKED_FILE[key])
                self.assertEqual(git("-C", str(bad), "status", "--porcelain"), "")
                self.refused(key, bad, "non-H tags")

    def test_other_commit_refused_in_each_root(self):
        for key in KEYS:
            with self.subTest(root=key):
                bad = self.clone(key, "othercommit")
                git("-C", str(bad), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "x")
                self.refused(key, bad, "!= pin")

    def test_parent_commit_refused_in_each_root(self):
        for key in KEYS:
            with self.subTest(root=key):
                bad = self.clone(key, "parent")
                git("-C", str(bad), "checkout", "-q", "--detach", PINS[key][1] + "~1")
                self.refused(key, bad, "!= pin")

    def test_wrong_roots_refused_in_each_root(self):
        for key in KEYS:
            other = next(k for k in KEYS if k != key)
            empty = self.tmp / ("empty-" + key)
            empty.mkdir()
            cases = (("missing", self.tmp / ("does-not-exist-" + key), "root missing", True),
                     ("empty", empty, "not a usable git checkout", False),
                     ("subdir", self.good[key] / TRACKED_FILE[key].split("/")[0], "not the top level|not a usable git checkout|root missing", False),
                     ("swapped_with_" + other, self.good[other], "!= pin", True))
            for name, bad, pattern, expect_key in cases:
                with self.subTest(root=key, case=name):
                    self.refused(key, bad, pattern, expect_key=expect_key)

    def test_root_unset_in_environment_refused_in_each_root_naming_the_c4_variable(self):
        for key in KEYS:
            with self.subTest(root=key):
                roots = {k: v for k, v in self.good.items() if k != key}
                out = run_probe(roots)  # the probe environment carries no COGNOUS_* variables
                self.assertEqual(out["raised"][0], "SourceIdentityError", out)
                self.assertIn("root missing", out["raised"][2])
                self.assertIn(ENVS[key], out["raised"][2], "the message must name the C4 variable")
                self.assertNotIn("COGNOUS_C3_", out["raised"][2])
                self.assertEqual(out["component_modules"], [])
                self.assertEqual(out["calls"]["produce"], 0)

    def test_c3_environment_variables_are_not_honoured_for_c4(self):
        c3_env = {"COGNOUS_C3_" + ENVS[k].split("COGNOUS_C4_")[1]: str(v) for k, v in self.good.items()}
        out = run_probe({}, env=c3_env)  # no roots, no C4 variables, valid C3 variables present
        self.assertEqual(out["raised"][0], "SourceIdentityError", out)
        self.assertEqual(out["component_modules"], [])
        self.assertEqual(out["calls"]["produce"], 0)

    def test_root_symlinked_to_pinned_checkout_resolves_to_real_top_level(self):
        link = self.tmp / "link-to-cp"
        link.symlink_to(self.good["control_plane"])
        out = run_probe(self.roots_with("control_plane", link))
        self.assertIsNone(out["raised"], "a symlinked root that resolves to the exact pinned clean checkout is the same source: %s" % out)

    def test_action_manifest_package_preloaded_from_outside_the_pinned_root_refused(self):
        """AM code imported from another location before the coordinator runs must be refused, never used."""
        evil = self.tmp / "evil-am"
        shutil.copytree(self.good["action_manifest"] / "src", evil / "src")
        pre = "sys.path.insert(0, %r); import agent_action_manifest" % str(evil / "src")
        out = run_probe(self.good, pre=pre)
        self.assertIsNotNone(out["raised"], "an AM package from outside the pinned root was accepted: %s" % out)
        self.assertIn("AdapterError", out["raised"][1], out)
        self.assertEqual(out["calls"]["produce"], 0)

    def test_pins_equal_frozen_literals(self):
        self.assertEqual(set(real_c4.PINS), set(KEYS))
        for key, (repo, sha, tree) in PINS.items():
            self.assertEqual(pin_triplet(real_c4.PINS[key]), (repo, sha, tree), key)
            self.assertEqual(git("-C", str(ROOTS[key]), "rev-parse", "HEAD").strip(), sha, key + ": the supplied root is not the frozen pin")
            self.assertEqual(git("-C", str(ROOTS[key]), "rev-parse", "HEAD^{tree}").strip(), tree, key)
        self.assertEqual(real_c4.ENV, ENVS)
        for key in KEYS:  # the public C3 measurement is reused and hard-codes the same pins
            self.assertEqual(pin_triplet(real_c3.PINS[key]), PINS[key], key)

    def test_cli_exit_code_2_for_source_failure_in_any_root(self):
        for key in KEYS:
            with self.subTest(root=key):
                bad = self.clone(key, "cli")
                (bad / "stray.txt").write_text("x\n")
                env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **{ENVS[k]: str(v) for k, v in self.roots_with(key, bad).items()}}
                out_json, work = self.tmp / ("cli-%s.json" % key), self.tmp / ("w-cli-" + key)
                done = subprocess.run([sys.executable, "-I", "-B", str(MANUAL / "real_c4.py"), "--case", "all", "--out", str(out_json),
                                       "--workdir", str(work)], capture_output=True, text=True, env=env, cwd=tempfile.gettempdir(), timeout=300)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertRegex(done.stderr.lower(), "error")
                self.assertNotIn("Traceback", done.stderr)
                self.assertFalse(out_json.exists(), "no result file is written for an adapter error")
                self.assertFalse(work.exists(), "no producer workdir after a failed source gate")

    def test_main_in_process_source_failure_returns_2(self):
        bad = self.clone("evidence_pack", "inproc")
        (bad / "stray.txt").write_text("x\n")
        envs = {ENVS[k]: str(v) for k, v in self.roots_with("evidence_pack", bad).items()}
        err = io.StringIO()
        with mock.patch.dict(os.environ, envs), contextlib.redirect_stderr(err), mock.patch.object(real_c4, "run_all", wraps=real_c4.run_all) as ra:
            rc = real_c4.main(["--case", "all", "--workdir", str(self.tmp / "w-inproc")])
        self.assertEqual(rc, 2)
        self.assertEqual(ra.call_count, 1)
        self.assertRegex(err.getvalue().lower(), "error")


# ------------------------------------------------------------------------------------------------------------------------------
class FixtureIntegrityTests(CloneMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.make_good_clones()

    @classmethod
    def tearDownClass(cls):
        cls.drop_clones()

    def test_frozen_fixture_literals_and_actual_files(self):
        frozen = set(flat_strings(real_c4.FROZEN)) | set(flat_strings(getattr(real_c4, "ORACLE", {})))
        for literal in (PROPOSAL_SHA, MANIFEST_FILE_SHA, MANIFEST_DIGEST, C2_PRODUCER_SHA, PROPOSAL_COMMITMENT, EFFECT_AUTHORIZED, EFFECT_HOLD):
            self.assertIn(literal, frozen, "the harness does not carry the frozen literal %s" % literal)
        self.assertEqual(sha256(PROPOSAL_PATH.read_bytes()), PROPOSAL_SHA)
        self.assertEqual(sha256((ROOTS["action_manifest"] / MANIFEST_REL).read_bytes()), MANIFEST_FILE_SHA)
        self.assertEqual(sha256((ROOTS["control_plane"] / CP_MANIFEST_REL).read_bytes()), MANIFEST_FILE_SHA, "the CP-repo copy is byte-identical")
        self.assertEqual(strict_loads((ROOTS["action_manifest"] / MANIFEST_REL).read_bytes()),
                         strict_loads((ROOTS["control_plane"] / CP_MANIFEST_REL).read_bytes()))

    def test_c2_producer_hash_constant_equals_blob_content_at_base(self):
        blob = git("-C", str(REPO), "show", "%s:tests/manual_contract/c2_producer.py" % BASE, text=False)
        self.assertEqual(sha256(blob), C2_PRODUCER_SHA)
        self.assertEqual(sha256((MANUAL / "c2_producer.py").read_bytes()), C2_PRODUCER_SHA, "the working-tree C2 producer is not the base file")
        self.assertEqual(git("-C", str(REPO), "hash-object", "--", "tests/manual_contract/c2_producer.py").strip(),
                         git("-C", str(REPO), "rev-parse", "%s:tests/manual_contract/c2_producer.py" % BASE).strip())
        self.assertEqual(git("-C", str(REPO), "rev-parse", BASE).strip(), BASE)
        self.assertEqual(real_c3.FROZEN["c2_producer_sha256"], C2_PRODUCER_SHA)
        self.assertNotEqual(sha256((MANUAL / "c4_producer.py").read_bytes()), C2_PRODUCER_SHA, "C4 is a separate producer, not an edit of C2")

    def run_copy(self, mutate, name):
        tree = make_tree(self.tmp / name)
        mutate(tree)
        return run_probe(ROOTS, tree=tree, work=self.tmp / (name + "-work"))

    def assert_refused_before_any_call(self, out, pattern):
        """Either an AdapterError, or a returned run in which the AM gate BLOCKED the chain: never a PASS, and no producer call."""
        if out["raised"] is not None:
            self.assertIn("AdapterError", out["raised"][1], out)
            self.assertRegex(out["raised"][2], pattern)
        else:
            self.assertNotIn("PASS", out["statuses"].values(), out)
            self.assertEqual(set(out["statuses"].values()), {"BLOCKED"}, out)
            self.assertTrue(any(f and re.search(pattern, f) for f in out["failures"].values()), out["failures"])
        self.assertEqual(out["calls"]["produce"], 0, "the producer must not run on an altered input")
        self.assertFalse(out["work_exists"] and any(out["work"].rglob("run.json")), "the producer must not have written a Control Plane record")

    def test_unaltered_copy_is_a_positive_control(self):
        out = self.run_copy(lambda tree: None, "control")
        self.assertIsNone(out["raised"], out)
        self.assertEqual(set(out["statuses"].values()), {"PASS"})
        self.assertEqual(sorted(out["statuses"]), sorted(CASES))

    def test_altered_proposal_fixture_refused_before_producer_replay_or_pack(self):
        def mutate(tree):
            path = tree / "c1" / "fixtures" / "proposal.tenant-alpha.json"
            path.write_bytes(path.read_bytes() + b"\n")  # one byte: same JSON value, different file sha256
        self.assert_refused_before_any_call(self.run_copy(mutate, "prop"), "(?i)proposal.*(sha256|differs|frozen)")

    def test_altered_proposal_value_refused(self):
        def mutate(tree):
            path = tree / "c1" / "fixtures" / "proposal.tenant-alpha.json"
            path.write_bytes(path.read_bytes().replace(b"tenant-alpha", b"tenant-alphb", 1))
        self.assert_refused_before_any_call(self.run_copy(mutate, "propval"), "(?i)proposal.*(sha256|differs|frozen)")

    def test_input_path_hooks_cannot_smuggle_a_different_file(self):
        """run_all keeps keyword-only manifest_path / proposal_path hooks: a file that is not byte-identical to the frozen input never reaches CP."""
        tmp = self.tmp / "hooks"
        tmp.mkdir()
        altered_manifest, altered_proposal = tmp / "m.json", tmp / "p.json"
        altered_manifest.write_bytes((ROOTS["action_manifest"] / MANIFEST_REL).read_bytes() + b"\n")
        altered_proposal.write_bytes(PROPOSAL_PATH.read_bytes().replace(b"tenant-alpha", b"tenant-alphb", 1))
        for name, kwargs, pattern in (("manifest", {"manifest_path": str(altered_manifest)}, "(?i)manifest.*(sha256|differs|frozen)"),
                                      ("proposal", {"proposal_path": str(altered_proposal)}, "(?i)proposal.*(sha256|differs|frozen)")):
            with self.subTest(hook=name):
                out = run_probe(ROOTS, run_kwargs=kwargs, work=self.tmp / ("hook-" + name))
                self.assert_refused_before_any_call(out, pattern)
        same = tmp / "same.json"
        same.write_bytes((ROOTS["action_manifest"] / MANIFEST_REL).read_bytes())
        out = run_probe(ROOTS, run_kwargs={"manifest_path": str(same)}, work=self.tmp / "hook-same")
        self.assertIsNone(out["raised"], out)
        self.assertEqual(set(out["statuses"].values()), {"PASS"}, "a byte-identical copy is the same frozen input")

    def test_modified_c2_producer_refused_before_any_call(self):
        def mutate(tree):
            path = tree / "c2_producer.py"
            path.write_bytes(path.read_bytes() + b"\n# modified\n")
        self.assert_refused_before_any_call(self.run_copy(mutate, "c2prod"), "(?i)c2_producer")

    def test_altered_action_manifest_in_a_copy_of_the_root_refused_before_any_call(self):
        for variant in ("worktree", "committed"):
            with self.subTest(variant=variant):
                bad = self.clone("action_manifest", "fixture-" + variant)
                target = bad / MANIFEST_REL
                target.write_bytes(target.read_bytes() + b"\n")
                if variant == "committed":
                    git("-C", str(bad), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-am", "altered")
                out = run_probe(self.roots_with("action_manifest", bad))
                self.assertEqual(out["raised"][0], "SourceIdentityError", out)
                self.assertIn("AdapterError", out["raised"][1])
                self.assertEqual(out["calls"]["produce"], 0)
                self.assertFalse(out["work_exists"], "no workdir after a failed source gate")
                self.assertEqual(out["component_modules"], [])

    def test_producer_refuses_manifest_unequal_to_the_cp_repo_copy_before_any_cp_decision(self):
        out = run_producer_probe("authorized", "altered")
        self.assertEqual(out["raised"][0], "ProducerError", out)
        self.assertEqual(out["decide_calls"], 0, "no Control Plane decide() on a manifest that differs from the CP-repo copy")
        self.assertNotIn("baseline", out["work_entries"])
        self.assertNotIn("run", out["work_entries"])

    def test_producer_refuses_a_non_object_manifest_before_any_cp_decision(self):
        out = run_producer_probe("authorized", "not_a_dict")
        self.assertEqual(out["raised"][0], "ProducerError", out)
        self.assertEqual(out["decide_calls"], 0)

    def test_producer_refuses_unknown_scenarios_before_any_cp_call(self):
        for scenario in ("bogus", "", "Authorized", "grant_revoked ", "hold", "flip_of_n1", "deny"):
            with self.subTest(scenario=scenario):
                out = run_producer_probe(scenario, "good")
                self.assertEqual(out["raised"][0], "ProducerError", out)
                self.assertEqual(out["decide_calls"], 0)
                self.assertEqual(out["work_entries"], [], "nothing is written before the scenario is validated")

    def test_producer_scenarios_constant(self):
        self.assertEqual(tuple(c4_producer.SCENARIOS), ("authorized", "grant_revoked"))
        self.assertEqual(c4_producer.CONFIG_ID, "C4-CP-RUNTIME-PROFILE-STRICT-TENANT-DECIDE-ONLY")

    def test_producer_good_scenarios_decide_only(self):
        for scenario, result in (("authorized", "authorized"), ("grant_revoked", "hold")):
            with self.subTest(scenario=scenario):
                out = run_producer_probe(scenario, "good")
                self.assertIsNone(out["raised"], out)
                self.assertEqual(out["result"], result)
                self.assertEqual(out["decide_calls"], 2, "one scratch baseline decide() plus the one final decide(), nothing else")


# ------------------------------------------------------------------------------------------------------------------------------
class BytePreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = shared()

    def scenario_dirs(self):
        return {"p1": CASE_P1, "n1": CASE_N1}

    def test_all_three_cases_present_with_the_frozen_schema(self):
        S = self.S
        self.assertEqual(sorted(S.results), sorted(CASES))
        for cid, ev in S.results.items():
            self.assertEqual(ev["case_id"], cid)
            self.assertEqual(ev["schema"], EVIDENCE_SCHEMA)

    def test_inputs_persisted_as_read_and_equal_the_pinned_files(self):
        S = self.S
        manifest_bytes = (ROOTS["action_manifest"] / MANIFEST_REL).read_bytes()
        self.assertEqual(S.bytes_of("inputs", "am-manifest.json"), manifest_bytes)
        self.assertEqual(S.bytes_of("inputs", "proposal.json"), PROPOSAL_PATH.read_bytes())
        self.assertEqual(sha256(manifest_bytes), MANIFEST_FILE_SHA)
        for cid in (CASE_P1, CASE_N1):
            ev = S.results[cid]["inputs"]
            self.assertEqual(bare(ev["manifest"]["sha256"]), MANIFEST_FILE_SHA)
            self.assertEqual(bare(ev["proposal"]["sha256"]), PROPOSAL_SHA)

    def test_am_manifest_is_read_once_and_the_same_parsed_bytes_feed_the_am_gate_and_the_producer(self):
        S = self.S
        reads = S.reads_of(S.manifest_path)
        self.assertEqual(len(reads), 1, "the AM manifest file is read exactly once by the coordinator or producer: %s" % reads)
        expected = strict_loads((ROOTS["action_manifest"] / MANIFEST_REL).read_bytes())
        loads = [c for c in S.am_calls if c["name"] == "load_manifest_json"]
        self.assertGreaterEqual(len(loads), 1)
        for call in loads:
            self.assertEqual(call["args"][0], expected, "the AM gate parsed the very bytes that were read")
        self.assertEqual(len(S.produce), 2, "exactly one producer call each for P1 and N1")
        self.assertEqual([p["scenario"] for p in S.produce], ["authorized", "grant_revoked"])
        for p in S.produce:
            self.assertEqual(p["manifest"], expected, "the producer received the AM-validated manifest object")
            self.assertEqual(p["manifest"], strict_loads((ROOTS["control_plane"] / CP_MANIFEST_REL).read_bytes()))
            self.assertEqual(p["proposal"], parsed_proposal())
            self.assertEqual(p["cp_root"], str(ROOTS["control_plane"]))
            self.assertEqual(p["extra"], ((), {}))

    def test_am_gate_ran_with_native_functions_before_any_control_plane_call(self):
        S = self.S
        kinds = [e for e in S.events if e[0] in ("am", "produce", "decide", "replay", "pack")]
        first_produce = next(i for i, e in enumerate(kinds) if e[0] == "produce")
        first_decide = next(i for i, e in enumerate(kinds) if e[0] == "decide")
        gate_before = {e[1] for e in kinds[:first_produce] if e[0] == "am"}
        self.assertEqual(gate_before, {"load_manifest_json", "validate_manifest", "manifest_digest", "proposal_digest", "proposal_mismatches"})
        self.assertLess(first_produce, first_decide)
        results = {c["name"]: c["result"] for c in S.am_calls}
        self.assertEqual(results["manifest_digest"], MANIFEST_DIGEST)
        self.assertEqual(results["proposal_digest"], PROPOSAL_COMMITMENT)
        self.assertEqual(results["proposal_mismatches"], [])
        # order of the downstream native calls per chain: produce -> replay -> pack, and no pack before its replay
        seq = [e[0] for e in kinds if e[0] in ("produce", "replay", "pack")]
        self.assertEqual(seq, ["produce", "replay", "pack", "pack", "produce", "replay", "pack", "pack", "pack"],
                         "P1 and N1 chains (Pack import + determinism re-import each), then N2: only the Pack import, no CP or Replay call")

    def persisted(self, s):
        return {"record": self.S.bytes_of(s, "cp-record.json"), "bundle": self.S.bytes_of(s, "reconstruction-bundle.json"),
                "dest": self.S.bytes_of(s, "destination.json"), "pack": self.S.bytes_of(s, "evidence-pack.json")}

    def replay_call_for(self, s):
        record = strict_loads(self.S.bytes_of(s, "cp-record.json"))
        hits = [c for c in self.S.replay if c["record"] == record]
        self.assertEqual(len(hits), 1, "exactly one Replay import of the persisted %s record" % s)
        return hits[0]

    def test_persisted_cp_record_read_once_unchanged_and_the_replay_input_is_its_parse(self):
        S = self.S
        for s, cid in self.scenario_dirs().items():
            with self.subTest(scenario=s):
                data = S.bytes_of(s, "cp-record.json")
                producer_file = S.path(s, "producer", "run", "run.json")
                self.assertTrue(producer_file.is_file(), "the producer's own record")
                self.assertEqual(producer_file.read_bytes(), data, "the byte copy equals the CP-produced record")
                reads = S.reads_of(producer_file, modules=("real_c4",))
                replay_at = S.event_positions("replay")[0 if s == "p1" else 1]
                before = [r for r in reads if r[2] <= replay_at]
                self.assertEqual(len(before), 1, "the persisted CP record is read exactly once before Replay consumes it (hashed and parsed from that buffer): %s" % reads)
                self.assertEqual(sha256(data), S.results[cid]["identity"]["per_run"]["cp_record_sha256"].replace("sha256:", ""))
                # later reads (post-import and evidence assembly) are verification re-reads only: the file is unchanged, never rewritten
                self.assertEqual([w for w in S.writes_to(producer_file)], [], "the coordinator never rewrites the CP record")
                self.assertEqual(S.results[cid]["identity"]["per_run"]["cp_record_sha256"].replace("sha256:", ""), sha256(data))
                call = self.replay_call_for(s)
                self.assertEqual(call["args"], ())
                self.assertEqual(set(call["kwargs"]), {"proposal", "control_plane_revision"})
                self.assertEqual(call["kwargs"]["control_plane_revision"], CP_SHA)
                self.assertEqual(call["kwargs"]["proposal"], parsed_proposal())
                self.assertEqual(call["record"], strict_loads(data), "Replay received exactly the parse of the persisted record")
                self.assertIsNone(call["raised"], "Replay imports both the authorized and the held record")

    def test_bundle_serialised_once_h1_is_the_persisted_bytes_and_h2_is_the_pack_canonical_hash(self):
        S = self.S
        for s, cid in self.scenario_dirs().items():
            with self.subTest(scenario=s):
                data = S.bytes_of(s, "reconstruction-bundle.json")
                writes = S.writes_to(S.path(s, "reconstruction-bundle.json"))
                self.assertEqual(len(writes), 1, "the bundle file is written exactly once")
                self.assertEqual(writes[0][1], data, "the bytes on disk are the bytes written")
                parsed = strict_loads(data)
                self.assertTrue(data.endswith(b"}\n") and not data.endswith(b"\n\n"))
                self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
                self.assertEqual(data, (json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
                self.assertNotEqual(data, json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
                per_run = S.results[cid]["identity"]["per_run"]
                h1, h2 = sha256(data), h2_of(parsed)
                self.assertNotEqual(h1, bare(h2))
                self.assertEqual(bare(per_run["bundle_h1_sha256"]), h1)
                self.assertEqual(bare(per_run["bundle_h2_pack_canonical_sha256"]), bare(h2))
                self.assertEqual(S.PI.sha256(parsed), h2, "H2 equals the Pack's own canonical hash")
                # the Pack received exactly the parse of the persisted bytes and the AM manifest as read
                pack_calls = [c for c in S.pack if c["bundle"] == parsed]
                self.assertEqual(len(pack_calls), 2, "the Pack import plus the declared determinism re-import of the identical bundle")
                for call in pack_calls:
                    self.assertEqual(call["manifest"], strict_loads(S.bytes_of("inputs", "am-manifest.json")))
                    self.assertEqual(call["extra"], ((), {}))
                    self.assertIsNone(call["raised"])
                self.assertEqual(pack_calls[0]["result"].pack_id, pack_calls[1]["result"].pack_id)
        files = sorted(p.name for p in S.work.rglob("*bundle*.json"))
        self.assertEqual(files, ["mutated-bundle.json", "reconstruction-bundle.json", "reconstruction-bundle.json"],
                         "no re-serialised copies: two persisted bundles (P1, N1) and the one declared N2 mutation")
        bundle_dumps = [d for d in S.dumps if d == ((), {"mode": "json"})]
        self.assertGreaterEqual(len(bundle_dumps), 2, "the harness takes model_dump(mode='json') of each native bundle")

    def test_bundle_id_and_generated_at_preserved_verbatim_and_no_member_added_dropped_or_renamed(self):
        S = self.S
        for s in ("p1", "n1"):
            with self.subTest(scenario=s):
                parsed = S.json_of(s, "reconstruction-bundle.json")
                call = self.replay_call_for(s)
                native = call["native_dump"]
                for member in ("bundle_id", "generated_at"):
                    self.assertIsInstance(parsed[member], str)
                    self.assertEqual(parsed[member], native[member], member)
                self.assertEqual(parsed["bundle_id"], call["bundle"].bundle_id)
                self.assertEqual(parsed, native, "the persisted bundle equals the native bundle's own model_dump(mode='json')")
                self.assertEqual(parsed["integrity"], [], "no integrity entry is attached")
                self.assertEqual(set(parsed), set(native))
                # this file's own independent Replay import of the same persisted record: only the per-import members may differ
                again = S.IMP.import_bounded_workflow(copy.deepcopy(call["record"]), proposal=parsed_proposal(), control_plane_revision=CP_SHA).model_dump(mode="json")
                per_import = {"bundle_id", "generated_at"}
                self.assertEqual({k: v for k, v in parsed.items() if k not in per_import}, {k: v for k, v in again.items() if k not in per_import})
                self.assertEqual(parsed["status"], "reconstruction_partial")

    def test_h1_and_h2_are_distinct_names_and_values_and_never_conflated(self):
        S = self.S
        expected = {}
        for s, cid in self.scenario_dirs().items():
            data = S.bytes_of(s, "reconstruction-bundle.json")
            expected[cid] = (sha256(data), bare(h2_of(strict_loads(data))))
        expected[CASE_N2] = expected[CASE_N1]  # N2 derives from the retained N1 bundle
        self.assertNotEqual(expected[CASE_P1][0], expected[CASE_N1][0])
        for cid, ev in S.results.items():
            h1, h2 = expected[cid]
            self.assertNotEqual(h1, h2)
            for path, value in walk(ev):
                key = [str(p) for p in path if isinstance(p, str)]
                if not isinstance(value, str) or "limits" in key or any("mutated" in k for k in key):
                    continue
                tokens = {t for k in key for t in re.split(r"[^A-Za-z0-9]+", k.lower()) if t}
                if "h1" in tokens and "h2" in tokens:
                    self.fail("%s %s mixes H1 and H2 in one label" % (cid, "/".join(key)))
                if "h1" in tokens:
                    self.assertEqual(bare(value), h1, "%s %s labelled H1 holds a different value" % (cid, "/".join(key)))
                if "h2" in tokens:
                    self.assertEqual(bare(value), h2, "%s %s labelled H2 holds a different value" % (cid, "/".join(key)))
                if bare(value) == h1 and cid != CASE_N2:
                    self.assertNotIn("h2", tokens, "%s: H1 value under an H2 label %s" % (cid, "/".join(key)))
                if bare(value) == h2:
                    self.assertNotIn("h1", tokens, "%s: H2 value under an H1 label %s" % (cid, "/".join(key)))
            per_run = ev["identity"]["per_run"] if "per_run" in ev.get("identity", {}) else {}
            for forbidden in ("bundle_sha256", "bundle_hash", "sha256"):
                self.assertNotIn(forbidden, per_run, "an unlabelled bundle hash would conflate H1 and H2")

    def test_pack_file_is_written_by_the_native_dumper_not_the_persisted_bundle(self):
        S = self.S
        for s, cid in self.scenario_dirs().items():
            with self.subTest(scenario=s):
                pack_bytes = S.bytes_of(s, "evidence-pack.json")
                self.assertEqual(bare(S.results[cid]["identity"]["per_run"]["pack_file_sha256"]), sha256(pack_bytes))
                self.assertNotEqual(sha256(pack_bytes), sha256(S.bytes_of(s, "reconstruction-bundle.json")))
                retained = strict_loads(pack_bytes)["metadata"]["traceable_import"]["retained_sources"]
                self.assertEqual(retained["reconstruction_bundle"], S.json_of(s, "reconstruction-bundle.json"),
                                 "the Pack retains exactly the persisted bundle")
                self.assertEqual(retained["manifest"], strict_loads(S.bytes_of("inputs", "am-manifest.json")))
                self.assertEqual(set(retained), {"manifest", "reconstruction_bundle"}, "L19: no raw Control Plane record is retained by the Pack")

    def test_n2_deep_copy_leaves_the_retained_n1_bundle_bytes_unchanged_and_differs_in_exactly_one_path(self):
        S = self.S
        n1_bytes = S.bytes_of("n1", "reconstruction-bundle.json")
        writes = S.writes_to(S.path("n1", "reconstruction-bundle.json"))
        self.assertEqual([w[1] for w in writes], [n1_bytes], "the N1 bundle was written once and never touched again")
        self.assertEqual(S.writes_to(S.path("n2", "reconstruction-bundle.json")), [])
        n1, mutated = strict_loads(n1_bytes), S.json_of("n2", "mutated-bundle.json")
        self.assertEqual(n1, S.replay and self.replay_call_for("n1")["native_dump"], "the retained N1 bundle is still the native N1 bundle")
        diffs = diff_paths(n1, mutated)
        self.assertEqual(len(diffs), 1, "the mutated copy differs from the retained N1 bundle in exactly one path: %s" % (diffs,))
        path = diffs[0]
        self.assertEqual(path[-2:], ("data", "result"), path)
        node = n1
        for p in path[:-2]:
            node = node[p]
        self.assertEqual(node.get("record_type"), "runtime_decision", "the mutated field is the retained runtime_decision record's result")
        old, new = n1, mutated
        for p in path:
            old, new = old[p], new[p]
        self.assertEqual((old, new), ("hold", "authorized"))
        self.assertEqual(S.bytes_of("n2", "mutated-bundle.json"),
                         (json.dumps(mutated, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"), "dumped by the same serialisation")
        self.assertFalse(S.path("n2", "evidence-pack.json").exists(), "N2 produces no pack")
        self.assertEqual(S.results[CASE_N1]["identity"]["per_run"]["bundle_h1_sha256"].replace("sha256:", ""), sha256(n1_bytes))

    def test_n2_native_pack_refusal_text_built_from_the_retained_n1_record(self):
        S = self.S
        record = S.json_of("n1", "cp-record.json")
        ids = {v for p, v in walk(record) if p and p[-1] == "decision_id" and isinstance(v, str)}
        self.assertEqual(len(ids), 1, "one decision id in the retained N1 record: %s" % ids)
        decision_id = next(iter(ids))
        expected = "decision %s is authorized but has no binding" % decision_id
        mutated = S.json_of("n2", "mutated-bundle.json")
        manifest = strict_loads(S.bytes_of("inputs", "am-manifest.json"))
        with self.assertRaises(S.PI.ImportContractError) as raised:  # this file's own independent Pack call
            S.PI.import_manifest_reconstruction(copy.deepcopy(manifest), copy.deepcopy(mutated))
        self.assertEqual(str(raised.exception), expected)
        self.assertIsNone(getattr(raised.exception, "code", None))
        calls = [c for c in S.pack if c["bundle"] == mutated]
        self.assertEqual(len(calls), 1, "one coordinator Pack import of the mutated copy")
        self.assertEqual(calls[0]["manifest"], manifest, "the ORIGINAL manifest was supplied")
        self.assertEqual(str(calls[0]["raised"]), expected)
        self.assertIsInstance(calls[0]["raised"], S.PI.ImportContractError)

    def test_pinned_trees_untouched_and_git_clean_after_run_all(self):
        S = self.S
        self.assertEqual(S.before, S.after)
        for key, status in S.git_status.items():
            self.assertEqual(status, "", key)
        roots = tuple(str(r) for r in ROOTS.values())
        for target, _, _ in S.writes:
            self.assertFalse(any(target == r or target.startswith(r + os.sep) for r in roots), "write into a pinned root: " + target)
        for target, _ in S.opens:
            self.assertFalse(any(os.path.abspath(target).startswith(r + os.sep) for r in roots), "open for write in a pinned root: " + target)
        work = str(S.work.resolve())
        for target, _, who in S.writes:
            if who in ("real_c4", "c4_producer"):
                self.assertTrue(os.path.abspath(target).startswith(work + os.sep), "the coordinator wrote outside its workdir: " + target)


# ------------------------------------------------------------------------------------------------------------------------------
class NoEffectTests(unittest.TestCase):
    """decide() only: execute / reconcile / apply are patched to raise and counted; destination files and provenance are re-read."""

    @classmethod
    def setUpClass(cls):
        cls.S = shared()

    def test_execute_reconcile_and_apply_never_called(self):
        self.assertEqual(self.S.forbidden_calls, [])

    def test_only_decide_ran_twice_per_producer_call(self):
        S = self.S
        self.assertEqual(S.decide_calls, 2 * len(S.produce), "one scratch baseline decide() plus the final decide() per scenario, N2 makes no CP call")

    def test_destination_effects_empty_in_every_scenario(self):
        S = self.S
        for s in ("p1", "n1"):
            dest = S.json_of(s, "destination.json")
            self.assertEqual(dest.get("effects"), {}, s)
        for cid in (CASE_P1, CASE_N1):
            self.assertEqual(S.results[cid]["destination"]["effects"], {})
            self.assertEqual(S.results[cid]["destination"]["effect_count"], 0)

    def test_producer_provenance_declares_decide_only_and_the_scenario_mutation(self):
        S = self.S
        for cid, scenario, mutation in ((CASE_P1, "authorized", None), (CASE_N1, "grant_revoked", "grant_status=revoked")):
            prov = S.results[cid]["producer"]
            self.assertEqual(prov["calls"], ["decide"], cid)
            self.assertEqual(prov["scenario"], scenario)
            self.assertEqual(prov["scenario_mutation"], mutation)
            self.assertEqual(prov["config_id"], "C4-CP-RUNTIME-PROFILE-STRICT-TENANT-DECIDE-ONLY")
            self.assertEqual(prov["manifest_source"], "supplied_validated_AM_bytes")
            self.assertIs(prov["manifest_equals_cp_repo_copy"], True)

    def test_pack_side_effect_counts_zero_in_the_retained_native_dumps(self):
        keys = ("control_plane_attempt_count", "executor_attempt_count", "attempt_transition_record_count", "destination_effect_count",
                "effect_observation_count", "reconciliation_count")
        for s in ("p1", "n1"):
            T = self.S.json_of(s, "evidence-pack.json")["metadata"]["traceable_import"]
            counts = T["derived_counts"]
            for k in keys:
                self.assertIn(k, counts, (s, k))
                self.assertIs(type(counts[k]), int)
                self.assertEqual(counts[k], 0, (s, k))
            self.assertEqual(T["lifecycle_summary"]["execution_attempted"], "no")

    def test_hold_and_authorized_semantics_in_the_retained_dumps(self):
        S = self.S
        p1 = S.json_of("p1", "evidence-pack.json")["metadata"]["traceable_import"]
        n1 = S.json_of("n1", "evidence-pack.json")["metadata"]["traceable_import"]
        self.assertEqual(p1["lifecycle_summary"]["authorization"], "authorized")
        self.assertEqual(n1["lifecycle_summary"]["authorization"], "held")
        self.assertEqual(n1["derived_counts"]["authorization_held_count"], 1)
        self.assertEqual(n1["derived_counts"]["authorization_granted_count"], 0)
        bundle = S.json_of("n1", "reconstruction-bundle.json")
        self.assertNotIn("authorized", [v for p, v in walk(bundle) if p[-2:] == ("data", "result")], "no authorized decision is carried downstream of a hold")

    def test_effect_ids_by_verdict_restated_literals(self):
        S = self.S
        for cid, literal in ((CASE_P1, EFFECT_AUTHORIZED), (CASE_N1, EFFECT_HOLD)):
            self.assertEqual(S.results[cid]["identity"]["effect_id"], literal)
        self.assertNotEqual(EFFECT_AUTHORIZED, EFFECT_HOLD)
        for cid in (CASE_P1, CASE_N1):
            stable = S.results[cid]["identity"]["stable"]
            self.assertEqual(stable["proposal_commitment"], PROPOSAL_COMMITMENT)
            self.assertEqual(stable["manifest_digest"], MANIFEST_DIGEST)
            self.assertEqual(stable["tenant_id"], "tenant-alpha")
            self.assertEqual(stable["action_id"], "urn:cognous:action:refund-issue-routine-v1")


# ------------------------------------------------------------------------------------------------------------------------------
def norm(text):
    return re.sub(r"[\s_]+", " ", text.lower().replace("-", " "))


class LimitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = shared()

    def test_every_case_carries_the_complete_limits_block(self):
        self.assertEqual(sorted(self.S.results), sorted(CASES))
        first = self.S.results[CASE_P1]["limits"]
        for cid, ev in self.S.results.items():
            with self.subTest(case=cid):
                lim = ev["limits"]
                numbered = sorted((k for k in lim if re.fullmatch(r"L\d+", k)), key=lambda k: int(k[1:]))
                self.assertEqual(numbered, ["L%d" % n for n in range(1, 28)], "L1..L27 present, none dropped or renumbered")
                for k in numbered:
                    self.assertEqual(lim[k], first[k], "identical %s in every case" % k)
                    self.assertIsInstance(lim[k], str)
                    self.assertTrue(lim[k].strip())

    def test_l1_to_l19_equal_the_approved_c3_text_verbatim(self):
        lim = self.S.results[CASE_P1]["limits"]
        c3 = real_c3.LIMITS  # read as data
        for n, phrases in LIMIT_PHRASES.items():
            with self.subTest(limit="L%d" % n):
                key = "L%d" % n
                for phrase in phrases:  # the approved C3 section 9 key phrases, restated here
                    self.assertIn(phrase, c3[key].lower(), "the C3 text itself lost %r" % phrase)
                    self.assertIn(phrase, lim[key].lower(), "C4 %s lost its key phrase %r" % (key, phrase))
                self.assertEqual(lim[key], c3[key], "C4 %s differs from the carried C3 text" % key)

    def test_l20_to_l27_carry_their_contract_16_key_phrases(self):
        lim = self.S.results[CASE_P1]["limits"]
        for n, phrases in NEW_LIMIT_PHRASES.items():
            with self.subTest(limit="L%d" % n):
                text = norm(lim["L%d" % n])
                for phrase in phrases:
                    self.assertIn(norm(phrase), text, "L%d lost its key phrase %r" % (n, phrase))

    def test_status_label_flags_and_hub_280(self):
        for cid, ev in self.S.results.items():
            lim = ev["limits"]
            self.assertIn("NOT_INDEPENDENTLY_QUALIFIED", lim["status"], cid)
            for key, value in LIMIT_FLAGS.items():
                self.assertEqual(lim[key], value, "%s %s" % (cid, key))
                self.assertIs(type(lim[key]), type(value))
            self.assertIs(lim["non_authorizing"], True)
            self.assertIs(lim["effect_executed"], False)
            self.assertEqual(lim["hub_280_digest_basis"], "OPEN")

    def test_hash_semantics_and_uncompared_members_carried(self):
        lim = self.S.results[CASE_P1]["limits"]
        self.assertGreater(lim["bundle_hash_semantics"].find("never interchangeable"), 0)
        for item in ("bundle_id", "generated_at", "integrity"):
            self.assertIn(item, lim["uncompared_by_pack"])
        self.assertEqual(len(lim["known_limitations_not_oracles"]), 4)

    def test_scenario_qualifications_are_additive_and_keep_the_hold_semantics(self):
        n1 = json.dumps(self.S.results[CASE_N1]["limits"]).lower()
        for needle in ("b005", "held"):
            self.assertIn(needle, n1, "the N1-HOLD limits must state the scenario qualification (%s)" % needle)
        self.assertIn("never complete", self.S.results[CASE_N1]["limits"]["L1"].lower(), "L1 itself is not softened for N1")

    def test_known_not_executed_lists_n3_gate(self):
        for cid, ev in self.S.results.items():
            text = json.dumps(ev.get("known_not_executed")).lower()
            self.assertIn("n3-gate", text, cid)
            self.assertNotIn("pass", text.replace("passed to", ""), "N3-GATE must not be reported as executed or passing: " + cid)


class ClaimPromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = shared()

    def hits(self, text):
        low = text.lower()
        return [(pat, m) for pat in FORBIDDEN_CLAIMS for m in re.finditer(pat, low)]

    def test_no_forbidden_positive_claim_outside_the_negated_limitation_texts(self):
        scanned = 0
        for cid, ev in self.S.results.items():
            for path, value in walk(ev):
                if not isinstance(value, str) or "limits" in path:
                    continue
                scanned += 1
                if "known_not_executed" in path:  # the explicit list of what is NOT done names the unexecuted capabilities
                    continue
                for pat, m in self.hits(value):
                    self.fail("%s %s carries forbidden claim %r: %s" % (cid, "/".join(map(str, path)), pat, value[:160]))
        self.assertGreater(scanned, 200, "the scan must not be vacuous")

    def test_no_forbidden_claim_in_any_retained_file_name_or_the_writer_text(self):
        for p in self.S.work.rglob("*"):
            self.assertFalse(self.hits(p.name), p.name)

    def test_forbidden_claims_in_limit_texts_are_always_negated(self):
        seen = 0
        for cid, ev in self.S.results.items():
            for key, text in ev["limits"].items():
                for t in flat_strings(text) if not isinstance(text, str) else [text]:
                    low = t.lower()
                    for pat, m in self.hits(t):
                        seen += 1
                        window = low[max(0, m.start() - 40):m.start() + len(m.group(0))]
                        self.assertRegex(window, NEGATION, "limit %s (%s) states %r without a negation: %s" % (key, cid, pat, t))
        self.assertGreaterEqual(seen, 3, "L17 and the carried limits must name qualification / certification in negated form")

    def test_the_claim_scan_detects_a_planted_positive_claim(self):
        for planted in ("the pack is approved", "this is certified", "production ready", "authenticated authority", "complete reconstruction",
                        "verified execution", "independently qualified", "security clearance", "the action is authorized to proceed"):
            self.assertTrue(self.hits(planted), planted)
        self.assertFalse(self.hits("unauthenticated authority"), "the word boundary keeps 'unauthenticated' out of the positive pattern")
        for negated in ("this is not production ready", "no production-ready claim"):
            for _, m in self.hits(negated):
                self.assertRegex(negated[:m.start() + 3], NEGATION)

    def test_status_vocabulary_never_promotes_a_downstream_import_or_a_hold(self):
        S = self.S
        for cid, ev in S.results.items():
            self.assertIn(ev["status"], ("PASS", "FAIL", "BLOCKED"), cid)
            self.assertNotIn(ev["status"], ("APPROVED", "AUTHORIZED", "COMPLETE"))
        n1 = S.results[CASE_N1]
        self.assertEqual(n1["chain_verdict"]["class"], "REFUSED_NATIVE")
        self.assertEqual(n1["chain_verdict"]["boundary"], "control_plane")
        by = {b["boundary"]: b for b in n1["boundaries"]}
        self.assertEqual(by["control_plane"]["orchestration_class"], "REFUSED_NATIVE")
        for b in ("replay_bundle", "evidence_pack"):
            self.assertIs(by[b]["retains_upstream_refusal"], True, b)
            self.assertEqual(by[b]["carried_authorization_state"], "held", b)
            self.assertNotEqual(by[b]["orchestration_class"], "REFUSED_NATIVE", "a downstream import is never relabelled as the upstream refusal")
        p1 = {b["boundary"]: b for b in S.results[CASE_P1]["boundaries"]}
        self.assertEqual(S.results[CASE_P1]["chain_verdict"]["class"], "ACCEPTED")
        for b in p1.values():
            self.assertIn(b["carried_authorization_state"], ("authorized", None))
        n2 = {b["boundary"]: b for b in S.results[CASE_N2]["boundaries"]}
        self.assertEqual(n2["evidence_pack"]["orchestration_class"], "REFUSED_NATIVE")
        for b in ("action_manifest", "control_plane", "replay_bundle"):
            self.assertEqual(n2[b]["orchestration_class"], "NOT_EXECUTED", b)


# ------------------------------------------------------------------------------------------------------------------------------
REAL_C4_TEXT = (MANUAL / "real_c4.py").read_text(encoding="utf-8")
PRODUCER_TEXT = (MANUAL / "c4_producer.py").read_text(encoding="utf-8")
FORBIDDEN_CALLS = {"execute", "reconcile", "apply", "system", "Popen", "urlopen", "connect", "exec", "eval", "check_output", "check_call",
                   "spawn", "popen", "fork", "__import__"}
FORBIDDEN_IMPORTS = {"socket", "urllib", "http", "requests", "ssl", "ftplib", "smtplib", "telnetlib", "asyncio", "moltbot", "runner",
                     "mock_cases", "xmlrpc", "imaplib", "poplib", "aiohttp", "httpx"}
WRITE_METHODS = {"write_bytes", "write_text", "mkdir", "unlink", "rmtree", "rename", "replace", "touch", "copy", "copy2", "copyfile", "copytree",
                 "move", "dump_evidence_pack", "open"}
READONLY_GIT = {"rev-parse", "ls-files", "status", "ls-tree", "cat-file", "hash-object", "show"}
PRIVATE_GUARDED = ("real_c1", "real_c2", "real_c3", "c2_producer")
REAL_C3_ALLOWED = {"measure", "AdapterError", "SourceIdentityError"}


def c4_py_files():
    return [MANUAL / "real_c4.py", MANUAL / "c4_producer.py", *sorted(HERE.glob("test_real_c4*.py"))]


def call_name(node):
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


class StaticGuardTests(unittest.TestCase):
    def trees(self):
        return {p.name: ast.parse(p.read_text(encoding="utf-8")) for p in c4_py_files()}

    def test_this_file_the_harness_and_the_producer_exist(self):
        names = {p.name for p in c4_py_files()}
        self.assertTrue({"real_c4.py", "c4_producer.py", "test_real_c4_integrity.py"} <= names, names)

    def test_no_effect_call_names_in_harness_producer_or_c4_tests(self):
        for fn, tree in self.trees().items():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = call_name(node)
                    self.assertNotIn(name, FORBIDDEN_CALLS, "%s calls %s" % (fn, name))
                    if name == "run":  # the only run() permitted is subprocess.run (checked separately)
                        f = node.func
                        self.assertTrue(isinstance(f, ast.Attribute) and ast.unparse(f.value) == "subprocess", "%s calls a run() that is not subprocess.run" % fn)

    def test_no_effect_method_names_are_referenced_as_attributes_in_harness_or_producer(self):
        for fn in ("real_c4.py", "c4_producer.py"):
            for node in ast.walk(self.trees()[fn]):
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, {"execute", "reconcile", "apply"}, "%s references .%s" % (fn, node.attr))
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertNotRegex(node.value, r"^(execute|reconcile|apply)$", fn)

    def test_no_network_imports_and_no_import_of_unrelated_runners(self):
        for fn, tree in self.trees().items():
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                    for m in mods:
                        self.assertNotIn(m.split(".")[0].lower(), FORBIDDEN_IMPORTS, "%s imports %s" % (fn, m))
                if isinstance(node, ast.Call) and call_name(node) in ("import_module", "__import__"):
                    self.assertNotRegex(ast.unparse(node), r"real_c[123]|c2_producer", fn)

    def test_no_underscore_private_symbol_taken_from_real_c1_c2_c3_or_c2_producer(self):
        for fn in ("real_c4.py", "c4_producer.py"):
            tree = self.trees()[fn]
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in PRIVATE_GUARDED:
                    for a in node.names:
                        self.assertFalse(a.name.startswith("_") or a.name == "*", "%s imports private %s.%s" % (fn, node.module, a.name))
                        if node.module == "real_c3":
                            self.assertTrue(a.name in REAL_C3_ALLOWED or re.fullmatch(r"[A-Z][A-Z0-9_]*", a.name), "%s imports real_c3.%s" % (fn, a.name))
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in PRIVATE_GUARDED:
                    self.assertFalse(node.attr.startswith("_") and node.attr != "__file__", "%s uses %s.%s" % (fn, node.value.id, node.attr))
                    if node.value.id == "real_c3":
                        self.assertTrue(node.attr in REAL_C3_ALLOWED or node.attr == "__file__" or re.fullmatch(r"[A-Z][A-Z0-9_]*", node.attr),
                                        "%s uses real_c3.%s" % (fn, node.attr))
                if isinstance(node, ast.Call) and call_name(node) in ("getattr", "hasattr", "setattr", "vars") and node.args:
                    self.assertNotIn(ast.unparse(node.args[0]), PRIVATE_GUARDED, "%s reflects over a predecessor module" % fn)
        for text in (REAL_C4_TEXT, PRODUCER_TEXT):
            self.assertNotRegex(text, r"real_c[123]\._|c2_producer\._(?!_file__)|from\s+real_c[123]\s+import\s+\(?\s*_")

    def test_real_c3_is_imported_for_the_allowed_public_names_only_and_c1_c2_not_at_all_as_modules_with_state(self):
        tree = ast.parse(REAL_C4_TEXT)
        local = {p.stem for p in MANUAL.glob("*.py")} - {"real_c4"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertTrue(imported & local <= {"real_c3", "c4_producer", "c2_producer", "real_c1", "real_c2"}, imported & local)
        self.assertIn("real_c3", imported)
        self.assertIn("c4_producer", imported)
        used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "real_c3"}
        self.assertIn("measure", used, "source measurement reuses the public real_c3.measure")
        c2 = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "c2_producer"}
        self.assertFalse({a for a in c2 if a.startswith("_") and a != "__file__"}, "nothing private from c2_producer")
        c4p = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "c4_producer"}
        self.assertIn("produce", c4p)

    def test_subprocess_in_harness_and_producer_is_only_read_only_git(self):
        for fn, text in (("real_c4.py", REAL_C4_TEXT), ("c4_producer.py", PRODUCER_TEXT)):
            tree = ast.parse(text)
            runs = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and ast.unparse(n.func.value) == "subprocess"]
            for n in runs:
                self.assertEqual(n.func.attr, "run", "%s: subprocess.%s" % (fn, n.func.attr))
                argv = n.args[0]
                self.assertIsInstance(argv, ast.List, fn)
                self.assertEqual(ast.literal_eval(argv.elts[0]), "git", fn)
                self.assertFalse([k for k in n.keywords if k.arg == "shell"], fn)
            git_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) in ("_git", "git")]
            for n in git_calls:
                sub = [a for a in n.args[1:] if isinstance(a, ast.Constant)]
                self.assertTrue(sub and sub[0].value in READONLY_GIT, "%s: non-read-only git subcommand: %s" % (fn, ast.unparse(n)))
            if runs:
                self.assertIn('"GIT_OPTIONAL_LOCKS": "0"', text, fn)

    def test_subprocess_in_c4_tests_runs_only_git_or_the_interpreter(self):
        for p in sorted(HERE.glob("test_real_c4*.py")):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and ast.unparse(node.func.value) == "subprocess":
                    if not node.args or not isinstance(node.args[0], (ast.List, ast.Name)):
                        self.fail("%s: subprocess call with an unreadable argv: %s" % (p.name, ast.unparse(node)[:80]))
                    if isinstance(node.args[0], ast.List) and node.args[0].elts:
                        first = ast.unparse(node.args[0].elts[0])
                        self.assertIn(first, ("'git'", "sys.executable", "str(real_c4_path)"), "%s: subprocess argv starts with %s" % (p.name, first))
                    self.assertFalse([k for k in node.keywords if k.arg == "shell" and getattr(k.value, "value", True)])

    def test_harness_write_calls_never_target_a_root(self):
        tree = ast.parse(REAL_C4_TEXT)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = call_name(node)
                if name in WRITE_METHODS:
                    receiver = ast.unparse(node.func.value) if isinstance(node.func, ast.Attribute) else "<builtin>"
                    found.append((name, receiver))
                    if name == "open" and receiver == "<builtin>" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                        self.assertNotRegex(str(node.args[1].value), "[wax+]", "builtin open() for writing in the harness")
                    if name == "dump_evidence_pack":
                        self.assertNotRegex(ast.unparse(node.args[1]), r"(?i)root|ROOTS|measured\[", "the native pack dump targets a pinned root")
                    else:
                        self.assertNotRegex(receiver, r"(?i)\broot\b|_root\b|roots\[|ROOTS|\[.root.\]", "write-capable call on a root: %s.%s" % (receiver, name))
        self.assertTrue(found, "the scan must see the harness writes")
        self.assertIn("dump_evidence_pack", [n for n, _ in found])

    def test_harness_and_tests_never_enable_bytecode_writes_or_shell(self):
        self.assertIn("sys.dont_write_bytecode = True", REAL_C4_TEXT)
        for p in sorted(HERE.glob("test_real_c4*.py")):
            self.assertTrue(p.read_text(encoding="utf-8").split('"""', 2)[2].lstrip().startswith("import sys\n\nsys.dont_write_bytecode = True"), p.name)
        for text in (REAL_C4_TEXT, PRODUCER_TEXT):
            self.assertNotIn("shell=True", text)
            self.assertNotIn("dont_write_bytecode = False", text)

    def test_no_credential_like_names_in_harness_or_producer(self):
        for fn in ("real_c4.py", "c4_producer.py"):
            for node in ast.walk(self.trees()[fn]):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertNotRegex(node.value, r"^[A-Z0-9_]*(TOKEN|SECRET|PASSWORD|CREDENTIAL|API_?KEY)[A-Z0-9_]*$", fn)

    def test_no_default_wildcard_or_environment_secret_reads_in_harness_or_producer(self):
        for fn, text in (("real_c4.py", REAL_C4_TEXT), ("c4_producer.py", PRODUCER_TEXT)):
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Call) and ast.unparse(node.func) in ("os.environ.get", "os.getenv") and node.args and isinstance(node.args[0], ast.Constant):
                    self.assertRegex(str(node.args[0].value), r"^(PATH|COGNOUS_C4_[A-Z_]+_ROOT|GITHUB_(RUN_ID|RUN_ATTEMPT|SHA))$", "%s reads env %s" % (fn, node.args[0].value))
                if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ" and isinstance(node.slice, ast.Constant):
                    self.assertRegex(str(node.slice.value), r"^(PATH|COGNOUS_C4_[A-Z_]+_ROOT|GITHUB_(RUN_ID|RUN_ATTEMPT|SHA))$", fn)


# ------------------------------------------------------------------------------------------------------------------------------
class ScopeContainmentTests(unittest.TestCase):
    ALLOWED_EXISTING_FILE_CHANGES = {".github/workflows/manual-contract-edge.yml", "tests/manual_contract/c3_hosted/test_manual_workflow_c3.py"}
    ALLOWED_GITHUB_CHANGES = {".github/workflows/manual-contract-edge.yml"}
    ALLOWED_NEW_TOP_LEVEL = {"tests/manual_contract/real_c4.py", "tests/manual_contract/c4_producer.py"}
    FROZEN_PATHS = ("tests/manual_contract/real_c1.py", "tests/manual_contract/real_c2.py", "tests/manual_contract/real_c3.py",
                    "tests/manual_contract/c2_producer.py", "tests/manual_contract/runner.py", "tests/manual_contract/mock_cases.py",
                    ".github/locks/cryptography-pydantic-pytest-513753.txt", ".github/locks/cryptography-pydantic-pytest-513753.in",
                    ".github/scripts/c2_hosted_check.py", ".github/scripts/c3_hosted_check.py", ".github/scripts/run_unittest_no_skips.py",
                    "tests/manual_contract/c3/test_real_c3.py", "tests/manual_contract/c3/test_real_c3_integrity.py",
                    "tests/manual_contract/c3_hosted/test_c3_hosted_check.py", "tests/manual_contract/c3_hosted/c3_hosted_fixtures.py")

    def base_listing(self):
        self.assertEqual(git("-C", str(REPO), "rev-parse", BASE + "^{commit}").strip(), BASE)
        return [line.split("\t", 1)[1] for line in git("-C", str(REPO), "ls-tree", "-r", BASE).splitlines()]

    def test_every_base_file_is_byte_identical_except_the_two_allowed_existing_files(self):
        names = self.base_listing()
        for r in self.FROZEN_PATHS:
            self.assertIn(r, names)
        self.assertTrue(any(n.startswith("tests/manual_contract/c1/fixtures/") for n in names))
        self.assertTrue(any(n.startswith("tests/manual_contract/c2/fixtures/") for n in names))
        differing = []
        for name in names:
            if not (REPO / name).is_file():
                differing.append(name + " (deleted)")
            elif git("-C", str(REPO), "hash-object", "--", name).strip() != git("-C", str(REPO), "rev-parse", "%s:%s" % (BASE, name)).strip():
                differing.append(name)
        self.assertEqual({d for d in differing if not d.endswith("(deleted)")} - self.ALLOWED_EXISTING_FILE_CHANGES, set(), differing)
        self.assertEqual([d for d in differing if d.endswith("(deleted)")], [], "no base file may be deleted")

    def test_frozen_predecessor_files_and_fixtures_and_lock_are_byte_identical_to_base(self):
        for name in self.FROZEN_PATHS:
            with self.subTest(path=name):
                self.assertEqual(git("-C", str(REPO), "hash-object", "--", name).strip(), git("-C", str(REPO), "rev-parse", "%s:%s" % (BASE, name)).strip())
        listing = git("-C", str(REPO), "ls-tree", "-r", BASE, "--", "tests/manual_contract/c1", "tests/manual_contract/c2").splitlines()
        self.assertGreater(len(listing), 5)
        for line in listing:
            name = line.split("\t", 1)[1]
            self.assertEqual(git("-C", str(REPO), "hash-object", "--", name).strip(), git("-C", str(REPO), "rev-parse", "%s:%s" % (BASE, name)).strip(), name)

    def test_the_only_modified_existing_files_are_the_workflow_and_the_amended_c3_workflow_test(self):
        changed = git("-C", str(REPO), "diff", "--name-only", "--diff-filter=MDRTUXB", BASE).split()
        self.assertEqual(set(changed) - self.ALLOWED_EXISTING_FILE_CHANGES, set(), "an existing file differs from the base")
        self.assertEqual(git("-C", str(REPO), "diff", "--name-only", "--diff-filter=D", BASE).strip(), "")
        for rel in sorted(self.ALLOWED_EXISTING_FILE_CHANGES):
            self.assertTrue((REPO / rel).is_file(), rel)

    def test_the_only_github_change_is_the_manual_contract_workflow(self):
        changed = set(git("-C", str(REPO), "diff", "--name-only", BASE, "--", ".github").split())
        untracked = {line[3:] for line in git("-C", str(REPO), "status", "--porcelain", "--untracked-files=all", "--", ".github").splitlines()}
        self.assertEqual((changed | untracked) - self.ALLOWED_GITHUB_CHANGES, set(), "only the manual-contract workflow may change under .github")

    def test_new_files_stay_out_of_predecessor_directories(self):
        added = set(git("-C", str(REPO), "diff", "--name-only", "--diff-filter=A", BASE).split())
        added |= set(git("-C", str(REPO), "ls-files", "--others", "--exclude-standard").split())
        for name in sorted(added):
            with self.subTest(path=name):
                if name.startswith("tests/manual_contract/c4/") or name in self.ALLOWED_NEW_TOP_LEVEL:
                    continue
                self.assertFalse(name.startswith((".github/", "tests/manual_contract/c1/", "tests/manual_contract/c2/", "tests/manual_contract/c3/",
                                                  "tests/manual_contract/c3_hosted/")), "unauthorised new file " + name)
                self.assertFalse(re.fullmatch(r"tests/manual_contract/[^/]+", name), "unauthorised new top-level manual_contract file " + name)
        for must in sorted(self.ALLOWED_NEW_TOP_LEVEL):
            self.assertTrue((REPO / must).is_file(), must)

    def test_changes_stay_inside_what_the_merged_c3_integrity_suite_allows(self):
        """The merged C3 integrity suite diffs against ITS base (fce552de); the amended file and the workflow are 'A'/allowlisted there."""
        c3_base = "fce552de1395d7d6dd2f51691089115c3d7f18f8"
        done = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", c3_base + "^{commit}"], capture_output=True, env=GITENV)
        if done.returncode != 0:
            return  # shallow checkout without the C3 base: the C3 suite itself fails closed there
        modified_vs_c3 = set(git("-C", str(REPO), "diff", "--name-only", "--diff-filter=MDRTUXB", c3_base).split())
        self.assertEqual(modified_vs_c3 - {".github/workflows/manual-contract-edge.yml"}, set(), "the C3 integrity suite would reject this")
        github_vs_c3 = set(git("-C", str(REPO), "diff", "--name-only", c3_base, "--", ".github").split())
        self.assertEqual(github_vs_c3 - {".github/workflows/manual-contract-edge.yml", ".github/scripts/c3_hosted_check.py"}, set())


class DispatchContainmentTests(unittest.TestCase):
    """No file under the repository drives a workflow dispatch (CLI or Actions API); the manual workflow only DECLARES its trigger."""
    PATTERNS = (re.compile(r"gh\s+workflow\s+run", re.I), re.compile(r"gh\s+api\b[^\n]*dispatches", re.I),
                re.compile(r"actions/workflows/[^\s\"']*dispatches", re.I), re.compile(r"/dis(?:patches)\b"),
                re.compile(r"create(?:W|_w)orkflow_?[Dd]ispatch|workflows\.dispatch", re.I),
                re.compile(r"curl[^\n]*(api\.github\.com|/dis(?:patches))", re.I))

    def test_no_tracked_or_untracked_file_mentions_a_dispatch_call(self):
        files = git("-C", str(REPO), "ls-files", "-co", "--exclude-standard", "-z").split("\0")
        scanned = 0
        for rel in filter(None, files):
            p = REPO / rel
            if not p.is_file() or p.is_symlink():
                continue
            data = p.read_bytes()
            if b"\0" in data[:4096]:
                continue
            scanned += 1
            text = data.decode("utf-8", "replace")
            for pat in self.PATTERNS:
                self.assertIsNone(pat.search(text), "%s mentions a dispatch call (%s)" % (rel, pat.pattern))
        self.assertGreater(scanned, 100, "the scan must not be vacuous")

    def test_the_dispatch_patterns_detect_planted_calls(self):
        planted_calls = (
            "gh " + "workflow run manual-contract-edge.yml",
            "gh api repos/o/r/actions/workflows/1/"
            "dispatches -f ref=main",
            "POST /repos/o/r/actions/workflows/x.yml/"
            "dispatches",
            "octokit.actions.create" "WorkflowDispatch(",
            "curl -X POST https://api." "github.com/x",
        )
        for planted in planted_calls:
            self.assertTrue(any(p.search(planted) for p in self.PATTERNS), planted)

    def test_workflow_declares_only_workflow_dispatch_and_contents_read(self):
        text = (REPO / ".github/workflows/manual-contract-edge.yml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^on:\s*\n\s+workflow_dispatch:")
        self.assertNotRegex(text, r"(?m)^\s+(push|pull_request|pull_request_target|schedule|workflow_run|repository_dispatch):")
        self.assertRegex(text, r"(?m)^permissions:\s*\n\s+contents:\s*read\s*$")
        self.assertNotRegex(text, r"(?m)^\s+(actions|id-token|contents|packages|pull-requests|issues|statuses|checks|deployments):\s*write")


# ------------------------------------------------------------------------------------------------------------------------------
class ApiShapeTests(unittest.TestCase):
    def test_public_surface_and_error_hierarchy(self):
        for name in ("run_all", "main", "AdapterError", "SourceIdentityError", "PINS", "FROZEN", "ENV", "SCHEMA", "CASE_P1", "CASE_N1", "CASE_N2"):
            self.assertTrue(hasattr(real_c4, name), name)
        self.assertTrue(issubclass(real_c4.SourceIdentityError, real_c4.AdapterError))
        self.assertTrue(issubclass(real_c4.AdapterError, Exception))
        self.assertFalse(issubclass(real_c4.AdapterError, ValueError))
        self.assertFalse(hasattr(real_c4, "ImportContractError"), "a native refusal is never an AdapterError type")
        self.assertTrue(issubclass(c4_producer.ProducerError, Exception))
        self.assertFalse(issubclass(c4_producer.ProducerError, ValueError))

    def test_case_ids_schema_and_constants(self):
        self.assertEqual((real_c4.CASE_P1, real_c4.CASE_N1, real_c4.CASE_N2), (CASE_P1, CASE_N1, CASE_N2))
        self.assertEqual(real_c4.SCHEMA, EVIDENCE_SCHEMA)
        self.assertEqual(set(shared().results), set(CASES))

    def test_inputs_cannot_be_overridden_through_the_api(self):
        import inspect
        params = inspect.signature(real_c4.run_all).parameters
        self.assertEqual([n for n, p in params.items() if p.kind is not inspect.Parameter.KEYWORD_ONLY], ["roots", "workdir"])
        # the only tolerated extra surface: keyword-only input PATH hooks, which stay behind the frozen sha256 gate (tested in
        # FixtureIntegrityTests.test_input_path_hooks_cannot_smuggle_a_different_file); nothing that carries a label, bundle, revision or scenario
        self.assertLessEqual({n for n, p in params.items() if p.kind is inspect.Parameter.KEYWORD_ONLY}, {"manifest_path", "proposal_path"})
        self.assertEqual(list(inspect.signature(real_c4.main).parameters), ["argv"])
        for fn in (real_c4.run_all, real_c4.main):
            self.assertFalse([p for p in inspect.signature(fn).parameters if re.search("label|bundle|revision|scenario|record|decision", p, re.I)])
        self.assertEqual(list(inspect.signature(c4_producer.produce).parameters), ["cp_root", "workdir", "proposal_obj", "manifest_obj", "scenario"])

    def test_unknown_case_id_exit_code_2_in_process(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), mock.patch.object(real_c4, "run_all", side_effect=AssertionError("must not run")) as ra:
            rc = real_c4.main(["--case", "nope"])
        self.assertEqual(rc, 2)
        self.assertEqual(ra.call_count, 0)
        for bad in ("", "c4_p1", "C4_P1_AUTHORIZED_CHAIN", "all ", CASE_P1 + " ", "../" + CASE_P1, "c4_n3_gate", "c3_p1_replay_to_pack_partial"):
            with self.subTest(case=bad), contextlib.redirect_stderr(io.StringIO()), mock.patch.object(real_c4, "run_all", side_effect=AssertionError("no")):
                self.assertEqual(real_c4.main(["--case", bad]), 2)

    def test_unknown_case_id_exit_code_2_subprocess_and_nothing_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, out = pathlib.Path(tmp) / "w", pathlib.Path(tmp) / "r.json"
            done = subprocess.run([sys.executable, "-I", "-B", str(MANUAL / "real_c4.py"), "--case", "nope", "--out", str(out), "--workdir", str(work)],
                                  capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")}, cwd=tempfile.gettempdir(), timeout=120)
            self.assertEqual(done.returncode, 2, done.stderr)
            self.assertFalse(work.exists() or out.exists())
            self.assertNotIn("Traceback", done.stderr)

    def test_good_p1_run_exits_0_and_writes_one_passing_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "r.json"
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **{ENVS[k]: str(v) for k, v in ROOTS.items()}}
            done = subprocess.run([sys.executable, "-I", "-B", str(MANUAL / "real_c4.py"), "--case", CASE_P1, "--out", str(out),
                                   "--workdir", str(pathlib.Path(tmp) / "w")], capture_output=True, text=True, env=env, cwd=tempfile.gettempdir(), timeout=900)
            self.assertEqual(done.returncode, 0, done.stderr)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(list(result), [CASE_P1])
            self.assertEqual(result[CASE_P1]["case_id"], CASE_P1)
            self.assertEqual(result[CASE_P1]["status"], "PASS")
            self.assertEqual(result[CASE_P1]["schema"], EVIDENCE_SCHEMA)
        for key, root in ROOTS.items():
            self.assertEqual(git("-C", str(root), "status", "--porcelain", "--ignored=matching", "--untracked-files=all"), "", key)

    def test_all_cases_cli_writes_one_object_keyed_by_case_id_and_exits_0_only_on_all_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "r.json"
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **{ENVS[k]: str(v) for k, v in ROOTS.items()}}
            done = subprocess.run([sys.executable, "-I", "-B", str(MANUAL / "real_c4.py"), "--case", "all", "--out", str(out),
                                   "--workdir", str(pathlib.Path(tmp) / "w")], capture_output=True, text=True, env=env, cwd=tempfile.gettempdir(), timeout=900)
            self.assertEqual(done.returncode, 0, done.stderr)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(sorted(result), sorted(CASES))
            self.assertEqual({v["status"] for v in result.values()}, {"PASS"})

    def test_workdir_must_be_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "stale").write_text("x")
            with self.assertRaises(real_c4.AdapterError):
                real_c4.run_all(dict(ROOTS), pathlib.Path(tmp))


class NoSkipTests(unittest.TestCase):
    def test_no_expected_failure_or_skip_in_this_file(self):
        """AST scan of this file (any spelling: decorator, call, import, SkipTest) plus a runtime scan of the loaded tests."""
        banned = {"expectedFailure", "skip", "skipIf", "skipUnless", "skipTest", "SkipTest"}
        for node in ast.walk(ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))):
            name = node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None) if isinstance(node, ast.Name) else None
            self.assertNotIn(name, banned, "this file uses %s" % name)
            if isinstance(node, ast.ImportFrom):
                self.assertFalse({a.name for a in node.names} & banned)
        for cls in (c for c in globals().values() if isinstance(c, type) and issubclass(c, unittest.TestCase)):
            for attr in dir(cls):
                fn = getattr(cls, attr)
                self.assertFalse(getattr(fn, "__unittest_expecting_failure__", False), "%s.%s" % (cls.__name__, attr))
                self.assertFalse(getattr(fn, "__unittest_skip__", False), "%s.%s" % (cls.__name__, attr))


if __name__ == "__main__":
    unittest.main()
