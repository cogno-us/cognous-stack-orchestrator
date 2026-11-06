"""Focused tests for the VSLICE-C4 coordinator (real_c4): Action Manifest gate -> Control Plane decide() -> Replay Bundle -> Governance
Evidence Pack (P1, N1-HOLD, N2-FLIP).

DRAFT. Expectations come ONLY from the frozen literals restated below (Hub #273 contract comment 6674059997 sections 6, 8, 9, 10 and
16, frozen for development by the Architect decision A1-A9) and from this file's OWN independent observations: persisted Control Plane
records, bundles, Packs and destination files read from disk, plus this file's own calls to the native Action Manifest, Replay and Pack
APIs. Harness evidence is compared AGAINST them and is never read back as an expectation. stdlib unittest only; run under
`python -I -B` through .github/scripts/run_unittest_no_skips.py. The four component roots are REQUIRED from the environment (the run
fails, it never skips). Pinned checkouts are never written to.

A green run means the pinned native components matched these literals on a synthetic fixture. It is not qualification, approval,
completeness, authenticity, custody, freshness or proof of any external effect. Cases named "control" and the L22 observation are NOT
frozen oracle cases. N3-GATE is deferred and not exercised here.
"""
import sys

sys.dont_write_bytecode = True  # never write .pyc into the pinned checkouts: their cleanliness is part of the source gate

import contextlib  # noqa: E402
import copy  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import pathlib  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
MANUAL_CONTRACT = HERE.parent
sys.path.insert(0, str(MANUAL_CONTRACT))
import real_c4  # noqa: E402  (must not import any component at module import time)

ENV = {"am": "COGNOUS_C4_ACTION_MANIFEST_ROOT", "cp": "COGNOUS_C4_CONTROL_PLANE_ROOT", "rb": "COGNOUS_C4_REPLAY_BUNDLE_ROOT",
       "pack": "COGNOUS_C4_EVIDENCE_PACK_ROOT"}
CASE_P1, CASE_N1, CASE_N2 = "c4_p1_authorized_chain", "c4_n1_hold_revoked_grant", "c4_n2_flip_hold_to_authorized"

# ---- frozen oracle literals, restated independently of real_c4 (contract sections 6, 8, 9, 10, 16) ----
CP_SHA = "484fdbd297235dd24148ddb0703f2055a31eabff"
RB_SHA = "93a76e281fcae6a65d2cd1d35376f87442dafb95"
AM_SHA = "fa170815ef96a54c233d0dd9da821b60debabf8b"
PROPOSAL_FILE_SHA = "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2"
MANIFEST_FILE_SHA = "789ad39596b9e1ef84a726a671883e1cb6b83343da3a31db0a1120906d68c074"
MANIFEST_REL = "examples/refund_integration_v1_1.manifest.json"
MANIFEST_DIGEST = "sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac"
PROPOSAL_COMMITMENT = "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53"
EFFECT_AUTH = "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8"
EFFECT_HOLD = "sha256:d0e4afe09cdf3a52aa3b530b822411b1dff35031973660fbbf9b707415f18465"
ACTION_ID = "urn:cognous:action:refund-issue-routine-v1"
TENANT, GENERATION = "tenant-alpha", "bounded-authorization-effect/0.3-strict-tenant"
PROFILE, VOCAB = "runtime-authority/0.1", "runtime-authority-reasons/0.1"
DECIDED_AT = "2026-10-05T19:00:00+00:00"
RB_STATUS = "reconstruction_partial"
P1_FINDINGS = [["B004", "warning"]]
N1_FINDING_CODES = {"B004", "B005"}
P1_RECORD_TYPES = {"input_time_floors", "resolution_check", "resolution_check_event", "runtime_decision", "runtime_proposal"}
TRANSFORMATION = "agep-manifest-reconstruction-import/0.3.10-strict-tenant-candidate"
VALIDATOR = "agent_replay_bundle.importers.import_bounded_workflow"
ZERO_COUNTS = ("control_plane_attempt_count", "executor_attempt_count", "attempt_transition_record_count", "destination_effect_count",
               "effect_observation_count", "reconciliation_count")
LIMIT_KEYS = ["L%d" % i for i in range(1, 28)]
CLAIM_WORDS = re.compile(r"complete reconstruction|authenticated authority|verified execution|certified|\bapproved\b|production[- ]ready|"
                         r"independently qualified|\breconstruction_complete\b|executed_effect", re.I)

ROOTS = {}
AM = RB = PK = None  # this file's own imports: AM package, agent_replay_bundle.importers, the Pack importer/validator modules


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
    global AM, RB, PK
    missing = [n for n in ENV.values() if not os.environ.get(n)]
    if missing:
        raise AssertionError("required environment variable(s) not set: %s (point them at the pinned checkouts)" % ", ".join(missing))
    for key, name in ENV.items():
        ROOTS[key] = pathlib.Path(os.environ[name]).resolve()
        if not ROOTS[key].is_dir():
            raise AssertionError("%s is not a directory: %s" % (name, ROOTS[key]))
    sys.path[:0] = [str(ROOTS["pack"] / "src"), str(ROOTS["rb"] / "src"), str(ROOTS["am"] / "src")]  # this test's own imports
    import agent_action_manifest
    from agent_action_manifest import models
    from agent_replay_bundle import importers
    from agent_governance_evidence_pack import importer, validator
    AM = type("AMModules", (), {"pkg": agent_action_manifest, "models": models})
    RB = importers
    PK = type("PackModules", (), {"importer": importer, "validator": validator})


def manifest_bytes():
    data = (ROOTS["am"] / MANIFEST_REL).read_bytes()
    assert sha256(data) == MANIFEST_FILE_SHA, "manifest fixture differs from the frozen literal"
    return data


def proposal_bytes():
    data = (MANUAL_CONTRACT / "c1" / "fixtures" / "proposal.tenant-alpha.json").read_bytes()
    assert sha256(data) == PROPOSAL_FILE_SHA, "proposal fixture differs from the frozen literal"
    return data


def pack_import(manifest, bundle):
    """This file's own call to the native Pack importer on deep copies. Returns (pack, None) or (None, exception)."""
    try:
        return PK.importer.import_manifest_reconstruction(copy.deepcopy(manifest), copy.deepcopy(bundle)), None
    except PK.importer.ImportContractError as exc:
        return None, exc


def diff_paths(a, b, path=""):
    """Paths at which two JSON values differ. Lists of different length differ at the list path itself."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            sub = "%s.%s" % (path, k) if path else k
            if k not in a or k not in b:
                out.append(sub)
            else:
                out += diff_paths(a[k], b[k], sub)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, "%s[%d]" % (path, i))
        return out
    return [] if a == b and type(a) is type(b) else [path]


def decision_index(bundle):
    idx = [i for i, r in enumerate(bundle["records"]) if r.get("record_type") == "runtime_decision"]
    assert len(idx) == 1
    return idx[0]


def pack_parts(pack):
    pd = pack.model_dump(mode="json")
    return pd, (pd.get("metadata") or {}).get("traceable_import") or {}


def dump_parts(pd):
    return pd, (pd.get("metadata") or {}).get("traceable_import") or {}


def errors_of(report):
    return [i for i in report.issues if getattr(i.severity, "value", str(i.severity)) == "error"]


ENV_KEYS = ("action_manifest", "control_plane", "replay_bundle", "evidence_pack")


def real_c3_limits():
    import real_c3  # frozen predecessor constants (L1-L19), hash-pinned by the C3 work; read as data
    return real_c3.LIMITS


def boundaries(ev):
    return {b["boundary"]: b for b in ev["boundaries"]}


class Observed:
    """One harness run_all (all cases) in a fresh workdir plus this file's own on-disk observations."""

    def __init__(self):
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="c4t-"))
        self.results = real_c4.run_all(None, self.work)
        self.manifest_bytes = (self.work / "inputs" / "am-manifest.json").read_bytes()
        self.proposal_bytes = (self.work / "inputs" / "proposal.json").read_bytes()
        self.manifest = strict_loads(self.manifest_bytes)
        self.proposal = strict_loads(self.proposal_bytes)
        self.s = {}
        for s in ("p1", "n1"):
            d = self.work / s
            for p in (d / "cp-record.json", d / "destination.json", d / "reconstruction-bundle.json", d / "evidence-pack.json"):
                assert self.work.resolve() in p.resolve().parents, "persisted artefact outside the workdir: %s" % p
            rec_b, bun_b = (d / "cp-record.json").read_bytes(), (d / "reconstruction-bundle.json").read_bytes()
            self.s[s] = {"dir": d, "record_bytes": rec_b, "record": strict_loads(rec_b), "bundle_path": d / "reconstruction-bundle.json",
                         "bundle_bytes": bun_b, "bundle": strict_loads(bun_b), "dest_path": d / "destination.json",
                         "pack_bytes": (d / "evidence-pack.json").read_bytes()}
            self.s[s]["pack_dump"] = strict_loads(self.s[s]["pack_bytes"])

    def dest_effects(self, s):
        return strict_loads(self.s[s]["dest_path"].read_bytes()).get("effects")

    def own_replay(self, s, proposal=None):
        rec = copy.deepcopy(self.s[s]["record"])
        return RB.import_bounded_workflow(rec, proposal=copy.deepcopy(proposal if proposal is not None else self.proposal),
                                          control_plane_revision=CP_SHA)

    def cleanup(self):
        shutil.rmtree(self.work, ignore_errors=True)


def replay_findings(bundle_model):
    return [[f.code, f.severity] for r in bundle_model.import_reports for f in r.findings]


class P1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obs = Observed()
        cls.ev = cls.obs.results[CASE_P1]
        cls.s = cls.obs.s["p1"]

    @classmethod
    def tearDownClass(cls):
        cls.obs.cleanup()

    def test_p1_harness_status_and_case(self):
        self.assertEqual(self.ev["case_id"], CASE_P1)
        self.assertEqual(self.ev["status"], "PASS")
        self.assertEqual(self.ev["scenario"], "authorized")
        self.assertEqual(self.obs.dest_effects("p1"), {})  # read from disk by this test
        self.assertEqual(self.ev["destination"]["effects"], {})
        for check in self.ev["oracle"]["checks"]:
            self.assertTrue(check["ok"], check["name"])
        self.assertTrue(self.ev["oracle"]["all_ok"])

    def test_p1_am_gate_by_own_native_calls(self):
        data = manifest_bytes()
        self.assertEqual(data, self.obs.manifest_bytes)  # the harness retained the frozen bytes as read
        self.assertEqual(sha256(self.obs.proposal_bytes), PROPOSAL_FILE_SHA)
        self.assertEqual(self.obs.proposal_bytes, proposal_bytes())
        model = AM.pkg.load_manifest_json(strict_loads(data))
        self.assertTrue(AM.pkg.validate_manifest(model).valid)
        self.assertEqual(AM.pkg.manifest_digest(model), MANIFEST_DIGEST)
        prop = AM.models.RuntimeActionProposalV12.model_validate(strict_loads(self.obs.proposal_bytes))
        self.assertEqual(AM.pkg.proposal_digest(prop), PROPOSAL_COMMITMENT)
        self.assertEqual(list(AM.pkg.proposal_mismatches(model, prop)), [])
        # the CP-repo copy parses equal to the gated bytes (contract section 8.1)
        cp_copy = (ROOTS["cp"] / "tests" / "fixtures" / "refund_integration_v1_1.manifest.json").read_bytes()
        self.assertEqual(sha256(cp_copy), MANIFEST_FILE_SHA)
        self.assertEqual(strict_loads(cp_copy), self.obs.manifest)
        # harness AM boundary agrees
        am = boundaries(self.ev)["action_manifest"]
        self.assertEqual(am["orchestration_class"], "ACCEPTED")
        self.assertEqual(am["input_sha256"], MANIFEST_FILE_SHA)

    def test_p1_control_plane_record_from_disk(self):
        rec = self.s["record"]
        self.assertEqual(len(rec["decisions"]), 1)
        d = rec["decisions"][0]
        self.assertEqual((d["result"], d["reasons"]), ("authorized", []))
        self.assertEqual(d["effect_id"], EFFECT_AUTH)
        self.assertEqual((d["time_source"], d["decided_at"], d["reason_vocabulary_version"]), ("test_override", DECIDED_AT, VOCAB))
        self.assertEqual(d["operation_horizon"]["proposal_commitment"], PROPOSAL_COMMITMENT)
        b = d["binding"]
        self.assertEqual((b["manifest_digest"], b["proposal_commitment"], b["tenant_id"], b["generation"], b["action_id"]),
                         (MANIFEST_DIGEST, PROPOSAL_COMMITMENT, TENANT, GENERATION, ACTION_ID))
        self.assertEqual(b["runtime_authority"]["profile"], PROFILE)
        events = rec["check_events"]
        self.assertEqual(len(events), 13)
        for e in events:
            self.assertIsNone(e["decision_id"])
            self.assertEqual(e["proposal_commitment"], PROPOSAL_COMMITMENT)
        for key in ("attempts", "observations", "reconciliations", "closeouts"):
            self.assertEqual(rec.get(key, []), [], key)
        self.assertEqual(self.obs.dest_effects("p1"), {})
        # harness: persisted bytes were read once and hashed
        self.assertEqual(self.ev["identity"]["per_run"]["cp_record_sha256"], sha256(self.s["record_bytes"]))
        self.assertEqual(self.ev["identity"]["per_run"]["decision_id"], d["decision_id"])

    def test_p1_producer_calls_decide_only(self):
        prov = self.ev["producer"] if "producer" in self.ev else self.ev["producer_provenance"]
        self.assertEqual(prov["calls"], ["decide"])
        self.assertEqual(prov["scenario"], "authorized")
        self.assertIsNone(prov["scenario_mutation"])
        self.assertEqual(prov["manifest_source"], "supplied_validated_AM_bytes")
        self.assertTrue(prov["manifest_equals_cp_repo_copy"])

    def test_p1_replay_own_import(self):
        own = self.obs.own_replay("p1")
        self.assertEqual(own.status, RB_STATUS)
        self.assertEqual(replay_findings(own), P1_FINDINGS)
        self.assertEqual(list(own.integrity), [])
        self.assertEqual({r.record_type for r in own.records}, P1_RECORD_TYPES)
        # the persisted bundle (H1 bytes) agrees with this independent import on the stable parts
        b = self.s["bundle"]
        self.assertEqual(b["status"], RB_STATUS)
        self.assertEqual([[f["code"], f["severity"]] for r in b["import_reports"] for f in r["findings"]], P1_FINDINGS)
        self.assertEqual(b["integrity"], [])
        self.assertEqual({r["record_type"] for r in b["records"]}, P1_RECORD_TYPES)
        # harness evidence agrees
        rp = self.ev["native"]["replay"]
        self.assertEqual(rp["status"], RB_STATUS)
        self.assertEqual(rp["findings"], P1_FINDINGS)
        self.assertEqual(rp["integrity"], [])

    def test_p1_pack_own_import_and_validation(self):
        pack, exc = pack_import(self.obs.manifest, self.s["bundle"])
        self.assertIsNone(exc)
        report = PK.validator.validate_evidence_pack(pack)
        self.assertTrue(report.valid)
        self.assertEqual(errors_of(report), [])
        pd, T = pack_parts(pack)
        self.assertEqual(pd["pack_version"], "0.2.0")
        self.assertEqual(pd["review_status"], "draft")
        self.assertEqual(T["transformation_version"], TRANSFORMATION)
        self.assertEqual(T["selected_revisions"], {"manifest": AM_SHA, "replay": RB_SHA, "control_plane": CP_SHA})
        self.assertEqual(T["replay_semantic_validation"], {"validator": VALIDATOR, "required_revision": RB_SHA, "status": "validated_partial"})
        rb0 = pd["replay_bundles"][0]
        self.assertEqual((rb0["status"], rb0["signed"], rb0["redacted"], rb0["validation_status"]),
                         ("validated_partial", False, False, "semantically_valid"))
        self.assertEqual(T["reconstruction_completeness"], RB_STATUS)
        self.assertEqual(T["input_artifacts"][0]["hash"], MANIFEST_DIGEST)
        lc = T["lifecycle_summary"]
        self.assertEqual({k: lc[k] for k in ("authorization", "current_permission", "execution_attempted", "destination_observed",
                                              "independent_verification", "reconstruction_status")},
                         {"authorization": "authorized", "current_permission": "not_evaluated_from_historical_records",
                          "execution_attempted": "no", "destination_observed": "unknown", "independent_verification": "unavailable",
                          "reconstruction_status": RB_STATUS})
        sem = T["replay_semantics"]
        self.assertEqual({k: sem[k] for k in ("policy_reevaluation", "external_effect_execution", "destination_observation",
                                               "independent_effect_verification")},
                         {"policy_reevaluation": False, "external_effect_execution": False, "destination_observation": "not_performed",
                          "independent_effect_verification": False})
        warnings = sorted(i.code for i in report.issues if getattr(i.severity, "value", str(i.severity)) == "warning")
        self.assertEqual(warnings, sorted(warnings))  # recorded only: the warning set is deliberately not frozen
        # harness evidence agrees
        v = self.ev["native"]["pack"]["validation"]
        self.assertTrue(v["valid"])
        self.assertEqual(v["errors"], [])

    def test_p1_six_zero_counts_from_retained_pack_dump(self):
        pd, T = dump_parts(self.s["pack_dump"])  # the harness-retained native dump, read from disk
        self.assertEqual(pd["pack_version"], "0.2.0")
        self.assertEqual(pd["review_status"], "draft")
        counts = T["derived_counts"]
        for k in ZERO_COUNTS:
            self.assertIn(k, counts)
            self.assertIs(type(counts[k]), int, k)  # int, not bool
            self.assertEqual(counts[k], 0, k)
        self.assertEqual(counts["authorization_granted_count"], 1)
        self.assertEqual(counts["authorization_held_count"], 0)
        lc = T["lifecycle_summary"]
        self.assertEqual((lc["authorization"], lc["current_permission"], lc["execution_attempted"], lc["destination_observed"],
                          lc["independent_verification"]),
                         ("authorized", "not_evaluated_from_historical_records", "no", "unknown", "unavailable"))
        self.assertEqual(T["transformation_version"], TRANSFORMATION)
        self.assertEqual(T["replay_semantic_validation"]["status"], "validated_partial")

    def test_p1_retained_decision_identity_tuple(self):
        pd, T = dump_parts(self.s["pack_dump"])
        retained = T["retained_sources"]
        self.assertEqual(retained["manifest"], self.obs.manifest)
        rb = retained["reconstruction_bundle"]
        self.assertEqual(rb, self.s["bundle"])  # Pack retained exactly the parsed persisted bundle
        dec = rb["records"][decision_index(rb)]["data"]
        persisted = self.s["record"]["decisions"][0]
        self.assertEqual(dec["decision_id"], persisted["decision_id"])  # per-run value taken from the persisted record
        self.assertEqual(dec["result"], "authorized")
        self.assertEqual(dec["effect_id"], EFFECT_AUTH)
        b = dec["binding"]
        self.assertEqual((b["action_id"], b["proposal_commitment"], b["manifest_digest"], b["tenant_id"], b["generation"]),
                         (ACTION_ID, PROPOSAL_COMMITMENT, MANIFEST_DIGEST, TENANT, GENERATION))
        prop = [r for r in rb["records"] if r["record_type"] == "runtime_proposal"][0]["data"]
        self.assertEqual((prop["action_id"], prop["tenant_id"], prop["manifest_digest"]), (ACTION_ID, TENANT, MANIFEST_DIGEST))
        # harness identity block agrees with the independent tuple
        st = self.ev["identity"]["stable"]
        self.assertEqual((st["action_id"], st["proposal_commitment"], st["manifest_digest"], st["tenant_id"]),
                         (ACTION_ID, PROPOSAL_COMMITMENT, MANIFEST_DIGEST, TENANT))
        self.assertEqual(self.ev["identity"]["effect_id"], EFFECT_AUTH)

    def test_p1_h1_h2_distinct_and_recomputed(self):
        h1 = sha256(self.s["bundle_bytes"])  # H1: exact persisted bytes, read from disk by this test
        h2 = PK.importer.sha256(self.s["bundle"])  # H2: the Pack's own canonicalisation helper on the parsed bundle
        self.assertNotEqual("sha256:" + h1, h2)
        pk = self.ev["identity"]["per_run"]
        self.assertEqual(pk["bundle_h1_sha256"], h1)
        self.assertEqual(pk["bundle_h2_pack_canonical_sha256"], h2)
        self.assertEqual(pk["pack_file_sha256"], sha256(self.s["pack_bytes"]))
        pack, _ = pack_import(self.obs.manifest, self.s["bundle"])
        _, T = pack_parts(pack)
        self.assertEqual(T["input_artifacts"][1]["hash"], h2)
        self.assertNotEqual(T["input_artifacts"][1]["hash"], "sha256:" + h1)
        # the raw CP record hash is not carried by the Pack (L19)
        self.assertNotIn(sha256(self.s["record_bytes"]), self.s["pack_bytes"].decode("utf-8"))

    def test_p1_same_bundle_bytes_same_pack_id(self):
        a, ea = pack_import(self.obs.manifest, self.s["bundle"])
        b, eb = pack_import(self.obs.manifest, strict_loads(self.s["bundle_bytes"]))
        self.assertIsNone(ea)
        self.assertIsNone(eb)
        self.assertEqual(a.pack_id, b.pack_id)
        self.assertEqual(self.ev["identity"]["per_run"]["pack_id"], a.pack_id)  # per-run value compared, never hard-coded
        self.assertEqual(self.s["pack_dump"]["pack_id"], a.pack_id)

    def test_p1_boundary_verdict_vector(self):
        self.assertEqual([b["boundary"] for b in self.ev["boundaries"]], ["action_manifest", "control_plane", "replay_bundle", "evidence_pack"])
        for b in self.ev["boundaries"]:
            self.assertEqual(b["orchestration_class"], "ACCEPTED", b["boundary"])
            self.assertIs(b["retains_upstream_refusal"], False, b["boundary"])
            self.assertIsNone(b["native_exception"], b["boundary"])
        v = boundaries(self.ev)
        self.assertEqual(v["control_plane"]["native_result"]["result"], "authorized")
        self.assertEqual(v["control_plane"]["native_result"]["reasons"], [])
        for name in ("control_plane", "replay_bundle", "evidence_pack"):
            self.assertEqual(v[name]["carried_authorization_state"], "authorized", name)  # historical, per L2
        self.assertEqual(self.ev["chain_verdict"]["class"], "ACCEPTED")
        self.assertEqual(v["control_plane"]["input_sha256"] is not None, True)

    def test_p1_no_per_run_value_hard_coded_in_this_file(self):
        text = pathlib.Path(__file__).read_text(encoding="utf-8")
        for per_run in (self.ev["identity"]["per_run"]["decision_id"], self.ev["identity"]["per_run"]["pack_id"],
                        self.ev["identity"]["per_run"]["bundle_id"], sha256(self.s["record_bytes"])):
            self.assertEqual(text.count(str(per_run)), 0)


class N1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obs = Observed()
        cls.ev = cls.obs.results[CASE_N1]
        cls.s = cls.obs.s["n1"]

    @classmethod
    def tearDownClass(cls):
        cls.obs.cleanup()

    def test_n1_status_and_scenario(self):
        self.assertEqual(self.ev["case_id"], CASE_N1)
        self.assertEqual(self.ev["status"], "PASS")
        self.assertEqual(self.ev["scenario"], "grant_revoked")
        for check in self.ev["oracle"]["checks"]:
            self.assertTrue(check["ok"], check["name"])
        self.assertTrue(self.ev["oracle"]["all_ok"])

    def test_n1_control_plane_record_from_disk(self):
        rec = self.s["record"]
        d = rec["decisions"][0]
        self.assertEqual((d["result"], d["reasons"]), ("hold", ["grant_revoked"]))
        self.assertIsNone(d["binding"])
        self.assertEqual(d["effect_id"], EFFECT_HOLD)
        self.assertEqual(d["operation_horizon"]["proposal_commitment"], PROPOSAL_COMMITMENT)
        self.assertEqual((d["time_source"], d["decided_at"]), ("test_override", DECIDED_AT))
        self.assertEqual(len(rec["check_events"]), 13)
        for key in ("attempts", "observations", "reconciliations", "closeouts"):
            self.assertEqual(rec.get(key, []), [], key)
        self.assertEqual(self.obs.dest_effects("n1"), {})
        self.assertEqual(self.ev["destination"]["effects"], {})
        prov = self.ev["producer"] if "producer" in self.ev else self.ev["producer_provenance"]
        self.assertEqual(prov["calls"], ["decide"])
        self.assertEqual(prov["scenario_mutation"], "grant_status=revoked")
        self.assertEqual(self.ev["identity"]["effect_id"], EFFECT_HOLD)

    def test_n1_replay_own_import_findings_b004_b005(self):
        own = self.obs.own_replay("n1")
        self.assertEqual(own.status, RB_STATUS)
        codes = {f.code for r in own.import_reports for f in r.findings}
        self.assertEqual(codes, N1_FINDING_CODES)
        self.assertNotIn("B002", codes)
        self.assertNotIn("B006", codes)
        dec = [r for r in own.records if r.record_type == "runtime_decision"][0]
        self.assertEqual(dec.data["result"], "hold")
        b = self.s["bundle"]
        self.assertEqual({f["code"] for r in b["import_reports"] for f in r["findings"]}, N1_FINDING_CODES)
        self.assertEqual(b["records"][decision_index(b)]["data"]["result"], "hold")
        rp = self.ev["native"]["replay"]
        self.assertEqual(rp["status"], RB_STATUS)
        self.assertEqual({f[0] if isinstance(f, (list, tuple)) else f["code"] for f in rp["findings"]}, N1_FINDING_CODES)

    def test_n1_pack_own_import_and_held_semantics(self):
        pack, exc = pack_import(self.obs.manifest, self.s["bundle"])
        self.assertIsNone(exc)
        report = PK.validator.validate_evidence_pack(pack)
        self.assertTrue(report.valid)
        self.assertEqual(errors_of(report), [])
        _, T = pack_parts(pack)
        lc = T["lifecycle_summary"]
        self.assertEqual((lc["authorization"], lc["execution_attempted"], lc["destination_observed"], lc["independent_verification"]),
                         ("held", "no", "unknown", "unavailable"))
        self.assertEqual(T["derived_counts"]["authorization_held_count"], 1)
        self.assertEqual(T["derived_counts"]["authorization_granted_count"], 0)
        v = self.ev["native"]["pack"]["validation"]
        self.assertTrue(v["valid"])
        self.assertEqual(v["errors"], [])

    def test_n1_retained_pack_dump_hold_and_zero_counts(self):
        pd, T = dump_parts(self.s["pack_dump"])
        counts = T["derived_counts"]
        for k in ZERO_COUNTS:
            self.assertIs(type(counts[k]), int, k)
            self.assertEqual(counts[k], 0, k)
        self.assertEqual((counts["authorization_held_count"], counts["authorization_granted_count"]), (1, 0))
        lc = T["lifecycle_summary"]
        self.assertEqual((lc["authorization"], lc["execution_attempted"], lc["destination_observed"], lc["independent_verification"]),
                         ("held", "no", "unknown", "unavailable"))
        rb = T["retained_sources"]["reconstruction_bundle"]
        self.assertEqual(rb["records"][decision_index(rb)]["data"]["result"], "hold")
        self.assertEqual(rb, self.s["bundle"])
        dumped = self.s["pack_bytes"].decode("utf-8")
        self.assertNotIn('"authorization": "authorized"', dumped)
        self.assertNotIn('"result": "authorized"', dumped)

    def test_n1_boundary_vector_chain_and_no_overwrite(self):
        v = boundaries(self.ev)
        self.assertEqual(v["action_manifest"]["orchestration_class"], "ACCEPTED")
        self.assertEqual(v["control_plane"]["orchestration_class"], "REFUSED_NATIVE")
        self.assertEqual(v["control_plane"]["native_result"]["result"], "hold")
        self.assertEqual(v["control_plane"]["native_result"]["reasons"], ["grant_revoked"])
        self.assertEqual(v["control_plane"]["carried_authorization_state"], "held")
        for name in ("replay_bundle", "evidence_pack"):
            self.assertEqual(v[name]["orchestration_class"], "ACCEPTED", name)
            self.assertIs(v[name]["retains_upstream_refusal"], True, name)
            self.assertEqual(v[name]["carried_authorization_state"], "held", name)
            self.assertNotEqual(v[name]["carried_authorization_state"], "authorized")
        self.assertEqual(self.ev["chain_verdict"]["class"], "REFUSED_NATIVE")
        self.assertEqual(self.ev["chain_verdict"]["boundary"], "control_plane")
        # a downstream ACCEPTED never overwrites the CP refusal
        self.assertEqual(self.ev["boundaries"][1]["orchestration_class"], "REFUSED_NATIVE")
        self.assertNotEqual(self.ev["chain_verdict"]["class"], "ACCEPTED")

    def test_n1_l22_supplied_proposal_tenant_not_bound_for_hold(self):
        """OBSERVED limitation L22, not an oracle: for a hold Replay does not bind the supplied proposal to the record."""
        other = copy.deepcopy(self.obs.proposal)
        self.assertEqual(other["tenant_id"], TENANT)
        other["tenant_id"] = "tenant-beta"
        own = self.obs.own_replay("n1", proposal=other)
        self.assertEqual(own.status, RB_STATUS)  # still imports
        self.assertIn("L22", self.ev["limits"])


class N2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obs = Observed()
        cls.ev = cls.obs.results[CASE_N2]
        cls.s = cls.obs.s["n1"]
        cls.n1_bytes_before = cls.s["bundle_path"].read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.obs.cleanup()

    def flipped(self):
        mutated = copy.deepcopy(self.s["bundle"])
        mutated["records"][decision_index(mutated)]["data"]["result"] = "authorized"
        return mutated

    def expected_message(self):
        return "decision %s is authorized but has no binding" % self.s["record"]["decisions"][0]["decision_id"]

    def test_control_unmutated_n1_bundle_imports(self):
        pack, exc = pack_import(self.obs.manifest, self.s["bundle"])
        self.assertIsNone(exc)
        self.assertTrue(PK.validator.validate_evidence_pack(pack).valid)

    def test_n2_single_field_flip_is_refused_by_pack(self):
        i = decision_index(self.s["bundle"])
        self.assertEqual(self.s["bundle"]["records"][i]["data"]["result"], "hold")
        mutated = self.flipped()
        self.assertEqual(diff_paths(self.s["bundle"], mutated), ["records[%d].data.result" % i])  # exactly one path
        pack, exc = pack_import(self.obs.manifest, mutated)
        self.assertIsNone(pack)
        self.assertIs(type(exc), PK.importer.ImportContractError)
        self.assertEqual(str(exc), self.expected_message())
        self.assertIsNone(getattr(exc, "code", None))
        # original bytes untouched, no effect
        self.assertEqual(self.s["bundle_path"].read_bytes(), self.n1_bytes_before)
        self.assertEqual(self.s["bundle"]["records"][i]["data"]["result"], "hold")
        self.assertEqual(self.obs.dest_effects("n1"), {})

    def test_n2_harness_evidence_agrees(self):
        ev = self.ev
        self.assertEqual(ev["case_id"], CASE_N2)
        self.assertEqual(ev["status"], "PASS")
        self.assertEqual(ev["scenario"], "flip_of_n1")
        pack = boundaries(ev)["evidence_pack"]
        self.assertEqual(pack["orchestration_class"], "REFUSED_NATIVE")
        exc = pack["native_exception"]
        self.assertEqual(exc["type"], "ImportContractError")
        self.assertEqual(exc["message"], self.expected_message())
        self.assertIsNone(exc["code"])
        for name in ("action_manifest", "control_plane", "replay_bundle"):
            self.assertEqual(boundaries(ev)[name]["orchestration_class"], "NOT_EXECUTED", name)
        self.assertEqual(ev["destination"]["effects_after"], {})
        self.assertTrue(ev["destination"]["no_effect"])
        self.assertTrue(ev["mutation"]["original_unmodified_after_run"])
        for check in ev["oracle"]["checks"]:
            self.assertTrue(check["ok"], check["name"])
        # the mutated copy the harness retained differs from the N1 bundle only at the flipped field
        mutated_path = self.obs.work / "n2" / "mutated-bundle.json"
        i = decision_index(self.s["bundle"])
        self.assertEqual(diff_paths(self.s["bundle"], strict_loads(mutated_path.read_bytes())), ["records[%d].data.result" % i])
        self.assertFalse((self.obs.work / "n2" / "evidence-pack.json").exists())  # no Pack is produced for N2

    def test_n2_replay_does_not_refuse_the_flip_documented_limitation(self):
        """Documented limitation (contract section 9): the Pack, not Replay, catches the flip. Observed through this file's own RB load."""
        from agent_replay_bundle import reconstruction as rb_reconstruction
        model, unretained = rb_reconstruction.load_reconstruction_bundle_checked(self.flipped())  # loads, no refusal
        self.assertEqual(model.status, RB_STATUS)
        self.assertEqual(unretained, [])
        flipped_decision = [r for r in model.records if r.record_type == "runtime_decision"][0]
        self.assertEqual(flipped_decision.data["result"], "authorized")  # Replay carries the flipped label without objection


class FidelityTests(unittest.TestCase):
    """Drives the harness with a patched Pack import call or a substitute input file (the harness's public seams)."""

    @classmethod
    def setUpClass(cls):
        cls.obs = Observed()
        cls.pack_importer = sys.modules["agent_governance_evidence_pack.importer"]
        cls.real_import = staticmethod(cls.pack_importer.import_manifest_reconstruction)
        cls.exc_type = cls.pack_importer.ImportContractError
        cls.expected = "decision %s is authorized but has no binding" % cls.obs.s["n1"]["record"]["decisions"][0]["decision_id"]

    @classmethod
    def tearDownClass(cls):
        cls.obs.cleanup()

    def run_patched(self, flipped_behaviour):
        """Re-run the whole harness; the genuine Pack import is used except for the flipped (authorized, no binding) bundle."""
        real = self.real_import

        def fake(manifest, bundle, **kw):
            decs = [r for r in bundle["records"] if r.get("record_type") == "runtime_decision"]
            if decs and decs[0]["data"].get("result") == "authorized" and decs[0]["data"].get("binding") is None:
                return flipped_behaviour(real, manifest, bundle)
            return real(manifest, bundle, **kw)
        work = pathlib.Path(tempfile.mkdtemp(prefix="c4t-fid-"))
        self.addCleanup(shutil.rmtree, work, True)
        with mock.patch.object(self.pack_importer, "import_manifest_reconstruction", side_effect=fake):
            return real_c4.run_all(None, work)

    def test_native_exception_preserved_verbatim_and_classified_refused_native(self):
        seen = []

        def boom(real, manifest, bundle):
            seen.append("decision %s is authorized but has no binding" % bundle["records"][decision_index(bundle)]["data"]["decision_id"])
            raise self.exc_type(seen[-1])
        res = self.run_patched(boom)[CASE_N2]
        self.expected = seen[0]  # this run's own N1 decision id, taken from the bundle the Pack was handed
        self.assertEqual(res["status"], "PASS")
        pack = boundaries(res)["evidence_pack"]
        self.assertEqual(pack["orchestration_class"], "REFUSED_NATIVE")
        self.assertEqual(pack["native_exception"], {"type": "ImportContractError", "message": self.expected, "code": None})
        self.assertEqual(res["chain_verdict"], {"class": "REFUSED_NATIVE", "boundary": "evidence_pack"})

    def test_non_native_exception_is_adapter_error_not_a_refusal(self):
        def crash(real, manifest, bundle):
            raise RuntimeError("not a contract refusal")
        with self.assertRaises(real_c4.AdapterError) as caught:
            self.run_patched(crash)
        self.assertIn("RuntimeError", str(caught.exception))
        self.assertFalse(issubclass(real_c4.AdapterError, self.exc_type))
        self.assertFalse(issubclass(self.exc_type, real_c4.AdapterError))

    def test_wrong_native_message_is_fail_not_pass(self):
        def wrong(real, manifest, bundle):
            raise self.exc_type("pinned Replay semantic validation failed unexpectedly: not the frozen message")
        res = self.run_patched(wrong)[CASE_N2]
        self.assertEqual(res["status"], "FAIL")
        self.assertEqual(boundaries(res)["evidence_pack"]["native_exception"]["message"],
                         "pinned Replay semantic validation failed unexpectedly: not the frozen message")
        self.assertFalse(res["oracle"]["all_ok"])
        self.assertIn("message", [c["name"] for c in res["oracle"]["checks"] if not c["ok"]])

    def test_wrong_native_message_with_code_is_fail(self):
        def coded(real, manifest, bundle):
            exc = self.exc_type("decision %s is authorized but has no binding" % bundle["records"][decision_index(bundle)]["data"]["decision_id"])
            exc.code = "synthetic_code"
            raise exc
        res = self.run_patched(coded)[CASE_N2]
        self.assertEqual(res["status"], "FAIL")
        self.assertEqual(boundaries(res)["evidence_pack"]["native_exception"]["code"], "synthetic_code")

    def test_unexpected_import_success_of_flipped_bundle_is_fail(self):
        def lenient(real, manifest, bundle):
            clean = copy.deepcopy(bundle)
            clean["records"][decision_index(clean)]["data"]["result"] = "hold"  # a lenient importer ignoring the flip
            return real(manifest, clean)
        res = self.run_patched(lenient)[CASE_N2]
        self.assertEqual(res["status"], "FAIL")
        self.assertEqual(boundaries(res)["evidence_pack"]["native_outcome"], "IMPORTED")
        self.assertNotEqual(boundaries(res)["evidence_pack"]["orchestration_class"], "REFUSED_NATIVE")
        self.assertFalse(res["oracle"]["all_ok"])

    def test_unexpected_pack_refusal_of_p1_is_not_pass(self):
        refusal = self.exc_type("synthetic refusal of an unmodified bundle")
        work = pathlib.Path(tempfile.mkdtemp(prefix="c4t-fid-"))
        self.addCleanup(shutil.rmtree, work, True)
        with mock.patch.object(self.pack_importer, "import_manifest_reconstruction", side_effect=refusal):
            res = real_c4.run_all(None, work)
        self.assertNotEqual(res[CASE_P1]["status"], "PASS")
        self.assertEqual(boundaries(res[CASE_P1])["evidence_pack"]["orchestration_class"], "REFUSED_NATIVE")
        self.assertNotEqual(res[CASE_P1]["chain_verdict"]["class"], "ACCEPTED")
        self.assertNotEqual(res[CASE_N2]["status"], "PASS")  # N2 needs a valid N1 bundle and an accepted control import

    def test_gate_failure_blocks_at_action_manifest_and_nothing_else_executes(self):
        altered = pathlib.Path(tempfile.mkdtemp(prefix="c4t-gate-"))
        self.addCleanup(shutil.rmtree, altered, True)
        copy_path = altered / "manifest.json"
        copy_path.write_bytes(manifest_bytes() + b"\n")  # still valid JSON, but not the frozen bytes
        self.assertNotEqual(sha256(copy_path.read_bytes()), MANIFEST_FILE_SHA)
        work = pathlib.Path(tempfile.mkdtemp(prefix="c4t-gate-run-"))
        self.addCleanup(shutil.rmtree, work, True)
        with mock.patch.object(real_c4.c4_producer, "produce", side_effect=AssertionError("CP must not be reached")) as spy:
            res = real_c4.run_all(None, work, manifest_path=copy_path)
        self.assertEqual(spy.call_count, 0)
        for case in (CASE_P1, CASE_N1):
            v = boundaries(res[case])
            self.assertEqual(v["action_manifest"]["orchestration_class"], "BLOCKED", case)
            for name in ("control_plane", "replay_bundle", "evidence_pack"):
                self.assertEqual(v[name]["orchestration_class"], "NOT_EXECUTED", (case, name))
            self.assertEqual(res[case]["chain_verdict"], {"class": "BLOCKED", "boundary": "action_manifest"})
            self.assertNotEqual(res[case]["status"], "PASS")
        self.assertNotEqual(res[CASE_N2]["status"], "PASS")
        self.assertFalse((work / "p1" / "cp-record.json").exists())
        self.assertFalse((work / "n1" / "reconstruction-bundle.json").exists())

    def test_missing_evidence_fails_closed(self):
        work = pathlib.Path(tempfile.mkdtemp(prefix="c4t-miss-"))
        self.addCleanup(shutil.rmtree, work, True)
        with self.assertRaises(real_c4.AdapterError):
            real_c4.run_all(None, work, manifest_path=work / "does-not-exist.json")
        work2 = pathlib.Path(tempfile.mkdtemp(prefix="c4t-miss-"))
        self.addCleanup(shutil.rmtree, work2, True)
        with self.assertRaises(real_c4.AdapterError):
            real_c4.run_all(None, work2, proposal_path=work2 / "does-not-exist.json")
        empty = {k: None for k in ENV_KEYS}
        with self.assertRaises(real_c4.AdapterError):
            real_c4.run_all(empty, pathlib.Path(tempfile.mkdtemp(prefix="c4t-miss-")))
        nonempty = pathlib.Path(tempfile.mkdtemp(prefix="c4t-miss-"))
        self.addCleanup(shutil.rmtree, nonempty, True)
        (nonempty / "stale").write_text("x")
        with self.assertRaises(real_c4.AdapterError):  # an old record store would resume state
            real_c4.run_all(None, nonempty)

    def test_unknown_scenario_and_case_are_refused(self):
        with self.assertRaises(real_c4.c4_producer.ProducerError):
            real_c4.c4_producer.produce(str(ROOTS["cp"]), pathlib.Path(tempfile.mkdtemp(prefix="c4t-scn-")), self.obs.proposal,
                                        self.obs.manifest, "not_a_scenario")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(real_c4.main(["--case", "c4_unknown_case", "--workdir", str(self.obs.work / "never")]), 2)
        self.assertFalse((self.obs.work / "never").exists())

    def test_no_claim_promotion_and_limits_block(self):
        strings = []

        def walk(v, path):
            if isinstance(v, dict):
                for k, x in v.items():
                    walk(x, path + "." + str(k))
            elif isinstance(v, (list, tuple)):
                for i, x in enumerate(v):
                    walk(x, "%s[%d]" % (path, i))
            elif isinstance(v, str):
                strings.append((path, v))
        negation = re.compile(r"\b(no|not|never|neither|nor|without|unverified|unqualified|unauthenticated|HOLD|none|cannot|is not|isn't)\b", re.I)
        for case, ev in self.obs.results.items():
            strings.clear()
            walk({k: v for k, v in ev.items() if k not in ("limits", "known_not_executed")}, case)  # both are negative lists by construction
            for path, text in strings:
                if CLAIM_WORDS.search(text):
                    self.assertIsNotNone(negation.search(text), "claim-promotion string outside a negation at %s: %r" % (path, text))
            limits = ev["limits"]
            for key in LIMIT_KEYS:
                self.assertIn(key, limits, case)
            for key in LIMIT_KEYS[:19]:  # L1..L19 carried verbatim from the frozen C3 harness block
                self.assertEqual(limits[key], real_c3_limits()[key], key)
            for key in LIMIT_KEYS:
                text = limits[key]
                if CLAIM_WORDS.search(text):
                    self.assertIsNotNone(negation.search(text), "%s %s: %r" % (case, key, text))
            self.assertIs(limits["effect_executed"], False)
            self.assertIs(limits["non_authorizing"], True)
            self.assertEqual(limits["no_certification_clearance_or_production_readiness"], "HOLD")
            self.assertIn("N3", " ".join(str(x) for x in ev["known_not_executed"]))
