"""Mutation tests for the hosted C4 checker `tests/manual_contract/c4/c4_hosted_check.py` (verify | check | summary).

Test-only, developer-scope; NOT qualification evidence. The checker is exercised only as a subprocess (`python -I -B`) with an explicit
minimal environment. One REAL pristine evidence directory is built once (c4_hosted_fixtures.pristine(): the real focused suites, one real
harness run, the retained native files copied under their hosted names, then `check` = the positive control, which must exit 0 with manifest
verdict PASS). Each mutation test copies that directory, applies exactly ONE mutation, runs the checker and asserts (a) exit 1, (b) the
intended NAMED check is among the failing lines and no unrelated check fails, (c) the oracle and manifest were still written (failed
artifacts are retained), (d) no traceback.
The four pinned component roots are REQUIRED from COGNOUS_C4_* (a missing root is a failure, never a skip). The interpreter running these
tests must have the hash-locked dependency set installed (the checker's `verify` compares versions with the lock, as the hosted job does).

Documented limits (not asserted as failures): the checker re-observes everything from the retained files and compares with restated
literals, but it has no independent anchor for the evidence directory itself. A wholesale, internally consistent fabrication of the whole
set (result, Pack dumps, bundles, records, destinations, hashes) that happens to match every literal is indistinguishable from a real run
without re-running the harness; per-run values (record sha256, bundle id, Pack id, decision id) are never golden. A forged NONZERO Pack
count with consistently updated file hashes IS detected (the count is read from the Pack file, not from the hash). The checker cannot call
the native Replay or Pack APIs (stdlib only, no component import): the N2 native refusal is checked from the retained harness record and
the retained mutated bundle, not re-executed here (the focused C4 suites re-execute it natively). The Pack `valid` verdict is
'harness-reported' because validation cannot be re-run without importing the Pack.
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
import c4_hosted_fixtures as F  # noqa: E402

CHECKER = F.CHECKER
THIS = pathlib.Path(__file__).resolve()
P1, N1, N2 = "c4_p1_authorized_chain", "c4_n1_hold_revoked_grant", "c4_n2_flip_hold_to_authorized"
CASES = (P1, N1, N2)
SHORT = {P1: "p1", N1: "n1"}
LABEL = {P1: "P1", N1: "N1-HOLD", N2: "N2-FLIP"}
ZERO_KEYS = ("control_plane_attempt_count", "executor_attempt_count", "attempt_transition_record_count", "destination_effect_count",
             "effect_observation_count", "reconciliation_count")
FOUND = ("sources.txt", "context.json")
INPUTS = ("tests.json", "cases.json", "tests.log", "c4.result.json", "c4.inputs.am-manifest.json", "c4.inputs.proposal.json",
          *("c4.%s.%s.json" % (s, n) for s in ("p1", "n1") for n in ("cp-record", "destination", "reconstruction-bundle", "evidence-pack")),
          "c4.n2.mutated-bundle.json")
NATIVE = tuple(n for n in INPUTS if n.startswith("c4.") and n != "c4.result.json")
MANIFEST_SHA = "789ad39596b9e1ef84a726a671883e1cb6b83343da3a31db0a1120906d68c074"
EFFECT_HOLD = "sha256:d0e4afe09cdf3a52aa3b530b822411b1dff35031973660fbbf9b707415f18465"
EFFECT_AUTH = "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8"
SLICES = ("p1.result.json", "n1-hold.result.json", "n2-flip.result.json", "p1.pack-validation-report.json", "n1.pack-validation-report.json",
          "c4-crosswalk.json", "limits-L1-L27.json", "boundary-verdicts.json")


def setUpModule():
    F.pristine()  # built once for the whole module; a failure here fails every test (never a skip)


def tearDownModule():
    F.drop_cache()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def trace_free(test, run):
    test.assertNotIn("Traceback", run.stderr + run.stdout)


def entry(r, case):
    return r[case]


def dcounts(d):
    return d["metadata"]["traceable_import"]["derived_counts"]


def decision_index(bundle):
    return [i for i, x in enumerate(bundle["records"]) if x.get("record_type") == "runtime_decision"][0]


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
            self.assertTrue(any(n in ln for n in tuple(must) + tuple(allow)), "unrelated FAIL line: %s\n%s" % (ln[:240], msg))
        for name, digest in run.manifest["evidence_file_sha256"].items():  # a failed run is still tamper-evident
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
            r = F.read_json(ev / "c4.result.json")
            fn(r)
            F.write_json(ev / "c4.result.json", r)
        return m

    def edit(self, name, fn, case=None, coherent=True):
        """Edit one retained native JSON file; coherent=True also updates the sha256 values the harness result reports for it."""
        def m(ev):
            d = F.read_json(ev / name)
            fn(d)
            F.write_json(ev / name, d)
            if coherent and case in SHORT:
                self.rehash(ev, name, case)
        return m

    def rehash(self, ev, name, case):
        r = F.read_json(ev / "c4.result.json")
        e = r[case]
        data = (ev / name).read_bytes()
        kind = name.split(".", 2)[2][:-5]
        per = e["identity"]["per_run"]
        if kind == "evidence-pack":
            per["pack_file_sha256"] = sha(data)
        elif kind == "cp-record":
            per["cp_record_sha256"] = sha(data)
        elif kind == "reconstruction-bundle":
            per["bundle_h1_sha256"] = sha(data)
            per["bundle_h2_pack_canonical_sha256"] = h2(json.loads(data))
        elif kind != "destination":
            raise AssertionError("rehash: unsupported retained file " + name)
        key = "%s/%s.json" % (SHORT[case], kind)
        if key in e["files"]:
            e["files"][key] = sha(data)
        F.write_json(ev / "c4.result.json", r)

    def pack(self, case, fn, coherent=True):
        return self.edit("c4.%s.evidence-pack.json" % SHORT[case], fn, case, coherent)

    def bundle(self, case, fn, coherent=True):
        return self.edit("c4.%s.reconstruction-bundle.json" % SHORT[case], fn, case, coherent)

    def record(self, case, fn, coherent=True):
        return self.edit("c4.%s.cp-record.json" % SHORT[case], fn, case, coherent)

    def run_mut(self, mutate, **overrides):
        return self.P.mutated(mutate, **overrides)

    def boundary(self, r, case, name):
        return [b for b in r[case]["boundaries"] if b["boundary"] == name][0]


def h2(obj):
    return "sha256:" + sha(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))


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
        for name in SLICES + ("c4.result.json", "c4.p1.evidence-pack.json", "c4.n1.evidence-pack.json", "c4.n2.mutated-bundle.json", "sources.txt", "context.json",
                              "oracle.txt"):
            self.assertIn(name, m["evidence_file_sha256"])

    def test_manifest_separates_stable_identity_from_per_run_values(self):
        m = F.read_json(self.P.ev / "evidence-manifest.json")
        self.assertIn("values_not_golden", m["per_run"])
        self.assertEqual(sorted(m["per_run"]["values_not_golden"]), ["n1", "p1"])
        stable_text = json.dumps(m["stable_identity"], sort_keys=True)
        r = F.read_json(self.P.ev / "c4.result.json")
        for case in (P1, N1):
            for k in ("decision_id", "bundle_id", "pack_id", "cp_record_sha256", "bundle_h1_sha256", "pack_file_sha256", "generated_at"):
                self.assertNotIn(r[case]["identity"]["per_run"][k], stable_text, "a per-run value leaked into the stable identity: " + k)
        self.assertEqual(m["stable_identity"]["frozen"]["n1_chain_verdict"], "REFUSED_NATIVE@control_plane")
        self.assertEqual(m["stable_identity"]["frozen"]["effect_id_hold"], EFFECT_HOLD)
        self.assertEqual(m["stable_identity"]["frozen"]["effect_id_authorized"], EFFECT_AUTH)
        self.assertIn("pins", json.dumps(m["stable_identity"]["sources"]) + "pins")
        digest = sha(json.dumps(m["stable_identity"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        self.assertEqual(m["stable_identity_sha256"], digest)

    def test_manifest_lists_what_was_not_executed(self):
        m = F.read_json(self.P.ev / "evidence-manifest.json")
        text = " | ".join(m["not_executed"])
        for needle in ("N3-GATE", "L22", "independent qualification"):
            self.assertIn(needle, text)
        self.assertIn("N-A", m["n_a_disposition"])

    def test_pristine_inputs_are_the_real_counts(self):
        tj = F.read_json(self.P.ev / "tests.json")
        self.assertEqual([s["pattern"] for s in tj["suites"]], list(F.SUITE_PATTERNS))
        for s, want in zip(tj["suites"], self.P.expected):
            self.assertEqual((s["exit_code"], s["expected_tests"], s["observed_tests"]), (0, want, want))
        self.assertEqual(F.read_json(self.P.ev / "cases.json")["exit_code"], 0)
        self.assertEqual(sorted(F.read_json(self.P.ev / "c4.result.json")), sorted(CASES))

    def test_pristine_verify_passes(self):
        proc, ev = self.verify()
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        self.assertEqual(F.read_json(ev / "context.json")["verify"], "PASS")

    def test_clean_component_copies_pass_verify(self):
        roots = self.P.clone_components(pathlib.Path(tempfile.mkdtemp(prefix="cc-", dir=str(self.P.base))))
        proc, ev = self.verify(roots=roots)
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])

    def test_derived_slices_match_the_retained_result(self):
        r = F.read_json(self.P.ev / "c4.result.json")
        self.assertEqual(F.read_json(self.P.ev / "p1.result.json"), r[P1])
        self.assertEqual(F.read_json(self.P.ev / "n1-hold.result.json"), r[N1])
        self.assertEqual(F.read_json(self.P.ev / "n2-flip.result.json"), r[N2])
        cw = F.read_json(self.P.ev / "c4-crosswalk.json")
        self.assertEqual((cw["p1"], cw["n1"]), (r[P1]["crosswalk"], r[N1]["crosswalk"]))
        bv = F.read_json(self.P.ev / "boundary-verdicts.json")
        self.assertEqual(bv[N1]["chain_verdict"], {"boundary": "control_plane", "class": "REFUSED_NATIVE"})
        lim = F.read_json(self.P.ev / "limits-L1-L27.json")
        self.assertTrue(all(("L%d" % n) in lim for n in range(1, 28)))
        self.assertEqual(F.read_json(self.P.ev / "n1.pack-validation-report.json"), r[N1]["native"]["pack"]["validation"])


class VerifyContextTests(Base):
    def test_wrong_github_ref(self):
        for ref in ("refs/heads/o0c-c4/composed-real-edge", "refs/tags/v1", "refs/pull/1/merge", "main", ""):
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
        for case in ("c3_p1_n1_n3_n5_hosted_group", "c4_p1_authorized_chain", "all", "c4_manifest_to_pack_one_action_hosted_group ", "C4_MANIFEST_TO_PACK_ONE_ACTION_HOSTED_GROUP",
                     "c4_", ""):
            with self.subTest(case=case):
                proc, ev = self.verify(CASE_ID=case)
                self.assert_verify_fails(proc, ev, ["is not the C4 hosted group"])
        proc, ev = self.verify(CASE_ID=None)
        self.assert_verify_fails(proc, ev, ["is not the C4 hosted group"])

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
        proc, ev = self.verify(C4_PACK_SHA=None)
        self.assert_verify_fails(proc, ev, ["evidence_pack: workflow pin"])

    def test_component_root_unset_or_wrong_path(self):
        for key, env in F.ROOT_ENV.items():
            with self.subTest(key=key):
                proc, ev = self.verify(**{env: None})
                self.assert_verify_fails(proc, ev, ["%s: %s is not set" % (key, env)], allow=["fixture action_manifest_fixture"])
        proc, ev = self.verify(COGNOUS_C4_CONTROL_PLANE_ROOT=str(self.P.base / "nope"))
        self.assert_verify_fails(proc, ev, ["control_plane"])

    def test_verify_does_not_import_component_code(self):
        text = CHECKER.read_text(encoding="utf-8")
        imported = _imports(ast.parse(text))
        self.assertFalse({n for n in imported if n.startswith(("agent_", "moltbot", "tests"))})
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
        for flag in ("--assume-unchanged", "--skip-worktree"):
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
        for rel in (".github/locks/cryptography-pydantic-pytest-513753.txt", "tests/manual_contract/real_c4.py", "tests/manual_contract/c4_producer.py",
                    "tests/manual_contract/real_c3.py", "tests/manual_contract/c4/test_real_c4.py", "tests/manual_contract/c4/test_real_c4_integrity.py"):
            with self.subTest(rel=rel):
                ws, head = self.edited_workspace("ws-missing", lambda w, rel=rel: (w / rel).unlink())
                proc, ev = self.verify(ws=ws, head=head)
                self.assert_verify_fails(proc, ev, ["host source %s is missing" % rel])
                shutil.rmtree(ws, ignore_errors=True)

    def test_altered_host_source_is_recorded_not_golden(self):
        # the host-source hashes of the C4 files are recorded for the manifest and compared with the harness report, not frozen here
        ws, head = self.edited_workspace("ws-realc4", lambda w: (w / "tests/manual_contract/real_c4.py").write_bytes(
            (w / "tests/manual_contract/real_c4.py").read_bytes() + b"\n# altered\n"))
        proc, ev = self.verify(ws=ws, head=head)
        self.assertEqual(proc.returncode, 0, proc.stderr[-600:])
        ctx = F.read_json(ev / "context.json")
        self.assertNotEqual(ctx["host_sources"]["tests/manual_contract/real_c4.py"], F.read_json(self.P.ev / "context.json")["host_sources"]["tests/manual_contract/real_c4.py"])


class VerifyDependencyTests(Base):
    def test_missing_dependency_pydantic_absent(self):
        venv = self.P.base / "venv-nodeps"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, capture_output=True, timeout=300)
        py = venv / "bin" / "python"
        probe = subprocess.run([str(py), "-I", "-c", "import importlib.metadata as m,sys\ntry:\n m.version('pydantic');sys.exit(1)\nexcept m.PackageNotFoundError:\n sys.exit(0)"])
        self.assertEqual(probe.returncode, 0, "the no-dependency interpreter unexpectedly has pydantic")
        ev = self.P.base / "ev-nodeps"
        proc = subprocess.run([str(py), "-I", "-B", F.CHECKER_REL, "verify"], env=self.P.env(ev=ev), cwd=str(self.P.ws), capture_output=True, text=True, timeout=300)
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

    def counts(self):
        return list(zip(F.SUITE_PATTERNS, self.P.expected))

    def test_failed_suite_exit_code(self):
        for i, pat in enumerate(F.SUITE_PATTERNS):
            with self.subTest(pat=pat):
                run = self.run_mut(self.tj_edit(lambda d, i=i: d["suites"][i].__setitem__("exit_code", 1)))
                self.assert_cause(run, ["suite %s exit code" % pat])

    def test_skip_exit_code_3(self):
        run = self.run_mut(self.tj_edit(lambda d: d["suites"][0].__setitem__("exit_code", 3)))
        self.assert_cause(run, ["suite test_real_c4.py exit code"])

    def test_short_suite_observed_count(self):
        for i, (pat, n) in enumerate(self.counts()):
            for bad in (n - 1, 0, n + 1, None, str(n), float(n)):
                with self.subTest(pat=pat, bad=bad):
                    run = self.run_mut(self.tj_edit(lambda d, i=i, bad=bad: d["suites"][i].__setitem__("observed_tests", bad)))
                    self.assert_cause(run, ["suite %s observed tests" % pat])

    def test_wrong_expected_count_recorded_in_tests_json(self):
        for i, pat in enumerate(F.SUITE_PATTERNS):
            with self.subTest(pat=pat):
                run = self.run_mut(self.tj_edit(lambda d, i=i: d["suites"][i].__setitem__("expected_tests", 1)))
                self.assert_cause(run, ["suite %s expected tests" % pat])

    def test_workflow_supplied_expected_count_differs_from_what_ran(self):
        for env_name, pat, n in zip(F.EXPECTED_ENV, F.SUITE_PATTERNS, self.P.expected):
            with self.subTest(env=env_name):
                run = self.run_mut(lambda ev: None, **{env_name: str(n + 1)})
                self.assert_cause(run, ["suite %s expected tests" % pat, "suite %s observed tests" % pat, "tests.log contains", "tests.log observed counts"])

    def test_expected_count_env_missing_or_malformed(self):
        for env_name in F.EXPECTED_ENV:
            for bad in (None, "", "abc", "0", "-1", "1.5", " 5", "05", "99999999"):
                with self.subTest(env=env_name, bad=bad):
                    run = self.run_mut(lambda ev: None, **{env_name: bad})
                    self.assert_cause(run, ["%s is set to a positive integer" % env_name], allow=["suite test_real_c4", "tests.log contains", "tests.log observed counts"])

    def test_suite_dropped_or_extra(self):
        run = self.run_mut(self.tj_edit(lambda d: d["suites"].pop()))
        self.assert_cause(run, ["tests.json lists exactly two suites"], allow=["suite test_real_c4_integrity.py"])
        run = self.run_mut(self.tj_edit(lambda d: d["suites"].append(dict(d["suites"][0]))))
        self.assert_cause(run, ["tests.json lists exactly two suites"])
        run = self.run_mut(self.tj_edit(lambda d: d.pop("suites")))
        self.assert_cause(run, ["tests.json lists exactly two suites"], allow=["suite test_real_c4"])

    def test_outcome_not_passed(self):
        for bad in ("FAILED", "passed", None):
            with self.subTest(bad=bad):
                run = self.run_mut(self.tj_edit(lambda d, bad=bad: d.__setitem__("outcome", bad)))
                self.assert_cause(run, ["tests.json outcome"])

    def test_log_ran_count_wrong(self):
        for n in self.P.expected:
            with self.subTest(n=n):
                run = self.run_mut(self.log(lambda t, n=n: t.replace("Ran %d tests" % n, "Ran %d tests" % (n + 1), 1)))
                self.assert_cause(run, ["tests.log contains", "tests.log observed counts"])

    def test_log_missing_or_empty(self):
        run = self.run_mut(self.log(lambda t: ""))
        self.assert_cause(run, ["artifact tests.log present and non-empty"], allow=["tests.log contains", "tests.log observed counts", "tests.log reports OK"])

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
        self.assert_cause(self.run_mut(m), ["cases.json harness exit code"])
        self.assert_cause(self.run_mut(lambda ev: F.write_json(ev / "cases.json", {"exit_code": "0"})), ["cases.json harness exit code"])
        self.assert_cause(self.run_mut(lambda ev: F.write_json(ev / "cases.json", {"exit_codes": {"c": 0}})), ["cases.json harness exit code"])

    def test_cases_json_case_ids_when_listed(self):
        run = self.run_mut(lambda ev: F.write_json(ev / "cases.json", {"exit_code": 0, "cases": [P1, N1]}))
        self.assert_cause(run, ["cases.json case ids"])


class CaseResultMutationTests(Base):
    def test_missing_case_result(self):
        for case in CASES:
            with self.subTest(case=case):
                run = self.run_mut(self.res(lambda r, case=case: r.pop(case)))
                self.assert_cause(run, ["c4.result.json holds exactly the three C4 case ids", "case %s result is an object" % case],
                                  allow=["P1 ", "N1-HOLD", "N2-FLIP", "limits", "claim", "slice", "every mandatory", "files index", "harness block"])

    def test_extra_case_result(self):
        run = self.run_mut(self.res(lambda r: r.__setitem__("c4_extra_case", {"status": "PASS"})))
        self.assert_cause(run, ["c4.result.json holds exactly the three C4 case ids"])

    def test_case_not_an_object(self):
        run = self.run_mut(self.res(lambda r: r.__setitem__(N1, "PASS")))
        self.assert_cause(run, ["case %s result is an object" % N1], allow=["c4.result.json holds exactly", "N1-HOLD", "N2-FLIP", "slice", "every mandatory", "limits", "claim"])

    def test_result_root_not_an_object(self):
        run = self.run_mut(lambda ev: (ev / "c4.result.json").write_text("[]\n", encoding="utf-8"))
        self.assert_cause(run, ["c4.result.json is a JSON object"], allow=["P1 ", "N1-HOLD", "N2-FLIP", "slice", "every mandatory", "limits", "claim", "retained native"])

    def test_wrong_case_schema_scenario_or_id(self):
        for case in CASES:
            for field, bad in (("schema", "other/0"), ("case_id", "c4_other"), ("scenario", "authorized" if case != P1 else "grant_revoked")):
                with self.subTest(case=case, field=field):
                    run = self.run_mut(self.res(lambda r, case=case, field=field, bad=bad: r[case].__setitem__(field, bad)))
                    self.assert_cause(run, ["%s %s" % (LABEL[case], field)], allow=["producer scenario"])

    def test_harness_pass_status_is_necessary_but_never_sufficient(self):
        for case in CASES:
            with self.subTest(case=case):
                run = self.run_mut(self.res(lambda r, case=case: r[case].__setitem__("status", "FAIL")))
                self.assert_cause(run, ["%s harness status" % LABEL[case]])
                run = self.run_mut(self.res(lambda r, case=case: r[case]["oracle"].__setitem__("all_ok", False)))
                self.assert_cause(run, ["%s harness status" % LABEL[case]])

    def test_harness_source_hashes_and_head(self):
        for case in CASES:
            lab = LABEL[case]
            with self.subTest(case=case):
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["harness"].__setitem__("c2_producer_sha256", "0" * 64))), ["%s harness c2_producer.py sha256" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["harness"].__setitem__("real_c4_sha256", "0" * 64))), ["%s harness real_c4.py" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["harness"].__setitem__("c4_producer_sha256", "0" * 64))), ["%s harness real_c4.py" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["harness"].__setitem__("real_c3_sha256", "0" * 64))), ["%s harness real_c4.py" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["harness"]["orchestrator"].__setitem__("head", "0" * 40))), ["%s harness orchestrator head" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["harness"]["orchestrator"].__setitem__("tracked_files_modified", True))),
                                  ["%s harness orchestrator head" % lab])

    def test_proposal_and_manifest_hash_in_harness_evidence(self):
        for case in CASES:
            lab = LABEL[case]
            with self.subTest(case=case):
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["inputs"]["proposal"].__setitem__("sha256", "0" * 64))), ["%s harness-reported proposal sha256" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["inputs"]["manifest"].__setitem__("sha256", "0" * 64))), ["%s harness-reported manifest sha256" % lab])

    def test_am_gate_values_altered(self):
        for case in (P1, N1):
            lab = LABEL[case]
            with self.subTest(case=case, what="gate"):
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: self.boundary(r, case, "action_manifest")["native_result"].__setitem__("valid", False))),
                                  ["%s AM gate native result" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: self.boundary(r, case, "action_manifest")["native_result"].__setitem__("proposal_mismatches", ["manifest_digest_mismatch"]))),
                                  ["%s AM gate native result" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: self.boundary(r, case, "action_manifest")["native_result"].__setitem__("manifest_digest", "sha256:" + "0" * 64))),
                                  ["%s AM gate native result" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["am_gate"].__setitem__("passed", False))), ["%s harness am_gate passed" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["am_gate"].__setitem__("proposal_digest", "sha256:" + "0" * 64))), ["%s harness am_gate digests" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: self.boundary(r, case, "action_manifest").__setitem__("orchestration_class", "BLOCKED"))),
                                  ["%s AM boundary orchestration class" % lab, "%s action_manifest orchestration class" % lab])

    def test_am_boundary_input_hash_disagrees_with_retained_input(self):
        for case in (P1, N1):
            with self.subTest(case=case):
                run = self.run_mut(self.res(lambda r, case=case: self.boundary(r, case, "action_manifest").__setitem__("input_sha256", "0" * 64)))
                self.assert_cause(run, ["%s AM boundary input sha256" % LABEL[case]])

    def test_measured_source_identity_in_result(self):
        for case in CASES:
            lab = LABEL[case]
            with self.subTest(case=case, what="head"):
                def bad_head(r, case=case):
                    r[case]["sources"]["sources"]["evidence_pack"]["observed_head"] = "0" * 40
                self.assert_cause(self.run_mut(self.res(bad_head)), ["%s measured evidence_pack head/tree" % lab])

                def dirty(r, case=case):
                    r[case]["sources"]["sources"]["action_manifest"]["status_ignored_clean"] = False
                self.assert_cause(self.run_mut(self.res(dirty)), ["%s action_manifest clean flags" % lab])

    def test_runtime_versions_in_result_differ_from_context(self):
        run = self.run_mut(self.res(lambda r: r[N2]["runtime"].__setitem__("pydantic", "1.0.0")))
        self.assert_cause(run, ["N2-FLIP runtime versions == context"])

    def test_producer_provenance_altered(self):
        cases = [("calls", ["decide", "execute"]), ("scenario", "other"), ("scenario_mutation", "grant_status=expired"), ("manifest_source", "cp_repo_copy"),
                 ("manifest_equals_cp_repo_copy", False)]
        for case in (P1, N1):
            for key, bad in cases:
                with self.subTest(case=case, key=key):
                    run = self.run_mut(self.res(lambda r, case=case, key=key, bad=bad: r[case]["producer"].__setitem__(key, bad)))
                    self.assert_cause(run, ["%s producer" % LABEL[case]])
        run = self.run_mut(self.res(lambda r: r[P1]["producer"].__setitem__("config_id", "C2-CP-RUNTIME-PROFILE-STRICT-TENANT-DECIDE-ONLY")))
        self.assert_cause(run, ["P1 producer config id"])

    def test_destination_effects_nonzero(self):
        for case in (P1, N1):
            lab = LABEL[case]
            with self.subTest(case=case, what="result"):
                run = self.run_mut(self.res(lambda r, case=case: r[case]["destination"].update({"effect_count": 1, "effects": {"e1": {}}})))
                self.assert_cause(run, ["%s destination effect count and effects" % lab])

            with self.subTest(case=case, what="file"):
                run = self.run_mut(self.edit("c4.%s.destination.json" % SHORT[case], lambda d: d.__setitem__("effects", {"e1": {"amount": 5}}), case))
                self.assert_cause(run, ["%s destination effects (retained destination file)" % lab])

    def test_n2_destination_effects_nonzero_or_no_effect_false(self):
        for k, bad in (("effects_after", {"e1": {"amount": 1}}), ("effects_before", {"e1": 1}), ("no_effect", False), ("no_effect", None)):
            with self.subTest(key=k, bad=bad):
                run = self.run_mut(self.res(lambda r, k=k, bad=bad: r[N2]["destination"].__setitem__(k, bad)))
                self.assert_cause(run, ["N2-FLIP destination no_effect / before / after"])

    def test_p1_pack_validation_harness_reported(self):
        for case in (P1, N1):
            lab = LABEL[case]
            with self.subTest(case=case):
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["native"]["pack"]["validation"].__setitem__("valid", False))), ["%s Pack validation valid" % lab])
                self.assert_cause(self.run_mut(self.res(lambda r, case=case: r[case]["native"]["pack"]["validation"].__setitem__("errors", [{"code": "E1"}]))),
                                  ["%s Pack validation errors" % lab])


# ======================================================================================= N1-HOLD specific
class HoldMutationTests(Base):
    """Mutations of the hold path: CP record, Replay bundle, Pack dump and the boundary vector (all coherent with the reported hashes)."""

    def test_cp_result_flipped_to_authorized(self):
        run = self.run_mut(self.record(N1, lambda d: d["decisions"][0].__setitem__("result", "authorized")))
        self.assert_cause(run, ["N1-HOLD CP result"], allow=["N1-HOLD retained decision"])

    def test_cp_reasons_altered(self):
        for bad in ([], ["grant_expired"], ["grant_revoked", "extra"], ["required_evidence_not_current"], None, "grant_revoked"):
            with self.subTest(bad=bad):
                run = self.run_mut(self.record(N1, lambda d, bad=bad: d["decisions"][0].__setitem__("reasons", bad)))
                self.assert_cause(run, ["N1-HOLD CP reasons"])

    def test_cp_binding_present(self):
        run = self.run_mut(self.record(N1, lambda d: d["decisions"][0].__setitem__("binding", {"tenant_id": "tenant-alpha"})))
        self.assert_cause(run, ["N1-HOLD CP binding is null"])

    def test_cp_effect_id_altered(self):
        for bad in (EFFECT_AUTH, "sha256:" + "0" * 64, None):
            with self.subTest(bad=bad):
                run = self.run_mut(self.record(N1, lambda d, bad=bad: d["decisions"][0].__setitem__("effect_id", bad)))
                self.assert_cause(run, ["N1-HOLD CP effect_id (hold)"])

    def test_cp_horizon_and_attempts(self):
        run = self.run_mut(self.record(N1, lambda d: d["decisions"][0]["operation_horizon"].__setitem__("proposal_commitment", "sha256:" + "0" * 64)))
        self.assert_cause(run, ["N1-HOLD CP decision operation_horizon.proposal_commitment"])
        run = self.run_mut(self.record(N1, lambda d: d.__setitem__("attempts", [{"attempt_id": "a1"}])))
        self.assert_cause(run, ["N1-HOLD attempts/observations/reconciliations/closeouts/refusals empty"])

    def test_cp_check_events_altered(self):
        run = self.run_mut(self.record(N1, lambda d: d["check_events"].pop()))
        self.assert_cause(run, ["N1-HOLD CP record has 13 check_events"], allow=["N1-HOLD CP check_events"])
        run = self.run_mut(self.record(N1, lambda d: d["check_events"][0].__setitem__("decision_id", "d1")))
        self.assert_cause(run, ["N1-HOLD CP check_events: every decision_id is null"])

    def test_chain_verdict_overwritten_to_accepted(self):
        for bad in ({"class": "ACCEPTED", "boundary": None}, {"class": "ACCEPTED", "boundary": "control_plane"}, {"class": "REFUSED_NATIVE", "boundary": "evidence_pack"},
                    {"class": "REFUSED_NATIVE", "boundary": "replay_bundle"}, {"class": "BLOCKED", "boundary": "control_plane"}):
            with self.subTest(bad=bad):
                run = self.run_mut(self.res(lambda r, bad=bad: r[N1].__setitem__("chain_verdict", bad)))
                self.assert_cause(run, ["N1-HOLD chain verdict"])

    def test_control_plane_refusal_overwritten(self):
        for bad in ("ACCEPTED", "FAILED", "BLOCKED", "NOT_EXECUTED"):
            with self.subTest(bad=bad):
                run = self.run_mut(self.res(lambda r, bad=bad: self.boundary(r, N1, "control_plane").__setitem__("orchestration_class", bad)))
                self.assert_cause(run, ["N1-HOLD control_plane orchestration class"])
        run = self.run_mut(self.res(lambda r: self.boundary(r, N1, "control_plane").__setitem__("native_outcome", "authorized")))
        self.assert_cause(run, ["N1-HOLD control_plane native outcome"])
        run = self.run_mut(self.res(lambda r: self.boundary(r, N1, "control_plane")["native_result"].__setitem__("binding_present", True)))
        self.assert_cause(run, ["N1-HOLD control_plane binding present"])

    def test_downstream_class_relabelled_refused_native(self):
        for name in ("replay_bundle", "evidence_pack"):
            for bad in ("REFUSED_NATIVE", "FAILED", "BLOCKED", "NOT_EXECUTED"):
                with self.subTest(name=name, bad=bad):
                    run = self.run_mut(self.res(lambda r, name=name, bad=bad: self.boundary(r, N1, name).__setitem__("orchestration_class", bad)))
                    self.assert_cause(run, ["N1-HOLD %s orchestration class" % name])

    def test_retains_upstream_refusal_false(self):
        for name in ("replay_bundle", "evidence_pack"):
            for bad in (False, None, "true", 1):
                with self.subTest(name=name, bad=bad):
                    run = self.run_mut(self.res(lambda r, name=name, bad=bad: self.boundary(r, N1, name).__setitem__("retains_upstream_refusal", bad)))
                    self.assert_cause(run, ["N1-HOLD %s retains_upstream_refusal" % name])

    def test_carried_authorization_state_authorized(self):
        for name in ("replay_bundle", "evidence_pack"):
            for bad in ("authorized", None, "denied", "HELD"):
                with self.subTest(name=name, bad=bad):
                    run = self.run_mut(self.res(lambda r, name=name, bad=bad: self.boundary(r, N1, name).__setitem__("carried_authorization_state", bad)))
                    self.assert_cause(run, ["N1-HOLD %s carried authorization state" % name])

    def test_boundary_order_changed_or_boundary_dropped(self):
        run = self.run_mut(self.res(lambda r: r[N1]["boundaries"].reverse()))
        self.assert_cause(run, ["N1-HOLD boundary order"], allow=["N1-HOLD"])
        run = self.run_mut(self.res(lambda r: r[N1]["boundaries"].pop()))
        self.assert_cause(run, ["N1-HOLD boundary order"], allow=["N1-HOLD evidence_pack"])

    def test_replay_findings_missing_b005(self):
        def drop(d):
            for rep in d["import_reports"]:
                rep["findings"] = [f for f in rep["findings"] if f["code"] != "B005"]
        run = self.run_mut(self.bundle(N1, drop))
        self.assert_cause(run, ["N1-HOLD Replay findings set {B004, B005}", "N1-HOLD Replay findings are warnings only"],
                          allow=["N1-HOLD Pack", "N2-FLIP", "bundle H2", "input_artifacts[1]", "retained_sources"])

    def test_replay_findings_extra_code(self):
        def add(d):
            d["import_reports"][0]["findings"].append({"code": "B002", "severity": "warning", "category": "x", "path": "p", "message": "m", "value_state": "absent"})
        run = self.run_mut(self.bundle(N1, add))
        self.assert_cause(run, ["N1-HOLD Replay findings set {B004, B005}", "N1-HOLD Replay findings are warnings only"],
                          allow=["N1-HOLD Pack", "N2-FLIP", "bundle H2", "input_artifacts[1]", "retained_sources"])

    def test_replay_status_forged_complete(self):
        run = self.run_mut(self.bundle(N1, lambda d: d.__setitem__("status", "reconstruction_complete")))
        self.assert_cause(run, ["N1-HOLD Replay status (bundle file)"], allow=["N1-HOLD Pack", "N2-FLIP", "bundle H2", "input_artifacts[1]", "retained_sources", "no positive claim"])

    def test_bundle_decision_result_authorized(self):
        def f(d):
            d["records"][decision_index(d)]["data"]["result"] = "authorized"
        run = self.run_mut(self.bundle(N1, f))
        self.assert_cause(run, ["N1-HOLD bundle runtime_decision.data.result is hold", "N1-HOLD no 'authorized' value"],
                          allow=["N1-HOLD bundle decision reasons", "N1-HOLD Pack", "N2-FLIP", "bundle H2", "input_artifacts[1]", "retained_sources"])

    def test_bundle_decision_binding_forged_present(self):
        def f(d):
            d["records"][decision_index(d)]["data"]["binding"] = {"tenant_id": "tenant-alpha"}
        run = self.run_mut(self.bundle(N1, f))
        self.assert_cause(run, ["N1-HOLD bundle decision reasons / binding / effect_id"], allow=["N1-HOLD Pack", "N2-FLIP", "bundle H2", "input_artifacts[1]", "retained_sources"])

    def test_pack_authorization_authorized(self):
        for bad in ("authorized", "denied", None, "HELD"):
            with self.subTest(bad=bad):
                run = self.run_mut(self.pack(N1, lambda d, bad=bad: d["metadata"]["traceable_import"]["lifecycle_summary"].__setitem__("authorization", bad)))
                self.assert_cause(run, ["N1-HOLD Pack lifecycle authorization is held"])

    def test_pack_held_and_granted_counts(self):
        for key, bad in (("authorization_held_count", 0), ("authorization_held_count", 2), ("authorization_held_count", True), ("authorization_held_count", "1"),
                         ("authorization_granted_count", 1), ("authorization_granted_count", True), ("authorization_granted_count", None)):
            with self.subTest(key=key, bad=bad):
                run = self.run_mut(self.pack(N1, lambda d, key=key, bad=bad: dcounts(d).__setitem__(key, bad)))
                self.assert_cause(run, ["N1-HOLD Pack authorization_held_count / authorization_granted_count"])
        run = self.run_mut(self.pack(N1, lambda d: dcounts(d).pop("authorization_held_count")))
        self.assert_cause(run, ["N1-HOLD Pack authorization_held_count / authorization_granted_count"])

    def test_pack_lifecycle_execution_fields(self):
        for key, bad in (("execution_attempted", "yes"), ("destination_observed", "applied"), ("independent_verification", "available"), ("reconstruction_status", "reconstruction_complete")):
            with self.subTest(key=key):
                run = self.run_mut(self.pack(N1, lambda d, key=key, bad=bad: d["metadata"]["traceable_import"]["lifecycle_summary"].__setitem__(key, bad)))
                self.assert_cause(run, ["N1-HOLD Pack lifecycle"])

    def test_pack_retained_decision_flipped_to_authorized(self):
        def f(d):
            rb = d["metadata"]["traceable_import"]["retained_sources"]["reconstruction_bundle"]
            rb["records"][decision_index(rb)]["data"]["result"] = "authorized"
        run = self.run_mut(self.pack(N1, f))
        self.assert_cause(run, ["N1-HOLD Pack retained_sources decision result is hold", "N1-HOLD no 'authorized' value", "N1-HOLD Pack retained_sources.reconstruction_bundle == parsed bundle file"])

    def test_effect_id_and_identity_altered_in_harness_result(self):
        run = self.run_mut(self.res(lambda r: r[N1]["identity"].__setitem__("effect_id", EFFECT_AUTH)))
        self.assert_cause(run, ["N1-HOLD identity.effect_id"])
        run = self.run_mut(self.res(lambda r: r[N1]["identity"]["stable"].__setitem__("tenant_id", "tenant-beta")))
        self.assert_cause(run, ["N1-HOLD identity.stable tuple"])
        run = self.run_mut(self.res(lambda r: r[N1]["identity"]["per_run"].__setitem__("decision_id", "00000000-0000-0000-0000-000000000000")))
        self.assert_cause(run, ["N1-HOLD identity decision_id"])

    def test_p1_vector_overwritten(self):
        run = self.run_mut(self.res(lambda r: r[P1].__setitem__("chain_verdict", {"class": "REFUSED_NATIVE", "boundary": "control_plane"})))
        self.assert_cause(run, ["P1 chain verdict class"])
        run = self.run_mut(self.res(lambda r: self.boundary(r, P1, "control_plane").__setitem__("carried_authorization_state", "held")))
        self.assert_cause(run, ["P1 control_plane carried authorization state"])
        run = self.run_mut(self.res(lambda r: self.boundary(r, P1, "evidence_pack").__setitem__("retains_upstream_refusal", True)))
        self.assert_cause(run, ["P1 evidence_pack retains_upstream_refusal false"])
        run = self.run_mut(self.res(lambda r: self.boundary(r, P1, "replay_bundle").__setitem__("orchestration_class", "REFUSED_NATIVE")))
        self.assert_cause(run, ["P1 replay_bundle orchestration class ACCEPTED"])


# ======================================================================================= P1 specific
class P1MutationTests(Base):
    def test_cp_record_fields(self):
        cases = [("P1 CP result / reasons", lambda d: d["decisions"][0].__setitem__("result", "hold")),
                 ("P1 CP result / reasons", lambda d: d["decisions"][0].__setitem__("reasons", ["grant_revoked"])),
                 ("P1 CP effect_id", lambda d: d["decisions"][0].__setitem__("effect_id", EFFECT_HOLD)),
                 ("P1 CP binding manifest_digest / proposal_commitment", lambda d: d["decisions"][0]["binding"].__setitem__("manifest_digest", "sha256:" + "0" * 64)),
                 ("P1 CP binding tenant / generation / action_id", lambda d: d["decisions"][0]["binding"].__setitem__("tenant_id", "tenant-beta")),
                 ("P1 CP binding runtime_authority.profile", lambda d: d["decisions"][0]["binding"]["runtime_authority"].__setitem__("profile", "other/1")),
                 ("P1 CP decision time_source / decided_at / vocabulary", lambda d: d["decisions"][0].__setitem__("time_source", "wall_clock")),
                 ("P1 attempts/observations/reconciliations/closeouts/refusals empty", lambda d: d.__setitem__("observations", [{"o": 1}]))]
        for needle, fn in cases:
            with self.subTest(needle=needle):
                run = self.run_mut(self.record(P1, fn))
                self.assert_cause(run, [needle], allow=["P1 retained decision"])

    def test_cp_record_has_two_decisions(self):
        run = self.run_mut(self.record(P1, lambda d: d["decisions"].append(dict(d["decisions"][0]))))
        self.assert_cause(run, ["P1 native record file has exactly one decision"])

    def test_replay_bundle_fields(self):
        def f(fn):
            return self.bundle(P1, fn)
        cases = [("P1 Replay status (bundle file)", lambda d: d.__setitem__("status", "reconstruction_complete")),
                 ("P1 Replay findings: exactly B004 warning", lambda d: d["import_reports"][0].__setitem__("findings", [])),
                 ("P1 Replay import reports are not complete", lambda d: d["import_reports"][0].__setitem__("complete", True)),
                 ("P1 Replay integrity [] (bundle file)", lambda d: d.__setitem__("integrity", [{"digest": "x"}])),
                 ("P1 Replay bundle_version", lambda d: d.__setitem__("bundle_version", "0.3.0")),
                 ("P1 Replay record types", lambda d: d["records"].append({"record_type": "destination_attempt", "data": {"attempt_id": "a1"}}))]
        for needle, fn in cases:
            with self.subTest(needle=needle):
                run = self.run_mut(f(fn))
                self.assert_cause(run, [needle], allow=["P1 Replay", "P1 Pack", "bundle H2", "input_artifacts[1]", "retained_sources", "no positive claim", "N2-FLIP"])

    def test_bundle_retained_decision_fields(self):
        def f(fn):
            return self.bundle(P1, lambda d: fn(d["records"][decision_index(d)]["data"]))
        cases = [("P1 retained decision effect_id", lambda x: x.__setitem__("effect_id", EFFECT_HOLD)),
                 ("P1 retained decision result", lambda x: x.__setitem__("result", "hold")),
                 ("P1 retained decision proposal commitment", lambda x: x["binding"].__setitem__("proposal_commitment", "sha256:" + "0" * 64)),
                 ("P1 retained decision tenant / generation", lambda x: x["binding"].__setitem__("tenant_id", "tenant-beta")),
                 ("P1 retained decision_id == native record file decision_id", lambda x: x.__setitem__("decision_id", "other-id"))]
        for needle, fn in cases:
            with self.subTest(needle=needle):
                run = self.run_mut(f(fn))
                self.assert_cause(run, [needle], allow=["P1 Pack", "P1 retained decision", "bundle H2", "input_artifacts[1]", "retained_sources", "N2-FLIP"])

    def test_pack_frozen_fields_each_mutated(self):
        T = lambda d: d["metadata"]["traceable_import"]  # noqa: E731
        cases = [("Pack pack_version", lambda d: d.__setitem__("pack_version", "0.3.0")),
                 ("Pack review_status draft", lambda d: d.__setitem__("review_status", "approved")),
                 ("Pack transformation_version", lambda d: T(d).__setitem__("transformation_version", "other")),
                 ("Pack selected_revisions", lambda d: T(d)["selected_revisions"].__setitem__("replay", "0" * 40)),
                 ("Pack replay_semantic_validation", lambda d: T(d)["replay_semantic_validation"].__setitem__("status", "validated_complete")),
                 ("Pack reconstruction_completeness", lambda d: T(d).__setitem__("reconstruction_completeness", "reconstruction_complete")),
                 ("Pack replay_semantics flags", lambda d: T(d)["replay_semantics"].__setitem__("external_effect_execution", True)),
                 ("Pack replay_bundles[0] status/signed/redacted/validation_status", lambda d: d["replay_bundles"][0].__setitem__("signed", True)),
                 ("Pack input_artifacts[0].hash == Action Manifest canonical digest", lambda d: T(d)["input_artifacts"][0].__setitem__("hash", "sha256:" + "0" * 64)),
                 ("Pack retained_sources.reconstruction_bundle == parsed bundle file", lambda d: T(d)["retained_sources"]["reconstruction_bundle"].__setitem__("status", "reconstruction_complete")),
                 ("Pack retained_sources.manifest == Action Manifest input file parsed", lambda d: T(d)["retained_sources"]["manifest"].__setitem__("manifest_id", "other"))]
        for case in (P1, N1):
            for needle, fn in cases:
                with self.subTest(case=case, needle=needle):
                    run = self.run_mut(self.pack(case, fn))
                    self.assert_cause(run, ["%s %s" % (LABEL[case], needle)])

    def test_p1_pack_lifecycle(self):
        for key, bad in (("authorization", "held"), ("current_permission", "granted"), ("execution_attempted", "yes"), ("destination_observed", "applied"),
                         ("independent_verification", "available"), ("reconstruction_status", "reconstruction_complete")):
            with self.subTest(key=key):
                run = self.run_mut(self.pack(P1, lambda d, key=key, bad=bad: d["metadata"]["traceable_import"]["lifecycle_summary"].__setitem__(key, bad)))
                self.assert_cause(run, ["P1 Pack lifecycle_summary"])

    def test_p1_chain_and_identity_in_harness_result(self):
        run = self.run_mut(self.res(lambda r: r[P1]["identity"].__setitem__("effect_id", EFFECT_HOLD)))
        self.assert_cause(run, ["P1 identity.effect_id"])
        run = self.run_mut(self.res(lambda r: r[P1]["identity"]["stable"].__setitem__("proposal_commitment", "sha256:" + "0" * 64)))
        self.assert_cause(run, ["P1 identity.stable tuple"])
        run = self.run_mut(self.res(lambda r: self.boundary(r, P1, "control_plane").__setitem__("native_outcome", "hold")))
        self.assert_cause(run, ["P1 control_plane native outcome"])


# ======================================================================================= N2-FLIP specific
class N2MutationTests(Base):
    MSG = "N2-FLIP native exception message"

    def exc(self, field, value):
        return self.res(lambda r: self.boundary(r, N2, "evidence_pack")["native_exception"].__setitem__(field, value))

    def test_native_message_altered(self):
        base = "decision %s is authorized but has no binding"
        did = F.read_json(self.P.ev / "c4.n1.cp-record.json")["decisions"][0]["decision_id"]
        msg = base % did
        for bad in (msg[:-1], msg + ".", msg.replace("decision", "Decision"), "", None, msg.upper(), base % "00000000-0000-0000-0000-000000000000",
                    "pinned Replay semantic validation failed: " + msg):
            with self.subTest(bad=bad):
                run = self.run_mut(self.exc("message", bad))
                self.assert_cause(run, [self.MSG])

    def test_wrong_exception_type_or_code(self):
        for bad in ("ValueError", "ImportError", "", None, "importcontracterror"):
            with self.subTest(type=bad):
                run = self.run_mut(self.exc("type", bad))
                self.assert_cause(run, ["N2-FLIP native exception type"])
        for bad in (0, 1, "E1", False, "None"):
            with self.subTest(code=bad):
                run = self.run_mut(self.exc("code", bad))
                self.assert_cause(run, ["N2-FLIP native exception code"])

    def test_native_exception_dropped(self):
        run = self.run_mut(self.res(lambda r: self.boundary(r, N2, "evidence_pack").__setitem__("native_exception", None)))
        self.assert_cause(run, ["N2-FLIP native exception type", "N2-FLIP native exception message"])

    def test_refused_native_downgraded_to_imported(self):
        run = self.run_mut(self.res(lambda r: self.boundary(r, N2, "evidence_pack").__setitem__("orchestration_class", "ACCEPTED")))
        self.assert_cause(run, ["N2-FLIP evidence_pack orchestration class"])
        run = self.run_mut(self.res(lambda r: self.boundary(r, N2, "evidence_pack").__setitem__("native_outcome", "IMPORTED")))
        self.assert_cause(run, ["N2-FLIP evidence_pack native_outcome"])
        for bad in ({"class": "ACCEPTED", "boundary": None}, {"class": "ACCEPTED", "boundary": "evidence_pack"}, {"class": "REFUSED_NATIVE", "boundary": "control_plane"}):
            with self.subTest(bad=bad):
                run = self.run_mut(self.res(lambda r, bad=bad: r[N2].__setitem__("chain_verdict", bad)))
                self.assert_cause(run, ["N2-FLIP chain verdict"])

    def test_upstream_boundaries_fabricated_as_executed(self):
        for name in ("action_manifest", "control_plane", "replay_bundle"):
            for bad in ("ACCEPTED", "REFUSED_NATIVE"):
                with self.subTest(name=name, bad=bad):
                    run = self.run_mut(self.res(lambda r, name=name, bad=bad: self.boundary(r, N2, name).__setitem__("orchestration_class", bad)))
                    self.assert_cause(run, ["N2-FLIP %s is NOT_EXECUTED" % name])

    def test_mutated_bundle_differs_in_two_paths(self):
        def f(d):
            d["records"][decision_index(d)]["data"]["result"] = "authorized"
            d["status"] = "reconstruction_complete"
        run = self.run_mut(self.edit("c4.n2.mutated-bundle.json", f, coherent=False))
        self.assert_cause(run, ["N2-FLIP mutated bundle differs from the N1 bundle in exactly one path"],
                          allow=["N2-FLIP harness mutated", "N2-FLIP Pack boundary input", "files index", "harness-reported file hashes", "N2-FLIP mutated bundle file bytes"])

    def test_mutated_bundle_not_flipped_at_all(self):
        run = self.run_mut(lambda ev: shutil.copyfile(ev / "c4.n1.reconstruction-bundle.json", ev / "c4.n2.mutated-bundle.json"))
        self.assert_cause(run, ["N2-FLIP mutated bundle differs from the N1 bundle in exactly one path", "N2-FLIP original value hold -> mutated value authorized"],
                          allow=["N2-FLIP harness mutated", "N2-FLIP Pack boundary input", "harness-reported file hashes", "N2-FLIP original and mutated H2 differ"])

    def test_mutated_bundle_flipped_other_direction_or_value(self):
        def f(d):
            d["records"][decision_index(d)]["data"]["result"] = "deny"
        run = self.run_mut(self.edit("c4.n2.mutated-bundle.json", f, coherent=False))
        self.assert_cause(run, ["N2-FLIP original value hold -> mutated value authorized"],
                          allow=["N2-FLIP harness mutated", "N2-FLIP Pack boundary input", "harness-reported file hashes"])

    def test_mutated_bundle_other_path_changed_instead(self):
        def f(d):
            d["records"][decision_index(d)]["data"]["reasons"] = ["grant_expired"]
        run = self.run_mut(self.edit("c4.n2.mutated-bundle.json", f, coherent=False))
        self.assert_cause(run, ["N2-FLIP mutated bundle differs from the N1 bundle in exactly one path"],
                          allow=["N2-FLIP harness mutated", "N2-FLIP Pack boundary input", "harness-reported file hashes", "N2-FLIP mutated bundle file bytes"])

    def test_mutated_bundle_missing_or_corrupt(self):
        run = self.run_mut(lambda ev: (ev / "c4.n2.mutated-bundle.json").unlink())
        self.assertEqual(run.rc, 1, run.describe())
        self.assertTrue(any("c4.n2.mutated-bundle.json" in ln for ln in run.fails), run.describe())
        run = self.run_mut(lambda ev: (ev / "c4.n2.mutated-bundle.json").write_text("[1]\n", encoding="utf-8"))
        self.assertEqual(run.rc, 1, run.describe())
        self.assertTrue(any("c4.n2.mutated-bundle.json" in ln for ln in run.fails), run.describe())

    def test_original_n1_bundle_altered(self):
        # whitespace-only: still parses to the same object, but the recorded H1 for the original differs
        def m(ev):
            p = ev / "c4.n1.reconstruction-bundle.json"
            p.write_bytes(p.read_bytes() + b"\n")
        run = self.run_mut(m)
        self.assert_cause(run, ["N2-FLIP harness original_bundle_H1", "N1-HOLD bundle H1 sha256", "harness-reported file hashes"],
                          allow=["N1-HOLD bundle H2"])

    def test_original_n1_bundle_content_altered(self):
        def f(d):
            d["records"][decision_index(d)]["data"]["result"] = "authorized"  # the original already carries the flip
        run = self.run_mut(self.bundle(N1, f, coherent=False))
        self.assert_cause(run, ["N2-FLIP mutated bundle differs from the N1 bundle in exactly one path", "N1-HOLD bundle runtime_decision.data.result is hold"],
                          allow=["N1-HOLD", "N2-FLIP", "files index", "harness-reported file hashes", "no 'authorized' value", "retained_sources", "input_artifacts[1]"])

    def test_n2_harness_flags_and_identity(self):
        run = self.run_mut(self.res(lambda r: r[N2]["mutation"].__setitem__("original_unmodified_after_run", False)))
        self.assert_cause(run, ["N2-FLIP original bundle unmodified after run"])
        run = self.run_mut(self.res(lambda r: r[N2]["mutation"].__setitem__("to", "something-else")))
        self.assert_cause(run, ["N2-FLIP mutation field_path/from/to"])
        run = self.run_mut(self.res(lambda r: r[N2]["mutation"].__setitem__("manifest_supplied", False)))
        self.assert_cause(run, ["N2-FLIP original Action Manifest supplied and pinned"])
        run = self.run_mut(self.res(lambda r: r[N2]["identity"].__setitem__("n1_decision_id", "00000000-0000-0000-0000-000000000000")))
        self.assert_cause(run, ["N2-FLIP identity n1_decision_id"])
        run = self.run_mut(self.res(lambda r: r[N2]["mutation"].__setitem__("mutated_bundle_H2_pack_canonical_sha256", "sha256:" + "ab" * 32)))
        self.assert_cause(run, ["N2-FLIP harness mutated H2"])
        run = self.run_mut(self.res(lambda r: r[N2]["mutation"].__setitem__("original_bundle_H1_sha256", "0" * 64)))
        self.assert_cause(run, ["N2-FLIP harness original_bundle_H1"])

    def test_n1_record_decision_id_changed_so_expected_message_changes(self):
        # the expected N2 text is built from the retained N1 CP record, never hard-coded: changing the record changes the expectation
        run = self.run_mut(self.record(N1, lambda d: d["decisions"][0].__setitem__("decision_id", "other-decision")))
        self.assert_cause(run, [self.MSG], allow=["N1-HOLD retained decision_id", "N1-HOLD identity decision_id", "N2-FLIP identity n1_decision_id", "N1-HOLD control_plane binding present"])


# ======================================================================================= check: evidence files and hashes
class EvidenceFileTests(Base):
    def test_each_mandatory_evidence_file_missing(self):
        for name in FOUND + INPUTS:
            with self.subTest(name=name):
                run = self.run_mut(lambda ev, name=name: (ev / name).unlink())
                self.assertEqual(run.rc, 1, run.describe())
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
        needle = {}
        for s, lab in (("p1", "P1"), ("n1", "N1-HOLD")):
            needle["c4.%s.cp-record.json" % s] = "%s record sha256: recomputed from the retained file" % lab
            needle["c4.%s.reconstruction-bundle.json" % s] = "%s bundle H1 sha256: recomputed from the retained file" % lab
            needle["c4.%s.evidence-pack.json" % s] = "%s Pack file sha256: recomputed from the retained dump" % lab
        for name, nd in needle.items():
            with self.subTest(name=name):
                def m(ev, name=name):
                    p = ev / name
                    p.write_bytes(p.read_bytes() + b" ")  # whitespace only: still valid JSON, bytes differ
                run = self.run_mut(m)
                self.assert_cause(run, [nd], allow=["harness-reported file hashes", "N2-FLIP"])

    def test_inputs_corrupted(self):
        for name, nd in (("c4.inputs.am-manifest.json", "retained AM manifest input sha256 == frozen manifest file hash"),
                         ("c4.inputs.proposal.json", "retained proposal input sha256 == frozen proposal file hash")):
            with self.subTest(name=name):
                def m(ev, name=name):
                    p = ev / name
                    p.write_bytes(p.read_bytes() + b" ")
                run = self.run_mut(m)
                self.assert_cause(run, [nd], allow=["harness-reported", "AM boundary input sha256", "harness am_gate", "harness-reported file hashes", "retained AM manifest input is byte-identical"])

    def test_inputs_content_altered(self):
        def m(ev):
            d = F.read_json(ev / "c4.inputs.am-manifest.json")
            d["manifest_version"] = "9.9"
            F.write_json(ev / "c4.inputs.am-manifest.json", d)
        run = self.run_mut(m)
        self.assertEqual(run.rc, 1, run.describe())
        self.assertTrue(any("retained AM manifest input sha256" in ln for ln in run.fails), run.describe())
        self.assertTrue(any("canonical digest of the retained AM manifest input" in ln for ln in run.fails), run.describe())

    def test_destination_file_bytes_change_is_recorded_in_the_index(self):
        before = F.read_json(self.P.ev / "evidence-manifest.json")["evidence_file_sha256"]["c4.p1.destination.json"]

        def m(ev):
            p = ev / "c4.p1.destination.json"
            p.write_bytes(p.read_bytes() + b"\n\n")
        run = self.run_mut(m)
        # the harness reports a destination file hash in `files`, so a whitespace-only change IS a recorded inconsistency
        self.assert_cause(run, ["P1 harness-reported file hashes equal the hashes recomputed from the retained files"])
        self.assertNotEqual(run.manifest["evidence_file_sha256"]["c4.p1.destination.json"], before)

    def test_corrupted_hash_inside_result(self):
        for case in (P1, N1):
            lab = LABEL[case]
            cases = [("%s record sha256: recomputed from the retained file" % lab, lambda r, case=case: r[case]["identity"]["per_run"].__setitem__("cp_record_sha256", "0" * 64)),
                     ("%s bundle H1 sha256" % lab, lambda r, case=case: r[case]["identity"]["per_run"].__setitem__("bundle_h1_sha256", "0" * 64)),
                     ("%s bundle H2" % lab, lambda r, case=case: r[case]["identity"]["per_run"].__setitem__("bundle_h2_pack_canonical_sha256", "sha256:" + "0" * 64)),
                     ("%s Pack file sha256: recomputed from the retained dump" % lab, lambda r, case=case: r[case]["identity"]["per_run"].__setitem__("pack_file_sha256", "0" * 64)),
                     ("%s pack_id" % lab, lambda r, case=case: r[case]["identity"]["per_run"].__setitem__("pack_id", "agep-0000000000000000")),
                     ("%s bundle_id" % lab, lambda r, case=case: r[case]["identity"]["per_run"].__setitem__("bundle_id", "x")),
                     ("%s generated_at" % lab, lambda r, case=case: r[case]["identity"]["per_run"].__setitem__("generated_at", "2020-01-01T00:00:00+00:00")),
                     ("%s harness-reported file hashes" % lab, lambda r, case=case: r[case]["files"].__setitem__("%s/cp-record.json" % SHORT[case], "0" * 64))]
            for needle, fn in cases:
                with self.subTest(case=case, needle=needle):
                    run = self.run_mut(self.res(fn))
                    self.assert_cause(run, [needle])

    def test_n2_files_index_altered(self):
        run = self.run_mut(self.res(lambda r: r[N2]["files"].__setitem__("n2/mutated-bundle.json", "0" * 64)))
        self.assert_cause(run, ["N2-FLIP harness-reported file hashes"])

    def test_files_index_dropped(self):
        for case in CASES:
            with self.subTest(case=case):
                run = self.run_mut(self.res(lambda r, case=case: r[case].__setitem__("files", {})))
                self.assert_cause(run, ["%s files index is a non-empty object" % LABEL[case], "%s at least one reported file hash" % LABEL[case]])


class ForgeryTests(Base):
    """The harness result says PASS while the underlying retained file disagrees."""

    def test_pack_bytes_edited_result_still_says_pass(self):
        for case in (P1, N1):
            with self.subTest(case=case):
                def m(ev, case=case):
                    d = F.read_json(ev / ("c4.%s.evidence-pack.json" % SHORT[case]))
                    d["review_status"] = "approved"
                    F.write_json(ev / ("c4.%s.evidence-pack.json" % SHORT[case]), d)  # c4.result.json untouched: status PASS, oracle all_ok True, old sha
                run = self.run_mut(m)
                self.assertEqual(F.read_json(run.ev / "c4.result.json")[case]["status"], "PASS")
                lab = LABEL[case]
                self.assert_cause(run, ["%s Pack file sha256: recomputed from the retained dump" % lab, "%s Pack review_status draft" % lab],
                                  allow=["harness-reported file hashes"])

    def test_bundle_status_forged_complete_coherent_p1(self):
        run = self.run_mut(self.bundle(P1, lambda d: d.__setitem__("status", "reconstruction_complete")))
        self.assert_cause(run, ["P1 Replay status (bundle file)"], allow=["P1 Pack", "bundle H2", "input_artifacts[1]", "retained_sources", "no positive claim"])

    def test_bundle_counts_forged_extra_records_coherent(self):
        def m(d):
            d["records"].append({"record_type": "destination_attempt", "data": {"attempt_id": "a1"}})
            d["import_reports"][0]["findings"] = []
        run = self.run_mut(self.bundle(P1, m))
        self.assert_cause(run, ["P1 Replay findings: exactly B004 warning (bundle file)", "P1 Replay record types"],
                          allow=["P1 Pack", "bundle H2", "input_artifacts[1]", "retained_sources"])

    def test_record_attempt_injected_into_native_records(self):
        for case in (P1, N1):
            with self.subTest(case=case):
                run = self.run_mut(self.record(case, lambda d: d.__setitem__("attempts", [{"attempt_id": "a1"}])))
                self.assert_cause(run, ["%s attempts/observations/reconciliations/closeouts/refusals empty (native record file)" % LABEL[case]])

    def test_pack_manifest_digest_altered(self):
        def f(d):
            d["metadata"]["traceable_import"]["input_artifacts"][0]["hash"] = "sha256:" + "0" * 64
        for case in (P1, N1):
            with self.subTest(case=case):
                self.assert_cause(self.run_mut(self.pack(case, f)), ["%s Pack input_artifacts[0].hash == Action Manifest canonical digest" % LABEL[case]])


class LimitsAndClaimsTests(Base):
    def test_limits_dropped_softened_or_promoted(self):
        for n in (1, 15, 22, 27):
            def drop(r, n=n):
                r[P1]["limits"].pop("L%d" % n)
            with self.subTest(n=n, what="drop"):
                run = self.run_mut(self.res(drop))
                self.assert_cause(run, ["P1 limits keys L1..L27", "limits L%d" % n], allow=["limits identical to the P1 limits block", "limits-L1-L27.json carries"])

        def soften(r):
            r[P1]["limits"]["L1"] = "Replay is partial."
        run = self.run_mut(self.res(soften))
        self.assert_cause(run, ["limits L1 text is the C3 contract section 9 text", "limits L1 carries its key phrases"], allow=["limits identical to the P1 limits block", "limits-L1-L27.json carries"])

        def flag(r):
            r[N1]["limits"]["effect_executed"] = True
        run = self.run_mut(self.res(flag))
        self.assert_cause(run, ["N1-HOLD limits flag effect_executed"], allow=["N1-HOLD limits identical"])

        def hub(r):
            r[P1]["limits"]["hub_280_digest_basis"] = "CLOSED"
        run = self.run_mut(self.res(hub))
        self.assert_cause(run, ["P1 limits flag hub_280_digest_basis"], allow=["limits identical to the P1 limits block"])

    def test_l1_l19_not_verbatim_c3_text(self):
        for n in range(1, 20):
            with self.subTest(n=n):
                def m(r, n=n):
                    for c in CASES:
                        r[c]["limits"]["L%d" % n] = r[c]["limits"]["L%d" % n] + " (reworded)"
                run = self.run_mut(self.res(m))
                self.assert_cause(run, ["limits L%d text is the C3 contract section 9 text" % n], allow=["limits-L1-L27.json carries"])

    def test_new_c4_limits_key_phrases(self):
        bad = {20: "The proposal is produced by the Action Manifest.", 21: "The decision comes from the C1 configuration.", 22: "Replay binds the supplied proposal for a hold.",
               23: "effect_id is the same for every verdict.", 24: "run-1 is the run identity.", 25: "Orchestration labels are component statuses.",
               26: "This is a real revocation event.", 27: "The producer configuration id is persisted."}
        for n, text in bad.items():
            with self.subTest(n=n):
                def m(r, n=n, text=text):
                    for c in CASES:
                        r[c]["limits"]["L%d" % n] = text
                run = self.run_mut(self.res(m))
                self.assert_cause(run, ["limits L%d carries its key phrases" % n], allow=["limits-L1-L27.json carries"])

    def test_limit_l22_dropped_in_one_case_only(self):
        run = self.run_mut(self.res(lambda r: r[N1]["limits"].pop("L22")))
        self.assert_cause(run, ["N1-HOLD limits keys L1..L27", "N1-HOLD limits identical to the P1 limits block"])

    def test_positive_claim_promotion_string_in_result(self):
        for case in CASES:
            for text in ("this run is a complete reconstruction and certified", "the held action is approved", "production ready", "verified execution of the refund"):
                with self.subTest(case=case, text=text):
                    run = self.run_mut(self.res(lambda r, case=case, text=text: r[case]["runtime"].__setitem__("note", text)))
                    self.assert_cause(run, ["no positive claim-promotion string"])

    def test_limits_text_with_unnegated_claim(self):
        def m(r):
            for c in CASES:
                r[c]["limits"]["L17"] = "Developer-scope only: not independently qualified, not production, no certification or clearance (HOLD). The run is approved."
        run = self.run_mut(self.res(m))
        self.assert_cause(run, ["limits state no forbidden claim without a negation"], allow=["limits identical", "limits L17", "limits L17 text is the C3 contract section 9 text", "limits-L1-L27.json carries"])

    def test_crosswalk_not_linked_rows_dropped(self):
        for case in (P1, N1):
            for kw in ("check_id", "raw cp record hash", "h1 persisted", "effect_id across", "producer config", "repository-name", "c1 record"):
                with self.subTest(case=case, kw=kw):
                    def m(r, case=case, kw=kw):
                        r[case]["crosswalk"] = [x for x in r[case]["crosswalk"] if kw not in x["name"].lower()]
                    run = self.run_mut(self.res(m))
                    self.assert_cause(run, ["%s crosswalk carries the NOT LINKED row" % LABEL[case]])

    def test_crosswalk_not_linked_row_promoted_to_exact(self):
        def m(r):
            for x in r[N1]["crosswalk"]:
                if x["name"].startswith("NOT LINKED: check_id"):
                    x["class"] = "EXACT"
        run = self.run_mut(self.res(m))
        self.assert_cause(run, ["N1-HOLD crosswalk carries the NOT LINKED row check_id+decision_id"])

    def test_hold_proposal_decision_row_promoted_in_n1_only(self):
        def m(r):
            for x in r[N1]["crosswalk"]:
                if "hold" in x["name"].lower() and "proposal" in x["name"].lower():
                    x["class"] = "EXACT"
        run = self.run_mut(self.res(m))
        self.assert_cause(run, ["N1-HOLD crosswalk carries the NOT LINKED row hold+proposal"])

    def test_crosswalk_missing_entirely(self):
        run = self.run_mut(self.res(lambda r: r[P1].pop("crosswalk")))
        self.assert_cause(run, ["P1 crosswalk has rows", "P1 crosswalk carries the NOT LINKED row"], allow=["slice c4-crosswalk.json written", "every mandatory"])


# ======================================================================================= N-A: Pack-side zero counts (P1 and N1)
class ZeroCountTests(Base):
    """Explicit N-A closure: the six keys are re-observed directly from BOTH retained native Pack dumps (coherent file hash)."""

    def na(self, case, key):
        return "N-A %s derived_counts.%s is present, an int (not bool) and == 0" % (LABEL[case], key)

    def only_na(self, run, case, key):
        self.assert_cause(run, [self.na(case, key)], allow=["N1-HOLD Pack authorization_held_count"] if False else ())
        self.assertEqual(len(run.fails), 1, run.describe())

    def test_each_key_set_to_nonzero(self):
        for case in (P1, N1):
            for key in ZERO_KEYS:
                for bad in (1, -1, 2, 10 ** 9):
                    with self.subTest(case=case, key=key, bad=bad):
                        self.only_na(self.run_mut(self.pack(case, lambda d, key=key, bad=bad: dcounts(d).__setitem__(key, bad))), case, key)

    def test_each_key_deleted(self):
        for case in (P1, N1):
            for key in ZERO_KEYS:
                with self.subTest(case=case, key=key):
                    self.only_na(self.run_mut(self.pack(case, lambda d, key=key: dcounts(d).pop(key))), case, key)

    def test_each_key_wrong_type(self):
        for case in (P1, N1):
            for key in ZERO_KEYS:
                for bad in ("0", "", "zero", None, 0.0, 1.5, True, False, [], [0], {}, {"n": 0}):
                    with self.subTest(case=case, key=key, bad=bad):
                        self.only_na(self.run_mut(self.pack(case, lambda d, key=key, bad=bad: dcounts(d).__setitem__(key, bad))), case, key)

    def test_derived_counts_object_deleted_or_wrong_type(self):
        for case in (P1, N1):
            for how in ("deleted", "null", "list", "string", "number"):
                with self.subTest(case=case, how=how):
                    def f(d, how=how):
                        t = d["metadata"]["traceable_import"]
                        if how == "deleted":
                            t.pop("derived_counts")
                        else:
                            t["derived_counts"] = {"null": None, "list": [], "string": "0", "number": 0}[how]
                    run = self.run_mut(self.pack(case, f))
                    extra = ["N1-HOLD Pack authorization_held_count / authorization_granted_count"] if case == N1 else []
                    self.assert_cause(run, [self.na(case, k) for k in ZERO_KEYS], allow=extra)
                    self.assertEqual(len(run.fails), len(ZERO_KEYS) + len(extra), run.describe())

    def test_traceable_import_deleted(self):
        for case in (P1, N1):
            with self.subTest(case=case):
                run = self.run_mut(self.pack(case, lambda d: d["metadata"].pop("traceable_import")))
                self.assert_cause(run, [self.na(case, k) for k in ZERO_KEYS], allow=["%s Pack" % LABEL[case], "%s retained_sources" % LABEL[case]])

    def test_harness_oracle_forced_ok_while_pack_nonzero(self):
        """A forced-green harness oracle (every check ok, all_ok, status PASS) must not rescue a nonzero Pack count."""
        for case in (P1, N1):
            with self.subTest(case=case):
                def force(ev, case=case):
                    p = ev / ("c4.%s.evidence-pack.json" % SHORT[case])
                    d = F.read_json(p)
                    dcounts(d)["destination_effect_count"] = 1
                    F.write_json(p, d)
                    r = F.read_json(ev / "c4.result.json")
                    for c in r[case]["oracle"]["checks"]:
                        c["ok"] = True
                    r[case]["oracle"]["all_ok"] = True
                    r[case]["status"] = "PASS"
                    F.write_json(ev / "c4.result.json", r)
                    self.rehash(ev, p.name, case)
                run = self.run_mut(force)
                self.only_na(run, case, "destination_effect_count")

    def test_nonzero_count_with_updated_file_hash_is_detected(self):
        for case in (P1, N1):
            for key in ZERO_KEYS:
                with self.subTest(case=case, key=key):
                    self.only_na(self.run_mut(self.pack(case, lambda d, key=key: dcounts(d).__setitem__(key, 3))), case, key)

    def test_noncoherent_forgery_is_double_flagged(self):
        for case in (P1, N1):
            with self.subTest(case=case):
                run = self.run_mut(self.pack(case, lambda d: dcounts(d).__setitem__("reconciliation_count", 1), coherent=False))
                self.assert_cause(run, [self.na(case, "reconciliation_count"), "%s Pack file sha256: recomputed from the retained dump" % LABEL[case]],
                                  allow=["harness-reported file hashes"])

    def test_extra_derived_count_keys_do_not_mask_missing_ones(self):
        def f(d):
            dc = dcounts(d)
            dc.pop("effect_observation_count")
            dc["effect_observation_count_x"] = 0
        for case in (P1, N1):
            with self.subTest(case=case):
                self.only_na(self.run_mut(self.pack(case, f)), case, "effect_observation_count")

    def test_a_zero_in_one_pack_does_not_cover_the_other(self):
        # P1 clean, N1 nonzero: exactly the N1 key fails, and vice versa
        self.only_na(self.run_mut(self.pack(N1, lambda d: dcounts(d).__setitem__("executor_attempt_count", 1))), N1, "executor_attempt_count")
        self.only_na(self.run_mut(self.pack(P1, lambda d: dcounts(d).__setitem__("executor_attempt_count", 1))), P1, "executor_attempt_count")

    def test_pack_dump_not_an_object_or_unparsable(self):
        for case in (P1, N1):
            name = "c4.%s.evidence-pack.json" % SHORT[case]
            with self.subTest(case=case):
                run = self.run_mut(lambda ev: (ev / name).write_text("[0]\n", encoding="utf-8"))
                self.assertEqual(run.rc, 1, run.describe())
                self.assertTrue(any(name in ln for ln in run.fails), run.describe())
                run = self.run_mut(lambda ev: (ev / name).write_text("{not json", encoding="utf-8"))
                self.assertEqual(run.rc, 1, run.describe())
                self.assertTrue(any(name in ln for ln in run.fails), run.describe())
                run = self.run_mut(lambda ev: (ev / name).write_bytes(
                    (ev / name).read_bytes().replace(b'"control_plane_attempt_count": 0', b'"control_plane_attempt_count": 0, "control_plane_attempt_count": 1', 1)))
                self.assertEqual(run.rc, 1, run.describe())
                self.assertTrue(any(name in ln for ln in run.fails), run.describe())


# ======================================================================================= context, garbage input, summary
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
                 ("context: case group", lambda d: d.__setitem__("case_id", "c3_p1_n1_n3_n5_hosted_group")),
                 ("context re-asserted: ref/event/head", lambda d: d.__setitem__("github_ref", "refs/heads/other")),
                 ("context re-asserted: ref/event/head", lambda d: d.__setitem__("event_name", "push")),
                 ("context re-asserted: ref/event/head", lambda d: d.__setitem__("orchestrator_head", "0" * 40)),
                 ("context re-asserted: GITHUB_SHA non-empty and equals context", lambda d: d.__setitem__("github_sha", "0" * 40)),
                 ("context re-asserted: c2_producer.py sha256 == frozen", lambda d: d["host_sources"].__setitem__("tests/manual_contract/c2_producer.py", "0" * 64)),
                 ("context re-asserted: component pins", lambda d: d["components"]["evidence_pack"].__setitem__("sha", "0" * 40)),
                 ("context re-asserted: component pins", lambda d: d["components"].pop("action_manifest")),
                 ("context re-asserted: fixture hashes", lambda d: d["fixtures"]["proposal"].__setitem__("sha256", "0" * 64)),
                 ("context re-asserted: locked dependency versions", lambda d: d["dependencies"].__setitem__("pydantic", "9.9.9")),
                 ("context re-asserted: dependency lock sha256 recorded", lambda d: d["host_sources"].pop(".github/locks/cryptography-pydantic-pytest-513753.txt"))]
        for needle, fn in cases:
            with self.subTest(needle=needle):
                run = self.run_mut(self.ctx(fn))
                self.assert_cause(run, [needle], allow=["harness real_c4.py", "runtime versions", "context re-asserted: host source hashes", "context re-asserted: c2_producer",
                                                        "harness orchestrator head", "harness c2_producer.py"])

    def test_check_run_with_a_different_github_sha_than_verify(self):
        run = self.run_mut(lambda ev: None, GITHUB_SHA="0" * 40)
        self.assert_cause(run, ["context re-asserted"], allow=["harness orchestrator head"])

    def test_check_with_component_root_unset(self):
        for key, name in F.ROOT_ENV.items():
            with self.subTest(key=key):
                run = self.run_mut(lambda ev: None, **{name: None})
                self.assert_cause(run, ["%s is set for the check step" % name], allow=["P1 ", "N1-HOLD", "N2-FLIP", "Action Manifest fixture", "retained AM manifest input is byte-identical"])


class GarbageInputTests(Base):
    def assert_closed(self, run):
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
        self.assert_closed(self.P.run_check(ev))

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
        for name in ("c4.result.json", "tests.json", "cases.json", "context.json", *NATIVE):
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
            for name in ("c4.result.json", "c4.p1.evidence-pack.json", "c4.n1.evidence-pack.json", "c4.n2.mutated-bundle.json", "context.json", "tests.json"):
                with self.subTest(label=label, name=name):
                    run = self.run_mut(lambda ev, name=name, blob=blob: (ev / name).write_bytes(blob))
                    self.assertEqual(run.rc, 1, run.describe())
                    self.assertNotIn("Traceback", run.stderr + run.stdout)

    def test_non_ascii_oracle_never_breaks_writing(self):
        def m(ev):
            r = F.read_json(ev / "c4.result.json")
            self.boundary(r, N2, "evidence_pack")["native_exception"]["message"] = "café ☃ \U0001f600"
            F.write_json(ev / "c4.result.json", r)
        run = self.run_mut(m)
        self.assert_cause(run, ["N2-FLIP native exception message"])
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
    STEPS = dict(STEP_VERIFY="success", STEP_TESTS="success", STEP_CASES="success", STEP_ORACLE="success", STEP_INSTALL="success",
                 STEP_CHECKOUT_CP="success", STEP_CHECKOUT_RB="success", STEP_CHECKOUT_PACK="success", STEP_CHECKOUT_AM="success")

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
        proc = self.summary(ev, **self.STEPS)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        for needle in ("hosted developer evidence only", "reconstruction_partial", "Hub #280 is OPEN", "REFUSED_NATIVE at control_plane", "never authorization of the action"):
            self.assertIn(needle, proc.stdout)
        self.assert_no_claims(proc.stdout)
        self.assertNotRegex(proc.stdout.lower(), r"qualification (granted|complete|achieved)|production ready|release approved")

    def test_summary_exits_zero_on_failed_run_and_reports_fail(self):
        run = self.run_mut(self.res(lambda r: self.boundary(r, N2, "evidence_pack")["native_exception"].__setitem__("message", "x")))
        proc = self.summary(run.ev, **{**self.STEPS, "STEP_ORACLE": "failure"})
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
        self.assertEqual(self.summary(ev, EVIDENCE_DIR=None).returncode, 0)
        self.assertEqual(self.summary(ev, GITHUB_STEP_SUMMARY=str(self.P.base / "nodir" / "summary.md")).returncode, 0)

    def test_summary_without_step_outcomes_is_not_pass(self):
        proc = self.summary(self.P.ev)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Developer check result: PASS", proc.stdout)

    def test_summary_blocked_prerequisite(self):
        proc = self.summary(self.P.ev, **{**self.STEPS, "STEP_CHECKOUT_RB": "failure"})
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Developer check result: BLOCKED", proc.stdout)

    def test_summary_writes_step_summary_file(self):
        out = self.P.base / "step-summary.md"
        proc = self.summary(self.P.ev, GITHUB_STEP_SUMMARY=str(out))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertIn("C4 hosted run", out.read_text(encoding="utf-8"))

    def test_summary_neutralises_markdown_and_html_in_oracle_lines(self):
        ev = pathlib.Path(tempfile.mkdtemp(prefix="sum-", dir=str(self.P.base))) / "evidence"
        shutil.copytree(self.P.ev, ev)
        (ev / "oracle.txt").write_text("C4 FAIL\nFAIL <script>alert(1)</script> | `x` [a](http://e)\n", encoding="utf-8")
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

    def test_checker_lives_under_tests_not_github_scripts(self):
        self.assertEqual(CHECKER.relative_to(F.REPO).as_posix(), "tests/manual_contract/c4/c4_hosted_check.py")
        self.assertFalse((F.REPO / ".github" / "scripts" / "c4_hosted_check.py").exists())

    def test_checker_is_stdlib_only(self):
        names = _imports(ast.parse(CHECKER.read_text(encoding="utf-8")))
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
        self.assertEqual(os_attrs & {"system", "popen", "execv", "execve", "execvp", "spawnl", "spawnv", "fork", "kill", "remove", "unlink", "rmdir", "removedirs", "rename", "chmod", "putenv"}, set())
        self.assertTrue(set(calls) >= {"rev-parse", "ls-files", "status"})
        self.assertLessEqual(set(calls), {"rev-parse", "ls-files", "status", "ls-tree", "cat-file", "log", "show", "diff", "describe"})
        runs = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"]
        self.assertEqual(len(runs), 2)  # `git --version` and the read-only git() helper
        for forbidden in ("shell=True", "curl", "wget", "pip install", "eval(", "exec("):
            self.assertNotIn(forbidden, text)
        strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for verb in ("fetch", "push", "pull", "clone", "checkout", "add", "commit", "reset", "clean", "gc", "config", "update-index", "remote"):
            self.assertNotIn(verb, strings)

    def test_checker_has_no_test_mode_bypass(self):
        text = CHECKER.read_text(encoding="utf-8")
        for banned in ("TEST_MODE", "C4_SKIP", "C4_BYPASS", "C4_DEV", "PYTEST_CURRENT_TEST", "unittest", "--no-verify", "ALLOW_"):
            self.assertNotIn(banned, text)
        envs = set(re.findall(r'os\.environ(?:\.get)?\(?\[?"([A-Za-z0-9_]+)"', text))
        self.assertTrue({"C4_EXPECTED_FUNCTIONAL", "C4_EXPECTED_INTEGRITY"} <= envs | set(re.findall(r'"(C4_EXPECTED_[A-Z]+)"', text)))

    def test_checker_restates_literals_independently_of_the_harness(self):
        text = CHECKER.read_text(encoding="utf-8")
        names = _imports(ast.parse(text))
        for banned in ("real_c3", "real_c4", "c4_producer", "c2_producer", "runner"):
            self.assertNotIn(banned, names)
            self.assertNotIn("import " + banned, text)

    def test_checker_never_reads_harness_oracle_for_the_zero_counts(self):
        text = CHECKER.read_text(encoding="utf-8")
        body = text.split("def check_zero_counts")[1].split("def check_hashes_vs_harness")[0]
        self.assertNotIn("pack_derived_counts_zero", body)
        self.assertNotIn('"oracle"', body)


if __name__ == "__main__":
    unittest.main()
