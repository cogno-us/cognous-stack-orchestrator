"""Mutation tests for the hosted C3 checker `.github/scripts/c3_hosted_check.py` (verify | check | summary).

Test-only, developer-scope; NOT qualification evidence. The checker is exercised only as a subprocess (`python -I -B`) with an explicit
minimal environment. One REAL pristine evidence directory is built once (c3_hosted_fixtures.pristine(): the real focused suites, one real
harness run, the four retained native files, then `check` = the positive control, which must exit 0 with manifest verdict PASS). Each mutation
test copies that directory, applies exactly ONE mutation, runs the checker and asserts (a) exit 1, (b) the intended NAMED check is among the
failing lines and no unrelated check fails, (c) the oracle and manifest were still written (failed artifacts are retained), (d) no traceback.
The four pinned component roots are REQUIRED from COGNOUS_C3_* (a missing root is a failure, never a skip). The interpreter running these
tests must have the hash-locked dependency set installed (the checker's `verify` compares versions with the lock, as the hosted job does).

Documented limits (not asserted as failures): the checker re-observes everything from the retained files and compares with restated
literals, but it has no independent anchor for the evidence directory itself. A wholesale, internally consistent fabrication of the whole set
(result, Pack dump, bundle, record, destination, hashes) that happens to match every literal is indistinguishable from a real run without
re-running the harness; per-run values (record sha256, bundle id, Pack id, decision id) are never golden. A forged NONZERO Pack count with a
consistently updated file hash IS detected (the count is read from the Pack file, not from the hash).
"""
import ast
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import c3_hosted_fixtures as F  # noqa: E402

CHECKER = F.CHECKER
THIS = pathlib.Path(__file__).resolve()
P1, N1, N3, N5 = "c3_p1_replay_to_pack_partial", "c3_n1_ten_tenant_tamper", "c3_n3_partial_as_complete", "c3_n5_rev_wrong_revision"
CASES = (P1, N1, N3, N5)
ZERO_KEYS = ("control_plane_attempt_count", "executor_attempt_count", "attempt_transition_record_count", "destination_effect_count",
             "effect_observation_count", "reconciliation_count")
INPUTS = ("tests.json", "cases.json", "tests.log", "c3.result.json", "c3.native-records.json", "c3.native-destination.json",
          "c3.reconstruction-bundle.json", "c3.evidence-pack.json")
FOUND = ("sources.txt", "context.json")
NATIVE = ("c3.native-records.json", "c3.native-destination.json", "c3.reconstruction-bundle.json", "c3.evidence-pack.json")
N1_MSG = "pinned Replay semantic validation failed: decisions[0].binding.tenant_id conflicts with committed operation"
N3_MSG = "pinned Replay semantic validation failed unexpectedly: retained Replay status differs from accepted reconstruction"
N5_MSG = "producer_profiles[0].revision for cogno-us/cognous-agent-control-plane conflicts with pinned supported revision"


def setUpModule():
    F.pristine()  # built once for the whole module; a failure here fails every test (never a skip)


def tearDownModule():
    F.drop_cache()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def trace_free(test, run):
    test.assertNotIn("Traceback", run.stderr + run.stdout)


def traced(test, run):
    trace_free(test, run)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.P = F.pristine()

    # ---- assertions
    def assert_cause(self, run, must, allow=()):
        """exit 1, retained artifacts, every `must` substring appears in a FAIL line, and every FAIL line carries a must/allow substring."""
        msg = run.describe()
        self.assertEqual(run.rc, 1, msg)
        trace_free(self, run)
        self.assertTrue(run.oracle.strip(), "oracle.txt was not written\n" + msg)
        self.assertIsNotNone(run.manifest, "evidence-manifest.json was not written\n" + msg)
        self.assertEqual(run.manifest.get("verdict"), "FAIL", msg)
        self.assertEqual(run.manifest.get("failed"), len(run.fails), msg)
        self.assertGreaterEqual(len(run.fails), 1, msg)
        for needle in must:
            self.assertTrue(any(needle in ln for ln in run.fails), "no FAIL line names %r\n%s" % (needle, msg))
        for ln in run.fails:
            self.assertTrue(any(n in ln for n in tuple(must) + tuple(allow)), "unrelated FAIL line: %s\n%s" % (ln[:200], msg))
        # the retained manifest index equals the files left on disk (a failed run is still tamper-evident)
        for name, digest in run.manifest["evidence_file_sha256"].items():
            self.assertEqual(sha((run.ev / name).read_bytes()), digest, name)

    def verify(self, ws=None, roots=None, head=None, **overrides):
        """Run `verify` into a fresh evidence dir; returns (proc, ev)."""
        ev = pathlib.Path(tempfile.mkdtemp(prefix="ver-", dir=str(self.P.base))) / "evidence"
        proc = self.P.checker("verify", self.P.env(ev=ev, roots=roots, ws=ws, head=head, **overrides), ws=ws)
        return proc, ev

    def assert_verify_fails(self, proc, ev, must, allow=()):
        err = "rc=%s\n%s" % (proc.returncode, proc.stderr[-1200:])
        self.assertEqual(proc.returncode, 1, err)
        self.assertNotIn("Traceback", proc.stderr, err)
        self.assertTrue((ev / "sources.txt").is_file() and (ev / "context.json").is_file(), "failed verify must still write its artifacts")
        ctx = F.read_json(ev / "context.json")
        self.assertEqual(ctx["verify"], "FAIL")
        failures = ctx["verify_failures"]
        self.assertTrue(failures, err)
        for needle in must:
            self.assertTrue(any(needle in f for f in failures), "no verify failure names %r: %s" % (needle, failures))
        for f in failures:
            self.assertTrue(any(n in f for n in tuple(must) + tuple(allow)), "unrelated verify failure: %s" % f)
        self.assertIn("SOURCE VERIFICATION FAILED", (ev / "sources.txt").read_text(encoding="utf-8"))

    # ---- mutation helpers
    def res(self, fn):
        def m(ev):
            r = F.read_json(ev / "c3.result.json")
            fn(r)
            F.write_json(ev / "c3.result.json", r)
        return m

    def pack(self, fn, coherent=True):
        """Edit the retained Pack dump; coherent=True also updates the sha256 the result reports (so only the independent check can fail)."""
        def m(ev):
            d = F.read_json(ev / "c3.evidence-pack.json")
            fn(d)
            F.write_json(ev / "c3.evidence-pack.json", d)
            if coherent:
                r = F.read_json(ev / "c3.result.json")
                r[P1]["native_pack"]["pack_file_sha256"] = sha((ev / "c3.evidence-pack.json").read_bytes())
                F.write_json(ev / "c3.result.json", r)
        return m

    def run_mut(self, mutate, **overrides):
        return self.P.mutated(mutate, **overrides)


def entry(r, case, variant=False):
    e = r[case]
    return e["variant_b"] if variant else e


def dcounts(d):
    return d["metadata"]["traceable_import"]["derived_counts"]


# ======================================================================================= positive control and verify
class PositiveControlTests(Base):
    def test_pristine_check_passes_and_manifest_is_consistent(self):
        run = self.P.run_check(self.P.ev)
        self.assertEqual(run.rc, 0, run.describe())
        self.assertEqual(run.fails, [])
        m = run.manifest
        self.assertEqual((m["verdict"], m["failed"]), ("PASS", 0))
        self.assertEqual(m["check_count"], len(run.oracle.strip().splitlines()) - 1)
        self.assertEqual(m["qualification"], "NOT independent qualification; hosted developer evidence only")
        for name, digest in m["evidence_file_sha256"].items():
            self.assertEqual(sha((self.P.ev / name).read_bytes()), digest, name)
        for name in ("p1.result.json", "n1-ten.result.json", "n3.result.json", "n5-rev.result.json", "p1.pack-validation-report.json",
                     "limits-L1-L19.json", "c3.result.json", "c3.evidence-pack.json", "sources.txt", "context.json"):
            self.assertIn(name, m["evidence_file_sha256"])

    def test_pristine_inputs_are_the_real_counts(self):
        tj = F.read_json(self.P.ev / "tests.json")
        self.assertEqual([(s["pattern"], s["expected_tests"], s["observed_tests"], s["exit_code"]) for s in tj["suites"]],
                         [("test_real_c3.py", 26, 26, 0), ("test_real_c3_integrity.py", 76, 76, 0)])
        self.assertEqual(F.read_json(self.P.ev / "cases.json")["exit_code"], 0)
        self.assertEqual(sorted(F.read_json(self.P.ev / "c3.result.json")), sorted(CASES))

    def test_pristine_verify_passes(self):
        proc, ev = self.verify()
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        self.assertEqual(F.read_json(ev / "context.json")["verify"], "PASS")

    def test_clean_component_copies_pass_verify(self):
        roots = self.P.clone_components(pathlib.Path(tempfile.mkdtemp(prefix="cc-", dir=str(self.P.base))))
        proc, ev = self.verify(roots=roots)
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])


class VerifyContextTests(Base):
    def test_wrong_github_ref(self):
        for ref in ("refs/heads/o0c-c3/hosted-validation-prep", "refs/tags/v1", "refs/pull/1/merge", "main", ""):
            with self.subTest(ref=ref):
                proc, ev = self.verify(GITHUB_REF=ref)
                self.assert_verify_fails(proc, ev, ["dispatched ref"])

    def test_missing_github_ref(self):
        proc, ev = self.verify(GITHUB_REF=None)
        self.assert_verify_fails(proc, ev, ["dispatched ref"])

    def test_wrong_event(self):
        for event in ("push", "pull_request", "schedule", "workflow_run", "pull_request_target", ""):
            with self.subTest(event=event):
                proc, ev = self.verify(GITHUB_EVENT_NAME=event)
                self.assert_verify_fails(proc, ev, ["not workflow_dispatch"])

    def test_wrong_or_unauthorized_case_id(self):
        for case in ("c2_p1_n1_n2_hosted_group", "c3_p1_replay_to_pack_partial", "all", "c3_p1_n1_n3_n5_hosted_group ", "C3_P1_N1_N3_N5_HOSTED_GROUP", ""):
            with self.subTest(case=case):
                proc, ev = self.verify(CASE_ID=case)
                self.assert_verify_fails(proc, ev, ["is not the C3 hosted group"])
        proc, ev = self.verify(CASE_ID=None)
        self.assert_verify_fails(proc, ev, ["is not the C3 hosted group"])

    def test_github_sha_differs_from_orchestrator_head(self):
        for sha_ in ("0" * 40, "716f3247a93fe5b9fcda5aa430412de0aeecfef1", "", "HEAD"):
            with self.subTest(sha=sha_):
                proc, ev = self.verify(GITHUB_SHA=sha_)
                self.assert_verify_fails(proc, ev, ["!= GITHUB_SHA"])
        proc, ev = self.verify(GITHUB_SHA=None)
        self.assert_verify_fails(proc, ev, ["!= GITHUB_SHA"])

    def test_env_pin_drift_for_each_component_sha_and_tree(self):
        for key, (want_sha, want_tree, prefix) in F.PINS.items():
            for suffix, want in (("_SHA", want_sha), ("_TREE", want_tree)):
                for bad in ("0" * 40, want[:-1] + ("0" if want[-1] != "0" else "1"), ""):
                    with self.subTest(key=key, var=prefix + suffix, bad=bad[:8]):
                        proc, ev = self.verify(**{prefix + suffix: bad})
                        self.assert_verify_fails(proc, ev, ["%s: workflow pin %s_SHA/%s_TREE differs" % (key, prefix, prefix)])
        # unset
        proc, ev = self.verify(C3_PACK_SHA=None)
        self.assert_verify_fails(proc, ev, ["evidence_pack: workflow pin"])

    def test_component_root_unset_or_wrong_path(self):
        for key, env in F.ROOT_ENV.items():
            with self.subTest(key=key):
                proc, ev = self.verify(**{env: None})
                self.assert_verify_fails(proc, ev, ["%s: %s is not set" % (key, env)], allow=["fixture action_manifest_fixture"])
        proc, ev = self.verify(COGNOUS_C3_CONTROL_PLANE_ROOT=str(self.P.base / "nope"))
        self.assert_verify_fails(proc, ev, ["control_plane"])

    def test_verify_does_not_import_component_code(self):
        # verify reads git state only: no component package is imported or put on sys.path by the checker
        tree = ast.parse(CHECKER.read_text(encoding="utf-8"))
        imported = _imports(tree)
        self.assertFalse({n for n in imported if n.startswith(("agent_", "moltbot", "tests"))})
        text = CHECKER.read_text(encoding="utf-8")
        for banned in ("sys.path", "import_module", "__import__", "runpy", "importlib.util"):
            self.assertNotIn(banned, text)


class VerifyCheckoutTests(Base):
    """Actual component checkouts (clones under a temp dir); the pinned scratch clones are never modified."""

    def comp_roots(self, key):
        base = pathlib.Path(tempfile.mkdtemp(prefix="cc-", dir=str(self.P.base)))
        roots = dict(self.P.comp)
        roots[key] = self.P.clone_components(base)[key]
        return roots

    def first_tracked(self, root):
        return F.git(root, "ls-files").splitlines()[0]

    def test_wrong_head_same_tree_each_component(self):
        for key in F.PINS:
            with self.subTest(key=key):
                roots = self.comp_roots(key)
                F.git(roots[key], "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x")
                proc, ev = self.verify(roots=roots)
                self.assert_verify_fails(proc, ev, ["%s HEAD is" % key])

    def test_wrong_head_and_tree_each_component(self):
        for key in F.PINS:
            with self.subTest(key=key):
                roots = self.comp_roots(key)
                rel = self.first_tracked(roots[key])
                (roots[key] / rel).write_text("changed\n", encoding="utf-8")
                F.git(roots[key], "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-am", "x")
                proc, ev = self.verify(roots=roots)
                self.assert_verify_fails(proc, ev, ["%s HEAD is" % key])

    def test_dirty_modified_tracked_file(self):
        for key in F.PINS:
            with self.subTest(key=key):
                roots = self.comp_roots(key)
                rel = self.first_tracked(roots[key])
                with open(roots[key] / rel, "ab") as fh:
                    fh.write(b"\n# dirty\n")
                proc, ev = self.verify(roots=roots)
                self.assert_verify_fails(proc, ev, ["%s working tree is not clean" % key], allow=["fixture action_manifest_fixture"])

    def test_dirty_untracked_file(self):
        for key in F.PINS:
            with self.subTest(key=key):
                roots = self.comp_roots(key)
                (roots[key] / "untracked-new-file.txt").write_text("x\n", encoding="utf-8")
                proc, ev = self.verify(roots=roots)
                self.assert_verify_fails(proc, ev, ["%s working tree is not clean" % key])

    def test_dirty_ignored_file(self):
        for key in F.PINS:
            with self.subTest(key=key):
                roots = self.comp_roots(key)
                (roots[key] / ".git" / "info" / "exclude").write_text("hidden-ignored.bin\n", encoding="utf-8")
                (roots[key] / "hidden-ignored.bin").write_text("x\n", encoding="utf-8")
                self.assertEqual(F.git(roots[key], "status", "--porcelain"), "")  # invisible to a plain status: only --ignored sees it
                proc, ev = self.verify(roots=roots)
                self.assert_verify_fails(proc, ev, ["%s working tree is not clean" % key])

    def test_assume_unchanged_and_skip_worktree_tags(self):
        for flag, tag in (("--assume-unchanged", "h"), ("--skip-worktree", "S")):
            for key in F.PINS:
                with self.subTest(flag=flag, key=key):
                    roots = self.comp_roots(key)
                    rel = self.first_tracked(roots[key])
                    with open(roots[key] / rel, "ab") as fh:
                        fh.write(b"\n# hidden modification\n")
                    F.git(roots[key], "update-index", flag, rel)
                    self.assertEqual(F.git(roots[key], "status", "--porcelain"), "")  # the modification is hidden from status
                    proc, ev = self.verify(roots=roots)
                    self.assert_verify_fails(proc, ev, ["%s has tracked files with a tag other than H" % key], allow=["fixture action_manifest_fixture"])

    def test_component_root_not_toplevel(self):
        roots = self.comp_roots("control_plane")
        sub = roots["control_plane"] / "subdir-not-top"
        sub.mkdir()
        roots["control_plane"] = sub
        proc, ev = self.verify(roots=roots)
        self.assert_verify_fails(proc, ev, ["control_plane"])

    def test_orchestrator_modified_tracked_file(self):
        ws = self.P.base / "ws-dirty"
        head = self.P.make_workspace(ws)
        with open(ws / "README.md", "ab") as fh:
            fh.write(b"\ndirty\n")
        proc, ev = self.verify(ws=ws, head=head)
        self.assert_verify_fails(proc, ev, ["orchestrator checkout has modified tracked files"])


class VerifyFixtureTests(Base):
    def edited_workspace(self, name, edit):
        ws = self.P.base / name
        self.P.make_workspace(ws)
        edit(ws)
        F.git(ws, "add", "-A")
        F.git(ws, "commit", "-q", "-m", "edit")
        return ws, F.git(ws, "rev-parse", "HEAD")

    def test_altered_proposal_fixture(self):
        ws, head = self.edited_workspace("ws-prop", lambda w: (w / "tests/manual_contract/c1/fixtures/proposal.tenant-alpha.json").write_bytes(b"{}\n"))
        proc, ev = self.verify(ws=ws, head=head)
        self.assert_verify_fails(proc, ev, ["fixture tests/manual_contract/c1/fixtures/proposal.tenant-alpha.json sha256"])

    def test_missing_proposal_fixture(self):
        ws, head = self.edited_workspace("ws-noprop", lambda w: (w / "tests/manual_contract/c1/fixtures/proposal.tenant-alpha.json").unlink())
        proc, ev = self.verify(ws=ws, head=head)
        self.assert_verify_fails(proc, ev, ["fixture proposal"])

    def test_altered_action_manifest_fixture(self):
        roots = dict(self.P.comp)
        base = pathlib.Path(tempfile.mkdtemp(prefix="cc-", dir=str(self.P.base)))
        roots["action_manifest"] = self.P.clone_components(base)["action_manifest"]
        path = roots["action_manifest"] / "examples/refund_integration_v1_1.manifest.json"
        path.write_bytes(path.read_bytes() + b" ")
        proc, ev = self.verify(roots=roots)
        self.assert_verify_fails(proc, ev, ["fixture examples/refund_integration_v1_1.manifest.json sha256", "action_manifest working tree is not clean"])

    def test_missing_action_manifest_fixture(self):
        roots = dict(self.P.comp)
        base = pathlib.Path(tempfile.mkdtemp(prefix="cc-", dir=str(self.P.base)))
        roots["action_manifest"] = self.P.clone_components(base)["action_manifest"]
        (roots["action_manifest"] / "examples/refund_integration_v1_1.manifest.json").unlink()
        proc, ev = self.verify(roots=roots)
        self.assert_verify_fails(proc, ev, ["fixture action_manifest_fixture", "action_manifest working tree is not clean"])

    def test_altered_c2_producer_hash(self):
        ws, head = self.edited_workspace("ws-c2p", lambda w: (w / "tests/manual_contract/c2_producer.py").write_bytes(
            (w / "tests/manual_contract/c2_producer.py").read_bytes() + b"\n# altered\n"))
        proc, ev = self.verify(ws=ws, head=head)
        self.assert_verify_fails(proc, ev, ["c2_producer.py sha256"])

    def test_missing_hosted_source_file(self):
        ws, head = self.edited_workspace("ws-nolock", lambda w: (w / ".github/locks/cryptography-pydantic-pytest-513753.txt").unlink())
        proc, ev = self.verify(ws=ws, head=head)
        self.assert_verify_fails(proc, ev, ["host source .github/locks/cryptography-pydantic-pytest-513753.txt is missing"])


class VerifyDependencyTests(Base):
    def test_missing_dependency_pydantic_absent(self):
        venv = self.P.base / "venv-nodeps"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, capture_output=True, timeout=300)
        py = venv / "bin" / "python"
        probe = subprocess.run([str(py), "-I", "-c", "import importlib.metadata as m,sys\ntry:\n m.version('pydantic');sys.exit(1)\nexcept m.PackageNotFoundError:\n sys.exit(0)"])
        self.assertEqual(probe.returncode, 0, "the no-dependency interpreter unexpectedly has pydantic")
        ev = self.P.base / "ev-nodeps"
        env = self.P.env(ev=ev)
        proc = subprocess.run([str(py), "-I", "-B", F.CHECKER_REL, "verify"], env=env, cwd=str(self.P.ws), capture_output=True, text=True, timeout=300)
        self.assert_verify_fails(proc, ev, ["dependency pydantic is not installed", "dependency cryptography is not installed", "dependency pytest is not installed"])


# ======================================================================================= check: suites and cases
class SuiteMutationTests(Base):
    def tj_edit(self, fn):
        def m(ev):
            d = F.read_json(ev / "tests.json")
            fn(d)
            F.write_json(ev / "tests.json", d)
        return m

    def log(self, fn):
        def m(ev):
            p = ev / "tests.log"
            p.write_text(fn(p.read_text(encoding="utf-8")), encoding="utf-8")
        return m

    def test_failed_suite_exit_code(self):
        for i, pat in enumerate(("test_real_c3.py", "test_real_c3_integrity.py")):
            with self.subTest(pat=pat):
                run = self.run_mut(self.tj_edit(lambda d, i=i: d["suites"][i].__setitem__("exit_code", 1)))
                self.assert_cause(run, ["suite %s exit code" % pat], allow=["tests.json outcome"])

    def test_skip_exit_code_3(self):
        run = self.run_mut(self.tj_edit(lambda d: d["suites"][0].__setitem__("exit_code", 3)))
        self.assert_cause(run, ["suite test_real_c3.py exit code"], allow=["tests.json outcome"])

    def test_short_suite_observed_count(self):
        for i, (pat, n) in enumerate((("test_real_c3.py", 26), ("test_real_c3_integrity.py", 76))):
            for bad in (n - 1, 0, n + 1, None, str(n), float(n)):
                with self.subTest(pat=pat, bad=bad):
                    run = self.run_mut(self.tj_edit(lambda d, i=i, bad=bad: d["suites"][i].__setitem__("observed_tests", bad)))
                    self.assert_cause(run, ["suite %s observed tests" % pat])

    def test_wrong_expected_count(self):
        for i, pat in enumerate(("test_real_c3.py", "test_real_c3_integrity.py")):
            with self.subTest(pat=pat):
                run = self.run_mut(self.tj_edit(lambda d, i=i: d["suites"][i].__setitem__("expected_tests", 25)))
                self.assert_cause(run, ["suite %s expected tests" % pat])

    def test_suite_dropped_or_extra(self):
        run = self.run_mut(self.tj_edit(lambda d: d["suites"].pop()))
        self.assert_cause(run, ["tests.json lists exactly two suites"], allow=["suite test_real_c3_integrity.py"])
        run = self.run_mut(self.tj_edit(lambda d: d["suites"].append(dict(d["suites"][0]))))
        self.assert_cause(run, ["tests.json lists exactly two suites"])
        run = self.run_mut(self.tj_edit(lambda d: d.pop("suites")))
        self.assert_cause(run, ["tests.json lists exactly two suites"], allow=["suite test_real_c3"])

    def test_outcome_not_passed(self):
        for bad in ("FAILED", "passed", None):
            with self.subTest(bad=bad):
                run = self.run_mut(self.tj_edit(lambda d, bad=bad: d.__setitem__("outcome", bad)))
                self.assert_cause(run, ["tests.json outcome"])

    def test_log_ran_count_wrong(self):
        run = self.run_mut(self.log(lambda t: t.replace("Ran 76 tests", "Ran 75 tests")))
        self.assert_cause(run, ["tests.log contains 'Ran 76 tests'"], allow=["tests.log total of observed counts"])
        run = self.run_mut(self.log(lambda t: t.replace("Ran 26 tests", "Ran 27 tests")))
        self.assert_cause(run, ["tests.log contains 'Ran 26 tests'"], allow=["tests.log total of observed counts"])

    def test_log_missing_or_empty(self):
        run = self.run_mut(self.log(lambda t: ""))
        self.assert_cause(run, ["artifact tests.log present and non-empty"], allow=["tests.log contains", "tests.log total", "tests.log reports OK"])

    def test_log_markers(self):
        cases = {"skipped": lambda t: t.replace("\nOK\n", "\ntest_x (m.T.test_x) ... skipped 'no'\nOK (skipped=1)\n", 1),
                 "expected failure": lambda t: t.replace("\nOK\n", "\ntest_x (m.T.test_x) ... expected failure\nOK (expected failures=1)\n", 1),
                 "FAILED (": lambda t: t.replace("\nOK\n", "\nFAILED (failures=1)\n", 1),
                 "ERROR:": lambda t: t.replace("\nOK\n", "\nERROR: test_x (m.T.test_x)\nOK\n", 1),
                 "unexpected success": lambda t: t.replace("\nOK\n", "\ntest_x (m.T.test_x) ... unexpected success\nOK\n", 1)}
        for name, fn in cases.items():
            with self.subTest(marker=name):
                run = self.run_mut(self.log(fn))
                self.assert_cause(run, ["no skip, expected-failure, unexpected-success, failure or error markers"], allow=["tests.log reports OK"])

    def test_cases_json(self):
        def m(ev):
            d = F.read_json(ev / "cases.json")
            d["exit_code"] = 1
            F.write_json(ev / "cases.json", d)
        run = self.run_mut(m)
        self.assert_cause(run, ["cases.json harness exit code"])

        def nonint(ev):
            F.write_json(ev / "cases.json", {"exit_code": "0"})
        self.assert_cause(self.run_mut(nonint), ["cases.json harness exit code"])
        self.assert_cause(self.run_mut(lambda ev: F.write_json(ev / "cases.json", {"exit_codes": {"c": 0}})), ["cases.json harness exit code"])


class CaseResultMutationTests(Base):
    def test_missing_case_result(self):
        for case in CASES:
            with self.subTest(case=case):
                run = self.run_mut(self.res(lambda r, case=case: r.pop(case)))
                self.assert_cause(run, ["c3.result.json holds exactly the four C3 case ids", "case %s result is an object" % case],
                                  allow=["P1 ", "N1-TEN", "N3", "N5-REV", "limits", "claim", "slice", "every mandatory", "N-A", "evidence index"])

    def test_extra_case_result(self):
        run = self.run_mut(self.res(lambda r: r.__setitem__("c3_extra_case", {"status": "PASS"})))
        self.assert_cause(run, ["c3.result.json holds exactly the four C3 case ids"])

    def test_case_not_an_object(self):
        run = self.run_mut(self.res(lambda r: r.__setitem__(N1, "PASS")))
        self.assert_cause(run, ["case %s result is an object" % N1], allow=["c3.result.json holds exactly", "N1-TEN", "slice", "every mandatory", "limits", "claim"])

    def test_result_root_not_an_object(self):
        run = self.run_mut(lambda ev: (ev / "c3.result.json").write_text("[]\n", encoding="utf-8"))
        self.assert_cause(run, ["c3.result.json is a JSON object"], allow=["P1 ", "N1-TEN", "N3", "N5", "slice", "every mandatory", "limits", "claim", "retained native"])

    def test_variant_b_missing(self):
        run = self.run_mut(self.res(lambda r: r[N3].pop("variant_b")))
        self.assert_cause(run, ["N3 carries a nested variant_b"], allow=["N3 variant_b"])

    def native(self, case, variant, field, value):
        return self.res(lambda r: entry(r, case, variant)["native_pack"].__setitem__(field, value))

    NEG = ((N1, False, "N1-TEN", N1_MSG), (N3, False, "N3 (status alone)", N3_MSG), (N3, True, "N3 variant_b (status and reports forged complete)", N3_MSG), (N5, False, "N5-REV", N5_MSG))

    def test_native_message_mismatch_each_negative_case(self):
        for case, variant, label, msg in self.NEG:
            for bad in (msg[:-1], msg + ".", msg.replace("pinned", "Pinned"), "", None, msg.upper()):
                with self.subTest(label=label, bad=bad):
                    run = self.run_mut(self.native(case, variant, "message", bad))
                    self.assert_cause(run, ["%s native exception message" % label])

    def test_wrong_exception_type_or_code(self):
        for case, variant, label, _ in self.NEG:
            with self.subTest(label=label, what="type"):
                run = self.run_mut(self.native(case, variant, "type", "ValueError"))
                self.assert_cause(run, ["%s native exception type" % label])
            for bad in (0, 1, "E1", False):
                with self.subTest(label=label, what="code", bad=bad):
                    run = self.run_mut(self.native(case, variant, "code", bad))
                    self.assert_cause(run, ["%s native exception code" % label])

    def test_refused_native_downgraded_to_imported(self):
        for case, variant, label, _ in self.NEG:
            with self.subTest(label=label, what="native outcome"):
                run = self.run_mut(self.native(case, variant, "outcome", "IMPORTED"))
                self.assert_cause(run, ["%s native outcome" % label])
            with self.subTest(label=label, what="entry outcome"):
                run = self.run_mut(self.res(lambda r, case=case, variant=variant: entry(r, case, variant).__setitem__("outcome", "IMPORTED")))
                self.assert_cause(run, ["%s outcome is REFUSED_NATIVE" % label])

    def test_harness_error_masquerading_as_refusal(self):
        for case, variant, label, _ in self.NEG:
            with self.subTest(label=label):
                run = self.run_mut(self.res(lambda r, case=case, variant=variant: entry(r, case, variant).__setitem__("reason", "AdapterError: x")))
                self.assert_cause(run, ["%s carries no harness failure reason" % label])

    def test_original_unmodified_after_run_false(self):
        for case, variant, label, _ in self.NEG:
            for bad in (False, None, "true", 1):
                with self.subTest(label=label, bad=bad):
                    run = self.run_mut(self.res(lambda r, case=case, variant=variant, bad=bad: entry(r, case, variant)["mutation"].__setitem__("original_unmodified_after_run", bad)))
                    self.assert_cause(run, ["%s original bundle unmodified after run" % label])

    def test_destination_effects_non_empty_or_no_effect_false(self):
        for case, variant, label, _ in self.NEG:
            with self.subTest(label=label, what="after"):
                run = self.run_mut(self.res(lambda r, case=case, variant=variant: entry(r, case, variant)["destination"].__setitem__("effects_after", {"e1": {"amount": 1}})))
                self.assert_cause(run, ["%s destination effects before/after" % label])
            with self.subTest(label=label, what="before"):
                run = self.run_mut(self.res(lambda r, case=case, variant=variant: entry(r, case, variant)["destination"].__setitem__("effects_before", {"e1": 1})))
                self.assert_cause(run, ["%s destination effects before/after" % label])
            for bad in (False, None):
                with self.subTest(label=label, what="no_effect", bad=bad):
                    run = self.run_mut(self.res(lambda r, case=case, variant=variant, bad=bad: entry(r, case, variant)["destination"].__setitem__("no_effect", bad)))
                    self.assert_cause(run, ["%s destination no_effect" % label])

    def test_mutation_descriptor_altered(self):
        for case, variant, label, _ in self.NEG:
            with self.subTest(label=label):
                run = self.run_mut(self.res(lambda r, case=case, variant=variant: entry(r, case, variant)["mutation"].__setitem__("to", "something-else")))
                self.assert_cause(run, ["%s mutation field_path/from/to" % label])

    def test_mutated_hash_not_reproducible_from_bundle_file(self):
        for case, variant, label, _ in self.NEG:
            with self.subTest(label=label):
                run = self.run_mut(self.res(lambda r, case=case, variant=variant: entry(r, case, variant)["mutation"].__setitem__(
                    "mutated_bundle_H2_pack_canonical_sha256", "sha256:" + "ab" * 32)))
                self.assert_cause(run, ["%s mutated H2 reproduced from the retained bundle file" % label])

    def test_p1_destination_effects_nonzero(self):
        run = self.run_mut(self.res(lambda r: r[P1]["destination"].update({"effect_count": 1, "effects": {"e1": {}}})))
        self.assert_cause(run, ["P1 destination effect count and effects"])

        def m(ev):
            d = F.read_json(ev / "c3.native-destination.json")
            d["effects"] = {"e1": {"amount": 5}}
            F.write_json(ev / "c3.native-destination.json", d)
        run = self.run_mut(m)
        self.assert_cause(run, ["P1 destination effects (retained destination file)"])

    def test_p1_status_outcome_and_pack_validation(self):
        self.assert_cause(self.run_mut(self.res(lambda r: r[P1].__setitem__("outcome", "REFUSED_NATIVE"))), ["P1 outcome"])
        self.assert_cause(self.run_mut(self.res(lambda r: r[P1]["native_pack"]["validation"].__setitem__("valid", False))), ["P1 Pack validation valid"])
        self.assert_cause(self.run_mut(self.res(lambda r: r[P1]["native_pack"]["validation"].__setitem__("errors", [{"code": "E1"}]))),
                          ["P1 Pack validation errors (zero)"])

    def test_harness_pass_status_is_necessary_but_never_sufficient(self):
        # a harness claiming FAIL fails; a harness claiming PASS with disagreeing evidence also fails (see ForgeryTests)
        for case, variant, label, _ in self.NEG:
            with self.subTest(label=label):
                run = self.run_mut(self.res(lambda r, case=case, variant=variant: entry(r, case, variant).__setitem__("status", "FAIL")))
                self.assert_cause(run, ["%s harness status" % label])
        run = self.run_mut(self.res(lambda r: r[P1].__setitem__("status", "FAIL")))
        self.assert_cause(run, ["P1 harness status/oracle"])
        run = self.run_mut(self.res(lambda r: r[P1]["oracle"].__setitem__("all_ok", False)))
        self.assert_cause(run, ["P1 harness status/oracle"])

    def test_harness_source_hashes_and_head(self):
        self.assert_cause(self.run_mut(self.res(lambda r: r[P1]["harness"].__setitem__("c2_producer_sha256", "0" * 64))), ["P1 harness c2_producer.py sha256"])
        self.assert_cause(self.run_mut(self.res(lambda r: r[P1]["harness"].__setitem__("real_c3_sha256", "0" * 64))), ["P1 harness real_c3.py sha256"])
        self.assert_cause(self.run_mut(self.res(lambda r: r[P1]["harness"]["orchestrator"].__setitem__("head", "0" * 40))), ["P1 harness orchestrator head"])
        self.assert_cause(self.run_mut(self.res(lambda r: r[P1]["harness"]["orchestrator"].__setitem__("tracked_files_modified", True))), ["P1 harness orchestrator head"])

    def test_proposal_and_manifest_hash_in_harness_evidence(self):
        self.assert_cause(self.run_mut(self.res(lambda r: r[P1]["inputs"]["proposal"].__setitem__("sha256", "0" * 64))), ["P1 proposal fixture sha256"])
        self.assert_cause(self.run_mut(self.res(lambda r: r[P1]["inputs"]["manifest"].__setitem__("sha256", "0" * 64))), ["P1 Action Manifest fixture sha256"])

    def test_measured_source_identity_in_result(self):
        def bad_head(r):
            r[P1]["sources"]["sources"]["evidence_pack"]["observed_head"] = "0" * 40
        self.assert_cause(self.run_mut(self.res(bad_head)), ["P1 measured evidence_pack head/tree"])

        def dirty(r):
            r[N5]["sources"]["sources"]["replay_bundle"]["status_ignored_clean"] = False
        self.assert_cause(self.run_mut(self.res(dirty)), ["N5-REV replay_bundle clean flags"])


# ======================================================================================= check: evidence files and hashes
class EvidenceFileTests(Base):
    def test_each_mandatory_evidence_file_missing(self):
        for name in FOUND + INPUTS:
            with self.subTest(name=name):
                run = self.run_mut(lambda ev, name=name: (ev / name).unlink())
                self.assertEqual(run.rc, 1, run.describe())
                self.assertTrue(any(name in ln for ln in run.fails), run.describe())
                self.assertTrue(any(("evidence artifact %s present" % name) in ln for ln in run.fails), run.describe())
                self.assertEqual(run.manifest["verdict"], "FAIL")
                self.assertTrue(run.oracle.strip())
                self.assertNotIn("Traceback", run.stderr)

    def test_each_mandatory_evidence_file_empty(self):
        for name in INPUTS + ("context.json",):
            with self.subTest(name=name):
                run = self.run_mut(lambda ev, name=name: (ev / name).write_bytes(b""))
                self.assertEqual(run.rc, 1, run.describe())
                self.assertTrue(any(name in ln for ln in run.fails), run.describe())
                self.assertEqual(run.manifest["verdict"], "FAIL")

    def test_corrupted_native_file_bytes(self):
        needle = {"c3.native-records.json": "P1 record sha256: recomputed from the retained file",
                  "c3.reconstruction-bundle.json": "P1 bundle H1 sha256: recomputed from the retained file",
                  "c3.evidence-pack.json": "P1 Pack file sha256: recomputed from the retained dump"}
        for name, nd in needle.items():
            with self.subTest(name=name):
                def m(ev, name=name):
                    p = ev / name
                    p.write_bytes(p.read_bytes() + b" ")  # whitespace only: still valid JSON, bytes differ
                run = self.run_mut(m)
                self.assert_cause(run, [nd], allow=["P1 raw-record-to-bundle linkage", "P1 record size_bytes", "P1 bundle size_bytes",
                                                    "precondition record == P1 record", "original bundle H"])

    def test_destination_file_bytes_change_is_recorded_in_the_index(self):
        # no hash of the destination file is reported by the harness; the manifest index must reflect the changed bytes
        before = F.read_json(self.P.ev / "evidence-manifest.json")["evidence_file_sha256"]["c3.native-destination.json"]

        def m(ev):
            p = ev / "c3.native-destination.json"
            p.write_bytes(p.read_bytes() + b"\n\n")
        run = self.run_mut(m)
        self.assertEqual(run.rc, 0, run.describe())  # whitespace-only change is not a content change; the index must still follow the bytes
        self.assertNotEqual(run.manifest["evidence_file_sha256"]["c3.native-destination.json"], before)

    def test_corrupted_hash_inside_result(self):
        cases = [("P1 record sha256: recomputed from the retained file", lambda r: r[P1]["record"].__setitem__("sha256", "0" * 64)),
                 ("P1 record size_bytes", lambda r: r[P1]["record"].__setitem__("size_bytes", 1)),
                 ("P1 bundle H1 sha256", lambda r: r[P1]["bundle"].__setitem__("H1_sha256_persisted_bytes", "0" * 64)),
                 ("P1 bundle H2", lambda r: r[P1]["bundle"].__setitem__("H2_pack_canonical_sha256", "sha256:" + "0" * 64)),
                 ("P1 bundle size_bytes", lambda r: r[P1]["bundle"].__setitem__("size_bytes", 1)),
                 ("P1 Pack file sha256: recomputed from the retained dump", lambda r: r[P1]["native_pack"].__setitem__("pack_file_sha256", "0" * 64)),
                 ("P1 Pack pack_id", lambda r: r[P1]["native_pack"].__setitem__("pack_id", "agep-0000000000000000"))]
        for needle, fn in cases:
            with self.subTest(needle=needle):
                run = self.run_mut(self.res(fn))
                self.assert_cause(run, [needle], allow=["P1 raw-record-to-bundle linkage", "P1 Pack input_artifacts", "P1 original", "mutation"])

    def test_original_hash_in_negative_cases_inconsistent_with_bundle_file(self):
        for case, variant, label, _ in CaseResultMutationTests.NEG:
            with self.subTest(label=label):
                run = self.run_mut(self.res(lambda r, case=case, variant=variant: entry(r, case, variant)["mutation"].__setitem__("original_bundle_H1_sha256", "0" * 64)))
                self.assert_cause(run, ["%s original bundle H1 == retained bundle file" % label])
                run = self.run_mut(self.res(lambda r, case=case, variant=variant: entry(r, case, variant)["mutation"].__setitem__("original_bundle_H2_pack_canonical_sha256", "sha256:" + "0" * 64)))
                self.assert_cause(run, ["%s original bundle H2 == recomputed from the bundle file" % label], allow=["original and mutated H2 differ"])

    def test_record_to_bundle_linkage_altered(self):
        run = self.run_mut(self.res(lambda r: r[P1]["raw_record_to_bundle_linkage"].__setitem__("carried_by_pack", True)))
        self.assert_cause(run, ["P1 raw-record-to-bundle linkage"])


class ForgeryTests(Base):
    """The harness result says PASS while the underlying retained file disagrees."""

    def test_pack_bytes_edited_result_still_says_pass(self):
        def m(ev):
            d = F.read_json(ev / "c3.evidence-pack.json")
            d["review_status"] = "approved"
            F.write_json(ev / "c3.evidence-pack.json", d)  # c3.result.json untouched: status PASS, oracle all_ok True, old sha
        run = self.run_mut(m)
        self.assertEqual(F.read_json(run.ev / "c3.result.json")[P1]["status"], "PASS")
        self.assert_cause(run, ["P1 Pack file sha256: recomputed from the retained dump", "P1 Pack review_status draft"])

    def test_pack_edited_coherently_with_result_hash_still_caught_by_the_file_itself(self):
        run = self.run_mut(self.pack(lambda d: d.__setitem__("review_status", "approved")))
        self.assert_cause(run, ["P1 Pack review_status draft"])

    def test_bundle_status_forged_complete_coherent(self):
        def m(ev):
            d = F.read_json(ev / "c3.reconstruction-bundle.json")
            d["status"] = "reconstruction_complete"
            F.write_json(ev / "c3.reconstruction-bundle.json", d)
            r = F.read_json(ev / "c3.result.json")
            b = (ev / "c3.reconstruction-bundle.json").read_bytes()
            r[P1]["bundle"]["H1_sha256_persisted_bytes"] = sha(b)
            r[P1]["bundle"]["size_bytes"] = len(b)
            F.write_json(ev / "c3.result.json", r)
        run = self.run_mut(m)
        self.assert_cause(run, ["P1 Replay status (bundle file)"], allow=["bundle H2", "retained_sources.reconstruction_bundle", "input_artifacts[1]", "original bundle H", "original and mutated", "raw-record-to-bundle linkage", "mutated H2 reproduced"])

    def test_bundle_counts_forged_extra_records_coherent(self):
        def m(ev):
            d = F.read_json(ev / "c3.reconstruction-bundle.json")
            d["records"].append({"record_type": "destination_attempt", "data": {"attempt_id": "a1"}})
            d["import_reports"][0]["findings"] = []
            F.write_json(ev / "c3.reconstruction-bundle.json", d)
            r = F.read_json(ev / "c3.result.json")
            b = (ev / "c3.reconstruction-bundle.json").read_bytes()
            r[P1]["bundle"]["H1_sha256_persisted_bytes"] = sha(b)
            r[P1]["bundle"]["size_bytes"] = len(b)
            F.write_json(ev / "c3.result.json", r)
        run = self.run_mut(m)
        self.assert_cause(run, ["P1 Replay findings: exactly B004 warning (bundle file)", "P1 Replay record types"],
                          allow=["bundle H2", "retained_sources.reconstruction_bundle", "input_artifacts[1]", "original bundle H", "original and mutated", "P1 Replay", "raw-record-to-bundle linkage", "mutated H2 reproduced"])

    def test_record_attempt_injected_into_native_records(self):
        def m(ev):
            d = F.read_json(ev / "c3.native-records.json")
            d["attempts"] = [{"attempt_id": "a1"}]
            F.write_json(ev / "c3.native-records.json", d)
            r = F.read_json(ev / "c3.result.json")
            b = (ev / "c3.native-records.json").read_bytes()
            r[P1]["record"]["sha256"] = sha(b)
            r[P1]["record"]["size_bytes"] = len(b)
            F.write_json(ev / "c3.result.json", r)
        run = self.run_mut(m)
        self.assert_cause(run, ["P1 attempts/observations/reconciliations/closeouts/refusals empty (native record file)"],
                          allow=["raw-record-to-bundle linkage", "precondition record == P1 record"])

    def test_bundle_retained_in_pack_differs_from_bundle_file(self):
        run = self.run_mut(self.pack(lambda d: d["metadata"]["traceable_import"]["retained_sources"]["reconstruction_bundle"].__setitem__("status", "reconstruction_complete")))
        self.assert_cause(run, ["P1 Pack retained_sources.reconstruction_bundle == parsed bundle file"])

    def test_pack_manifest_digest_altered(self):
        def f(d):
            d["metadata"]["traceable_import"]["input_artifacts"][0]["hash"] = "sha256:" + "0" * 64
        run = self.run_mut(self.pack(f))
        self.assert_cause(run, ["P1 Pack input_artifacts[0].hash == Action Manifest canonical digest"])

    def test_pack_frozen_fields_each_mutated(self):
        T = lambda d: d["metadata"]["traceable_import"]  # noqa: E731
        cases = [("P1 Pack pack_version", lambda d: d.__setitem__("pack_version", "0.3.0")),
                 ("P1 Pack transformation_version", lambda d: T(d).__setitem__("transformation_version", "other")),
                 ("P1 Pack selected_revisions", lambda d: T(d)["selected_revisions"].__setitem__("replay", "0" * 40)),
                 ("P1 Pack replay_semantic_validation", lambda d: T(d)["replay_semantic_validation"].__setitem__("status", "validated_complete")),
                 ("P1 Pack reconstruction_completeness", lambda d: T(d).__setitem__("reconstruction_completeness", "reconstruction_complete")),
                 ("P1 Pack lifecycle_summary", lambda d: T(d)["lifecycle_summary"].__setitem__("execution_attempted", "yes")),
                 ("P1 Pack replay_semantics flags", lambda d: T(d)["replay_semantics"].__setitem__("external_effect_execution", True)),
                 ("P1 Pack replay_bundles[0] status/signed/redacted/validation_status", lambda d: d["replay_bundles"][0].__setitem__("signed", True))]
        for needle, fn in cases:
            with self.subTest(needle=needle):
                self.assert_cause(self.run_mut(self.pack(fn)), [needle])


class LimitsAndClaimsTests(Base):
    def test_limits_dropped_softened_or_promoted(self):
        def drop(r):
            r[P1]["limits"].pop("L15")
        run = self.run_mut(self.res(drop))
        self.assert_cause(run, ["P1 limits key set"], allow=["limits L15", "limits identical to the P1 limits block", "limits L15 is a non-empty string", "limits-L1-L19.json carries L1..L19"])

        def soften(r):
            r[P1]["limits"]["L1"] = "Replay is partial."
        run = self.run_mut(self.res(soften))
        self.assert_cause(run, ["limits L1 carries its key phrases"], allow=["limits identical to the P1 limits block"])

        def flag(r):
            r[N1]["limits"]["effect_executed"] = True
        run = self.run_mut(self.res(flag))
        self.assert_cause(run, ["N1-TEN limits flag effect_executed"], allow=["N1-TEN limits identical"])

        def hub(r):
            r[P1]["limits"]["hub_280_digest_basis"] = "CLOSED"
        run = self.run_mut(self.res(hub))
        self.assert_cause(run, ["P1 limits flag hub_280_digest_basis"], allow=["limits identical to the P1 limits block"])

    def test_positive_claim_promotion_string_in_result(self):
        def m(r):
            r[N5]["producer"]["note"] = "this run is a complete reconstruction and certified"
        run = self.run_mut(self.res(m))
        self.assert_cause(run, ["no positive claim-promotion string"])

    def test_limits_text_with_unnegated_claim(self):
        def m(r):
            for c in CASES:
                r[c]["limits"]["L17"] = "Developer-scope only: not independently qualified, not production, no certification or clearance (HOLD). The run is approved."
        run = self.run_mut(self.res(m))
        self.assert_cause(run, ["limits state no forbidden claim without a negation"], allow=["limits identical", "P1 limits identical", "limits L17"])


# ======================================================================================= N-A: Pack-side zero counts
class ZeroCountTests(Base):
    """Explicit N-A closure: the six keys are re-observed directly from the retained native Pack dump (coherent file hash)."""

    NA = "N-A derived_counts.%s is present, an int (not bool) and == 0"

    def only_na(self, run, key):
        self.assert_cause(run, [self.NA % key])
        self.assertEqual(len(run.fails), 1, run.describe())

    def test_each_key_set_to_one(self):
        for key in ZERO_KEYS:
            for bad in (1, -1, 2, 10 ** 9):
                with self.subTest(key=key, bad=bad):
                    self.only_na(self.run_mut(self.pack(lambda d, key=key, bad=bad: dcounts(d).__setitem__(key, bad))), key)

    def test_each_key_deleted(self):
        for key in ZERO_KEYS:
            with self.subTest(key=key):
                self.only_na(self.run_mut(self.pack(lambda d, key=key: dcounts(d).pop(key))), key)

    def test_each_key_wrong_type(self):
        for key in ZERO_KEYS:
            for bad in ("0", "", "zero", None, 0.0, 1.5, True, False, [], [0], {}, {"n": 0}):
                with self.subTest(key=key, bad=bad):
                    self.only_na(self.run_mut(self.pack(lambda d, key=key, bad=bad: dcounts(d).__setitem__(key, bad))), key)

    def test_derived_counts_object_deleted_or_wrong_type(self):
        for how in ("deleted", "null", "list", "string"):
            with self.subTest(how=how):
                def f(d, how=how):
                    t = d["metadata"]["traceable_import"]
                    if how == "deleted":
                        t.pop("derived_counts")
                    else:
                        t["derived_counts"] = {"null": None, "list": [], "string": "0"}[how]
                run = self.run_mut(self.pack(f))
                self.assert_cause(run, [self.NA % k for k in ZERO_KEYS])
                self.assertEqual(len(run.fails), len(ZERO_KEYS), run.describe())

    def test_traceable_import_deleted(self):
        run = self.run_mut(self.pack(lambda d: d["metadata"].pop("traceable_import")))
        self.assert_cause(run, [self.NA % k for k in ZERO_KEYS], allow=["P1 Pack"])

    def test_harness_oracle_forced_ok_while_pack_nonzero(self):
        """A forced-green harness oracle (pack_derived_counts_zero ok, all_ok, status PASS) must not rescue a nonzero Pack count."""
        def force(ev):
            d = F.read_json(ev / "c3.evidence-pack.json")
            dcounts(d)["destination_effect_count"] = 1
            F.write_json(ev / "c3.evidence-pack.json", d)
            r = F.read_json(ev / "c3.result.json")
            for c in r[P1]["oracle"]["checks"]:
                if c["name"] == "pack_derived_counts_zero":
                    c["ok"] = True
                    c["observed"] = {k: 0 for k in ZERO_KEYS}
            r[P1]["oracle"]["all_ok"] = True
            r[P1]["status"] = "PASS"
            r[P1]["native_pack"]["pack_file_sha256"] = sha((ev / "c3.evidence-pack.json").read_bytes())  # coherent file hash
            F.write_json(ev / "c3.result.json", r)
        run = self.run_mut(force)
        names = [c["name"] for c in F.read_json(run.ev / "c3.result.json")[P1]["oracle"]["checks"]]
        self.assertIn("pack_derived_counts_zero", names)
        self.only_na(run, "destination_effect_count")

    def test_nonzero_count_with_updated_file_hash_is_detected(self):
        # coherent forgery of count + sha256 reported in c3.result.json: still caught because the count is read from the Pack file
        for key in ZERO_KEYS:
            with self.subTest(key=key):
                self.only_na(self.run_mut(self.pack(lambda d, key=key: dcounts(d).__setitem__(key, 3))), key)

    def test_noncoherent_forgery_is_double_flagged(self):
        run = self.run_mut(self.pack(lambda d: dcounts(d).__setitem__("reconciliation_count", 1), coherent=False))
        self.assert_cause(run, [self.NA % "reconciliation_count", "P1 Pack file sha256: recomputed from the retained dump"])

    def test_extra_derived_count_keys_do_not_mask_missing_ones(self):
        def f(d):
            dc = dcounts(d)
            dc.pop("effect_observation_count")
            dc["effect_observation_count_x"] = 0
        self.only_na(self.run_mut(self.pack(f)), "effect_observation_count")

    def test_pack_dump_not_an_object_or_unparsable(self):
        run = self.run_mut(lambda ev: (ev / "c3.evidence-pack.json").write_text("[0]\n", encoding="utf-8"))
        self.assertEqual(run.rc, 1, run.describe())
        self.assertTrue(any("c3.evidence-pack.json" in ln for ln in run.fails), run.describe())
        run = self.run_mut(lambda ev: (ev / "c3.evidence-pack.json").write_text("{not json", encoding="utf-8"))
        self.assertEqual(run.rc, 1, run.describe())
        self.assertTrue(any("c3.evidence-pack.json" in ln for ln in run.fails), run.describe())
        run = self.run_mut(lambda ev: (ev / "c3.evidence-pack.json").write_bytes(
            (ev / "c3.evidence-pack.json").read_bytes().replace(b'"control_plane_attempt_count": 0', b'"control_plane_attempt_count": 0, "control_plane_attempt_count": 1', 1)))
        self.assertEqual(run.rc, 1, run.describe())
        self.assertTrue(any("c3.evidence-pack.json" in ln for ln in run.fails), run.describe())


# ======================================================================================= garbage input and summary
class ContextMutationTests(Base):
    """`check` re-asserts what `verify` recorded; a doctored context.json must not pass."""

    def ctx(self, fn):
        def m(ev):
            d = F.read_json(ev / "context.json")
            fn(d)
            F.write_json(ev / "context.json", d)
        return m

    def test_context_fields(self):
        cases = [("context: verify PASS", lambda d: d.__setitem__("verify", "FAIL")),
                 ("context: case group", lambda d: d.__setitem__("case_id", "c2_p1_n1_n2_hosted_group")),
                 ("context re-asserted: ref/event/head", lambda d: d.__setitem__("github_ref", "refs/heads/other")),
                 ("context re-asserted: ref/event/head", lambda d: d.__setitem__("event_name", "push")),
                 ("context re-asserted: ref/event/head", lambda d: d.__setitem__("orchestrator_head", "0" * 40)),
                 ("context re-asserted: GITHUB_SHA non-empty and equals context", lambda d: d.__setitem__("github_sha", "0" * 40)),
                 ("context re-asserted: c2_producer.py sha256 == frozen", lambda d: d["host_sources"].__setitem__("tests/manual_contract/c2_producer.py", "0" * 64)),
                 ("context re-asserted: component pins", lambda d: d["components"]["evidence_pack"].__setitem__("sha", "0" * 40)),
                 ("context re-asserted: fixture hashes", lambda d: d["fixtures"]["proposal"].__setitem__("sha256", "0" * 64)),
                 ("context re-asserted: locked dependency versions", lambda d: d["dependencies"].__setitem__("pydantic", "9.9.9")),
                 ("context re-asserted: dependency lock sha256 recorded", lambda d: d["host_sources"].pop(".github/locks/cryptography-pydantic-pytest-513753.txt"))]
        for needle, fn in cases:
            with self.subTest(needle=needle):
                run = self.run_mut(self.ctx(fn))
                self.assert_cause(run, [needle], allow=["P1 harness real_c3.py sha256", "P1 runtime versions", "context re-asserted: host source hashes",
                                                       "context re-asserted: c2_producer", "P1 harness orchestrator head"])

    def test_check_run_with_a_different_github_sha_than_verify(self):
        run = self.run_mut(lambda ev: None, GITHUB_SHA="0" * 40)
        self.assert_cause(run, ["context re-asserted"], allow=["P1 harness orchestrator head"])

    def test_check_with_component_root_unset(self):
        run = self.run_mut(lambda ev: None, COGNOUS_C3_EVIDENCE_PACK_ROOT=None)
        self.assert_cause(run, ["COGNOUS_C3_EVIDENCE_PACK_ROOT is set for the check step"], allow=["P1 "])


class GarbageInputTests(Base):
    def assert_closed(self, run, empty_ok=False):
        self.assertEqual(run.rc, 1, run.describe())
        self.assertNotIn("Traceback", run.stderr + run.stdout)
        self.assertTrue(run.stderr.strip() or run.fails, "a failure must be reported")

    def garbage_dir(self, content, names=FOUND + INPUTS):
        def m(ev):
            for name in names:
                (ev / name).write_bytes(content)
        return m

    def test_empty_evidence_directory(self):
        ev = pathlib.Path(tempfile.mkdtemp(prefix="empty-", dir=str(self.P.base))) / "evidence"
        ev.mkdir()
        run = self.P.run_check(ev)
        self.assert_closed(run)
        self.assertTrue(any("FAIL" in ln for ln in run.fails))
        self.assertEqual(run.manifest["verdict"], "FAIL")

    def test_nonexistent_evidence_directory(self):
        ev = pathlib.Path(tempfile.mkdtemp(prefix="none-", dir=str(self.P.base))) / "deep" / "evidence"
        run = self.P.run_check(ev)
        self.assert_closed(run)

    def test_evidence_dir_unset(self):
        run = CheckRunProc(self.P.checker("check", self.P.env(EVIDENCE_DIR=None)))
        self.assertEqual(run.rc, 1)
        self.assertNotIn("Traceback", run.stderr)

    def test_evidence_dir_is_a_file(self):
        f = self.P.base / "afile"
        f.write_text("x", encoding="utf-8")
        run = CheckRunProc(self.P.checker("check", self.P.env(EVIDENCE_DIR=str(f))))
        self.assertEqual(run.rc, 1)
        self.assertNotIn("Traceback", run.stderr)

    def test_non_json_garbage_in_every_file(self):
        for label, blob in (("text", b"this is not json {"), ("binary", bytes(range(256))), ("bom", b"\xef\xbb\xbf{}"), ("nul", b"\x00\x00\x00"),
                            ("bad-utf8", b"\xff\xfe{\"a\": 1}"), ("nan", b'{"a": NaN}'), ("infinity", b'{"a": Infinity}'), ("array", b"[]"), ("null", b"null"),
                            ("number", b"42"), ("string", b'"x"'), ("empty-object", b"{}")):
            with self.subTest(label=label):
                run = self.run_mut(self.garbage_dir(blob))
                self.assert_closed(run)
                self.assertNotEqual((run.manifest or {}).get("verdict"), "PASS")

    def test_duplicate_key_json(self):
        for name in ("c3.result.json", "c3.evidence-pack.json", "c3.reconstruction-bundle.json", "c3.native-records.json", "c3.native-destination.json",
                     "tests.json", "cases.json", "context.json"):
            with self.subTest(name=name):
                def m(ev, name=name):
                    p = ev / name
                    text = p.read_text(encoding="utf-8")
                    p.write_text(text.rstrip()[:-1] + ', "dup": 1, "dup": 2}\n', encoding="utf-8")
                run = self.run_mut(m)
                self.assertEqual(run.rc, 1, run.describe())
                self.assertNotIn("Traceback", run.stderr)
                self.assertTrue(any(name in ln for ln in run.fails) or run.stderr.strip(), run.describe())

    def test_huge_and_deeply_nested_json(self):
        big = b'{"a": [' + b",".join([b'"x' + b"y" * 50 + b'"'] * 150000) + b"]}"  # ~8 MB
        deep = b"[" * 200000 + b"]" * 200000
        wide = b"{" + b",".join(b'"k%d": %d' % (i, i) for i in range(200000)) + b"}"
        for label, blob in (("big", big), ("deep", deep), ("wide", wide)):
            for name in ("c3.result.json", "c3.evidence-pack.json", "context.json", "tests.json"):
                with self.subTest(label=label, name=name):
                    run = self.run_mut(lambda ev, name=name, blob=blob: (ev / name).write_bytes(blob))
                    self.assertEqual(run.rc, 1, run.describe())
                    self.assertNotIn("Traceback", run.stderr + run.stdout)

    def test_non_ascii_oracle_never_breaks_writing(self):
        def m(ev):
            r = F.read_json(ev / "c3.result.json")
            r[N1]["native_pack"]["message"] = "café ☃ \U0001f600"
            F.write_json(ev / "c3.result.json", r)
        run = self.run_mut(m)
        self.assert_cause(run, ["N1-TEN native exception message"])
        run.oracle.encode("ascii")

    def test_usage_errors(self):
        for args in ([], ["bogus"], ["check", "extra"], ["VERIFY"]):
            with self.subTest(args=args):
                proc = subprocess.run([sys.executable, "-I", "-B", F.CHECKER_REL, *args], env=self.P.env(), cwd=str(self.P.ws), capture_output=True, text=True, timeout=120)
                self.assertEqual(proc.returncode, 2)
                self.assertNotIn("Traceback", proc.stderr)


class CheckRunProc:
    def __init__(self, proc):
        self.rc, self.stdout, self.stderr = proc.returncode, proc.stdout, proc.stderr


CLAIM_WORDS = re.compile(r"independently qualified|certified|production[ -]ready|approved|compliant|complete reconstruction|authenticated authority|verified execution|cleared for", re.I)
NEGATION = re.compile(r"\b(not|no|never|neither|nor|without)\b", re.I)


class SummaryTests(Base):
    def summary(self, ev, **extra):
        env = self.P.env(ev=ev, **extra)
        return subprocess.run([sys.executable, "-I", "-B", F.CHECKER_REL, "summary"], env=env, cwd=str(self.P.ws), capture_output=True, text=True, timeout=120)

    def assert_no_claims(self, text):
        for m in CLAIM_WORDS.finditer(text):
            line = text[text.rfind("\n", 0, m.start()) + 1:text.find("\n", m.end()) if text.find("\n", m.end()) >= 0 else len(text)]
            self.assertTrue(NEGATION.search(line), "un-negated claim %r in summary line: %s" % (m.group(0), line))

    def test_summary_exits_zero_and_makes_no_claims_on_pristine(self):
        ev = pathlib.Path(tempfile.mkdtemp(prefix="sum-", dir=str(self.P.base))) / "evidence"
        shutil.copytree(self.P.ev, ev)
        proc = self.summary(ev, STEP_VERIFY="success", STEP_TESTS="success", STEP_CASES="success", STEP_ORACLE="success", STEP_INSTALL="success",
                            STEP_CHECKOUT_CP="success", STEP_CHECKOUT_RB="success", STEP_CHECKOUT_PACK="success", STEP_CHECKOUT_AM="success")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("hosted developer evidence only", proc.stdout)
        self.assertIn("reconstruction_partial", proc.stdout)
        self.assertIn("Hub #280 is OPEN", proc.stdout)
        self.assert_no_claims(proc.stdout)
        self.assertNotRegex(proc.stdout.lower(), r"qualification (granted|complete|achieved)|production ready|release approved")

    def test_summary_exits_zero_on_failed_run_and_reports_fail(self):
        run = self.run_mut(self.res(lambda r: r[N1]["native_pack"].__setitem__("message", "x")))
        proc = self.summary(run.ev, STEP_VERIFY="success", STEP_TESTS="success", STEP_CASES="success", STEP_ORACLE="failure", STEP_INSTALL="success",
                            STEP_CHECKOUT_CP="success", STEP_CHECKOUT_RB="success", STEP_CHECKOUT_PACK="success", STEP_CHECKOUT_AM="success")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("FAIL", proc.stdout)
        self.assertNotIn("Developer check result: PASS", proc.stdout)
        self.assert_no_claims(proc.stdout)

    def test_summary_never_fails_on_empty_garbage_or_missing(self):
        ev = pathlib.Path(tempfile.mkdtemp(prefix="sum-", dir=str(self.P.base))) / "evidence"
        ev.mkdir()
        for label, setup in (("empty", lambda: None), ("garbage", lambda: [(ev / n).write_bytes(b"\xff\x00{") for n in ("context.json", "oracle.txt")])):
            setup()
            with self.subTest(label=label):
                proc = self.summary(ev)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                self.assertNotIn("Developer check result: PASS", proc.stdout)
        proc = self.summary(ev, EVIDENCE_DIR=None)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.summary(ev, GITHUB_STEP_SUMMARY=str(self.P.base / "nodir" / "summary.md"))
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_summary_without_step_outcomes_is_not_pass(self):
        proc = self.summary(self.P.ev)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Developer check result: PASS", proc.stdout)

    def test_summary_writes_step_summary_file(self):
        out = self.P.base / "step-summary.md"
        proc = self.summary(self.P.ev, GITHUB_STEP_SUMMARY=str(out))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertIn("C3 hosted run", out.read_text(encoding="utf-8"))

    def test_summary_neutralises_markdown_and_html_in_oracle_lines(self):
        ev = pathlib.Path(tempfile.mkdtemp(prefix="sum-", dir=str(self.P.base))) / "evidence"
        shutil.copytree(self.P.ev, ev)
        (ev / "oracle.txt").write_text("C3 FAIL\nFAIL <script>alert(1)</script> | `x` [a](http://e)\n", encoding="utf-8")
        proc = self.summary(ev, STEP_VERIFY="success")
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("<script>", proc.stdout)


# ======================================================================================= structure of tests and checker
def _imports(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.add("." * node.level)
            elif node.module:
                names.add(node.module.split(".")[0])
    return names


class StructureTests(unittest.TestCase):
    def test_this_test_file_has_no_skip_or_expected_failure(self):
        banned = {"skip", "skipIf", "skipUnless", "skipTest", "SkipTest", "expectedFailure", "xfail", "importorskip", "addSkip", "addExpectedFailure"}
        for path in (THIS, pathlib.Path(F.__file__).resolve()):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            used = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in banned:
                    used.add(node.attr)
                if isinstance(node, ast.Name) and node.id in banned:
                    used.add(node.id)
                if isinstance(node, ast.ImportFrom):
                    used.update(a.name for a in node.names if a.name in banned)
            self.assertEqual(used, set(), path.name)

    def test_roots_are_required_not_optional(self):
        saved = {k: os.environ.pop(v) for k, v in F.ROOT_ENV.items() if v in os.environ}
        try:
            with self.assertRaises(F.FixtureError):
                F.required_roots()
        finally:
            for k, v in saved.items():
                os.environ[F.ROOT_ENV[k]] = v

    def test_checker_is_stdlib_only(self):
        tree = ast.parse(CHECKER.read_text(encoding="utf-8"))
        names = _imports(tree)
        self.assertEqual(sorted(n for n in names if n not in sys.stdlib_module_names), [])
        self.assertTrue(names)
        for banned in ("socket", "urllib", "http", "requests", "ssl", "ftplib", "smtplib", "xmlrpc", "asyncio", "pydantic", "cryptography", "pytest", "yaml"):
            self.assertNotIn(banned, names)

    def test_checker_has_no_network_and_only_read_only_subprocess(self):
        text = CHECKER.read_text(encoding="utf-8")
        tree = ast.parse(text)
        sub_attrs, os_attrs, calls = set(), set(), []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "subprocess":
                    sub_attrs.add(node.attr)
                if node.value.id == "os":
                    os_attrs.add(node.attr)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "git" and len(node.args) >= 2:
                a = node.args[1]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    calls.append(a.value)
        self.assertLessEqual(sub_attrs, {"run", "SubprocessError"})
        self.assertEqual(os_attrs & {"system", "popen", "execv", "execve", "execvp", "spawnl", "spawnv", "fork", "kill", "remove", "unlink", "rmdir", "removedirs", "rename", "chmod", "putenv", "environ_put"}, set())
        self.assertTrue(set(calls) >= {"rev-parse", "ls-files", "status"})
        self.assertLessEqual(set(calls), {"rev-parse", "ls-files", "status", "ls-tree", "cat-file", "log", "show", "diff", "describe"})
        # the one direct subprocess.run is `git --version`; every other launch goes through the read-only git() helper
        runs = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"]
        self.assertEqual(len(runs), 2)
        for forbidden in ("shell=True", "curl", "wget", "pip install", "eval(", "exec("):
            self.assertNotIn(forbidden, text)
        strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for verb in ("fetch", "push", "pull", "clone", "checkout", "add", "commit", "reset", "clean", "gc", "config", "update-index", "remote"):
            self.assertNotIn(verb, strings)

    def test_checker_restates_literals_independently_of_the_harness(self):
        names = _imports(ast.parse(CHECKER.read_text(encoding="utf-8")))
        self.assertNotIn("real_c3", names)
        self.assertNotIn("c2_producer", names)
        self.assertNotIn("runner", names)
        text = CHECKER.read_text(encoding="utf-8")
        self.assertNotIn("import real_c3", text)

    def test_checker_never_reads_harness_oracle_for_the_zero_counts(self):
        text = CHECKER.read_text(encoding="utf-8")
        self.assertNotIn("pack_derived_counts_zero", text.split("N-A closure")[1].split("retained sources")[0])


if __name__ == "__main__":
    unittest.main()
