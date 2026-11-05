"""Focused tests for the VSLICE-C1 adapter (real_c1). Expectations come from the frozen oracle literals below and from
direct Action Manifest / Control Plane calls, never from values read back from the adapter. stdlib unittest only."""
import sys

sys.dont_write_bytecode = True  # never write .pyc into the pinned checkouts: their cleanliness is part of the source gate

import contextlib
import copy
import hashlib
import inspect
import io
import json
import os
import pathlib
import subprocess
import tempfile
import types
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
MANUAL_CONTRACT = HERE.parent
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(MANUAL_CONTRACT))
import runner  # noqa: E402
import real_c1  # noqa: E402

ENV_AM, ENV_CP = "COGNOUS_C1_ACTION_MANIFEST_ROOT", "COGNOUS_C1_CONTROL_PLANE_ROOT"
MANIFEST_REL = "examples/refund_integration_v1_1.manifest.json"
CASE_A, CASE_B = "c1_manifest_to_cp_authorized", "c1_manifest_to_cp_no_authority"
# ---- frozen oracle literals (cogno-us/cognous-stack-orchestrator#138 comment 6660750456, Hub #273 comment 6660913875) ----
MANIFEST_FILE_SHA = "789ad39596b9e1ef84a726a671883e1cb6b83343da3a31db0a1120906d68c074"
MANIFEST_DIGEST = "sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac"
PROPOSAL_DIGEST = "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53"
TENANTLESS_COMMITMENT = "sha256:133c4baa21d85e41ae7f75af45a96810aa1a175ee3e693913585568630aea96b"
EFFECT_ID_A = "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8"
EFFECT_ID_B = "sha256:d0e4afe09cdf3a52aa3b530b822411b1dff35031973660fbbf9b707415f18465"
FIXTURE_SHA = {
    "proposal.tenant-alpha.json": "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2",
    "authority-context.tenant-alpha.json": "87a231dda0756bf7e66a72f13e4fd655830640baa955e1b79b9654e1fd69ba32",
    "resolver-state.tenant-alpha.json": "075fb26f316311be9f3d4b3932e60191012f6370eb709b5b893f3a0c2d4913bd",
}
PINS = {
    "manifest": ("cogno-us/cognous-action-manifest", "fa170815ef96a54c233d0dd9da821b60debabf8b", "3b0e3772e944aa668c8f4b879588c7cc3e2c32be"),
    "control_plane": ("cogno-us/cognous-control-plane", "484fdbd297235dd24148ddb0703f2055a31eabff", "c182939882103015f12c5360fccf377c54e2c4f9"),
}
BINDING_A = {
    "generation": "bounded-authorization-effect/0.3-strict-tenant", "tenant_id": "tenant-alpha", "manifest_digest": MANIFEST_DIGEST,
    "proposal_commitment": PROPOSAL_DIGEST, "grant_id": "urn:cognous:grant:routine-1", "grant_revision": "1",
    "manifest_id": "refund-integration-pilot-v1", "manifest_version": "1.1",
    "action_id": "urn:cognous:action:refund-issue-routine-v1", "adapter_id": "urn:cognous:adapter:synthetic-refund-v1",
    "actor": "urn:cognous:identity:refund-agent-1", "amount": 50.0, "effects": 1,
}
CORE_NATIVE_KEYS = {"binding", "decided_at", "decision_id", "effect_id", "operation_horizon", "reasons", "resolution_inputs", "result", "time_source"}
NOW_ISO = "2026-10-05T19:00:00+00:00"
LIMITS = {
    "status": "DEVELOPMENT_ONLY_FIXTURE_SCOPED", "authority_basis": "SYNTHETIC_UNAUTHENTICATED_RESOLVER", "decision_semantics_only": True,
    "not_institutional_authority": True, "not_independent_qualification": True, "not_general_interoperability": True,
    "hub_280_digest_basis": "OPEN", "effect_executed": False,
}
AM = CP = None  # agent_action_manifest, agent_control_plane.bounded (imported in setUpModule from the pinned roots)
AM_ROOT = CP_ROOT = None


def setUpModule():
    global AM, CP, AM_ROOT, CP_ROOT
    missing = [n for n in (ENV_AM, ENV_CP) if not os.environ.get(n)]
    if missing:
        raise AssertionError("required environment variable(s) not set: %s (point them at the pinned checkouts)" % ", ".join(missing))
    AM_ROOT, CP_ROOT = pathlib.Path(os.environ[ENV_AM]), pathlib.Path(os.environ[ENV_CP])
    for root in (AM_ROOT, CP_ROOT):
        if not (root / "src").is_dir():
            raise AssertionError("checkout root has no src/: %s" % root)
        sys.path.insert(0, str(root / "src"))
    import agent_action_manifest
    import agent_control_plane.bounded
    AM, CP = agent_action_manifest, agent_control_plane.bounded
    for name, sha in FIXTURE_SHA.items():
        assert sha256(FIXTURES.joinpath(name).read_bytes()) == sha, "fixture drifted from the frozen sha256: " + name
    assert sha256((AM_ROOT / MANIFEST_REL).read_bytes()) == MANIFEST_FILE_SHA, "pinned manifest file drifted"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fixture_json(name):
    return json.loads((FIXTURES / (name + ".tenant-alpha.json")).read_text(encoding="utf-8"))


def manifest_json():
    return json.loads((AM_ROOT / MANIFEST_REL).read_text(encoding="utf-8"))


def write_json(directory, name, obj):
    path = pathlib.Path(directory) / name
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return path


def run_case(case_id, **overrides):
    ctx = real_c1.build(**overrides)
    return real_c1.run(case_id, ctx), ctx


def run_spied(case_id, **overrides):
    """Run a case while wrapping the REAL BoundedAuthorizationWorkflow.decide and every effect path; returns (result, ctx, spy).
    `spy` is the decide() spy; `spy.forbidden` holds the execute/reconcile/apply spies, which must never be called."""
    W, D = CP.BoundedAuthorizationWorkflow, CP.LocalRefundDestination
    with mock.patch.object(W, "decide", autospec=True, side_effect=W.decide) as spy, \
            mock.patch.object(W, "execute", autospec=True, side_effect=W.execute) as execute, \
            mock.patch.object(W, "reconcile", autospec=True, side_effect=W.reconcile) as reconcile, \
            mock.patch.object(D, "apply", autospec=True, side_effect=D.apply) as apply:
        result, ctx = run_case(case_id, **overrides)
    spy.forbidden = {"execute": execute, "reconcile": reconcile, "apply": apply}
    return result, ctx, spy


def under(path, root):
    return os.path.realpath(path).startswith(os.path.realpath(str(root / "src")) + os.sep)


def read_destination(ctx):
    return json.loads((ctx.workdir / "destination.json").read_text(encoding="utf-8"))


class OracleMixin:
    def assert_runner_and_common(self, result, ctx, spy, case_id, expected, native_result, reasons):
        self.assertEqual(spy.call_count, 1, "the real CP decide() must run exactly once")
        for name, forbidden in spy.forbidden.items():
            self.assertEqual(forbidden.call_count, 0, name + " (an effect path) must never be called")
        self.assertTrue(under(inspect.getsourcefile(CP), CP_ROOT))
        CP.RuntimeDecision.model_validate(result["native_response"])
        self.assertEqual(result["schema"], "cognous.orchestrator.manual-contract-result/0-candidate")
        self.assertEqual(result["case_id"], case_id)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual((result["expected_outcome"], result["observed_outcome"]), (expected, expected))
        self.assertEqual(result["invocation_status"], "INVOKED")
        for key in ("fixture_sha256", "producer_output_sha256", "consumer_input_sha256"):
            self.assertEqual(result[key], MANIFEST_FILE_SHA, key)
        self.assertIsNone(result["consumer_reported_input_sha256"])
        native = result["native_response"]
        # model_dump omits None/empty optional fields (exclude_if), so the dumped keys are a subset of model_fields; nothing may be added
        self.assertLessEqual(set(native), set(CP.RuntimeDecision.model_fields), "adapter must add no native keys")
        self.assertEqual(set(native), CORE_NATIVE_KEYS)
        self.assertEqual((native["result"], native["reasons"]), (native_result, reasons))
        self.assertEqual((native["time_source"], native["decided_at"]), ("test_override", NOW_ISO))
        self.assertTrue(isinstance(native["decision_id"], str) and native["decision_id"])
        inputs = {row["input_type"]: row for row in native["resolution_inputs"]}
        self.assertEqual(inputs["manifest"]["record_commitment"], MANIFEST_DIGEST)
        self.assertIs(inputs["manifest"]["missing"], False)
        self.assertEqual(native["operation_horizon"]["proposal_commitment"], PROPOSAL_DIGEST)
        # destination read from disk, not from evidence or the runner's constant effect_status
        self.assertEqual(read_destination(ctx)["effects"], {})
        ev = ctx.evidence
        self.assertEqual(ev["schema"], "cognous.orchestrator.c1-evidence/0-candidate")
        self.assertEqual((ev["case_id"], ev["frozen_fixture"], ev["consumer_invocations"]), (case_id, True, 1))
        self.assertEqual(ev["gate"], {"passed": True, "failure": None})
        self.assertEqual(ev["clock"], {"now": NOW_ISO, "allow_test_time": True, "developer_only_override": True})
        self.assertEqual(ev["limits"], LIMITS)
        self.assertEqual(ev["mode"], "frozen")
        self.assertEqual(ev["runner_result_sha256"], sha256(runner.result_json(result).encode()))
        self.assertEqual(ev["harness"]["real_c1_sha256"], sha256(pathlib.Path(real_c1.__file__).read_bytes()))
        for name, entry in ev["fixtures"].items():
            self.assertEqual(entry.get("mode", "frozen"), "frozen", name)
            if "sha256" in entry:
                self.assertEqual(entry["sha256_of"], "file_bytes", name)
        records = json.loads((ctx.workdir / "records.json").read_text(encoding="utf-8"))  # records: {run_id, input_time_floors, resolution_checks, decisions[]}
        self.assertIn(native["decision_id"], [d.get("decision_id") for d in records["decisions"]])
        self.assertEqual(ev["destination"]["effects"], {})
        self.assertEqual(ev["destination"]["effect_count"], 0)
        self.assertEqual(ev["digests"]["am_manifest_digest"], MANIFEST_DIGEST)
        self.assertEqual(ev["digests"]["cp_manifest_commitment"], MANIFEST_DIGEST)
        self.assertEqual(ev["digests"]["am_proposal_digest"], PROPOSAL_DIGEST)
        self.assertEqual(ev["digests"]["proposal_mismatches"], [])
        self.assertEqual(ev["fixtures"]["manifest_file"]["sha256"], MANIFEST_FILE_SHA)
        self.assertEqual(ev["fixtures"]["proposal"]["sha256"], FIXTURE_SHA["proposal.tenant-alpha.json"])
        self.assertEqual(ev["fixtures"]["resolver_state"]["sha256"], FIXTURE_SHA["resolver-state.tenant-alpha.json"])
        for key, (repo, sha, tree) in PINS.items():
            src = ev["sources"][key]
            self.assertEqual((src["repository"], src["pinned_sha"], src["observed_head"]), (repo, sha, sha))
            self.assertEqual((src["pinned_tree"], src["observed_tree"]), (tree, tree))
            self.assertIs(src["tracked_files_clean"], True)
            self.assertIs(src["ls_files_all_H"], True)
            self.assertIs(src["status_ignored_clean"], True)
            root = AM_ROOT if key == "manifest" else CP_ROOT
            self.assertTrue(src["imported_modules"])
            for name, info in src["imported_modules"].items():
                self.assertTrue(under(info["file"], root), name)
            wanted = ["agent_action_manifest"] if key == "manifest" else ["agent_control_plane.bounded", "agent_control_plane.cli_run"]
            for name in wanted:
                self.assertIn(name, src["imported_modules"])
        json.dumps(ev)  # JSON-serialisable
        return native, inputs


class AuthorizedAndWithheldTests(OracleMixin, unittest.TestCase):
    def test_case_a_authorized_full_oracle(self):
        result, ctx, spy = run_spied(CASE_A)
        native, _ = self.assert_runner_and_common(result, ctx, spy, CASE_A, "ACCEPTED", "authorized", [])
        self.assertEqual(native["effect_id"], EFFECT_ID_A)
        for key, value in BINDING_A.items():  # the native binding carries more members; the frozen ones must match exactly
            self.assertEqual(native["binding"][key], value, key)
        authority = ctx.evidence["fixtures"]["authority_context"]
        self.assertEqual((authority["sha256"], authority["mode"], authority["sha256_of"]),
                         (FIXTURE_SHA["authority-context.tenant-alpha.json"], "frozen", "file_bytes"))

    def test_case_b_no_authority_full_oracle(self):
        result, ctx, spy = run_spied(CASE_B)
        native, inputs = self.assert_runner_and_common(result, ctx, spy, CASE_B, "REFUSED", "hold", ["authority_context_missing"])
        self.assertEqual(native["effect_id"], EFFECT_ID_B)
        self.assertIsNone(native["binding"])
        self.assertIs(inputs["authority_context"]["missing"], True)
        self.assertIs(ctx.evidence["fixtures"]["authority_context"]["withheld"], True)
        self.assertEqual(result["fixture_sha256"], MANIFEST_FILE_SHA)  # same manifest bytes as case A


class FailClosedTests(unittest.TestCase):
    def assert_blocked_before_consumer(self, step, etype, overridden, **overrides):
        result, ctx = run_case(CASE_A, **overrides)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["invocation_status"], "NOT_INVOKED")
        self.assertEqual(result["observed_outcome"], "UNKNOWN")
        self.assertIsNone(result["native_response"])
        ev = ctx.evidence
        self.assertEqual(ev["consumer_invocations"], 0)
        self.assertIsNone(ev["destination"])
        self.assertIs(ev["gate"]["passed"], False)
        self.assertEqual((ev["gate"]["failure"]["step"], ev["gate"]["failure"]["type"]), (step, etype))
        self.assertEqual((ev["mode"], ev["frozen_fixture"], ev["overridden_inputs"]), ("test_override", False, [overridden]))
        self.assertEqual(ev["fixtures"][overridden]["mode"], "test_override")
        if overridden != "manifest_file":  # dict override: hash of the canonical re-serialisation
            self.assertEqual(ev["fixtures"][overridden]["sha256_of"], "canonical_reserialisation")
        if (ctx.workdir / "destination.json").exists():
            self.assertEqual(read_destination(ctx).get("effects", {}), {})
        return ev

    def test_a_raising_decide_is_never_accepted(self):
        for case_id in (CASE_A, CASE_B):
            with self.subTest(case=case_id):
                with mock.patch.object(CP.BoundedAuthorizationWorkflow, "decide", autospec=True, side_effect=RuntimeError("synthetic decide failure")):
                    result, ctx = run_case(case_id)
                self.assertEqual((result["invocation_status"], result["observed_outcome"]), ("INVOKED", "ERROR"))
                self.assertEqual(result["status"], "FAIL")  # an error is never PASS, whichever outcome was expected
                self.assertEqual(result["consumer_error"]["type"], "RuntimeError")
                self.assertIsNone(result["native_response"])
                self.assertEqual(ctx.evidence["consumer_invocations"], 1)
                self.assertIsNone(ctx.evidence["destination"])  # decide never completed, so no destination state is claimed

    def test_destination_effect_count_is_read_from_the_real_file(self):
        seeded = {"effects": {"seeded-synthetic-effect": {"note": "seeded by the test"}}, "grant_effect_counts": {}}
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "destination.json").write_text(json.dumps(seeded), encoding="utf-8")
            result, ctx = run_case(CASE_A, workdir=pathlib.Path(tmp))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(read_destination(ctx), seeded)  # decide() never wrote an effect
            self.assertEqual(ctx.evidence["destination"]["effects"], seeded["effects"])  # the evidence mirrors the FILE, not a constant
            self.assertEqual(ctx.evidence["destination"]["effect_count"], 1)

    def test_remaining_gates_fail_closed(self):
        with self.subTest(gate="native validate_manifest"):  # loads (closed schema ok) but the native validator reports it invalid
            manifest = manifest_json()
            manifest["actions"][0]["action_id"] = " " + manifest["actions"][0]["action_id"] + " "
            with tempfile.TemporaryDirectory() as tmp:
                path = write_json(tmp, "m.json", manifest)
                self.assertFalse(AM.validate_manifest(AM.load_manifest(path)).valid)
                self.assert_blocked_before_consumer("manifest_validate", "C1GateError", "manifest_file", manifest_file=path)
        with self.subTest(gate="frozen manifest sha256"):
            with mock.patch.dict(real_c1.FROZEN, {"manifest_file_sha256": "0" * 64}):
                result, ctx = run_case(CASE_A)
            self.assertEqual((result["status"], result["invocation_status"]), ("BLOCKED", "NOT_INVOKED"))
            self.assertEqual(ctx.evidence["gate"]["failure"]["step"], "manifest_bytes")
            self.assertEqual(ctx.evidence["consumer_invocations"], 0)
        with self.subTest(gate="frozen fixture sha256"):
            with mock.patch.dict(real_c1.FROZEN, {"proposal_sha256": "0" * 64}):
                with self.assertRaisesRegex(real_c1.C1GateError, r"fixture proposal sha256 differs"):
                    real_c1.build()
        with self.subTest(gate="checkout top level"):  # a subdirectory of the pinned checkout is not the checkout
            with self.assertRaisesRegex(real_c1.SourceIdentityError, r"top level of a git checkout"):
                real_c1.build(manifest_root=AM_ROOT / "examples", cp_root=CP_ROOT)

    def test_unknown_manifest_member_fails_closed(self):
        manifest = manifest_json()
        manifest["unexpected_member"] = "x"
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "m.json", manifest)
            with self.assertRaises(AM.loader.ManifestLoadError):
                AM.load_manifest(path)
            self.assert_blocked_before_consumer("manifest_load", "ManifestLoadError", "manifest_file", manifest_file=path)

    def test_unknown_proposal_member_fails_closed(self):
        proposal = dict(fixture_json("proposal"), unexpected_member="x")
        with self.assertRaises(Exception) as caught:
            AM.models.RuntimeActionProposalV12.model_validate(proposal)
        self.assertEqual(type(caught.exception).__name__, "ValidationError")
        self.assert_blocked_before_consumer("proposal_model", "ValidationError", "proposal", proposal=proposal)

    def test_manifest_version_1_0_fails_closed(self):
        manifest = manifest_json()
        manifest["manifest_version"] = "1.0"
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "m.json", manifest)
            model = AM.load_manifest(path)  # the 1.0 manifest is itself AM-valid
            self.assertTrue(AM.validate_manifest(model).valid)
            self.assertEqual(model.manifest_version, "1.0")
            self.assert_blocked_before_consumer("manifest_version", "C1GateError", "manifest_file", manifest_file=path)

    def test_digest_basis_divergence_fails_closed_without_normalizing(self):
        manifest = manifest_json()
        manifest["actions"][0].pop("redaction_hints")
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "m.json", manifest)
            model = AM.load_manifest(path)
            self.assertTrue(AM.validate_manifest(model).valid)
            am_digest, cp_digest = AM.manifest_digest(model), CP.commitment(json.loads(path.read_text(encoding="utf-8")))
            self.assertNotEqual(am_digest, cp_digest)
            ev = self.assert_blocked_before_consumer("digest_basis", "C1GateError", "manifest_file", manifest_file=path)
            self.assertIn("digest basis", ev["gate"]["failure"]["message"])
            self.assertIn("#280", ev["gate"]["failure"]["message"])
            self.assertEqual((ev["digests"]["am_manifest_digest"], ev["digests"]["cp_manifest_commitment"]), (am_digest, cp_digest))
            self.assertNotIn("redaction_hints", json.loads(path.read_text(encoding="utf-8"))["actions"][0])  # input untouched

    def test_changed_manifest_content_is_a_preflight_mismatch(self):
        manifest = manifest_json()
        manifest["actions"][0]["description"] = manifest["actions"][0]["description"] + " (changed)"
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "m.json", manifest)
            model = AM.load_manifest(path)
            self.assertTrue(AM.validate_manifest(model).valid)
            proposal = AM.models.RuntimeActionProposalV12.model_validate(fixture_json("proposal"))
            self.assertIn("manifest_digest_mismatch", AM.proposal_mismatches(model, proposal))
            expected = AM.manifest_digest(model)
            self.assertEqual(expected, CP.commitment(json.loads(path.read_text(encoding="utf-8"))))  # digest bases agree here
            ev = self.assert_blocked_before_consumer("proposal_mismatches", "C1GateError", "manifest_file", manifest_file=path)
            self.assertIn("manifest_digest_mismatch", ev["gate"]["failure"]["message"])
            self.assertEqual(ev["digests"]["am_manifest_digest"], ev["digests"]["cp_manifest_commitment"])
            self.assertEqual(ev["digests"]["am_manifest_digest"], expected)

    def test_stale_approval_binding_is_a_native_hold(self):
        stale, revoked = copy.deepcopy(fixture_json("resolver-state")), copy.deepcopy(fixture_json("resolver-state"))
        for approval in stale["approvals"].values():  # resolver_state approvals (not the authority-context file) carry the commitment
            approval["proposal_commitment"] = TENANTLESS_COMMITMENT
        for status in revoked["statuses"].values():  # differential: a different real CP rule fires for a revoked grant
            status["status"] = "revoked"
        variants = (("stale_approval_binding", stale, ["approval_operation_binding_mismatch"]), ("revoked_grant", revoked, ["grant_not_active"]))
        for label, state, reasons in variants:
            with self.subTest(label):
                result, ctx = run_case(CASE_A, resolver_state=state)
                self.assertEqual(result["invocation_status"], "INVOKED")
                self.assertEqual(result["observed_outcome"], "REFUSED")
                self.assertEqual(result["status"], "FAIL")  # case A expects ACCEPTED; the native hold is a refusal
                native = result["native_response"]
                self.assertEqual(native["result"], "hold")
                self.assertEqual(native["reasons"], reasons)
                self.assertIsNone(native["binding"])
                self.assertEqual(read_destination(ctx)["effects"], {})
                self.assertEqual(ctx.evidence["consumer_invocations"], 1)
                self.assertEqual((ctx.evidence["mode"], ctx.evidence["overridden_inputs"]), ("test_override", ["resolver_state"]))
                self.assertEqual(ctx.evidence["fixtures"]["resolver_state"]["sha256_of"], "canonical_reserialisation")

    def test_unmapped_native_result_is_unknown_blocked(self):
        registry = runner.Registry(
            producers={"p": lambda data: data},
            consumers={"c": runner.Consumer(lambda data: {"result": "deferred"}, "result", real_c1.ADMISSION_MAP)},
            cases={"x": ("p", b"{}", "c")}, expectations={"x": "ACCEPTED"},
        )
        result = runner.run_case("x", registry)
        self.assertEqual(result["invocation_status"], "INVOKED")
        self.assertEqual(result["observed_outcome"], "UNKNOWN")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertNotEqual(result["observed_outcome"], "ACCEPTED")

    def test_wrong_source_revision_is_refused(self):
        def git(cwd, *args):
            cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args]
            done = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True, env={"PATH": os.environ.get("PATH", ""), "HOME": str(cwd)})
            return done.stdout.strip()

        def make_repo(parent):
            repo = pathlib.Path(parent, "repo")
            (repo / "src").mkdir(parents=True)
            (repo / "src" / "mod.py").write_text("X = 1\n")
            git(repo, "init", "-q")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "one")
            return repo

        with tempfile.TemporaryDirectory() as tmp:
            repo, plain = make_repo(tmp), pathlib.Path(tmp, "plain")
            plain.mkdir()
            # Each refusal must come from ITS OWN gate: assert the gate's message, not just the exception type
            # (a SourceIdentityError can also come from the later "imported from the wrong root" check).
            for bad, gate_message in ((repo, r"HEAD/tree"), (plain, r"not a usable git checkout")):  # wrong commit / not a git checkout
                with self.subTest(kind="wrong_commit" if bad == repo else "non_git"):
                    with self.assertRaisesRegex(real_c1.SourceIdentityError, gate_message):
                        real_c1.build(manifest_root=bad, cp_root=CP_ROOT)
                    with self.assertRaisesRegex(real_c1.SourceIdentityError, gate_message):
                        real_c1.build(manifest_root=AM_ROOT, cp_root=bad)
            # HEAD and tree now MATCH the (patched) pin, so only the tampering below can be the reason for refusal
            pins = copy.deepcopy(real_c1.PINS)
            pins["manifest"].update(sha=git(repo, "rev-parse", "HEAD"), tree=git(repo, "rev-parse", "HEAD^{tree}"))
            with mock.patch.object(real_c1, "PINS", pins):
                git(repo, "update-index", "--skip-worktree", "src/mod.py")
                (repo / "src" / "mod.py").write_text("X = 2  # hidden tracked modification\n")
                with self.subTest(kind="skip_worktree_modified"):
                    self.assertEqual(git(repo, "status", "--porcelain", "--untracked-files=no"), "")  # plain status is blind to it
                    with self.assertRaisesRegex(real_c1.SourceIdentityError, r"non-H tags"):
                        real_c1.build(manifest_root=repo, cp_root=CP_ROOT)
                git(repo, "update-index", "--no-skip-worktree", "src/mod.py")
                git(repo, "checkout", "--", "src/mod.py")
                (repo / "src" / "json.py").write_text("# untracked module that would shadow the stdlib\n")
                with self.subTest(kind="untracked_file_under_src"):
                    self.assertEqual(git(repo, "status", "--porcelain", "--untracked-files=no"), "")  # old-style status is blind to it
                    with self.assertRaisesRegex(real_c1.SourceIdentityError, r"modified, untracked or ignored files"):
                        real_c1.build(manifest_root=repo, cp_root=CP_ROOT)

    def test_imported_module_must_equal_the_pinned_git_blob(self):
        """Defence in depth for the source gate: a loaded module whose bytes differ from HEAD's blob is refused."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp, "repo").resolve()
            (repo / "src").mkdir(parents=True)
            (repo / "src" / "c1_blob_probe.py").write_text("X = 1\n")
            for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "one")):
                subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],
                               cwd=repo, check=True, capture_output=True, env={"PATH": os.environ.get("PATH", ""), "HOME": str(repo)})
            probe = types.ModuleType("c1_blob_probe")
            probe.__file__ = str(repo / "src" / "c1_blob_probe.py")
            sys.modules["c1_blob_probe"] = probe
            try:
                recorded = {}
                real_c1._check_modules(repo, recorded)  # positive control: byte-identical to HEAD => recorded, no error
                self.assertEqual(list(recorded["imported_modules"]), ["c1_blob_probe"])
                (repo / "src" / "c1_blob_probe.py").write_text("X = 2  # differs from the pinned blob\n")
                with self.assertRaisesRegex(real_c1.SourceIdentityError, r"differs from the pinned git blob"):
                    real_c1._check_modules(repo, {})
            finally:
                sys.modules.pop("c1_blob_probe", None)


class CliTests(unittest.TestCase):
    def run_main(self, argv):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return real_c1.main(argv)

    def test_cli_exit_codes_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            for case_id in (CASE_A, CASE_B):
                out, ev = pathlib.Path(tmp, case_id + ".json"), pathlib.Path(tmp, case_id + ".evidence.json")
                self.assertEqual(self.run_main(["--case", case_id, "--out", str(out), "--evidence-out", str(ev)]), 0, case_id)
                result, evidence = json.loads(out.read_text()), json.loads(ev.read_text())
                self.assertEqual((result["case_id"], result["status"]), (case_id, "PASS"))
                self.assertEqual(result["fixture_sha256"], MANIFEST_FILE_SHA)
                self.assertEqual((evidence["case_id"], evidence["consumer_invocations"]), (case_id, 1))
            bad_out, bad_ev = pathlib.Path(tmp, "bad.json"), pathlib.Path(tmp, "bad.evidence.json")
            for bad in ("no_such_case", "../x; echo pwned", CASE_A + "\n--out"):
                self.assertEqual(self.run_main(["--case", bad, "--out", str(bad_out), "--evidence-out", str(bad_ev)]), 2, bad)
            self.assertFalse(bad_out.exists() or bad_ev.exists())


if __name__ == "__main__":
    unittest.main()
