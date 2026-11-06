"""Builds a REAL hosted-style C3 evidence directory by running the actual harness (test helper for test_c3_hosted_check.py).

Test-only and developer-scope. Nothing here is qualification evidence. The pristine run mirrors the hosted job:
  clone of the orchestrator (full history) + clean --no-hardlinks copies of the four pinned components -> checker `verify`
  -> the two focused C3 suites (real, 26 + 76 tests) -> ONE harness run (--case all) -> the four retained native files
  -> checker `check`.
Every subprocess runs `python -I -B` with an explicit minimal environment. The pinned scratch clones named by the COGNOUS_C3_*
environment variables are only ever READ (git clone source); nothing is written into them.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

REPO = pathlib.Path(__file__).resolve().parents[3]
CHECKER_REL = ".github/scripts/c3_hosted_check.py"
CHECKER = REPO / CHECKER_REL
CASE_ID = "c3_p1_n1_n3_n5_hosted_group"
ROOT_ENV = {"control_plane": "COGNOUS_C3_CONTROL_PLANE_ROOT", "replay_bundle": "COGNOUS_C3_REPLAY_BUNDLE_ROOT",
            "evidence_pack": "COGNOUS_C3_EVIDENCE_PACK_ROOT", "action_manifest": "COGNOUS_C3_ACTION_MANIFEST_ROOT"}
# Restated independently of the checker and the harness (frozen contract, Hub #273 6671327666 / 6671384213).
PINS = {
    "control_plane": ("484fdbd297235dd24148ddb0703f2055a31eabff", "c182939882103015f12c5360fccf377c54e2c4f9", "C3_CP"),
    "replay_bundle": ("93a76e281fcae6a65d2cd1d35376f87442dafb95", "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f", "C3_RB"),
    "evidence_pack": ("065150852cc2a8abeb748777bb69d72ccd0e03d8", "fe428a89da2e74346648cdfe014462ddc8624c77", "C3_PACK"),
    "action_manifest": ("fa170815ef96a54c233d0dd9da821b60debabf8b", "3b0e3772e944aa668c8f4b879588c7cc3e2c32be", "C3_AM"),
}
RAW_FILES = ("sources.txt", "context.json", "tests.log", "tests.json", "cases.json", "c3.result.json", "c3.native-records.json",
             "c3.native-destination.json", "c3.reconstruction-bundle.json", "c3.evidence-pack.json")
SUITES = (("test_real_c3.py", 26), ("test_real_c3_integrity.py", 76))
CASES_CMD = "python -I -B tests/manual_contract/real_c3.py --case all --workdir <fresh>/c3 --out <evidence>/c3.result.json"
_GIT_ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"}


class FixtureError(AssertionError):
    """The test environment is not usable. This is a failure, never a skip."""


def required_roots():
    out = {}
    for key, name in ROOT_ENV.items():
        value = os.environ.get(name, "")
        if not value or not os.path.isdir(value):
            raise FixtureError("%s is unset or not a directory (the C3 hosted checker tests require the four pinned component roots)" % name)
        out[key] = pathlib.Path(value).resolve()
    return out


def git(cwd, *args, check=True):
    done = subprocess.run(["git", "-C", str(cwd), *args], env=_GIT_ENV, capture_output=True, text=True, timeout=300, check=False)
    if check and done.returncode != 0:
        raise FixtureError("git %s failed in %s: %s" % (args[0], cwd, done.stderr.strip()[:300]))
    return done.stdout.strip()


def minimal_env(ws, roots, ev, work, head, **overrides):
    """The explicit environment the hosted job gives the checker (no inherited variables besides PATH)."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "HOME": "/nonexistent",
           "GITHUB_WORKSPACE": str(ws), "GITHUB_SHA": head, "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
           "GITHUB_WORKFLOW": "manual-contract-edge", "GITHUB_RUN_ID": "1000", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY": "cogno-us/cognous-stack-orchestrator",
           "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64", "CASE_ID": CASE_ID, "EVIDENCE_DIR": str(ev), "WORK_ROOT": str(work),
           "PIP_VERSION_TEXT": "pip (test)"}
    for key, (sha, tree, prefix) in PINS.items():
        env[prefix + "_SHA"], env[prefix + "_TREE"] = sha, tree
        env[ROOT_ENV[key]] = str(roots[key])
    for k, v in overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return env


def run_py(args, env, cwd, timeout=900):
    return subprocess.run([sys.executable, "-I", "-B", *args], env=env, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False)


class CheckRun:
    """Result of one checker invocation plus the artifacts it left behind."""

    def __init__(self, proc, ev):
        self.rc, self.stdout, self.stderr, self.ev = proc.returncode, proc.stdout, proc.stderr, pathlib.Path(ev)
        self.oracle = self._read("oracle.txt")
        self.fails = [ln for ln in self.oracle.splitlines() if ln.startswith("FAIL")]
        try:
            self.manifest = json.loads((self.ev / "evidence-manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.manifest = None

    def _read(self, name):
        try:
            return (self.ev / name).read_text(encoding="utf-8")
        except OSError:
            return ""

    def describe(self):
        return "rc=%s\nstderr=%s\nFAIL lines:\n%s" % (self.rc, self.stderr[-800:], "\n".join(self.fails[:12]))


class Pristine:
    """One fully built, passing evidence directory (and the workspace / component copies that produced it)."""

    def __init__(self):
        self.roots_src = required_roots()
        self.base = pathlib.Path(tempfile.mkdtemp(prefix="c3-hosted-test-"))
        self.ws = self.base / "ws"
        self.comp = {}
        self.ev = self.base / "evidence"
        self.work = self.base / "work"
        self.build()

    # -- workspace / components
    def make_workspace(self, dest):
        git(self.base, "clone", "-q", "--no-hardlinks", str(REPO), str(dest))
        shutil.copyfile(CHECKER, dest / CHECKER_REL)  # the live checker, even if not yet committed in the source repository
        git(dest, "config", "user.email", "t@example.invalid")
        git(dest, "config", "user.name", "t")
        if git(dest, "status", "--porcelain", "--untracked-files=all"):
            git(dest, "add", "-A")
            git(dest, "commit", "-q", "-m", "test workspace")
        return git(dest, "rev-parse", "HEAD")

    def clone_components(self, dest):
        out = {}
        for key, src in self.roots_src.items():
            target = dest / key
            git(self.base, "clone", "-q", "--no-hardlinks", "--no-checkout", str(src), str(target))
            git(target, "checkout", "-q", "--detach", PINS[key][0])
            out[key] = target.resolve()
        return out

    def env(self, ev=None, roots=None, ws=None, head=None, **overrides):
        return minimal_env(ws or self.ws, roots or self.comp, ev or self.ev, self.work, head or self.head, **overrides)

    def checker(self, sub, env, ws=None):
        ws = ws or self.ws
        return run_py([CHECKER_REL, sub], env, ws)

    def build(self):
        self.head = self.make_workspace(self.ws)
        self.comp = self.clone_components(self.base / "comp")
        self.ev.mkdir()
        env = self.env()
        v = self.checker("verify", env)
        if v.returncode != 0:
            raise FixtureError("pristine verify failed (the locked dependency set must be installed): %s" % v.stderr[-600:])
        # focused suites (real): exactly what the hosted job runs
        suites, log = [], []
        req = []
        for name in ROOT_ENV.values():
            req += ["--require-env", name]
        for pattern, expected in SUITES:
            p = run_py([".github/scripts/run_unittest_no_skips.py", "tests/manual_contract/c3", "--pattern", pattern, *req], env, self.ws)
            text = (p.stdout or "") + (p.stderr or "")
            log.append(text)
            observed = None
            for ln in text.splitlines():
                if ln.startswith("Ran ") and " test" in ln:
                    observed = int(ln.split()[1])
            suites.append({"pattern": pattern, "command": "run_unittest_no_skips.py tests/manual_contract/c3 --pattern " + pattern,
                           "exit_code": p.returncode, "expected_tests": expected, "observed_tests": observed})
        (self.ev / "tests.log").write_text("".join(log), encoding="utf-8")
        ok = all(s["exit_code"] == 0 and s["observed_tests"] == s["expected_tests"] for s in suites)
        (self.ev / "tests.json").write_text(json.dumps({"suites": suites, "outcome": "PASSED" if ok else "FAILED"}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not ok:
            raise FixtureError("the real focused suites did not pass with the expected counts: %s" % json.dumps(suites))
        # one harness invocation
        h = run_py(["tests/manual_contract/real_c3.py", "--case", "all", "--workdir", str(self.work / "c3"), "--out", str(self.ev / "c3.result.json")], env, self.ws)
        (self.ev / "cases.json").write_text(json.dumps({"exit_code": h.returncode, "command": CASES_CMD}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if h.returncode != 0:
            raise FixtureError("the real harness failed: %s" % (h.stderr or h.stdout)[-600:])
        for src, dst in (("run/run.json", "c3.native-records.json"), ("run/destination.json", "c3.native-destination.json"),
                         ("reconstruction-bundle.json", "c3.reconstruction-bundle.json"), ("evidence-pack.json", "c3.evidence-pack.json")):
            shutil.copyfile(self.work / "c3" / src, self.ev / dst)
        run = self.run_check(self.ev)
        if run.rc != 0 or not run.manifest or run.manifest.get("verdict") != "PASS":
            raise FixtureError("the positive control (check on the pristine evidence) did not pass:\n" + run.describe())

    # -- check on a copy of the pristine evidence
    def run_check(self, ev, **overrides):
        return CheckRun(self.checker("check", self.env(ev=ev, **overrides)), ev)

    def mutated(self, mutate, **overrides):
        """Copy the pristine evidence, drop the checker outputs, apply ONE mutation(evdir), run `check`."""
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="mut-", dir=str(self.base)))
        ev = tmp / "evidence"
        shutil.copytree(self.ev, ev)
        for name in ("oracle.txt", "evidence-manifest.json", "p1.result.json", "n1-ten.result.json", "n3.result.json", "n5-rev.result.json",
                     "p1.pack-validation-report.json", "limits-L1-L19.json"):
            (ev / name).unlink(missing_ok=True)
        mutate(ev)
        return self.run_check(ev, **overrides)

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)


_CACHE = {}


def pristine():
    """Build the pristine evidence once per test process."""
    if "p" not in _CACHE:
        _CACHE["p"] = Pristine()
    return _CACHE["p"]


def drop_cache():
    p = _CACHE.pop("p", None)
    if p is not None:
        p.cleanup()


# ---- small mutation helpers
def read_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def write_json(path, obj):
    pathlib.Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
