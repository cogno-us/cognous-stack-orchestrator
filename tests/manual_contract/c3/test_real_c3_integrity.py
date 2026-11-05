"""Integrity tests for the VSLICE-C3 harness (real_c3): source identity, fixture integrity, byte preservation, limitations,
claim promotion, static guards, API shape. Companion to test_real_c3.py (P1 / N1-TEN / N3 / N5-REV observations), which this file
does not duplicate.

DRAFT. Expectations come ONLY from the frozen literals restated below (Hub #273 contract comment 6671327666, frozen for development
by 6671384213: sections 2, 9, 13, 14, 17, 18, and the issue text pins) and from this file's own independent observations (files read
from disk, this file's own Replay import, spies on the real Replay/Pack calls). They are never read back from harness output;
harness evidence is only compared AGAINST them. stdlib unittest only; run with `python -I -B`. The four component roots come from
the environment and are REQUIRED (the run fails, it does not skip). Pinned roots are only read: every mutation is made on a clone.

A green run means the C3 harness preserved bytes, identity and limitations on a synthetic fixture. It is not qualification,
authenticity, effect proof, approval or acceptance of anything.
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
import real_c3  # noqa: E402  (must not import any component at module import time; checked in SourceIdentityTests)

ENVS = {"control_plane": "COGNOUS_C3_CONTROL_PLANE_ROOT", "replay_bundle": "COGNOUS_C3_REPLAY_BUNDLE_ROOT",
        "evidence_pack": "COGNOUS_C3_EVIDENCE_PACK_ROOT", "action_manifest": "COGNOUS_C3_ACTION_MANIFEST_ROOT"}
KEYS = tuple(ENVS)
BASE = "fce552de1395d7d6dd2f51691089115c3d7f18f8"  # orchestrator base commit of this slice
CASE_P1, CASE_N1, CASE_N3, CASE_N5 = ("c3_p1_replay_to_pack_partial", "c3_n1_ten_tenant_tamper", "c3_n3_partial_as_complete",
                                      "c3_n5_rev_wrong_revision")
EVIDENCE_SCHEMA = "cognous.orchestrator.c3-evidence/0-candidate"

# ---- frozen literals (contract section 2 / issue text) ----
PINS = {
    "control_plane": ("cogno-us/cognous-control-plane", "484fdbd297235dd24148ddb0703f2055a31eabff", "c182939882103015f12c5360fccf377c54e2c4f9"),
    "replay_bundle": ("cogno-us/cognous-replay-bundle", "93a76e281fcae6a65d2cd1d35376f87442dafb95", "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f"),
    "evidence_pack": ("cogno-us/cognous-governance-evidence-pack", "065150852cc2a8abeb748777bb69d72ccd0e03d8", "fe428a89da2e74346648cdfe014462ddc8624c77"),
    "action_manifest": ("cogno-us/cognous-action-manifest", "fa170815ef96a54c233d0dd9da821b60debabf8b", "3b0e3772e944aa668c8f4b879588c7cc3e2c32be"),
}
CP_SHA = PINS["control_plane"][1]
PROPOSAL_SHA = "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2"
MANIFEST_FILE_SHA = "789ad39596b9e1ef84a726a671883e1cb6b83343da3a31db0a1120906d68c074"
C2_PRODUCER_SHA = "7c4f2595d7939e4a373586faafc0de86469dc03b791d893d7b27fb328a02a895"
MANIFEST_REL = "examples/refund_integration_v1_1.manifest.json"
TRACKED_FILE = {  # one tracked file per root that the harness loads or reads
    "control_plane": "src/agent_control_plane/bounded.py", "replay_bundle": "src/agent_replay_bundle/importers.py",
    "evidence_pack": "src/agent_governance_evidence_pack/importer.py", "action_manifest": MANIFEST_REL}
PACK_MODULES = ("importer", "validator", "loader")
COMPONENT_PREFIXES = ("agent_control_plane", "agent_replay_bundle", "agent_governance_evidence_pack")

# ---- contract section 9: required limitations, key phrase(s) per L (compared lower-case) ----
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
LIMIT_STATUS = "DEVELOPMENT_TESTED_NOT_INDEPENDENTLY_QUALIFIED_FIXTURE_SCOPED"
LIMIT_FLAGS = {"decision_semantics_only": True, "effect_executed": False, "non_authorizing": True,
               "no_certification_clearance_or_production_readiness": "HOLD", "hub_280_digest_basis": "OPEN"}
LIMIT_KEYS = {"status", "bundle_hash_semantics", "uncompared_by_pack", "known_limitations_not_oracles", "synthetic_key_scope",
              *LIMIT_FLAGS, *("L%d" % n for n in LIMIT_PHRASES)}
# positive claims that may appear ONLY inside a negated limitation text (never as a value elsewhere in the evidence)
FORBIDDEN_CLAIMS = (r"complete reconstruction", r"fully reconstructed", r"reconstruction_complete(?!ness)", r"\bauthenticated authority",
                    r"\bverified execution", r"\bexecution verified", r"\bcertified\b", r"\bapproved\b", r"production[ -]ready",
                    r"\bindependently qualified", r"\bcompliant\b", r"\bcleared for\b", r"\bclearance granted")
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
    return strict_loads((MANUAL / "c1" / "fixtures" / "proposal.tenant-alpha.json").read_bytes())


# ------------------------------------------------------------------------------------------------------------------------------
class Shared:
    """ONE full run_all() with spies on the REAL Replay import, the REAL Pack import, the serialiser and every file write."""

    def __init__(self):
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="c3i-")) / "w"
        P = real_c3.measure()["_modules"]  # modules are cached: the spies below patch the objects the run will use
        self.IMP, self.PI = P["importers"], P["pack_importer"]
        bundle_cls = sys.modules["agent_replay_bundle.reconstruction"].ReconstructionBundle
        self.before = {k: tree_signature(r) for k, r in ROOTS.items()}
        self.replay, self.pack, self.serialise, self.dumps, self.writes, self.opens = [], [], [], [], [], []
        self.replay_internal, self.pack_internal, self.dumps_internal = 0, 0, 0  # calls made by the components themselves, not by real_c3
        outer = self
        real_replay, real_pack, real_ser = self.IMP.import_bounded_workflow, self.PI.import_manifest_reconstruction, real_c3._serialise_bundle
        real_dump, real_wb, real_wt, real_open = bundle_cls.model_dump, pathlib.Path.write_bytes, pathlib.Path.write_text, builtins.open

        def from_harness():  # the spy's caller's caller: the Pack also re-derives through the same module attributes
            return sys._getframe(2).f_globals.get("__name__") == "real_c3"

        def replay_spy(record, *a, **kw):
            bundle = real_replay(record, *a, **kw)
            if not from_harness():
                outer.replay_internal += 1
                return bundle
            outer.replay.append({"record": copy.deepcopy(record), "args": a, "kwargs": copy.deepcopy(kw), "bundle": bundle,
                                 "native_dump": real_dump(bundle, mode="json")})
            return bundle

        def pack_spy(manifest, bundle, *a, **kw):
            if not from_harness():
                outer.pack_internal += 1
                return real_pack(manifest, bundle, *a, **kw)
            outer.pack.append({"manifest": copy.deepcopy(manifest), "bundle": copy.deepcopy(bundle), "extra": (a, kw)})
            return real_pack(manifest, bundle, *a, **kw)

        def ser_spy(bundle):
            data = real_ser(bundle)
            outer.serialise.append(data)
            return data

        def dump_spy(self_, *a, **kw):
            if from_harness():
                outer.dumps.append((a, dict(kw)))
            else:
                outer.dumps_internal += 1
            return real_dump(self_, *a, **kw)

        def wb_spy(self_, data):
            outer.writes.append((str(self_), bytes(data)))
            return real_wb(self_, data)

        def wt_spy(self_, data, *a, **kw):
            outer.writes.append((str(self_), None))
            return real_wt(self_, data, *a, **kw)

        def open_spy(file, mode="r", *a, **kw):
            if isinstance(file, (str, os.PathLike)) and any(c in str(mode) for c in "wax+"):
                outer.opens.append(str(file))
            return real_open(file, mode, *a, **kw)
        with mock.patch.object(self.IMP, "import_bounded_workflow", replay_spy), mock.patch.object(self.PI, "import_manifest_reconstruction", pack_spy), \
                mock.patch.object(real_c3, "_serialise_bundle", ser_spy), mock.patch.object(bundle_cls, "model_dump", dump_spy), \
                mock.patch.object(pathlib.Path, "write_bytes", wb_spy), mock.patch.object(pathlib.Path, "write_text", wt_spy), \
                mock.patch.object(builtins, "open", open_spy):
            self.results = real_c3.run_all(workdir=self.work)
        self.after = {k: tree_signature(r) for k, r in ROOTS.items()}
        self.git_status = {k: git("-C", str(r), "status", "--porcelain", "--ignored=matching", "--untracked-files=all") for k, r in ROOTS.items()}
        self.p1 = self.results[CASE_P1]
        self.record_path = pathlib.Path(self.p1["record"]["path"])
        self.bundle_path = pathlib.Path(self.p1["bundle"]["path"])
        self.bundle_bytes = self.bundle_path.read_bytes()
        self.bundle_cls = bundle_cls


def shared():
    if "run" not in SHARED:
        SHARED["run"] = Shared()
    return SHARED["run"]


def walk(obj, path=()):
    """Yield (path, key-or-None, value) for every scalar; keys are yielded as pseudo-entries too."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, path + (i,))
    else:
        yield path, obj


# ------------------------------------------------------------------------------------------------------------------------------
PROBE = r"""
import sys, json, os
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import real_c3
roots = json.loads(sys.argv[2])
before_path = list(sys.path)
PREFIXES = ("agent_control_plane", "agent_replay_bundle", "agent_governance_evidence_pack")
out = {"clean_at_import": not any(m.startswith(PREFIXES) for m in sys.modules)}
try:
    CALL
    out["raised"] = None
except BaseException as e:
    out["raised"] = [type(e).__name__, [c.__name__ for c in type(e).__mro__], str(e)[:400]]
out["component_modules"] = sorted(m for m in sys.modules if m.startswith(PREFIXES))
out["tests_pkg_loaded"] = "tests" in sys.modules
out["path_added"] = [p for p in sys.path if p not in before_path]
print(json.dumps(out))
"""

RUNPROBE = r"""
import sys, json, os
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import real_c3, c2_producer
roots, work = json.loads(sys.argv[2]), sys.argv[3]
PREFIXES = ("agent_control_plane", "agent_replay_bundle", "agent_governance_evidence_pack")
calls = {"produce": 0, "replay": 0, "pack": 0}
out = {"measure_raised": None, "raised": None, "statuses": None, "calls": calls}
try:
    P = real_c3.measure(roots)["_modules"]
except BaseException as e:
    out["measure_raised"] = [type(e).__name__, [c.__name__ for c in type(e).__mro__], str(e)[:400]]
    P = None
if P is not None:
    def counting(owner, name, key):
        real = getattr(owner, name)
        def spy(*a, **kw):
            if sys._getframe(1).f_globals.get("__name__") == "real_c3":  # the Pack also re-derives via these attributes
                calls[key] += 1
            return real(*a, **kw)
        setattr(owner, name, spy)
    counting(c2_producer, "produce", "produce")
    counting(P["importers"], "import_bounded_workflow", "replay")
    counting(P["pack_importer"], "import_manifest_reconstruction", "pack")
    try:
        res = real_c3.run_all(roots, work)
        out["statuses"] = {k: [v["status"], v["outcome"]] for k, v in res.items()}
    except BaseException as e:
        out["raised"] = [type(e).__name__, [c.__name__ for c in type(e).__mro__], str(e)[:400]]
out["component_modules"] = sorted(m for m in sys.modules if m.startswith(PREFIXES))
out["work_exists"] = os.path.isdir(work)
out["work_has_run"] = os.path.isdir(os.path.join(work, "run"))
print(json.dumps(out))
"""

GUARD = r"""
import sys, json, os, pathlib, subprocess, tempfile, importlib
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import real_c3
scenario = sys.argv[2]
PKG = "agent_governance_evidence_pack"
env = {"PATH": os.environ["PATH"], "HOME": "/nonexistent", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
tmp = pathlib.Path(tempfile.mkdtemp(prefix="c3g-")).resolve()
root = tmp / "pack"
(root / "src" / PKG).mkdir(parents=True)
for name in ("__init__",) + %(mods)r:
    (root / "src" / PKG / (name + ".py")).write_text("VALUE = '%%s'\n" %% name)
(root / "fixture.json").write_text("{}\n")
if scenario == "symlink":
    (root / "link.json").symlink_to("fixture.json")
for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x"]):
    subprocess.run(["git", "-C", str(root), *args], check=True, env=env, capture_output=True)
syspath = str(root / "src")
if scenario == "symlinked_path":
    link = tmp / "linked-src"
    link.symlink_to(root / "src")
    syspath = str(link)
sys.path.insert(0, syspath)
mods = %(mods)r[:-1] if scenario == "missing_required" else %(mods)r
for name in mods:
    importlib.import_module(PKG + "." + name)
required = tuple(PKG + "." + n for n in %(mods)r)
extra = ("fixture.json",)
ev = {}
package = PKG
if scenario == "tampered_module":
    (root / "src" / PKG / "validator.py").write_text("VALUE = 'tampered'\n")
elif scenario == "tampered_extra":
    (root / "fixture.json").write_text('{"x": 1}\n')
elif scenario == "outside_submodule":
    other = tmp / "elsewhere"
    other.mkdir()
    (other / "extra.py").write_text("VALUE = 1\n")
    sys.modules[PKG].__path__.append(str(other))
    importlib.import_module(PKG + ".extra")
elif scenario == "outside_package":
    other = tmp / "elsewhere"
    (other / "c3outside").mkdir(parents=True)
    (other / "c3outside" / "__init__.py").write_text("VALUE = 1\n")
    sys.path.insert(0, str(other))
    importlib.import_module("c3outside")
    package = "c3outside"
    required = ()
try:
    real_c3._check_modules(root.resolve(), ev, package, required=required, extra_files=extra)
    res = {"raised": None, "modules": sorted(ev["imported_modules"])}
except BaseException as e:
    res = {"raised": [type(e).__name__, str(e)[:300]]}
print(json.dumps(res))
"""


def run_probe(call, roots, tree=MANUAL, env=None):
    argv = [sys.executable, "-I", "-B", "-c", PROBE.replace("CALL", call), str(tree), json.dumps({k: str(v) for k, v in roots.items()})]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=tempfile.gettempdir(),
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **(env or {})})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def run_runprobe(tree, roots, work):
    argv = [sys.executable, "-I", "-B", "-c", RUNPROBE, str(tree), json.dumps({k: str(v) for k, v in roots.items()}), str(work)]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=600, cwd=tempfile.gettempdir(),
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def make_tree(dst):
    """Copy of the manual_contract directory (harness, producer, runner, fixtures) for alteration tests."""
    shutil.copytree(MANUAL, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "test_*.py"))
    return pathlib.Path(dst)


class CloneMixin:
    """Fresh clones of the pinned roots in a private tempdir (the pinned roots themselves are never written)."""

    @classmethod
    def make_good_clones(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="c3i-src-")).resolve()
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
    """Fresh interpreters (python -I -B): no component is imported and no sys.path entry is added when ANY of the four gates fails."""

    @classmethod
    def setUpClass(cls):
        cls.make_good_clones()

    @classmethod
    def tearDownClass(cls):
        cls.drop_clones()

    def refused(self, key, bad, pattern, *, expect_key=True):
        out = run_probe("real_c3.measure(roots)", self.roots_with(key, bad))
        self.assertTrue(out["clean_at_import"], "importing real_c3 must not import component code")
        self.assertIsNotNone(out["raised"], "source gate accepted a bad %s root: %s" % (key, bad))
        self.assertEqual(out["raised"][0], "SourceIdentityError", out)
        self.assertIn("AdapterError", out["raised"][1])
        self.assertRegex(out["raised"][2], pattern)
        if expect_key:
            self.assertIn(key, out["raised"][2])
        self.assertEqual(out["component_modules"], [], "no component module may be imported after a failed source gate (%s)" % key)
        self.assertFalse(out["tests_pkg_loaded"])
        self.assertEqual([p for p in out["path_added"] if "c3i-src" in p], [], "no clone path may be added to sys.path after a failed gate")

    def test_positive_control_clean_clones_pass_measurement(self):
        out = run_probe("real_c3.measure(roots)", self.good)
        self.assertIsNone(out["raised"], out)
        self.assertTrue(out["clean_at_import"])
        self.assertTrue(out["component_modules"], "a passing measurement does import the components")

    def test_positive_control_pinned_env_roots_pass(self):
        self.assertIsNone(run_probe("real_c3.measure(roots)", ROOTS)["raised"])

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

    def test_modified_pack_module_files_are_each_refused(self):
        for name in PACK_MODULES:
            with self.subTest(module=name):
                bad = self.clone("evidence_pack", "mod-" + name)
                target = bad / "src" / "agent_governance_evidence_pack" / (name + ".py")
                target.write_bytes(target.read_bytes() + b"\n# tampered\n")
                self.refused("evidence_pack", bad, "modified, untracked or ignored")

    def test_skip_worktree_hidden_modification_refused_in_each_root(self):
        for key in KEYS:
            with self.subTest(root=key):
                bad = self.clone(key, "skipwt")
                target = bad / TRACKED_FILE[key]
                target.write_bytes(target.read_bytes() + b"\n# hidden tamper\n")
                git("-C", str(bad), "update-index", "--skip-worktree", TRACKED_FILE[key])
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

    def test_replay_clone_at_parent_commit_refused(self):
        bad = self.clone("replay_bundle", "parent")
        git("-C", str(bad), "checkout", "-q", "--detach", PINS["replay_bundle"][1] + "~1")
        self.refused("replay_bundle", bad, "!= pin")

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

    def test_root_unset_in_environment_refused_in_each_root(self):
        for key in KEYS:
            with self.subTest(root=key):
                roots = {k: v for k, v in self.good.items() if k != key}
                out = run_probe("real_c3.measure(roots)", roots)  # env carries no COGNOUS_C3_* variables
                self.assertEqual(out["raised"][0], "SourceIdentityError", out)
                self.assertIn("root missing (set %s)" % ENVS[key], out["raised"][2])
                self.assertEqual(out["component_modules"], [])

    def test_root_symlinked_to_pinned_checkout_resolves_to_real_top_level(self):
        link = self.tmp / "link-to-cp"
        link.symlink_to(self.good["control_plane"])
        out = run_probe("real_c3.measure(roots)", self.roots_with("control_plane", link))
        self.assertIsNone(out["raised"], "a symlinked root that resolves to the exact pinned clean checkout is the same source: %s" % out)

    def test_pins_equal_frozen_literals(self):
        self.assertEqual(set(real_c3.PINS), set(KEYS))
        for key, (repo, sha, tree) in PINS.items():
            pin = real_c3.PINS[key]
            self.assertEqual((pin["repository"], pin["sha"], pin["tree"]), (repo, sha, tree), key)
            self.assertEqual(git("-C", str(ROOTS[key]), "rev-parse", "HEAD").strip(), sha, key + ": the supplied root is not the frozen pin")
            self.assertEqual(git("-C", str(ROOTS[key]), "rev-parse", "HEAD^{tree}").strip(), tree, key)
        self.assertEqual(real_c3.ENV, ENVS)

    def test_cli_exit_code_2_for_source_failure_in_any_root(self):
        for key in KEYS:
            with self.subTest(root=key):
                bad = self.clone(key, "cli")
                (bad / "stray.txt").write_text("x\n")
                env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **{ENVS[k]: str(v) for k, v in self.roots_with(key, bad).items()}}
                out_json, work = self.tmp / ("cli-%s.json" % key), self.tmp / ("w-cli-" + key)
                done = subprocess.run([sys.executable, "-I", "-B", str(MANUAL / "real_c3.py"), "--case", CASE_P1, "--out", str(out_json),
                                       "--workdir", str(work)], capture_output=True, text=True, env=env, cwd=tempfile.gettempdir(), timeout=300)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("adapter error", done.stderr)
                self.assertFalse(out_json.exists(), "no result file is written for an adapter error")
                self.assertFalse(work.exists(), "no producer workdir after a failed source gate")

    def test_main_in_process_source_failure_returns_2(self):
        bad = self.clone("evidence_pack", "inproc")
        (bad / "stray.txt").write_text("x\n")
        envs = {ENVS[k]: str(v) for k, v in self.roots_with("evidence_pack", bad).items()}
        err = io.StringIO()
        with mock.patch.dict(os.environ, envs), contextlib.redirect_stderr(err), mock.patch.object(real_c3, "run_all", wraps=real_c3.run_all) as ra:
            rc = real_c3.main(["--case", CASE_P1, "--workdir", str(self.tmp / "w-inproc")])
        self.assertEqual(rc, 2)
        self.assertEqual(ra.call_count, 1)
        self.assertIn("adapter error", err.getvalue())

    def test_measure_requires_isolated_interpreter(self):
        argv = [sys.executable, "-B", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import real_c3\n"
                "try:\n    real_c3.measure({})\nexcept real_c3.AdapterError as e:\n    print('REFUSED', str(e))", str(MANUAL)]
        done = subprocess.run(argv, capture_output=True, text=True, cwd=tempfile.gettempdir(), timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("REFUSED run under `python -I -B`", done.stdout)


class ModuleGuardTests(unittest.TestCase):
    """The git-blob guards of _check_modules fail closed on their own, adapted for a Pack-shaped package (fresh interpreter each)."""

    def guard(self, scenario):
        code = GUARD % {"mods": PACK_MODULES}
        done = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(MANUAL), scenario], capture_output=True, text=True, timeout=120,
                              cwd=tempfile.gettempdir(), env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def assert_refused(self, scenario, pattern):
        out = self.guard(scenario)
        self.assertIsNotNone(out["raised"], "guard accepted scenario %s" % scenario)
        self.assertEqual(out["raised"][0], "SourceIdentityError")
        self.assertRegex(out["raised"][1], pattern)

    def test_clean_pack_package_and_extra_file_pass(self):
        out = self.guard("clean")
        self.assertIsNone(out["raised"], out)
        for name in PACK_MODULES:
            self.assertIn("agent_governance_evidence_pack." + name, out["modules"])
        self.assertIn("fixture.json", out["modules"])

    def test_tampered_loaded_pack_module_refused(self):
        self.assert_refused("tampered_module", "differs from the pinned git blob")

    def test_tampered_extra_file_refused(self):
        self.assert_refused("tampered_extra", "differs from the pinned git blob")

    def test_pack_submodule_loaded_from_outside_the_pinned_root_refused(self):
        self.assert_refused("outside_submodule", "not under")

    def test_package_loaded_from_outside_the_pinned_root_refused(self):
        self.assert_refused("outside_package", "not under")

    def test_missing_required_pack_module_refused(self):
        self.assert_refused("missing_required", "required modules not loaded")

    def test_symlink_in_pinned_tree_refused(self):
        self.assert_refused("symlink", "symlink or gitlink")

    def test_module_reached_through_symlinked_path_refused(self):
        self.assert_refused("symlinked_path", "through a symlink")

    def test_required_pack_modules_constant(self):
        self.assertEqual(real_c3._PACK_REQUIRED, tuple("agent_governance_evidence_pack." + n for n in PACK_MODULES))


# ------------------------------------------------------------------------------------------------------------------------------
class FixtureIntegrityTests(CloneMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.make_good_clones()
        shared()  # modules loaded for the in-process strict-loader tests

    @classmethod
    def tearDownClass(cls):
        cls.drop_clones()

    def test_frozen_fixture_literals_and_actual_files(self):
        self.assertEqual(real_c3.FROZEN, {"proposal_sha256": PROPOSAL_SHA, "manifest_file_sha256": MANIFEST_FILE_SHA, "c2_producer_sha256": C2_PRODUCER_SHA})
        self.assertEqual(sha256((MANUAL / "c1" / "fixtures" / "proposal.tenant-alpha.json").read_bytes()), PROPOSAL_SHA)
        self.assertEqual(sha256((ROOTS["action_manifest"] / MANIFEST_REL).read_bytes()), MANIFEST_FILE_SHA)
        self.assertEqual(real_c3.MANIFEST_RELATIVE_PATH, MANIFEST_REL)
        self.assertEqual(real_c3.PROPOSAL_PATH, MANUAL / "c1" / "fixtures" / "proposal.tenant-alpha.json")

    def test_producer_hash_constant_equals_blob_content_at_base(self):
        blob = git("-C", str(REPO), "show", "%s:tests/manual_contract/c2_producer.py" % BASE, text=False)
        self.assertEqual(sha256(blob), C2_PRODUCER_SHA)
        self.assertEqual(real_c3.FROZEN["c2_producer_sha256"], sha256(blob))
        self.assertEqual(sha256((MANUAL / "c2_producer.py").read_bytes()), sha256(blob), "the working-tree producer is not the base file")
        self.assertEqual(git("-C", str(REPO), "rev-parse", BASE).strip(), BASE)

    def run_copy(self, mutate, name):
        tree = make_tree(self.tmp / name)
        mutate(tree)
        return run_runprobe(tree, ROOTS, self.tmp / (name + "-work"))

    def test_unaltered_copy_is_a_positive_control(self):
        out = self.run_copy(lambda tree: None, "control")
        self.assertIsNone(out["measure_raised"], out)
        self.assertIsNone(out["raised"], out)
        self.assertEqual(sorted(out["statuses"]), sorted((CASE_P1, CASE_N1, CASE_N3, CASE_N5)))
        self.assertEqual({v[0] for v in out["statuses"].values()}, {"PASS"})
        self.assertEqual(out["calls"]["produce"], 1)
        self.assertEqual(out["calls"]["replay"], 1)

    def assert_refused_before_any_call(self, out, cls_name, pattern):
        self.assertIsNone(out["measure_raised"], out)
        self.assertEqual(out["raised"][0], cls_name, out)
        self.assertRegex(out["raised"][2], pattern)
        self.assertEqual(out["calls"], {"produce": 0, "replay": 0, "pack": 0}, "producer, Replay and Pack must not run on an altered input")
        self.assertFalse(out["work_has_run"], "the producer must not have written a run")

    def test_altered_proposal_fixture_refused_before_producer_replay_or_pack(self):
        def mutate(tree):
            path = tree / "c1" / "fixtures" / "proposal.tenant-alpha.json"
            path.write_bytes(path.read_bytes() + b"\n")  # one byte: same JSON value, different file sha256
        self.assert_refused_before_any_call(self.run_copy(mutate, "prop"), "AdapterError", "proposal fixture sha256 differs from the frozen value")

    def test_altered_proposal_value_refused(self):
        def mutate(tree):
            path = tree / "c1" / "fixtures" / "proposal.tenant-alpha.json"
            path.write_bytes(path.read_bytes().replace(b"tenant-alpha", b"tenant-alphb", 1))
        self.assert_refused_before_any_call(self.run_copy(mutate, "propval"), "AdapterError", "proposal fixture sha256 differs")

    def test_modified_producer_refused_before_any_call(self):
        def mutate(tree):
            path = tree / "c2_producer.py"
            path.write_bytes(path.read_bytes() + b"\n# modified\n")
        self.assert_refused_before_any_call(self.run_copy(mutate, "prod"), "AdapterError", "c2_producer.py differs from the pinned C2 file")

    def test_altered_action_manifest_fixture_in_a_copy_of_the_root_refused(self):
        for variant in ("worktree", "committed"):
            with self.subTest(variant=variant):
                bad = self.clone("action_manifest", "fixture-" + variant)
                target = bad / MANIFEST_REL
                target.write_bytes(target.read_bytes() + b"\n")
                if variant == "committed":
                    git("-C", str(bad), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-am", "altered")
                work = self.tmp / ("am-work-" + variant)
                out = run_runprobe(MANUAL, self.roots_with("action_manifest", bad), work)
                self.assertEqual(out["measure_raised"][0], "SourceIdentityError", out)
                self.assertIn("AdapterError", out["measure_raised"][1])
                self.assertEqual(out["calls"], {"produce": 0, "replay": 0, "pack": 0})
                self.assertFalse(out["work_exists"], "no workdir after a failed source gate")
                self.assertEqual(out["component_modules"], [])

    def test_read_fixture_refuses_altered_bytes_before_parsing(self):
        src = (MANUAL / "c1" / "fixtures" / "proposal.tenant-alpha.json").read_bytes()
        tmp = self.tmp / "rf"
        tmp.mkdir()
        good = tmp / "good.json"
        good.write_bytes(src)
        data, obj = real_c3._read_fixture(good, PROPOSAL_SHA, "proposal")
        self.assertEqual(data, src, "the verified bytes are the parsed bytes")
        self.assertEqual(obj, strict_loads(src))
        altered = tmp / "altered.json"
        altered.write_bytes(src + b" ")
        with self.assertRaisesRegex(real_c3.AdapterError, "differs from the frozen value"):
            real_c3._read_fixture(altered, PROPOSAL_SHA, "proposal")
        with self.assertRaisesRegex(real_c3.AdapterError, "unreadable"):
            real_c3._read_fixture(tmp / "absent.json", PROPOSAL_SHA, "proposal")
        dup = tmp / "dup.json"
        dup.write_bytes(b'{"a": 1, "a": 2}')
        with self.assertRaisesRegex(real_c3.AdapterError, "not strict JSON"):
            real_c3._read_fixture(dup, sha256(b'{"a": 1, "a": 2}'), "proposal")

    def test_strict_loader_rejects_duplicate_keys_nan_and_malformed_input(self):
        for text in (b'{"a": 1, "a": 2}', b'{"a": {"b": 1, "b": 2}}', b'[{"k": 1, "k": 1}]', b'{"a": NaN}', b'{"a": Infinity}', b'{"a": -Infinity}',
                     b'\xef\xbb\xbf{}', b'\xff\xfe', b'{} trailing', b'', b'[' * 5000 + b']' * 5000):
            with self.subTest(text=text[:30]):
                with self.assertRaises(ValueError):
                    real_c3._strict_loads(text)
        self.assertEqual(real_c3._strict_loads(b'{"a": [1, 2.5, "x", null, true]}'), {"a": [1, 2.5, "x", None, True]})

    def test_strict_loader_needs_measured_components(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import real_c3\n"
                "try:\n    real_c3._strict_loads(b'{}')\nexcept real_c3.AdapterError as e:\n    print('REFUSED', e)")
        done = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(MANUAL)], capture_output=True, text=True, cwd=tempfile.gettempdir(), timeout=60)
        self.assertIn("REFUSED strict loader requires", done.stdout, done.stderr)


# ------------------------------------------------------------------------------------------------------------------------------
class BytePreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = shared()

    def test_persisted_bundle_bytes_hash_parse_and_pack_input_are_one_buffer(self):
        S, data = self.S, self.S.bundle_bytes
        ev = S.p1["bundle"]
        self.assertTrue(str(S.bundle_path.resolve()).startswith(str(S.work.resolve())), "the bundle lives in the run workdir")
        h1 = sha256(data)
        self.assertEqual(ev["H1_sha256_persisted_bytes"], h1)  # H1 = sha256 of the exact bytes on disk
        self.assertEqual(ev["size_bytes"], len(data))
        parsed = strict_loads(data)
        self.assertGreaterEqual(len(S.pack), 2)
        for call in S.pack[:2]:  # P1 import and its determinism re-import
            self.assertEqual(call["bundle"], parsed, "the Pack received exactly the parse of the persisted bytes")
            self.assertEqual(call["extra"], ((), {}))
        self.assertEqual(S.pack[0]["manifest"], strict_loads((ROOTS["action_manifest"] / MANIFEST_REL).read_bytes()))
        # the Pack's retained bundle is that same object value; the Pack's own canonical hash of it is H2
        h2 = h2_of(parsed)
        self.assertEqual(ev["H2_pack_canonical_sha256"], h2)
        self.assertEqual(S.p1["native_pack"]["input_artifacts"][1]["hash"], h2)
        self.assertEqual(S.PI.sha256(parsed), h2)
        # format of the single serialisation: sorted keys, indent 2, utf-8, one trailing newline, no BOM
        self.assertTrue(data.endswith(b"}\n") and not data.endswith(b"\n\n"))
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(data, (json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
        self.assertNotEqual(data, (json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)).encode("utf-8"))

    def test_bundle_serialised_and_written_exactly_once(self):
        S = self.S
        self.assertEqual(len(S.serialise), 1)
        self.assertEqual(S.serialise[0], S.bundle_bytes)
        self.assertEqual(S.dumps, [((), {"mode": "json"})], "the harness calls model_dump(mode='json') on the native bundle exactly once")
        writes = [w for w in S.writes if pathlib.Path(w[0]).name == "reconstruction-bundle.json"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][1], S.bundle_bytes)
        self.assertEqual([p for p in S.opens if "reconstruction-bundle" in p], [])
        bundles = [p for p in S.work.rglob("*") if "bundle" in p.name and p.is_file()]
        self.assertEqual(bundles, [S.bundle_path], "exactly one bundle file, no re-serialised copies")
        self.assertEqual(len(S.replay), 1, "Replay is imported exactly once; the bundle is never rebuilt")

    def test_bundle_id_and_generated_at_preserved_verbatim_from_the_native_bundle(self):
        S = self.S
        parsed = strict_loads(S.bundle_bytes)
        native = S.replay[0]["native_dump"]
        for member in ("bundle_id", "generated_at"):
            self.assertIn(member, parsed)
            self.assertEqual(parsed[member], native[member], member)
            self.assertIsInstance(parsed[member], str)
        self.assertEqual(parsed["bundle_id"], S.replay[0]["bundle"].bundle_id)
        self.assertEqual(S.p1["native_replay"]["bundle_id"], native["bundle_id"])
        self.assertEqual(parsed, native, "the persisted bundle equals the native bundle's own model_dump(mode='json'), member for member")

    def test_no_integrity_entry_attached_and_no_member_added_dropped_or_renamed(self):
        S = self.S
        parsed = strict_loads(S.bundle_bytes)
        native = S.replay[0]["native_dump"]
        self.assertEqual(parsed["integrity"], native["integrity"])
        self.assertEqual(parsed["integrity"], [], "no integrity entry is attached")
        self.assertEqual(set(parsed), set(native))
        # this file's own independent Replay import of the same persisted Control Plane record
        record = strict_loads(S.record_path.read_bytes())
        again = S.IMP.import_bounded_workflow(copy.deepcopy(record), proposal=parsed_proposal(), control_plane_revision=CP_SHA)
        mine = again.model_dump(mode="json")
        self.assertEqual(set(parsed), set(mine))
        per_import = {"bundle_id", "generated_at"}  # per-import by design (contract section 15, RB owner item 3)
        self.assertEqual({k: v for k, v in parsed.items() if k not in per_import}, {k: v for k, v in mine.items() if k not in per_import},
                         "no member added, dropped, renamed or rescored relative to an independent native import")
        self.assertEqual(S.p1["native_replay"]["status"], mine["status"])
        self.assertEqual(parsed["status"], "reconstruction_partial")

    def test_replay_received_the_persisted_record_the_proposal_and_the_measured_label(self):
        S = self.S
        call = S.replay[0]
        self.assertEqual(call["args"], ())
        self.assertEqual(set(call["kwargs"]), {"proposal", "control_plane_revision"})
        self.assertEqual(call["kwargs"]["control_plane_revision"], CP_SHA)
        self.assertEqual(call["kwargs"]["proposal"], parsed_proposal())
        self.assertEqual(call["record"], strict_loads(S.record_path.read_bytes()), "Replay received exactly the parse of the persisted record")

    def test_persisted_control_plane_record_is_unchanged(self):
        S = self.S
        data = S.record_path.read_bytes()
        self.assertEqual(S.p1["record"]["sha256"], sha256(data))
        self.assertEqual(S.p1["record"]["size_bytes"], len(data))
        self.assertEqual(sha256(json.dumps(strict_loads(data), sort_keys=True).encode()) == sha256(data), False, "stored form is the Control Plane store's own")
        self.assertEqual(S.p1["raw_record_to_bundle_linkage"]["cp_record_sha256"], sha256(data))
        self.assertEqual(S.p1["raw_record_to_bundle_linkage"]["bundle_H1"], sha256(S.bundle_bytes))
        self.assertIs(S.p1["raw_record_to_bundle_linkage"]["carried_by_pack"], False)
        self.assertEqual([w for w in S.writes if w[0] == str(S.record_path)], [], "the harness never writes the record")

    def test_pinned_trees_untouched_and_git_clean_after_run_all(self):
        S = self.S
        self.assertEqual(S.before, S.after)
        for key, status in S.git_status.items():
            self.assertEqual(status, "", key)
        roots = tuple(str(r) for r in ROOTS.values())
        for target, _ in S.writes:
            self.assertFalse(any(target == r or target.startswith(r + os.sep) for r in roots), "write into a pinned root: " + target)
        for target in S.opens:
            self.assertFalse(any(os.path.abspath(target).startswith(r + os.sep) for r in roots), "open for write in a pinned root: " + target)

    def test_h1_and_h2_are_distinct_names_and_values_and_never_conflated(self):
        S = self.S
        h1, h2 = sha256(S.bundle_bytes), h2_of(strict_loads(S.bundle_bytes))
        self.assertNotEqual(h1, h2)
        self.assertNotEqual("sha256:" + h1, h2)
        self.assertTrue(h2.startswith("sha256:") and not h1.startswith("sha256:"))
        b = S.p1["bundle"]
        self.assertIn("H1_sha256_persisted_bytes", b)
        self.assertIn("H2_pack_canonical_sha256", b)
        self.assertNotIn("sha256", b)
        self.assertNotIn("bundle_sha256", b)
        self.assertEqual(S.p1["limits"]["bundle_hash_semantics"],
                         "H1 = sha256 of the exact persisted bytes; H2 = the Pack's canonical-JSON sha256; never interchangeable")
        for cid, ev in S.results.items():
            for path, value in walk(ev):
                key = " ".join(str(p) for p in path if isinstance(p, str))
                if not isinstance(value, str) or "limits" in path:
                    continue
                if "mutated" in key:
                    continue
                if re.search(r"\bH1\b|H1_", key):
                    self.assertEqual(value, h1, "%s %s labelled H1 holds a different value" % (cid, key))
                if re.search(r"\bH2\b|H2_", key):
                    self.assertEqual(value, h2, "%s %s labelled H2 holds a different value" % (cid, key))
        # no H1 value appears under an H2 label and vice versa anywhere (including the mutated H2 of negatives)
        for cid, ev in S.results.items():
            for path, value in walk(ev):
                key = " ".join(str(p) for p in path if isinstance(p, str))
                if isinstance(value, str) and value == h1:
                    self.assertNotRegex(key, r"H2", "%s: H1 value under H2 label %s" % (cid, key))

    def test_pack_file_is_written_by_the_native_dumper_not_the_persisted_bundle(self):
        S = self.S
        pack_path = pathlib.Path(S.p1["native_pack"]["pack_path"])
        self.assertEqual(S.p1["native_pack"]["pack_file_sha256"], sha256(pack_path.read_bytes()))
        self.assertNotEqual(sha256(pack_path.read_bytes()), sha256(S.bundle_bytes))
        self.assertEqual(S.p1["native_pack"]["pack_file_sha256_of"], "file_bytes_as_written_by_native_dump")
        self.assertIsNot(S.p1["native_pack"]["pack_signed"], True, "the Pack is never reported signed")

    def test_retained_bundle_in_the_pack_equals_the_persisted_bundle(self):
        S = self.S
        pack_json = strict_loads(pathlib.Path(S.p1["native_pack"]["pack_path"]).read_bytes())
        retained = pack_json["metadata"]["traceable_import"]["retained_sources"]
        self.assertEqual(retained["reconstruction_bundle"], strict_loads(S.bundle_bytes))
        self.assertEqual(retained["manifest"], strict_loads((ROOTS["action_manifest"] / MANIFEST_REL).read_bytes()))
        self.assertEqual(set(retained), {"manifest", "reconstruction_bundle"}, "L19: no raw Control Plane record is retained by the Pack")


# ------------------------------------------------------------------------------------------------------------------------------
class LimitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = shared()

    def test_every_case_carries_the_complete_limits_block(self):
        self.assertEqual(sorted(self.S.results), sorted((CASE_P1, CASE_N1, CASE_N3, CASE_N5)))
        for cid, ev in self.S.results.items():
            with self.subTest(case=cid):
                lim = ev["limits"]
                self.assertEqual(set(lim), LIMIT_KEYS, "no limit key dropped or invented relative to the contract")
                self.assertEqual(lim, self.S.p1["limits"], "identical limits in every case")

    def test_l1_to_l19_non_empty_and_carry_their_key_phrases(self):
        lim = self.S.p1["limits"]
        self.assertEqual(sorted(k for k in lim if re.fullmatch(r"L\d+", k)), sorted("L%d" % n for n in range(1, 20)))
        for n, phrases in LIMIT_PHRASES.items():
            with self.subTest(limit="L%d" % n):
                text = lim["L%d" % n]
                self.assertIsInstance(text, str)
                self.assertTrue(text.strip())
                for phrase in phrases:
                    self.assertIn(phrase, text.lower(), "L%d lost its key phrase %r" % (n, phrase))

    def test_status_label_flags_and_hub_280(self):
        for cid, ev in self.S.results.items():
            lim = ev["limits"]
            self.assertEqual(lim["status"], LIMIT_STATUS, cid)
            self.assertIn("NOT_INDEPENDENTLY_QUALIFIED", lim["status"])
            for key, value in LIMIT_FLAGS.items():
                self.assertEqual(lim[key], value, "%s %s" % (cid, key))
                self.assertIs(type(lim[key]), type(value))
            self.assertIs(lim["non_authorizing"], True)
            self.assertIs(lim["effect_executed"], False)
            self.assertEqual(lim["hub_280_digest_basis"], "OPEN")
            self.assertEqual(ev["schema"], EVIDENCE_SCHEMA)

    def test_mandatory_statements(self):
        lim = {k: v.lower() for k, v in self.S.p1["limits"].items() if isinstance(v, str)}
        self.assertTrue(all(w in lim["L2"] for w in ("synthetic", "unauthenticated", "test-only")), "synthetic unauthenticated authority")
        self.assertTrue("reconstruction_partial" in lim["L1"] and "b004" in lim["L1"] and "never complete" in lim["L1"])
        self.assertIn("proposal-level only", lim["L3"])
        self.assertIn("event_decision_linkage not_established", lim["L3"])
        self.assertIn("no custody chain", lim["L8"])
        self.assertIn("no freshness", lim["L9"])
        self.assertTrue("provisional" in lim["L16"] and "unqualified" in lim["L16"], "provisional / unqualified Replay pin row")
        self.assertIn("unverified", lim["L18"])
        self.assertIn("constitution", lim["L18"])
        self.assertTrue("valid=true" in lim["L11"] and "not reviewer approval" in lim["L11"], "pack valid is not approval")
        self.assertIn("hold", lim["L17"])
        self.assertTrue(lim["bundle_hash_semantics"].find("never interchangeable") > 0)
        for item in ("bundle_id", "generated_at", "integrity"):
            self.assertIn(item, self.S.p1["limits"]["uncompared_by_pack"])
        self.assertEqual(len(self.S.p1["limits"]["known_limitations_not_oracles"]), 4)

    def test_p1_evidence_states_the_partial_zero_effect_non_approval_semantics(self):
        p1 = self.S.p1
        self.assertIs(p1["pack_valid_is_not_approval"], True)
        self.assertEqual(p1["destination"]["effect_count"], 0)
        self.assertEqual(p1["destination"]["effects"], {})
        self.assertEqual((p1["outcome"], p1["status"]), ("IMPORTED", "PASS"))
        self.assertEqual(p1["native_replay"]["status"], "reconstruction_partial")
        self.assertEqual(p1["native_pack"]["reconstruction_completeness"], "reconstruction_partial")
        self.assertEqual(p1["native_pack"]["lifecycle_summary"]["current_permission"], "not_evaluated_from_historical_records")
        self.assertEqual(p1["native_pack"]["lifecycle_summary"]["execution_attempted"], "no")
        self.assertEqual(p1["native_pack"]["review_status"], "draft")


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
                for pat, m in self.hits(value):
                    # the only tolerated carrier outside limits is the N3 mutation descriptor naming the FORGED status it injected
                    self.assertTrue(pat.startswith("reconstruction_complete") and "mutation" in path and cid == CASE_N3,
                                    "%s %s carries forbidden claim %r: %s" % (cid, "/".join(map(str, path)), pat, value[:120]))
        self.assertGreater(scanned, 200, "the scan must not be vacuous")

    def test_forbidden_claims_in_limit_texts_are_always_negated(self):
        seen = 0
        for key, text in self.S.p1["limits"].items():
            if not isinstance(text, str):
                continue
            low = text.lower()
            for pat, m in self.hits(text):
                seen += 1
                window = low[max(0, m.start() - 40):m.start() + len(m.group(0))]
                self.assertRegex(window, NEGATION, "limit %s states %r without a negation: %s" % (key, pat, text))
        self.assertGreaterEqual(seen, 1, "L17 must name 'independently qualified' in negated form")

    def test_the_claim_scan_detects_a_planted_positive_claim(self):
        for planted in ("the pack is approved", "this is certified", "production ready", "authenticated authority", "complete reconstruction",
                        "verified execution", "independently qualified"):
            self.assertTrue(self.hits(planted), planted)
        self.assertFalse(self.hits("unauthenticated authority"), "the word boundary keeps 'unauthenticated' out of the positive pattern")
        for negated in ("this is not production ready", "no production-ready claim"):
            for _, m in self.hits(negated):
                self.assertRegex(negated[:m.start() + 3], NEGATION)
        self.assertTrue(NEGATION.search("is not independently"))

    def test_no_result_vocabulary_promotes_the_import(self):
        for cid, ev in self.S.results.items():
            self.assertIn(ev["outcome"], ("IMPORTED", "REFUSED_NATIVE"), cid)
            self.assertIn(ev["status"], ("PASS", "FAIL"), cid)
        p1 = self.S.p1
        self.assertNotIn(p1["native_pack"]["outcome"], ("APPROVED", "ACCEPTED", "COMPLETE", "VERIFIED", "CERTIFIED"))
        self.assertNotIn(p1["native_replay"]["outcome"], ("APPROVED", "ACCEPTED", "COMPLETE", "VERIFIED", "CERTIFIED"))
        self.assertIsNot(p1["native_pack"]["pack_signed"], True)
        self.assertNotEqual(p1["native_pack"]["review_status"], "approved")
        self.assertFalse([w for _, w in walk(p1) if isinstance(w, str) and w in ("reconstruction_complete", "complete", "authenticated", "certified")])


# ------------------------------------------------------------------------------------------------------------------------------
HARNESS_TEXT = (MANUAL / "real_c3.py").read_text(encoding="utf-8")
FORBIDDEN_CALLS = {"execute", "reconcile", "apply", "system", "Popen", "urlopen", "connect", "exec", "eval", "check_output", "check_call",
                   "spawn", "popen", "fork"}
FORBIDDEN_IMPORTS = {"socket", "urllib", "http", "requests", "ssl", "ftplib", "smtplib", "telnetlib", "asyncio", "moltbot", "real_c1", "real_c2",
                     "runner", "mock_cases"}
WRITE_METHODS = {"write_bytes", "write_text", "mkdir", "unlink", "rmtree", "rename", "replace", "touch", "copy", "copytree", "move", "dump_evidence_pack", "open"}
ALLOWED_WRITE_RECEIVERS = {"bundle_path", "work", "pathlib.Path(args.out)", "P['pack_loader']"}  # run workdir, --out file, native pack dump (workdir)
READONLY_GIT = {"rev-parse", "ls-files", "status", "ls-tree"}


def c3_files():
    return [MANUAL / "real_c3.py", *sorted(HERE.glob("test_real_c3*.py"))]


class StaticGuardTests(unittest.TestCase):
    def trees(self):
        return {p.name: ast.parse(p.read_text(encoding="utf-8")) for p in c3_files()}

    def test_this_file_and_harness_exist(self):
        names = {p.name for p in c3_files()}
        self.assertIn("real_c3.py", names)
        self.assertIn("test_real_c3_integrity.py", names)

    def test_no_effect_call_names_in_harness_or_c3_tests(self):
        for fn, tree in self.trees().items():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                    self.assertNotIn(name, FORBIDDEN_CALLS, "%s calls %s" % (fn, name))
                    if name == "run":  # the only run() permitted is subprocess.run (checked separately)
                        self.assertTrue(isinstance(f, ast.Attribute) and ast.unparse(f.value) == "subprocess", "%s calls a run() that is not subprocess.run" % fn)

    def test_no_network_or_c1_c2_private_imports(self):
        for fn, tree in self.trees().items():
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                    for m in mods:
                        self.assertNotIn(m.split(".")[0].lower(), FORBIDDEN_IMPORTS, "%s imports %s" % (fn, m))
                if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in ("import_module", "__import__"):
                    self.assertNotRegex(ast.unparse(node), r"real_c[12]", fn)

    def test_harness_imports_only_the_public_c2_producer_symbol(self):
        tree = ast.parse(HARNESS_TEXT)
        local = {p.stem for p in MANUAL.glob("*.py")} - {"real_c3"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported & local, {"c2_producer"}, "only c2_producer may be imported from the manual_contract directory (D9)")
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "c2_producer"}
        self.assertLessEqual(attrs, {"produce", "CONFIG_ID", "__file__"}, "nothing private from c2_producer")
        self.assertIn("produce", attrs)
        self.assertNotRegex(HARNESS_TEXT, r"from\s+real_c[12]|import\s+real_c[12]|c2_producer\._(?!_file__)")

    def test_subprocess_in_harness_is_only_the_readonly_git_helper(self):
        tree = ast.parse(HARNESS_TEXT)
        runs = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and ast.unparse(n.func.value) == "subprocess"]
        self.assertEqual([n.func.attr for n in runs], ["run"], "exactly one subprocess call in the harness")
        argv = runs[0].args[0]
        self.assertIsInstance(argv, ast.List)
        self.assertEqual(ast.literal_eval(argv.elts[0]), "git")
        self.assertFalse([k for k in runs[0].keywords if k.arg == "shell"])
        git_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_git"]
        self.assertGreaterEqual(len(git_calls), 6)
        for n in git_calls:
            sub = [a for a in n.args[1:] if isinstance(a, ast.Constant)]
            self.assertTrue(sub and sub[0].value in READONLY_GIT, "non-read-only git subcommand: " + ast.unparse(n))
        self.assertIn('"GIT_OPTIONAL_LOCKS": "0"', HARNESS_TEXT)

    def test_subprocess_in_c3_tests_runs_only_git_or_the_interpreter(self):
        for p in sorted(HERE.glob("test_real_c3*.py")):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and ast.unparse(node.func.value) == "subprocess":
                    if not node.args or not isinstance(node.args[0], (ast.List, ast.Name)):
                        self.fail("%s: subprocess call with an unreadable argv: %s" % (p.name, ast.unparse(node)[:80]))
                    if isinstance(node.args[0], ast.List) and node.args[0].elts:
                        first = ast.unparse(node.args[0].elts[0])
                        self.assertIn(first, ("'git'", "sys.executable", "str(real_c3_path)"), "%s: subprocess argv starts with %s" % (p.name, first))
                    self.assertFalse([k for k in node.keywords if k.arg == "shell" and getattr(k.value, "value", True)])

    def test_harness_writes_only_into_the_workdir_or_the_out_file(self):
        tree = ast.parse(HARNESS_TEXT)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                if name in WRITE_METHODS:
                    receiver = ast.unparse(f.value) if isinstance(f, ast.Attribute) else "<builtin>"
                    found.append((name, receiver))
                    if name == "dump_evidence_pack":
                        self.assertEqual(ast.unparse(node.args[1]), "pack_path")
                    else:
                        self.assertIn(receiver, ALLOWED_WRITE_RECEIVERS, "write-capable call on %s.%s" % (receiver, name))
        self.assertTrue(found)
        self.assertNotIn("pack_path = ctx[\"measured\"]", HARNESS_TEXT)
        self.assertRegex(HARNESS_TEXT, r'pack_path = ctx\["work"\] / "evidence-pack.json"')
        self.assertRegex(HARNESS_TEXT, r'bundle_path = work / "reconstruction-bundle.json"')

    def test_harness_and_tests_never_enable_bytecode_writes_or_shell(self):
        self.assertIn("sys.dont_write_bytecode = True", HARNESS_TEXT)
        for p in sorted(HERE.glob("test_real_c3*.py")):
            self.assertTrue(p.read_text(encoding="utf-8").split('"""', 2)[2].lstrip().startswith("import sys\n\nsys.dont_write_bytecode = True"), p.name)

    def test_c1_c2_and_runner_files_are_byte_identical_to_base(self):
        listing = git("-C", str(REPO), "ls-tree", "-r", BASE, "--", "tests/manual_contract").splitlines()
        names = [line.split("\t", 1)[1] for line in listing]
        required = ("tests/manual_contract/real_c2.py", "tests/manual_contract/c2_producer.py", "tests/manual_contract/real_c1.py",
                    "tests/manual_contract/runner.py", "tests/manual_contract/c2/test_real_c2.py", "tests/manual_contract/c1/test_real_c1.py",
                    "tests/manual_contract/c1/fixtures/proposal.tenant-alpha.json")
        for r in required:
            self.assertIn(r, names)
        self.assertTrue(any(n.startswith("tests/manual_contract/c2/fixtures/") for n in names))
        for name in names:
            with self.subTest(path=name):
                self.assertTrue((REPO / name).is_file(), "deleted relative to base")
                self.assertEqual(git("-C", str(REPO), "hash-object", "--", name).strip(), git("-C", str(REPO), "rev-parse", "%s:%s" % (BASE, name)).strip())

    def test_no_github_file_is_modified_added_or_untracked(self):
        self.assertEqual(git("-C", str(REPO), "diff", "--name-only", BASE, "--", ".github").strip(), "")
        self.assertEqual(git("-C", str(REPO), "status", "--porcelain", "--untracked-files=all", "--", ".github").strip(), "")
        changed = set(git("-C", str(REPO), "diff", "--name-only", BASE).split())
        self.assertFalse([c for c in changed if c.startswith(".github/")], changed)

    def test_no_existing_tracked_file_is_modified_relative_to_base(self):
        changed = git("-C", str(REPO), "diff", "--name-only", "--diff-filter=MDRTUXB", BASE).split()  # everything except added files
        self.assertEqual(changed, [], "an existing file differs from the base")


# ------------------------------------------------------------------------------------------------------------------------------
class ApiShapeTests(unittest.TestCase):
    def test_public_surface_and_error_hierarchy(self):
        for name in ("run_all", "measure", "main", "AdapterError", "SourceIdentityError", "PINS", "FROZEN", "LIMITS", "ORACLE", "ENV",
                     "CASE_P1", "CASE_N1", "CASE_N3", "CASE_N5", "EVIDENCE_SCHEMA", "_check_modules", "_strict_loads", "_verify_git"):
            self.assertTrue(hasattr(real_c3, name), name)
        self.assertTrue(issubclass(real_c3.SourceIdentityError, real_c3.AdapterError))
        self.assertTrue(issubclass(real_c3.AdapterError, Exception))
        self.assertFalse(issubclass(real_c3.AdapterError, ValueError))
        self.assertFalse(hasattr(real_c3, "ImportContractError"), "a native refusal is never an AdapterError type")

    def test_case_ids_schema_and_allowlist_constants(self):
        self.assertEqual((real_c3.CASE_P1, real_c3.CASE_N1, real_c3.CASE_N3, real_c3.CASE_N5), (CASE_P1, CASE_N1, CASE_N3, CASE_N5))
        self.assertEqual(real_c3.EVIDENCE_SCHEMA, EVIDENCE_SCHEMA)
        self.assertEqual(set(shared().results), {CASE_P1, CASE_N1, CASE_N3, CASE_N5})

    def test_inputs_cannot_be_overridden_through_the_api(self):
        import inspect
        self.assertEqual(list(inspect.signature(real_c3.run_all).parameters), ["roots", "workdir"])
        self.assertEqual(list(inspect.signature(real_c3.measure).parameters), ["roots"])
        self.assertEqual(list(inspect.signature(real_c3.main).parameters), ["argv"])
        for fn in (real_c3.run_all, real_c3.measure, real_c3.main):
            self.assertFalse([p for p in inspect.signature(fn).parameters if re.search("proposal|manifest|label|bundle|revision", p, re.I)])

    def test_unknown_case_id_exit_code_2_in_process(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), mock.patch.object(real_c3, "run_all", side_effect=AssertionError("must not run")) as ra:
            rc = real_c3.main(["--case", "nope"])
        self.assertEqual(rc, 2)
        self.assertEqual(ra.call_count, 0)
        self.assertIn("not allowlisted", err.getvalue())
        for bad in ("", "c3_p1", "C3_P1_REPLAY_TO_PACK_PARTIAL", "all ", CASE_P1 + " ", "../" + CASE_P1):
            with self.subTest(case=bad), contextlib.redirect_stderr(io.StringIO()), mock.patch.object(real_c3, "run_all", side_effect=AssertionError("no")):
                self.assertEqual(real_c3.main(["--case", bad]), 2)

    def test_unknown_case_id_exit_code_2_subprocess_and_nothing_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, out = pathlib.Path(tmp) / "w", pathlib.Path(tmp) / "r.json"
            done = subprocess.run([sys.executable, "-I", "-B", str(MANUAL / "real_c3.py"), "--case", "nope", "--out", str(out), "--workdir", str(work)],
                                  capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")}, cwd=tempfile.gettempdir(), timeout=120)
            self.assertEqual(done.returncode, 2, done.stderr)
            self.assertFalse(work.exists() or out.exists())
            self.assertNotIn("Traceback", done.stderr)

    def test_good_single_case_run_exits_0_and_writes_one_passing_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "r.json"
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **{ENVS[k]: str(v) for k, v in ROOTS.items()}}
            done = subprocess.run([sys.executable, "-I", "-B", str(MANUAL / "real_c3.py"), "--case", CASE_N5, "--out", str(out),
                                   "--workdir", str(pathlib.Path(tmp) / "w")], capture_output=True, text=True, env=env, cwd=tempfile.gettempdir(), timeout=600)
            self.assertEqual(done.returncode, 0, done.stderr)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(list(result), [CASE_N5])
            self.assertEqual(result[CASE_N5]["case_id"], CASE_N5)
            self.assertEqual((result[CASE_N5]["status"], result[CASE_N5]["outcome"]), ("PASS", "REFUSED_NATIVE"))
            self.assertEqual(result[CASE_N5]["schema"], EVIDENCE_SCHEMA)
        for key, root in ROOTS.items():
            self.assertEqual(git("-C", str(root), "status", "--porcelain", "--ignored=matching", "--untracked-files=all"), "", key)

    def test_workdir_must_be_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "stale").write_text("x")
            with self.assertRaisesRegex(real_c3.AdapterError, "not empty"):
                real_c3._fresh_workdir(tmp)

    def test_native_refusal_is_distinct_from_adapter_error(self):
        S = shared()
        exc = S.IMP.ImportContractError("synthetic native message", code="synthetic_code")
        self.assertEqual(real_c3._native(exc), {"type": "ImportContractError", "message": "synthetic native message", "code": "synthetic_code"})
        self.assertFalse(isinstance(exc, real_c3.AdapterError))
        with mock.patch.object(S.IMP, "import_bounded_workflow", side_effect=RuntimeError("not a contract refusal")):
            with self.assertRaises(real_c3.AdapterError):
                real_c3._import_replay(S.IMP, {}, {}, CP_SHA)
        with mock.patch.object(S.PI, "import_manifest_reconstruction", side_effect=RuntimeError("not a contract refusal")):
            with self.assertRaises(real_c3.AdapterError):
                real_c3._import_pack({"pack_importer": S.PI}, {}, {})
        with mock.patch.object(S.IMP, "import_bounded_workflow", side_effect=exc):
            self.assertEqual(real_c3._import_replay(S.IMP, {}, {}, CP_SHA), (None, real_c3._native(exc)))
        with self.assertRaisesRegex(real_c3.AdapterError, "proposal is mandatory"):
            real_c3._import_replay(S.IMP, {}, None, CP_SHA)


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
