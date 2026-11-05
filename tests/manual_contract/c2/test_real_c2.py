"""Focused tests for the VSLICE-C2 adapter (real_c2): Control Plane runtime-profile decide-only record -> Replay Bundle import.

DRAFT. Expectations come ONLY from the frozen oracle literals below (Hub #273 comments 6665625039 / 6665588148 / 6665220369,
contract sections 3, 5, 7, 8, 14) and from this file's own independent observations (the persisted record file read
from disk, the destination file read from disk, and this file's own call to the Replay Bundle importer). They are never
read back from adapter output; adapter evidence is only compared AGAINST them. stdlib unittest only; run with
`python -I -B`. The two component roots come from the environment and are REQUIRED (the run fails, it does not skip).

A green run means the Replay Bundle native result matched these literals on a synthetic fixture. It is not
qualification, authenticity, effect proof, or acceptance of C1 records by the Replay Bundle.
"""
import sys

sys.dont_write_bytecode = True  # never write .pyc into the pinned checkouts: their cleanliness is part of the source gate

import contextlib
import copy
import hashlib
import inspect
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
MANUAL_CONTRACT = HERE.parent
C1_FIXTURES = MANUAL_CONTRACT / "c1" / "fixtures"
C2_FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(MANUAL_CONTRACT))
import real_c2  # noqa: E402  (must not import any component at module import time; checked in SourceIdentityTests)

ENV_CP, ENV_RB = "COGNOUS_C2_CONTROL_PLANE_ROOT", "COGNOUS_C2_REPLAY_BUNDLE_ROOT"
CASE_P1, CASE_N1, CASE_N2 = "c2_p1_runtime_profile_partial", "c2_n1_stored_tenant_tamper", "c2_n2_c1_records_incompatible"

# ---- frozen oracle literals (Hub #273 comment 6665220369 sections 2,3,5,7,8,14; approval 6665625039) ----
PINS = {  # section 2
    "cp": ("cogno-us/cognous-control-plane", "484fdbd297235dd24148ddb0703f2055a31eabff", "c182939882103015f12c5360fccf377c54e2c4f9"),
    "rb": ("cogno-us/cognous-replay-bundle", "93a76e281fcae6a65d2cd1d35376f87442dafb95", "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f"),
}
CP_SHA, RB_SHA = PINS["cp"][1], PINS["rb"][1]
PROPOSAL_FILE_SHA = "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2"  # sections 3, 5
C1_RECORDS_SHA = {  # section 3 (native-records.json sha256, computed from the retained copy)
    "positive": "51e4d278b61134fda1db36b4fa82af7e4ad03df761f53c58941b8e9203b70e91",
    "negative": "6a3e188088fe5fa2913ac5b085351175aa8db77e19d19420c8ed68d8a7b8e9cd",
}
C1_RUNS = {"positive": ("42067811832", "13433583494"), "negative": ("42068362339", "13434638870")}  # run id, artifact id
C1_POSITIVE_DECISION_ID = "44ce8e27-4e6e-4a38-9ae8-bbd653dd07b7"  # section 9 (decision_id differs in C2)
# section 7 P1
RB_STATUS = "reconstruction_partial"
FINDINGS = [("B004", "warning")]
FORBIDDEN_CODES = {"B001", "B002", "B005", "B006"}
RECORD_TYPES = {"input_time_floors", "resolution_check", "resolution_check_event", "runtime_decision", "runtime_proposal"}
EFFECT_ID = "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8"
PROPOSAL_COMMITMENT = "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53"
TENANT, GENERATION = "tenant-alpha", "bounded-authorization-effect/0.3-strict-tenant"
DECIDED_AT, TIME_SOURCE = "2026-10-05T19:00:00+00:00", "test_override"
VOCAB, PROFILE = "runtime-authority-reasons/0.1", "runtime-authority/0.1"
RUN_ID = "run-1"
CONFIG_ID = "C2-CP-RUNTIME-PROFILE-STRICT-TENANT-DECIDE-ONLY"
EVIDENCE_SCHEMA = "cognous.orchestrator.c2-evidence/0-candidate"
# section 7 N1 / N2 (importers.py:287-300; refusal_evidence.py:259)
N1_MESSAGE = "decisions[0].binding.tenant_id conflicts with committed operation"
N2_MESSAGE = "typed refusal profile: resolution journal missing"
# section 8 / 14 limits labels, carried verbatim as (key, value) the adapter must expose in evidence["limits"].
# The key SPELLINGS below are this test's reading of sections 8 and 14; the VALUES are the frozen label text.
LIMITS = {
    "status": "DEVELOPMENT_ONLY_FIXTURE_SCOPED",
    "authority_basis": "SYNTHETIC_UNAUTHENTICATED_RESOLVER",
    "time_source": "test_override",
    "decision_semantics_only": True,
    "effect_executed": False,
    "hub_280_digest_basis": "OPEN",
    "not_institutional_authority": True,
    "not_independent_qualification": True,
    "not_general_interoperability": True,
}
MIN_FRESH_REQUIRED_WORDS = (  # section 8/14 label words that must each appear somewhere in the limits block (key or value)
    "consistency_only", "no_key_or_attestation", "not_authority_reevaluation", "not_proof_of_external_effect", "not_complete_history",
    "replay_protection", "tenant_generation", "digest_basis", "revision_label", "signature_key_basis",
    "producer_revision_basis", "lineage", "no_authenticated_issuer", "correlation_id", "private_cp_api_dependency",
)

CP_ROOT = RB_ROOT = None
B = IMP = None  # agent_control_plane.bounded, agent_replay_bundle.importers (this file's own imports of the pinned components)
SHARED = {}


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


def setUpModule():
    global CP_ROOT, RB_ROOT, B, IMP
    missing = [n for n in (ENV_CP, ENV_RB) if not os.environ.get(n)]
    if missing:
        raise AssertionError("required environment variable(s) not set: %s (point them at the pinned checkouts)" % ", ".join(missing))
    CP_ROOT, RB_ROOT = pathlib.Path(os.environ[ENV_CP]).resolve(), pathlib.Path(os.environ[ENV_RB]).resolve()
    for root in (CP_ROOT, RB_ROOT):
        if not (root / "src").is_dir():
            raise AssertionError("checkout root has no src/: %s" % root)
    assert sha256((C1_FIXTURES / "proposal.tenant-alpha.json").read_bytes()) == PROPOSAL_FILE_SHA, "proposal fixture drifted"
    for label, name in (("positive", "c1-hosted-native-records.positive.json"), ("negative", "c1-hosted-native-records.negative.json")):
        assert sha256((C2_FIXTURES / name).read_bytes()) == C1_RECORDS_SHA[label], "C1 hosted record fixture drifted: " + name
    sys.path[:0] = [str(CP_ROOT / "src"), str(CP_ROOT), str(RB_ROOT / "src")]  # the test's own imports (adapter measures separately)
    import agent_control_plane.bounded as bounded
    from agent_replay_bundle import importers
    B, IMP = bounded, importers


def tree_signature(root):
    """Hash of every file name+bytes below root, excluding .git: the pinned trees must be unchanged by a run."""
    h = hashlib.sha256()
    for p in sorted(pathlib.Path(root).rglob("*")):
        if ".git" in p.relative_to(root).parts or not p.is_file():
            continue
        h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


class Spied:
    """One adapter call wrapped with spies on the REAL Replay Bundle importer and every Control Plane effect path."""

    def __init__(self, fn, *args):
        self.rb_calls, self.fingerprint = [], []
        real_import = IMP.import_bounded_workflow
        outer = self

        def rb_spy(record, *a, **kw):
            outer.rb_calls.append({"args": a, "kwargs": dict(kw), "record": copy.deepcopy(record)})
            path = outer.record_path_hint
            if path is not None and os.path.exists(path):
                st = os.stat(path)
                outer.fingerprint.append((sha256(pathlib.Path(path).read_bytes()), st.st_size, st.st_mtime_ns, st.st_ino))
            return real_import(record, *a, **kw)
        self.record_path_hint = None
        W, D = B.BoundedAuthorizationWorkflow, B.LocalRefundDestination
        self.decide_wfs = []
        real_decide = W.decide

        def decide_spy(wf, *a, **kw):
            self.decide_wfs.append(wf)
            if getattr(wf.records, "path", None) is not None:
                self.record_path_hint = str(wf.records.path) if getattr(wf, "runtime_authority_profile", None) is not None else self.record_path_hint
            return real_decide(wf, *a, **kw)
        orig_now = B._now
        with mock.patch.object(IMP, "import_bounded_workflow", rb_spy), \
                mock.patch.object(W, "decide", decide_spy), \
                mock.patch.object(W, "execute", autospec=True, side_effect=W.execute) as ex, \
                mock.patch.object(W, "reconcile", autospec=True, side_effect=W.reconcile) as rc, \
                mock.patch.object(D, "apply", autospec=True, side_effect=D.apply) as ap:
            try:
                self.result, self.error = fn(*args), None
            except Exception as exc:  # recorded, asserted on by the caller
                self.result, self.error = None, exc
        self.forbidden = {"execute": ex, "reconcile": rc, "apply": ap}
        self.clock_restored = B._now is orig_now


def make_tree(dst):
    """Copy of the manual_contract directory (adapter, producer, runner, real_c1, fixtures) for mutation / alteration tests."""
    shutil.copytree(MANUAL_CONTRACT, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "test_real_c2.py", "test_real_c1.py"))
    return pathlib.Path(dst)


def p1():
    if "p1" not in SHARED:
        work = pathlib.Path(tempfile.mkdtemp(prefix="c2t-p1-"))
        before = (tree_signature(CP_ROOT), tree_signature(RB_ROOT))
        SHARED["p1"] = Spied(real_c2.run_p1, CP_ROOT, RB_ROOT, work)
        SHARED["p1"].work, SHARED["p1"].trees_before = work, before
        SHARED["p1"].trees_after = (tree_signature(CP_ROOT), tree_signature(RB_ROOT))
    return SHARED["p1"]


def n1():
    if "n1" not in SHARED:
        work = pathlib.Path(tempfile.mkdtemp(prefix="c2t-n1-"))
        SHARED["n1"] = Spied(real_c2.run_n1, CP_ROOT, RB_ROOT, work)
        SHARED["n1"].work = work
    return SHARED["n1"]


def n2():
    if "n2" not in SHARED:
        SHARED["n2"] = Spied(real_c2.run_n2, CP_ROOT, RB_ROOT)
    return SHARED["n2"]


def proposal_obj():
    return strict_loads((C1_FIXTURES / "proposal.tenant-alpha.json").read_bytes())


class P1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spy = p1()
        if cls.spy.error is not None:
            raise cls.spy.error
        cls.ev = cls.spy.result

    def independent_record(self):
        """The persisted record, read once from disk by this test (path only taken from the evidence), plus its bytes hash."""
        path = pathlib.Path(self.ev["record"]["path"])
        self.assertTrue(str(path.resolve()).startswith(str(self.spy.work.resolve())), "record must live in the case workdir")
        data = path.read_bytes()
        return data, strict_loads(data)

    def test_p1_full_oracle_independent_observations(self):
        ev = self.ev
        data, record = self.independent_record()
        # (1) persisted bytes pinned: the adapter's hash equals this test's own hash of the file on disk
        self.assertEqual(ev["record"]["sha256"], sha256(data))
        self.assertEqual(ev["record"]["size_bytes"], len(data))
        self.assertEqual(ev["record"]["sha256_of"], "file_bytes")
        # (2) this test's own call to the real Replay Bundle importer: label is the frozen pin literal, proposal is the pinned dict
        bundle = IMP.import_bounded_workflow(copy.deepcopy(record), proposal=proposal_obj(), control_plane_revision=CP_SHA)
        self.assertEqual(bundle.status, RB_STATUS)
        findings = [(f.code, f.severity) for r in bundle.import_reports for f in r.findings]
        self.assertEqual(findings, FINDINGS)
        self.assertFalse({c for c, _ in findings} & FORBIDDEN_CODES)
        self.assertEqual({r.record_type for r in bundle.records}, RECORD_TYPES)
        # (3) the decision as persisted on disk
        self.assertEqual(len(record["decisions"]), 1)
        d = record["decisions"][0]
        self.assertEqual((d["result"], d["reasons"]), ("authorized", []))
        self.assertEqual((d["time_source"], d["decided_at"]), (TIME_SOURCE, DECIDED_AT))
        self.assertEqual(d["effect_id"], EFFECT_ID)
        self.assertEqual(d["operation_horizon"]["proposal_commitment"], PROPOSAL_COMMITMENT)
        b = d["binding"]
        self.assertEqual((b["tenant_id"], b["generation"], b["proposal_commitment"]), (TENANT, GENERATION, PROPOSAL_COMMITMENT))
        self.assertEqual(b["runtime_authority"]["profile"], PROFILE)
        self.assertEqual(d["reason_vocabulary_version"], VOCAB)
        self.assertEqual(record["run_id"], RUN_ID)
        self.assertNotEqual(d["decision_id"], C1_POSITIVE_DECISION_ID)  # NEW (random uuid4), never equal to C1's
        # (4) journal: top-level non-empty check_events, every event bound to this decision, vocabulary version present
        events = record["check_events"]
        self.assertIsInstance(events, list)
        self.assertGreater(len(events), 0)
        for e in events:
            self.assertEqual(e["reason_vocabulary_version"], VOCAB)
        # NOTE: the frozen "event decision_id == decisions[0].decision_id" assertion is test_p1_check_events_decision_id_frozen_oracle
        # (expected failure at these pins, see its docstring); here only that the journal is one check is asserted (events' check_id also differs from resolution_checks[0].check_id at these pins).
        self.assertEqual(len({e["check_id"] for e in events}), 1, "one journalled check")
        self.assertEqual(len(d["resolution_inputs"]), 11)
        self.assertEqual(len(record["resolution_checks"]), 1)
        # (5) no attempts/observations/reconciliations/closeouts persisted by a decide-only run
        for key in ("attempts", "observations", "reconciliations", "closeouts"):
            self.assertEqual(record.get(key, []), [], key)
        # (6) destination read from disk by this test: no effect
        dest = json.loads((self.spy.work / "run" / "destination.json").read_text(encoding="utf-8") or "{}")
        self.assertEqual(dest.get("effects", {}), {})

    @unittest.expectedFailure
    def test_p1_check_events_decision_id_frozen_oracle(self):
        """FROZEN literal (contract section 14, 'P1 journal assertions'): every check_events entry's decision_id equals
        decisions[0].decision_id. OBSERVED at CP 484fdbd2 with a decide-only run: every entry has decision_id None, because
        the journal is written before the decision exists. This test states the frozen oracle and FAILS against the real
        record, hence expectedFailure: it is a reported oracle/behaviour mismatch (see report), NOT a pass. If CP ever
        starts linking events, this flips to an 'unexpected success' error and must be revisited deliberately."""
        _, record = self.independent_record()
        did = record["decisions"][0]["decision_id"]
        for e in record["check_events"]:
            self.assertEqual(e["decision_id"], did)

    def test_p1_check_events_decision_id_observed(self):
        """Observation that documents the mismatch above (so it cannot drift silently)."""
        _, record = self.independent_record()
        self.assertEqual({e["decision_id"] for e in record["check_events"]}, {None})
        self.assertEqual(len(record["check_events"]), 13)  # fixture-observed literal, not a contract invariant (section 7 / 14)

    def test_p1_adapter_evidence_agrees_with_independent_observation(self):
        ev = self.ev
        self.assertEqual(ev["schema"], EVIDENCE_SCHEMA)
        self.assertEqual(ev["case_id"], CASE_P1)
        nr = ev["native_replay"]
        self.assertEqual(nr["outcome"], "IMPORTED")
        self.assertEqual(nr["status"], RB_STATUS)
        self.assertEqual([tuple(f) for f in nr["findings"]], FINDINGS)
        self.assertEqual(set(nr["record_types"]), RECORD_TYPES)
        self.assertIs(nr["has_check_events"], True)
        for key in ("attempts", "observations", "reconciliations", "closeouts"):
            self.assertEqual(nr["counts"][key], 0, key)
        self.assertEqual(ev["native_cp_decision"]["effect_id"], EFFECT_ID)
        self.assertEqual(ev["native_cp_decision"]["result"], "authorized")
        self.assertEqual(ev["destination"]["effect_count"], 0)
        self.assertEqual(ev["destination"]["effects"], {})
        self.assertEqual(ev["producer_config_id"], CONFIG_ID)
        self.assertEqual(ev["producer"]["config_id"], CONFIG_ID)
        self.assertEqual(ev["inputs"]["proposal"]["sha256"], PROPOSAL_FILE_SHA)
        for key, adapter_key in (("cp", "control_plane"), ("rb", "replay_bundle")):
            src = ev["sources"][adapter_key]
            self.assertEqual((src["repository"], src["pinned_sha"], src["observed_head"]), (PINS[key][0], PINS[key][1], PINS[key][1]))
            self.assertEqual((src["pinned_tree"], src["observed_tree"]), (PINS[key][2], PINS[key][2]))
            self.assertIs(src["tracked_files_clean"], True)
            self.assertIs(src["ls_files_all_H"], True)
            self.assertIs(src["status_ignored_clean"], True)
            self.assertTrue(src["imported_modules"])
        self.assertEqual(ev["sources"]["revision_label"], CP_SHA)
        self.assertIn("tests.test_runtime_authority", ev["sources"]["control_plane"]["imported_modules"])
        self.assertTrue(ev["runtime"]["python"] and ev["runtime"]["pydantic"])
        # the oracle block is the adapter's own comparison; every entry must be true, and it must not be vacuous
        self.assertGreaterEqual(len(ev["oracle"]["checks"]), 20, "oracle block must not be vacuous")
        for chk in ev["oracle"]["checks"]:
            self.assertIs(chk["ok"], True, chk["name"])
        self.assertIs(ev["oracle"]["all_ok"], True)
        self.assertEqual((ev["outcome"], ev["status"]), ("IMPORTED", "PASS"))
        json.dumps(ev)

    def test_p1_vocabulary_never_claims_complete_replay(self):
        text = json.dumps(self.ev).lower()
        for word in ("reconstruction_complete", "\"replayed\"", "\"complete\"", "rb accepts c1"):
            self.assertNotIn(word, text)
        self.assertNotIn(self.ev["native_replay"]["outcome"], ("ACCEPTED", "COMPLETE", "REPLAYED", "VERIFIED", "PASS"))

    def test_lineage_is_identity_level_only(self):
        lin = self.ev["lineage"]
        self.assertEqual(lin["level"], "identity_and_proposal_level_not_decision_exact")
        # section 9 continuity table: EQUAL rows and NEW rows (classification is frozen text, values are this test's)
        for key in ("effect_id", "proposal_commitment", "tenant_id", "generation", "result", "run_id", "decided_at", "time_source"):
            self.assertIs(lin["equal"][key], True, key)
        self.assertIs(lin["new"]["decision_id_differs"], True)
        self.assertIs(lin["new"]["check_events_present"], True)
        self.assertIs(lin["new"]["c1_check_events_present"], False)
        self.assertIs(lin["new"]["binding_runtime_authority"], True)
        self.assertIs(lin["new"]["c1_binding_runtime_authority"], False)
        self.assertIs(lin["new"]["record_sha256_differs"], True)
        self.assertEqual(lin["c1_records_sha256"], C1_RECORDS_SHA["positive"])
        self.assertNotIn("decision_exact\": true", json.dumps(lin).lower())

    def test_no_effect_path_called_and_decide_count(self):
        for name, spy in self.spy.forbidden.items():
            self.assertEqual(spy.call_count, 0, name + " (an effect path) must never be called")
        with_profile = [w for w in self.spy.decide_wfs if getattr(w, "runtime_authority_profile", None) is not None]
        self.assertEqual(len(with_profile), 1, "decide() runs exactly once on the runtime-profile workflow that yields the record")
        # SPEC allows a discarded baseline decide() (learns required_inputs); nothing else may call decide()
        self.assertLessEqual(len(self.spy.decide_wfs), 2)
        self.assertEqual(self.ev["producer"]["calls"], ["decide"])

    def test_rb_receives_pinned_proposal_and_measured_label(self):
        calls = self.spy.rb_calls
        self.assertEqual(len(calls), 1, "P1 makes exactly one Replay Bundle import call (no retry under another label)")
        c = calls[0]
        self.assertEqual(c["args"], ())
        self.assertEqual(set(c["kwargs"]), {"proposal", "control_plane_revision"})
        self.assertIsNotNone(c["kwargs"]["proposal"], "proposal is mandatory (R4)")
        self.assertEqual(c["kwargs"]["proposal"], proposal_obj())
        self.assertEqual(c["kwargs"]["control_plane_revision"], CP_SHA)  # measured head == pin literal
        self.assertNotEqual(c["kwargs"]["control_plane_revision"], IMP.CONTROL_PLANE_REVISION, "never the RB default/older label")

    def test_record_bytes_preserved_and_not_reserialised(self):
        data, record = self.independent_record()
        c = self.spy.rb_calls[0]
        self.assertEqual(c["record"], record, "RB receives exactly the parse of the persisted bytes")
        # the file's hash/size/mtime/inode as seen INSIDE the RB call equal those seen after the run: the adapter never rewrote it
        self.assertEqual(len(self.spy.fingerprint), 1)
        st = os.stat(self.ev["record"]["path"])
        self.assertEqual(self.spy.fingerprint[0], (sha256(data), st.st_size, st.st_mtime_ns, st.st_ino))
        self.assertEqual(self.ev["record"]["sha256"], self.spy.fingerprint[0][0])
        # byte form is the CP store's own (indent-2, ensure_ascii); a canonical re-serialisation by the adapter would differ
        self.assertNotEqual(sha256((json.dumps(record, sort_keys=True) + "\n").encode()), self.ev["record"]["sha256"])

    def test_pinned_trees_untouched_by_the_run(self):
        self.assertEqual(self.spy.trees_before, self.spy.trees_after)
        for root in (CP_ROOT, RB_ROOT):
            done = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--ignored=matching", "--untracked-files=all"],
                                  capture_output=True, text=True, check=True)
            self.assertEqual(done.stdout, "")

    def test_clock_patch_restored_and_declared(self):
        self.assertTrue(self.spy.clock_restored, "bounded._now must be the original function after the run")
        # producer reports no patch; if a draft ever reports one it must be the declared private symbol (and was restored above)
        self.assertIn(self.ev["producer"]["clock_patch"], ("none", "private_cp_symbol"))
        self.assertEqual(self.ev["clock"]["clock_patch"], self.ev["producer"]["clock_patch"])
        self.assertEqual((self.ev["clock"]["now"], self.ev["clock"]["allow_test_time"]), (DECIDED_AT, True))

    def test_private_dependencies_declared(self):
        deps = self.ev["producer"]["private_api_dependencies"]
        self.assertTrue(deps)
        for d in deps:
            for key in ("module", "file", "git_blob_sha", "file_sha256", "symbol", "why"):
                self.assertTrue(d.get(key), key)
        files = {d["file"] for d in deps}
        self.assertEqual(files, {"tests/test_runtime_authority.py", "tests/test_bounded_authorization.py"})
        self.assertIn("sign_evidence", " ".join(d["symbol"] for d in deps))
        for d in deps:  # blob + sha of the pinned files, computed here from the pinned worktree
            data = (CP_ROOT / d["file"]).read_bytes()
            self.assertEqual(d["file_sha256"], sha256(data))
            self.assertEqual(d["git_blob_sha"], hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest())

    def test_limits_block_complete_and_non_overclaiming(self):
        limits = self.ev["limits"]
        for key, value in LIMITS.items():
            self.assertIn(key, limits, key)
            self.assertEqual(limits[key], value, key)
        blob = json.dumps(limits).lower()
        for word in MIN_FRESH_REQUIRED_WORDS:
            self.assertIn(word.lower(), blob, "limits block lacks the frozen label: " + word)
        self.assertEqual(self.ev["limits"]["hub_280_digest_basis"], "OPEN")
        for claim in ("certified", "production ready", "production-ready", "cleared", "qualified by"):
            self.assertNotIn(claim, blob.replace("not_independent_qualification", ""))


class N1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spy = n1()
        if cls.spy.error is not None:
            raise cls.spy.error
        cls.ev = cls.spy.result
        cls.record_path = cls.spy.work / "run" / "run.json"  # the persisted record of N1's own P1 precondition run

    def test_native_tenant_refusal_proves_tenant_check_reached(self):
        ev = self.ev
        self.assertEqual(ev["case_id"], CASE_N1)
        nr = ev["native_replay"]
        self.assertEqual(nr["outcome"], "REFUSED_NATIVE")
        self.assertEqual(nr["type"], "ImportContractError")
        self.assertEqual(nr["message"], N1_MESSAGE)  # equality, not substring: another check firing first must fail
        self.assertIsNone(nr["code"])
        self.assertIs(ev["tenant_check_reached"], True)
        self.assertEqual((ev["outcome"], ev["status"]), ("REFUSED_NATIVE", "PASS"))
        self.assertEqual([c["ok"] for c in ev["oracle"]["checks"]], [True, True])

    def test_mutation_scope_and_hash_semantics(self):
        ev, m = self.ev, self.ev["mutation"]
        self.assertEqual(m["field_path"], "decisions[0].binding.tenant_id")
        self.assertEqual((m["from"], m["to"]), ("tenant-alpha", "tenant-beta"))
        self.assertEqual(m["sha256_of"], "canonical_reserialisation_of_test_mutation")
        self.assertIs(m["proposal_supplied"], True)
        original = self.record_path.read_bytes()
        self.assertEqual(m["original_record_sha256"], sha256(original))  # independent hash of the persisted file
        self.assertEqual(ev["p1_precondition"]["record_sha256"], sha256(original))
        self.assertNotEqual(m["mutated_input_sha256"], sha256(original), "mutated input must not carry the original bytes hash")
        self.assertEqual(m["proposal_sha256"], PROPOSAL_FILE_SHA)

    def test_rb_received_exactly_one_field_changed_and_the_original_proposal(self):
        original = strict_loads(self.record_path.read_bytes())
        self.assertEqual(len(self.spy.rb_calls), 2, "P1 precondition import + one mutated import; no retry")
        self.assertEqual(self.spy.rb_calls[0]["record"], original)
        mutated = copy.deepcopy(original)
        mutated["decisions"][0]["binding"]["tenant_id"] = "tenant-beta"
        self.assertEqual(self.spy.rb_calls[1]["record"], mutated)  # only that field differs: not tenantless, not commitment, not journal
        for c in self.spy.rb_calls:
            self.assertEqual(c["args"], ())
            self.assertEqual(c["kwargs"], {"proposal": proposal_obj(), "control_plane_revision": CP_SHA})

    def test_control_without_proposal_would_import(self):
        """Why the proposal is mandatory (contract 7, R4): the same mutation WITHOUT the proposal skips the tenant check. This
        test makes its own direct RB call; the adapter must therefore never reach that path (see ApiShapeTests / label tests)."""
        original = strict_loads(self.record_path.read_bytes())
        original["decisions"][0]["binding"]["tenant_id"] = "tenant-beta"
        IMP.import_bounded_workflow(original, control_plane_revision=CP_SHA)  # must not raise

    def test_native_error_preserved_distinct_from_adapter_error(self):
        """Native refusals are data in the evidence (type/message/code verbatim), never an AdapterError; a non-native
        exception from Replay is not turned into a native refusal."""
        with tempfile.TemporaryDirectory() as tmp:
            boom = IMP.ImportContractError("synthetic native message", code="synthetic_code")
            with mock.patch.object(IMP, "import_bounded_workflow", side_effect=boom):
                ev = real_c2.run_p1(CP_ROOT, RB_ROOT, pathlib.Path(tmp) / "w")
            self.assertEqual(ev["native_replay"], {"outcome": "REFUSED_NATIVE", "type": "ImportContractError",
                                                   "message": "synthetic native message", "code": "synthetic_code"})
            self.assertNotEqual(ev["status"], "PASS")  # a refusal on P1 is never an adapter PASS
            self.assertEqual(ev["outcome"], "REFUSED_NATIVE")
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(IMP, "import_bounded_workflow", side_effect=RuntimeError("not a contract refusal")):
                with self.assertRaises(real_c2.AdapterError):
                    real_c2.run_p1(CP_ROOT, RB_ROOT, pathlib.Path(tmp) / "w")

    def test_other_native_message_is_a_fail_not_a_pass(self):
        real = IMP.import_bounded_workflow
        n = []

        def wrong_message(record, **kw):
            n.append(1)
            if len(n) == 1:
                return real(record, **kw)  # the P1 precondition import is genuine
            raise IMP.ImportContractError("typed refusal profile: original horizon commitment differs from original binding")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(IMP, "import_bounded_workflow", side_effect=wrong_message):
            ev = real_c2.run_n1(CP_ROOT, RB_ROOT, pathlib.Path(tmp) / "w")
        self.assertEqual(ev["status"], "FAIL")
        self.assertNotEqual(ev["outcome"], "REFUSED_NATIVE")
        self.assertIs(ev["tenant_check_reached"], False)

    def test_n1_import_that_succeeds_is_a_fail(self):
        real = IMP.import_bounded_workflow
        with tempfile.TemporaryDirectory() as tmp:
            def lenient(record, **kw):
                kw.pop("proposal", None)  # simulates an importer that skips the tenant check
                return real(record, **kw)
            with mock.patch.object(IMP, "import_bounded_workflow", side_effect=lenient):
                ev = real_c2.run_n1(CP_ROOT, RB_ROOT, pathlib.Path(tmp) / "w")
        self.assertEqual(ev["status"], "FAIL")
        self.assertNotEqual(ev["outcome"], "REFUSED_NATIVE")
        self.assertEqual(ev["native_replay"]["outcome"], "IMPORTED")

    def test_no_effect_path_in_n1(self):
        for name, spy in self.spy.forbidden.items():
            self.assertEqual(spy.call_count, 0, name)


class N2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spy = n2()
        if cls.spy.error is not None:
            raise cls.spy.error
        cls.ev = cls.spy.result

    def test_both_c1_hosted_records_refused_natively(self):
        self.assertEqual(self.ev["case_id"], CASE_N2)
        self.assertEqual((self.ev["outcome"], self.ev["status"]), ("REFUSED_NATIVE", "PASS"))
        self.assertEqual(self.ev["sources"]["revision_label"], CP_SHA)
        for label in ("positive", "negative"):
            entry = self.ev["records"][label]
            with self.subTest(record=label):
                nr = entry["native_replay"]
                self.assertEqual(nr["outcome"], "REFUSED_NATIVE")
                self.assertEqual((nr["type"], nr["message"], nr["code"]), ("ImportContractError", N2_MESSAGE, None))
                self.assertEqual(entry["records_sha256"], C1_RECORDS_SHA[label])
                self.assertEqual(entry["sha256_of"], "file_bytes")
                self.assertEqual((entry["hosted_run_id"], entry["hosted_artifact_id"]), C1_RUNS[label])

    def test_independent_native_refusal_on_the_fixture_bytes(self):
        for label, name in (("positive", "c1-hosted-native-records.positive.json"), ("negative", "c1-hosted-native-records.negative.json")):
            data = (C2_FIXTURES / name).read_bytes()
            self.assertEqual(sha256(data), C1_RECORDS_SHA[label])
            with self.assertRaises(IMP.ImportContractError) as cm:
                IMP.import_bounded_workflow(strict_loads(data), proposal=proposal_obj(), control_plane_revision=CP_SHA)
            self.assertEqual((str(cm.exception), cm.exception.code), (N2_MESSAGE, None))

    def test_label_and_proposal_on_every_call_and_no_retry(self):
        calls = self.spy.rb_calls
        self.assertEqual(len(calls), 2, "one import per hosted record; never retried under another label")
        for c in calls:
            self.assertEqual(c["args"], ())
            self.assertEqual(c["kwargs"], {"proposal": proposal_obj(), "control_plane_revision": CP_SHA})
        self.assertEqual(sorted(json.dumps(c["record"], sort_keys=True) for c in calls),
                         sorted(json.dumps(strict_loads((C2_FIXTURES / n).read_bytes()), sort_keys=True)
                                for n in ("c1-hosted-native-records.positive.json", "c1-hosted-native-records.negative.json")))

    def test_mislabel_hazard_never_appears_in_adapter_evidence(self):
        """Under another label RB may behave differently on the same C1 record (a mislabel). The adapter must never try one:
        every RB call carried the measured pin (above) and the evidence never records an IMPORTED C1 record or the older label."""
        older = IMP.CONTROL_PLANE_REVISION
        self.assertNotEqual(older, CP_SHA)
        for label in ("positive", "negative"):
            self.assertNotEqual(self.ev["records"][label]["native_replay"]["outcome"], "IMPORTED")
        self.assertNotIn(older, json.dumps(self.ev))

    def test_no_effect_path_in_n2(self):
        for name, spy in self.spy.forbidden.items():
            self.assertEqual(spy.call_count, 0, name)
        self.assertEqual(self.spy.decide_wfs, [], "N2 never runs the producer")


class SourceIdentityTests(unittest.TestCase):
    """Run in fresh interpreters (python -I -B): proves no component is imported / no sys.path entry is added when the source gate fails."""

    PROBE = r"""
import sys, json, os, pathlib
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import real_c2
before_path = list(sys.path)
out = {"clean_at_import": not any(m.startswith(("agent_control_plane", "agent_replay_bundle")) for m in sys.modules)}
try:
    real_c2.%s
    out["raised"] = None
except BaseException as e:
    out["raised"] = [type(e).__name__, [c.__name__ for c in type(e).__mro__]]
out["component_modules"] = sorted(m for m in sys.modules if m.startswith(("agent_control_plane", "agent_replay_bundle")))
out["tests_pkg_loaded"] = "tests" in sys.modules
out["path_added"] = [p for p in sys.path if p not in before_path]
out["workdir_files"] = sorted(os.listdir(sys.argv[4])) if os.path.isdir(sys.argv[4]) else None
print(json.dumps(out))
"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="c2t-src-"))
        cls.good_cp = cls.tmp / "cp-good"
        cls.run_git("clone", "-q", "--no-hardlinks", str(CP_ROOT), str(cls.good_cp))
        cls.run_git("-C", str(cls.good_cp), "checkout", "-q", "--detach", CP_SHA)
        cls.good_rb = cls.tmp / "rb-good"
        cls.run_git("clone", "-q", "--no-hardlinks", str(RB_ROOT), str(cls.good_rb))
        cls.run_git("-C", str(cls.good_rb), "checkout", "-q", "--detach", RB_SHA)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def run_git(*args):
        subprocess.run(["git", "-c", "advice.detachedHead=false", *args], check=True, capture_output=True,
                       env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent", "GIT_CONFIG_GLOBAL": "/dev/null"})

    def probe(self, call, cp, rb, workdir=None, tree=None):
        workdir = workdir or (self.tmp / "work-probe")
        argv = [sys.executable, "-I", "-B", "-c", self.PROBE % call, str(tree or MANUAL_CONTRACT), str(cp), str(rb), str(workdir)]
        done = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=tempfile.gettempdir())
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def assert_refused_clean(self, out):
        self.assertTrue(out["clean_at_import"], "importing real_c2 must not import component code")
        self.assertEqual(out["raised"][0], "SourceIdentityError")
        self.assertIn("AdapterError", out["raised"][1])
        self.assertEqual(out["component_modules"], [], "no component module may be imported after a failed source gate")
        self.assertFalse(out["tests_pkg_loaded"])
        self.assertEqual([p for p in out["path_added"] if "cp" in pathlib.Path(p).name or "rb" in pathlib.Path(p).name], [])

    def clone(self, which, name):
        src = self.good_cp if which == "cp" else self.good_rb
        dst = self.tmp / name
        self.run_git("clone", "-q", "--no-hardlinks", str(src), str(dst))
        self.run_git("-C", str(dst), "checkout", "-q", "--detach", CP_SHA if which == "cp" else RB_SHA)
        return dst

    def test_positive_control_clean_clones_pass_measurement(self):
        out = self.probe("measure(sys.argv[2], sys.argv[3])", self.good_cp, self.good_rb)
        self.assertIsNone(out["raised"], out)

    def test_dirty_cp_untracked_file(self):
        bad = self.clone("cp", "cp-untracked")
        (bad / "src" / "stray.py").write_text("x = 1\n")
        out = self.probe("run_p1(sys.argv[2], sys.argv[3], sys.argv[4])", bad, self.good_rb, self.tmp / "w-untracked")
        self.assert_refused_clean(out)
        self.assertIn(out["workdir_files"], (None, []), "no producer output after a failed gate")

    def test_dirty_cp_modified_tracked_file(self):
        bad = self.clone("cp", "cp-modified")
        target = bad / "src" / "agent_control_plane" / "bounded.py"
        target.write_bytes(target.read_bytes() + b"\n# tampered\n")
        out = self.probe("run_p1(sys.argv[2], sys.argv[3], sys.argv[4])", bad, self.good_rb, self.tmp / "w-modified")
        self.assert_refused_clean(out)

    def test_dirty_rb_modified_tracked_file(self):
        bad = self.clone("rb", "rb-modified")
        target = bad / "src" / "agent_replay_bundle" / "importers.py"
        target.write_bytes(target.read_bytes() + b"\n# tampered\n")
        out = self.probe("run_p1(sys.argv[2], sys.argv[3], sys.argv[4])", self.good_cp, bad, self.tmp / "w-rbmod")
        self.assert_refused_clean(out)

    def test_skip_worktree_hides_modification_is_refused(self):
        bad = self.clone("cp", "cp-skipworktree")
        target = bad / "src" / "agent_control_plane" / "bounded.py"
        target.write_bytes(target.read_bytes() + b"\n# hidden tamper\n")
        self.run_git("-C", str(bad), "update-index", "--skip-worktree", "src/agent_control_plane/bounded.py")
        out = self.probe("measure(sys.argv[2], sys.argv[3])", bad, self.good_rb)
        self.assert_refused_clean(out)

    def test_other_commit_is_refused_not_downgraded(self):
        bad = self.clone("cp", "cp-othercommit")
        self.run_git("-C", str(bad), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "x")
        out = self.probe("measure(sys.argv[2], sys.argv[3])", bad, self.good_rb)
        self.assert_refused_clean(out)

    def test_wrong_roots_are_refused(self):
        for name, cp in (("missing", self.tmp / "does-not-exist"), ("empty", self.tmp / "empty-dir"), ("subdir", self.good_cp / "src")):
            if name == "empty":
                cp.mkdir()
            with self.subTest(root=name):
                self.assert_refused_clean(self.probe("measure(sys.argv[2], sys.argv[3])", cp, self.good_rb))
        # cp and rb swapped
        self.assert_refused_clean(self.probe("measure(sys.argv[2], sys.argv[3])", self.good_rb, self.good_cp))

    def test_cli_exit_code_2_for_source_failure(self):
        bad = self.clone("cp", "cp-cli")
        (bad / "stray.txt").write_text("x\n")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), ENV_CP: str(bad), ENV_RB: str(self.good_rb)}
        out_json = self.tmp / "cli-result.json"
        done = subprocess.run([sys.executable, "-I", "-B", str(MANUAL_CONTRACT / "real_c2.py"), "--case", CASE_P1, "--out", str(out_json),
                               "--workdir", str(self.tmp / "w-cli")], capture_output=True, text=True, env=env, cwd=tempfile.gettempdir(), timeout=300)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertFalse(out_json.exists(), "no result file is written for an adapter error")


class FixtureIntegrityTests(unittest.TestCase):
    def run_in_tree(self, tree, call):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        code = ("import sys, json; sys.dont_write_bytecode=True; sys.path.insert(0, sys.argv[1]); import real_c2, pathlib\n"
                "try:\n    real_c2.%s\n    print(json.dumps(['OK']))\n"
                "except BaseException as e:\n    print(json.dumps([type(e).__name__, [c.__name__ for c in type(e).__mro__], str(e)[:200]]))\n" % call)
        done = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(tree), str(CP_ROOT), str(RB_ROOT), str(tree / "work")],
                              capture_output=True, text=True, timeout=300, cwd=tempfile.gettempdir(), env=dict(env))
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_altered_proposal_fixture_is_refused_before_any_producer_or_rb_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(pathlib.Path(tmp) / "mc")
            path = tree / "c1" / "fixtures" / "proposal.tenant-alpha.json"
            path.write_bytes(path.read_bytes() + b"\n")  # one byte: same JSON value, different file sha256
            out = self.run_in_tree(tree, "run_p1(sys.argv[2], sys.argv[3], sys.argv[4])")
            self.assertIn("AdapterError", out[1])
            self.assertNotEqual(out[0], "OK")
            self.assertFalse((tree / "work" / "run" / "run.json").exists(), "producer must not run on an altered proposal fixture")

    def test_altered_c1_hosted_record_fixture_is_refused_by_n2(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(pathlib.Path(tmp) / "mc")
            path = tree / "c2" / "fixtures" / "c1-hosted-native-records.positive.json"
            path.write_bytes(path.read_bytes() + b"\n")
            out = self.run_in_tree(tree, "run_n2(sys.argv[2], sys.argv[3])")
            self.assertIn("AdapterError", out[1])

    def test_strict_loader_rejects_duplicate_keys_and_nan(self):
        for text in ('{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}'):
            with self.subTest(text=text):
                loader = getattr(real_c2, "_strict_loads", None)
                self.assertIsNotNone(loader, "adapter must expose a strict loader")
                with self.assertRaises(ValueError):
                    loader(text.encode())


class ApiShapeTests(unittest.TestCase):
    def test_public_surface_and_error_hierarchy(self):
        for name in ("run_p1", "run_n1", "run_n2", "measure", "main", "AdapterError", "SourceIdentityError"):
            self.assertTrue(hasattr(real_c2, name), name)
        self.assertTrue(issubclass(real_c2.SourceIdentityError, real_c2.AdapterError))
        self.assertTrue(issubclass(real_c2.AdapterError, Exception))

    def test_proposal_cannot_be_omitted_or_overridden_through_the_api(self):
        for fn in (real_c2.run_p1, real_c2.run_n1, real_c2.run_n2):
            params = inspect.signature(fn).parameters
            for p in params:
                self.assertNotIn("proposal", p.lower(), fn.__name__ + " must not accept a proposal argument")
        self.assertEqual(list(inspect.signature(real_c2.run_p1).parameters), ["cp_root", "rb_root", "workdir"])
        self.assertEqual(list(inspect.signature(real_c2.run_n1).parameters), ["cp_root", "rb_root", "workdir"])
        self.assertEqual(list(inspect.signature(real_c2.run_n2).parameters), ["cp_root", "rb_root"])

    def test_adapter_constants_match_frozen_literals(self):
        self.assertEqual(real_c2.EVIDENCE_SCHEMA, EVIDENCE_SCHEMA)
        self.assertEqual((real_c2.ENV_CP_ROOT, real_c2.ENV_RB_ROOT), (ENV_CP, ENV_RB))
        for key, (repo, sha, tree) in PINS.items():
            adapter_key = {"cp": "control_plane", "rb": "replay_bundle"}[key]
            pin = real_c2.PINS[adapter_key]
            self.assertEqual((pin["repository"], pin["sha"], pin["tree"]), (repo, sha, tree))
        self.assertEqual(real_c2.FROZEN["proposal_sha256"], PROPOSAL_FILE_SHA)
        self.assertEqual(real_c2.FROZEN["c1_records_positive_sha256"], C1_RECORDS_SHA["positive"])
        self.assertEqual(real_c2.FROZEN["c1_records_negative_sha256"], C1_RECORDS_SHA["negative"])


class ProvenanceAndDeviationTests(unittest.TestCase):
    """Review SHOULD-FIX 2/3: the contract section 14 provenance record, and the machine-readable frozen-oracle deviation."""

    @classmethod
    def setUpClass(cls):
        cls.ev = p1().result

    def test_producer_configuration_identity_and_provenance(self):
        prod = self.ev["producer"]
        self.assertEqual(prod["config_id"], "C2-CP-RUNTIME-PROFILE-STRICT-TENANT-DECIDE-ONLY")
        self.assertEqual(prod["catalogue_version"], "synthetic-catalogue/1")
        self.assertEqual(prod["action_class_id"], "synthetic-irreversible")
        self.assertEqual(prod["producer_key_id"], "synthetic-validator")
        self.assertRegex(prod["producer_public_key_hex"], r"^[0-9a-f]{64}$")  # the TEST-ONLY public key (bytes(range(32)) seed)
        self.assertEqual(prod["authority_profile"], "runtime-authority/0.1")
        self.assertIs(prod["allow_synthetic_resolver"], True)
        self.assertEqual(prod["tenant_binding_generation"], GENERATION)
        for key in ("derived_authority_context_commitment", "required_inputs_digest"):
            self.assertRegex(prod[key], r"^sha256:[0-9a-f]{64}$")
        self.assertIn("NO RuntimeAuthorityProfile", prod["c1_configuration_contrast"])
        self.assertIn("agent_replay_bundle.ingress.check_depth", prod["other_symbols_used"])

    def test_frozen_oracle_deviation_is_machine_readable(self):
        dev = self.ev["frozen_oracle_deviations"]
        self.assertEqual(len(dev), 1)
        self.assertIn("freeze", dev[0]["contract_section"])
        self.assertEqual(dev[0]["observed"]["event_decision_ids"], ["None"])
        self.assertEqual(dev[0]["observed"]["event_count"], 13)
        self.assertIs(dev[0]["observed"]["events_check_id_equals_resolution_check_id"], False)
        self.assertEqual(dev[0]["disposition"], "contract amendment requested from the Architect")
        names = {c["name"]: c for c in self.ev["oracle"]["checks"]}
        self.assertTrue(names["check_events_decision_id_observed_null"]["ok"])
        self.assertTrue(names["check_events_proposal_commitment"]["ok"])


class ModuleGuardTests(unittest.TestCase):
    """Review SHOULD-FIX 1: the git-blob guards of _check_modules fail closed on their own (not only via the dirty-tree gate)."""

    def make_repo(self, tmp, symlink=False):
        import uuid
        name = "c2guard" + uuid.uuid4().hex[:8]
        root = pathlib.Path(tmp).resolve()
        (root / name).mkdir()
        (root / name / "__init__.py").write_text("VALUE = 1\n")
        (root / "fixture.json").write_text("{}\n")
        if symlink:
            (root / "link.json").symlink_to("fixture.json")
        env = {"PATH": os.environ["PATH"], "HOME": "/nonexistent", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x"]):
            subprocess.run(["git", "-C", str(root), *args], check=True, env=env, capture_output=True)
        sys.path.insert(0, str(root))
        self.addCleanup(lambda: (sys.path.remove(str(root)), [sys.modules.pop(m) for m in [m for m in sys.modules if m.startswith(name)]]))
        __import__(name)
        return root, name

    def test_clean_module_and_extra_file_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, name = self.make_repo(tmp)
            ev = {}
            real_c2._check_modules(root, ev, name, required=(name,), extra_files=("fixture.json",))
            self.assertIn(name, ev["imported_modules"])
            self.assertIn("fixture.json", ev["imported_modules"])

    def test_tampered_loaded_module_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, name = self.make_repo(tmp)
            (root / name / "__init__.py").write_text("VALUE = 2\n")
            with self.assertRaisesRegex(real_c2.SourceIdentityError, "differs from the pinned git blob"):
                real_c2._check_modules(root, {}, name, required=(name,))

    def test_tampered_extra_file_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, name = self.make_repo(tmp)
            (root / "fixture.json").write_text('{"x": 1}\n')
            with self.assertRaisesRegex(real_c2.SourceIdentityError, "differs from the pinned git blob"):
                real_c2._check_modules(root, {}, name, required=(name,), extra_files=("fixture.json",))

    def test_missing_required_module_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, name = self.make_repo(tmp)
            with self.assertRaisesRegex(real_c2.SourceIdentityError, "required modules not loaded"):
                real_c2._check_modules(root, {}, name, required=(name + ".never_imported",))

    def test_symlink_in_pinned_tree_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, name = self.make_repo(tmp, symlink=True)
            with self.assertRaisesRegex(real_c2.SourceIdentityError, "symlink or gitlink"):
                real_c2._check_modules(root, {}, name, required=(name,))


class StaticEffectPathGuardTests(unittest.TestCase):
    """Review NIT 4: the new modules never name an effect path (the runtime spies only catch dynamic calls)."""

    def test_no_effect_call_names_in_adapter_or_producer(self):
        import ast
        forbidden_calls = {"execute", "reconcile", "apply", "system", "Popen", "urlopen", "connect"}
        forbidden_imports = {"socket", "urllib", "http", "requests", "moltbot", "ssl"}
        for fn in ("real_c2.py", "c2_producer.py"):
            tree = ast.parse((MANUAL_CONTRACT / fn).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                    self.assertNotIn(name, forbidden_calls, fn + " calls " + str(name))
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                    for m in mods:
                        self.assertNotIn(m.split(".")[0].lower(), forbidden_imports, fn + " imports " + m)


class MainCliTests(unittest.TestCase):
    def run_cli(self, case, extra_env=None):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "result.json"
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), ENV_CP: str(CP_ROOT), ENV_RB: str(RB_ROOT)}
            env.update(extra_env or {})
            done = subprocess.run([sys.executable, "-I", "-B", str(MANUAL_CONTRACT / "real_c2.py"), "--case", case, "--out", str(out),
                                   "--workdir", str(pathlib.Path(tmp) / "w")], capture_output=True, text=True, env=env,
                                  cwd=tempfile.gettempdir(), timeout=600)
            return done, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None)

    def test_unknown_case_is_refused_with_exit_2(self):
        done, result = self.run_cli("not_a_case")
        self.assertIn(done.returncode, (2,))  # argparse choices error also exits 2
        self.assertIsNone(result)

    def test_n2_case_exit_0_and_native_result(self):
        done, result = self.run_cli(CASE_N2)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(result["case_id"], CASE_N2)
        self.assertEqual(result["schema"], EVIDENCE_SCHEMA)


if __name__ == "__main__":
    unittest.main()
