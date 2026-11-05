"""Focused tests for the VSLICE-C3 harness (real_c3): Replay Bundle output -> Governance Evidence Pack native import (P1, N1-TEN, N3, N5-REV).

DRAFT. Expectations come ONLY from the frozen literals re-stated below (Hub #273 contract comment 6671327666, sections 8 and 11, frozen
for development by 6671384213) and from this file's OWN independent observations: the persisted bundle read from disk, the destination
file read from disk, and this file's own calls to the native Replay and Pack APIs. Harness evidence is only compared AGAINST them, never
read back as an expectation. stdlib unittest only; run under `python -I -B` through .github/scripts/run_unittest_no_skips.py. The four
component roots are REQUIRED from the environment (the run fails, it never skips). Pinned checkouts are never written to.

A green run means the Pack's native importer and validator matched these literals on a synthetic fixture. It is not qualification,
approval, completeness, authenticity, custody, freshness or proof of any external effect. Cases named "control" are NOT frozen oracle
cases; they only make the attribution of a refusal to its single mutation explicit.
"""
import sys

sys.dont_write_bytecode = True  # never write .pyc into the pinned checkouts: their cleanliness is part of the source gate

import contextlib  # noqa: E402
import copy  # noqa: E402
import hashlib  # noqa: E402
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
import real_c3  # noqa: E402  (must not import any component at module import time)

ENV = {"cp": "COGNOUS_C3_CONTROL_PLANE_ROOT", "rb": "COGNOUS_C3_REPLAY_BUNDLE_ROOT", "pack": "COGNOUS_C3_EVIDENCE_PACK_ROOT",
       "manifest": "COGNOUS_C3_ACTION_MANIFEST_ROOT"}
CASE_P1, CASE_N1, CASE_N3, CASE_N5 = "c3_p1_replay_to_pack_partial", "c3_n1_ten_tenant_tamper", "c3_n3_partial_as_complete", "c3_n5_rev_wrong_revision"

# ---- frozen oracle literals, restated independently of real_c3.ORACLE (contract sections 8 and 11) ----
CP_SHA = "484fdbd297235dd24148ddb0703f2055a31eabff"
RB_SHA = "93a76e281fcae6a65d2cd1d35376f87442dafb95"
MANIFEST_SHA = "fa170815ef96a54c233d0dd9da821b60debabf8b"
PROPOSAL_FILE_SHA = "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2"
MANIFEST_FILE_SHA = "789ad39596b9e1ef84a726a671883e1cb6b83343da3a31db0a1120906d68c074"
MANIFEST_REL = "examples/refund_integration_v1_1.manifest.json"
EFFECT_ID = "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8"
PROPOSAL_COMMITMENT = "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53"
MANIFEST_DIGEST = "sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac"
TENANT, GENERATION = "tenant-alpha", "bounded-authorization-effect/0.3-strict-tenant"
RB_STATUS, FINDINGS = "reconstruction_partial", [["B004", "warning"]]
TRANSFORMATION = "agep-manifest-reconstruction-import/0.3.10-strict-tenant-candidate"
VALIDATOR = "agent_replay_bundle.importers.import_bounded_workflow"
N1_MESSAGE = "pinned Replay semantic validation failed: decisions[0].binding.tenant_id conflicts with committed operation"
N3_MESSAGE = "pinned Replay semantic validation failed unexpectedly: retained Replay status differs from accepted reconstruction"
N5_WRONG_REVISION = "f63ce914504dd06813c4ccd199b0570dbd8dd427"
N5_MESSAGE = "producer_profiles[0].revision for cogno-us/cognous-agent-control-plane conflicts with pinned supported revision"
N2_MESSAGE = "reconstruction bundle must include producer_profiles"
N2P_MESSAGE = "a producer profile names a v2 Control Plane revision but metadata.control_plane_revision is missing"

ROOTS = {}
RB = PK = None  # this file's own imports: agent_replay_bundle.importers, and the Pack importer/validator modules


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
    global RB, PK
    missing = [n for n in ENV.values() if not os.environ.get(n)]
    if missing:
        raise AssertionError("required environment variable(s) not set: %s (point them at the pinned checkouts)" % ", ".join(missing))
    for key, name in ENV.items():
        ROOTS[key] = pathlib.Path(os.environ[name]).resolve()
        if not ROOTS[key].is_dir():
            raise AssertionError("%s is not a directory: %s" % (name, ROOTS[key]))
    sys.path[:0] = [str(ROOTS["pack"] / "src"), str(ROOTS["rb"] / "src")]  # the test's own imports (the harness measures separately)
    from agent_replay_bundle import importers
    from agent_governance_evidence_pack import importer, validator
    RB, PK = importers, type("PackModules", (), {"importer": importer, "validator": validator})


def manifest_obj():
    data = (ROOTS["manifest"] / MANIFEST_REL).read_bytes()
    assert sha256(data) == MANIFEST_FILE_SHA, "manifest fixture differs from the frozen literal"
    return strict_loads(data)


def proposal_obj():
    data = (MANUAL_CONTRACT / "c1" / "fixtures" / "proposal.tenant-alpha.json").read_bytes()
    assert sha256(data) == PROPOSAL_FILE_SHA, "proposal fixture differs from the frozen literal"
    return strict_loads(data)


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


class Observed:
    """One harness run_all in a fresh workdir plus this file's own on-disk observations."""

    def __init__(self):
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="c3t-"))
        self.results = real_c3.run_all(None, self.work)
        self.bundle_path = self.work / "reconstruction-bundle.json"
        self.bundle_bytes = self.bundle_path.read_bytes()
        self.bundle = strict_loads(self.bundle_bytes)
        ev = self.results[CASE_P1]
        rec_path, dest_path = pathlib.Path(ev["record"]["path"]), pathlib.Path(ev["destination"]["path"])
        for p in (rec_path, dest_path):
            assert self.work.resolve() in p.resolve().parents, "persisted artefact outside the case workdir: %s" % p
        self.record = strict_loads(rec_path.read_bytes())
        self.dest_path = dest_path
        self.manifest = manifest_obj()

    def dest_effects(self):
        return strict_loads(self.dest_path.read_bytes()).get("effects")

    def cleanup(self):
        shutil.rmtree(self.work, ignore_errors=True)


class P1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obs = Observed()
        cls.ev = cls.obs.results[CASE_P1]

    @classmethod
    def tearDownClass(cls):
        cls.obs.cleanup()

    def test_p1_harness_status_and_destination(self):
        self.assertEqual(self.ev["status"], "PASS")
        self.assertEqual(self.ev["outcome"], "IMPORTED")
        self.assertEqual(self.ev["case_id"], CASE_P1)
        self.assertEqual(self.obs.dest_effects(), {})  # read from disk by this test
        self.assertEqual(self.ev["destination"]["effects"], {})
        for check in self.ev["oracle"]["checks"]:
            self.assertTrue(check["ok"], check["name"])
        self.assertTrue(self.ev["oracle"]["all_ok"])

    def test_p1_replay_status_findings_and_zero_effect_records(self):
        b, rec = self.obs.bundle, self.obs.record
        self.assertEqual(b["status"], RB_STATUS)
        findings = [[f["code"], f["severity"]] for rep in b["import_reports"] for f in rep["findings"]]
        self.assertEqual(findings, FINDINGS)
        for key in ("attempts", "observations", "reconciliations", "closeouts"):
            self.assertEqual(rec.get(key, []), [], key)
        # this file's own call to the native Replay importer on the persisted record reproduces status and findings
        own = RB.import_bounded_workflow(copy.deepcopy(rec), proposal=proposal_obj(), control_plane_revision=CP_SHA)
        self.assertEqual(own.status, RB_STATUS)
        self.assertEqual([[f.code, f.severity] for r in own.import_reports for f in r.findings], FINDINGS)
        # harness evidence agrees
        self.assertEqual(self.ev["native_replay"]["status"], RB_STATUS)
        self.assertEqual(self.ev["native_replay"]["findings"], FINDINGS)
        self.assertEqual(set(self.ev["native_replay"]["counts"].values()), {0})

    def test_p1_pack_import_and_validation_by_own_call(self):
        pack, exc = pack_import(self.obs.manifest, self.obs.bundle)
        self.assertIsNone(exc)
        report = PK.validator.validate_evidence_pack(pack)
        self.assertTrue(report.valid)
        errors = [i for i in report.issues if getattr(i.severity, "value", str(i.severity)) == "error"]
        self.assertEqual(errors, [])
        pd, T = pack_parts(pack)
        self.assertEqual(pd["pack_version"], "0.2.0")
        self.assertEqual(pd["review_status"], "draft")
        self.assertEqual(T["transformation_version"], TRANSFORMATION)
        self.assertEqual(T["selected_revisions"], {"manifest": MANIFEST_SHA, "replay": RB_SHA, "control_plane": CP_SHA})
        self.assertEqual(T["replay_semantic_validation"], {"validator": VALIDATOR, "required_revision": RB_SHA, "status": "validated_partial"})
        rb0 = pd["replay_bundles"][0]
        self.assertEqual((rb0["status"], rb0["signed"], rb0["redacted"], rb0["validation_status"]),
                         ("validated_partial", False, False, "semantically_valid"))
        self.assertEqual(T["reconstruction_completeness"], RB_STATUS)
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
        self.assertEqual(T["input_artifacts"][0]["hash"], MANIFEST_DIGEST)
        zero = ("control_plane_attempt_count", "executor_attempt_count", "attempt_transition_record_count", "destination_effect_count",
                "effect_observation_count", "reconciliation_count")  # contract section 8: effect counts 0, observed on the PACK side
        self.assertEqual({k: T["derived_counts"][k] for k in zero}, {k: 0 for k in zero})
        # warnings are recorded, deliberately NOT asserted as a frozen set (implementation-observed, contract section 8)
        warnings = sorted(i.code for i in report.issues if getattr(i.severity, "value", str(i.severity)) == "warning")
        self.assertEqual(warnings, sorted(warnings))  # recorded for evidence only; the set itself is not asserted
        type(self).observed_warning_codes = warnings
        # harness evidence agrees with this test's own observation
        v = self.ev["native_pack"]["validation"]
        self.assertTrue(v["valid"])
        self.assertEqual(v["errors"], [])
        self.assertEqual(self.ev["native_pack"]["review_status"], "draft")

    def test_p1_retained_sources_and_identity_in_decision(self):
        pack, exc = pack_import(self.obs.manifest, self.obs.bundle)
        self.assertIsNone(exc)
        _, T = pack_parts(pack)
        retained = T["retained_sources"]
        self.assertEqual(retained["reconstruction_bundle"], self.obs.bundle)  # equals the bundle parsed from the persisted bytes
        self.assertEqual(retained["manifest"], self.obs.manifest)
        dec = retained["reconstruction_bundle"]["records"][decision_index(retained["reconstruction_bundle"])]["data"]
        persisted_decision = self.obs.record["decisions"][0]
        self.assertEqual(dec["decision_id"], persisted_decision["decision_id"])  # per-run value taken from the persisted record, not hard-coded
        self.assertEqual(dec["effect_id"], EFFECT_ID)
        self.assertEqual(dec["binding"]["proposal_commitment"], PROPOSAL_COMMITMENT)
        self.assertEqual(dec["binding"]["tenant_id"], TENANT)
        self.assertEqual(dec["binding"]["generation"], GENERATION)

    def test_p1_pack_id_deterministic_for_identical_bundle(self):
        a, ea = pack_import(self.obs.manifest, self.obs.bundle)
        b, eb = pack_import(self.obs.manifest, self.obs.bundle)
        self.assertIsNone(ea)
        self.assertIsNone(eb)
        self.assertEqual(a.pack_id, b.pack_id)
        self.assertEqual(self.ev["native_pack"]["pack_id"], a.pack_id)  # per-run value compared, never hard-coded

    def test_p1_two_bundle_hashes_are_named_and_distinct(self):
        h1 = sha256(self.obs.bundle_bytes)  # H1: exact persisted bytes, read from disk by this test
        h2 = PK.importer.sha256(self.obs.bundle)  # H2: the Pack's own canonicalisation helper on the parsed bundle
        self.assertEqual(self.ev["bundle"]["H1_sha256_persisted_bytes"], h1)
        self.assertEqual(self.ev["bundle"]["H2_pack_canonical_sha256"], h2)
        self.assertNotEqual("sha256:" + h1, h2)
        self.assertTrue(self.ev["bundle"]["h1_and_h2_are_distinct_values"])
        self.assertEqual(self.ev["bundle"]["size_bytes"], len(self.obs.bundle_bytes))
        pack, _ = pack_import(self.obs.manifest, self.obs.bundle)
        _, T = pack_parts(pack)
        self.assertEqual(T["input_artifacts"][1]["hash"], h2)
        self.assertNotEqual(T["input_artifacts"][1]["hash"], "sha256:" + h1)
        self.assertEqual(self.ev["raw_record_to_bundle_linkage"]["bundle_H1"], h1)
        self.assertFalse(self.ev["raw_record_to_bundle_linkage"]["carried_by_pack"])

    def test_p1_no_integrity_entry_attached(self):
        self.assertEqual(self.obs.bundle.get("integrity"), [])
        self.assertFalse(self.ev["bundle"]["integrity_attached"])
        self.assertEqual(self.ev["native_replay"]["integrity"], [])

    def test_p1_no_claim_promotion_in_evidence(self):
        forbidden = re.compile(r"\breconstruction_complete\b|complete reconstruction|authenticated authority|verified execution|executed_effect|"
                               r"certified|\bapproved\b|production[- ]ready|\bfresh\b|custody chain (?:established|verified)", re.I)
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
        walk({k: v for k, v in self.ev.items() if k != "limits"}, "ev")
        for path, text in strings:
            self.assertIsNone(forbidden.search(text), "forbidden positive claim at %s: %r" % (path, text))
        # the limitation texts may mention these words only to negate them
        negation = re.compile(r"\b(no|not|never|neither|nor|without|unverified|unqualified|unauthenticated|HOLD|none|only)\b", re.I)
        loose = re.compile(r"complete|authenticat|verified|custody|fresh|certif|approv|production|clearance", re.I)
        limits = self.ev["limits"]
        for key, value in limits.items():
            if isinstance(value, str) and loose.search(value) and key not in ("status", "synthetic_key_scope"):
                self.assertIsNotNone(negation.search(value), "limit %s mentions a claim word without negation: %r" % (key, value))
        self.assertIs(limits["effect_executed"], False)
        self.assertIs(limits["non_authorizing"], True)
        self.assertEqual(limits["no_certification_clearance_or_production_readiness"], "HOLD")
        self.assertIs(self.ev["pack_valid_is_not_approval"], True)


class NegativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obs = Observed()

    @classmethod
    def tearDownClass(cls):
        cls.obs.cleanup()

    def mutate(self, fn):
        mutated = copy.deepcopy(self.obs.bundle)
        fn(mutated)
        return mutated

    def run_negative(self, case_ev, mutated, expected_paths, expected_message):
        """This file's own single-mutation proof: diff, original manifest, native importer call, exact type and message, no side effects."""
        before_bytes = self.obs.bundle_path.read_bytes()
        original = copy.deepcopy(self.obs.bundle)
        self.assertEqual(sorted(diff_paths(self.obs.bundle, mutated)), sorted(expected_paths))  # exactly the named path(s) differ
        pack, exc = pack_import(self.obs.manifest, mutated)
        self.assertIsNone(pack)
        self.assertIs(type(exc), PK.importer.ImportContractError)
        self.assertEqual(str(exc), expected_message)
        self.assertIsNone(getattr(exc, "code", None))
        self.assertEqual(self.obs.bundle_path.read_bytes(), before_bytes)  # persisted file unchanged
        self.assertEqual(self.obs.bundle, original)
        self.assertEqual(self.obs.dest_effects(), {})
        # harness evidence agrees with the observation
        self.assertEqual(case_ev["status"], "PASS")
        self.assertEqual(case_ev["outcome"], "REFUSED_NATIVE")
        self.assertEqual(case_ev["native_pack"]["type"], "ImportContractError")
        self.assertEqual(case_ev["native_pack"]["message"], expected_message)
        self.assertIsNone(case_ev["native_pack"]["code"])
        self.assertTrue(case_ev["mutation"]["original_unmodified_after_run"])
        self.assertTrue(case_ev["mutation"]["manifest_supplied"])
        self.assertTrue(case_ev["destination"]["no_effect"])
        self.assertEqual(case_ev["destination"]["effects_after"], {})
        self.assertEqual(case_ev["mutation"]["original_bundle_H1_sha256"], sha256(before_bytes))
        for check in case_ev["oracle"]["checks"]:
            self.assertTrue(check["ok"], check["name"])

    def test_control_unmutated_bundle_imports(self):
        pack, exc = pack_import(self.obs.manifest, self.obs.bundle)
        self.assertIsNone(exc)
        self.assertTrue(PK.validator.validate_evidence_pack(pack).valid)
        self.assertEqual(self.obs.results[CASE_P1]["status"], "PASS")

    def test_n1_ten_tenant_tamper(self):
        i = decision_index(self.obs.bundle)
        self.assertEqual(self.obs.bundle["records"][i]["data"]["binding"]["tenant_id"], TENANT)

        def m(b):
            b["records"][i]["data"]["binding"]["tenant_id"] = "tenant-beta"
        mutated = self.mutate(m)
        self.assertEqual(mutated["records"][i]["data"]["binding"]["tenant_id"], "tenant-beta")
        self.run_negative(self.obs.results[CASE_N1], mutated, ["records[%d].data.binding.tenant_id" % i], N1_MESSAGE)

    def test_n3_status_alone(self):
        def m(b):
            b["status"] = "reconstruction_complete"
        self.assertEqual(self.obs.bundle["status"], RB_STATUS)
        ev = self.obs.results[CASE_N3]
        self.assertEqual(ev["mutation"]["variant"], "status_alone")
        self.run_negative(ev, self.mutate(m), ["status"], N3_MESSAGE)

    def test_n3_status_reports_complete_findings_cleared(self):
        def m(b):
            b["status"] = "reconstruction_complete"
            for rep in b["import_reports"]:
                rep["complete"] = True
                rep["findings"] = []
        expected = ["status"]
        for i, rep in enumerate(self.obs.bundle["import_reports"]):
            if rep["complete"] is not True:
                expected.append("import_reports[%d].complete" % i)
            if rep["findings"]:
                expected.append("import_reports[%d].findings" % i)
        self.assertGreater(len(expected), 1)  # the forged variant really changes the reports too
        ev = self.obs.results[CASE_N3]["variant_b"]
        self.assertEqual(ev["mutation"]["variant"], "status_and_reports_forged_complete")
        self.run_negative(ev, self.mutate(m), expected, N3_MESSAGE)
        self.assertEqual(self.obs.results[CASE_N3]["status"], "PASS")  # N3 passes only when BOTH variants pass

    def test_n5_rev_wrong_revision(self):
        self.assertEqual(self.obs.bundle["producer_profiles"][0]["revision"], CP_SHA)

        def m(b):
            b["producer_profiles"][0]["revision"] = N5_WRONG_REVISION
        self.run_negative(self.obs.results[CASE_N5], self.mutate(m), ["producer_profiles[0].revision"], N5_MESSAGE)

    def test_control_deleting_required_evidence_is_refused_natively(self):
        """Optional extras, NOT frozen oracle cases (contract N2/N2' are recommended additions): required evidence cannot be dropped."""
        def drop_profiles(b):
            del b["producer_profiles"]

        def drop_revision(b):
            del b["metadata"]["control_plane_revision"]

        for fn, message in ((drop_profiles, N2_MESSAGE), (drop_revision, N2P_MESSAGE)):
            mutated = self.mutate(fn)
            self.assertNotEqual(mutated, self.obs.bundle)
            pack, exc = pack_import(self.obs.manifest, mutated)
            self.assertIsNone(pack, fn.__name__)
            self.assertIs(type(exc), PK.importer.ImportContractError, fn.__name__)
            self.assertEqual(str(exc), message, fn.__name__)


class HarnessFidelityTests(unittest.TestCase):
    """Drives the harness negative cases with a patched Pack import call, from a separate prepared context."""

    @classmethod
    def setUpClass(cls):
        cls.work = pathlib.Path(tempfile.mkdtemp(prefix="c3t-fid-"))
        cls.ctx = real_c3._prepare(None, cls.work)
        cls.p1 = real_c3._p1_from(cls.ctx)
        cls.mut_n1 = (real_c3._mut_n1, {"field_path": "records[runtime_decision].data.binding.tenant_id", "from": TENANT, "to": "tenant-beta"}, N1_MESSAGE)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def negative(self):
        fn, mutation, message = self.mut_n1
        return real_c3._negative(CASE_N1, self.ctx, self.p1, fn, mutation, message)

    def patch_pack(self, side_effect):
        return mock.patch.object(self.ctx["P"]["pack_importer"], "import_manifest_reconstruction", side_effect=side_effect)

    def test_precondition_p1_sanity(self):
        self.assertEqual(self.p1["status"], "PASS")
        self.assertEqual(self.negative()["status"], "PASS")

    def test_native_error_preserved_verbatim_and_distinct_from_adapter_error(self):
        exc_type = self.ctx["P"]["pack_importer"].ImportContractError
        boom = exc_type(N1_MESSAGE)
        with self.patch_pack(boom):
            ev = self.negative()
        self.assertEqual(ev["native_pack"], {"outcome": "REFUSED_NATIVE", "type": "ImportContractError", "message": N1_MESSAGE, "code": None})
        self.assertEqual((ev["outcome"], ev["status"]), ("REFUSED_NATIVE", "PASS"))
        # a non-native exception is an AdapterError and never evidence of a native refusal
        with self.patch_pack(RuntimeError("not a contract refusal")):
            with self.assertRaises(real_c3.AdapterError):
                self.negative()
        with self.patch_pack(ValueError("not a contract refusal")):
            with self.assertRaises(real_c3.AdapterError):
                real_c3._p1_from(self.ctx)
        self.assertFalse(issubclass(real_c3.AdapterError, exc_type))
        self.assertFalse(issubclass(exc_type, real_c3.AdapterError))

    def test_wrong_native_message_is_fail_not_pass(self):
        wrong = self.ctx["P"]["pack_importer"].ImportContractError(N3_MESSAGE)  # a real message, but not the frozen N1 one
        with self.patch_pack(wrong):
            ev = self.negative()
        self.assertEqual(ev["status"], "FAIL")
        self.assertNotEqual(ev["outcome"], "REFUSED_NATIVE")
        self.assertEqual(ev["native_pack"]["message"], N3_MESSAGE)
        self.assertFalse(ev["oracle"]["all_ok"])
        self.assertIn("message", [c["name"] for c in ev["oracle"]["checks"] if not c["ok"]])

    def test_wrong_native_message_with_code_is_fail(self):
        wrong = self.ctx["P"]["pack_importer"].ImportContractError(N1_MESSAGE)
        wrong.code = "synthetic_code"
        with self.patch_pack(wrong):
            ev = self.negative()
        self.assertEqual(ev["status"], "FAIL")
        self.assertEqual(ev["native_pack"]["code"], "synthetic_code")

    def test_unexpected_import_of_mutated_bundle_is_fail(self):
        real = self.ctx["P"]["pack_importer"].import_manifest_reconstruction
        original = self.ctx["bundle_obj"]
        with self.patch_pack(lambda manifest, bundle: real(manifest, copy.deepcopy(original))):  # a lenient importer ignoring the tamper
            for fn, mutation, message in (self.mut_n1, (real_c3._mut_n3a, {"field_path": "status"}, N3_MESSAGE),
                                          (real_c3._mut_n5, {"field_path": "producer_profiles[0].revision"}, N5_MESSAGE)):
                ev = real_c3._negative(CASE_N1, self.ctx, self.p1, fn, mutation, message)
                self.assertEqual(ev["status"], "FAIL")
                self.assertEqual(ev["outcome"], "FAIL")
                self.assertEqual(ev["native_pack"]["outcome"], "IMPORTED")

    def test_failed_precondition_yields_fail_not_pass(self):
        for bad in (dict(self.p1, status="FAIL"), dict(self.p1, outcome="REFUSED_NATIVE"), dict(self.p1, outcome="REFUSED_NATIVE", status="FAIL")):
            ev = self.negative_with(bad)
            self.assertEqual(ev["status"], "FAIL")
            self.assertEqual(ev["outcome"], "FAIL")
            self.assertNotIn("native_pack", ev)
            self.assertIn("precondition", ev["reason"])

    def negative_with(self, p1):
        fn, mutation, message = self.mut_n1
        with self.patch_pack(AssertionError("the Pack must not be reached when the P1 precondition failed")):
            return real_c3._negative(CASE_N1, self.ctx, p1, fn, mutation, message)

    def test_p1_with_unexpected_pack_refusal_is_fail(self):
        refusal = self.ctx["P"]["pack_importer"].ImportContractError("synthetic refusal of the unmodified bundle")
        with self.patch_pack(refusal):
            ev = real_c3._p1_from(self.ctx)
        self.assertEqual((ev["outcome"], ev["status"]), ("REFUSED_NATIVE", "FAIL"))

    def test_mutation_that_changes_nothing_is_an_adapter_error(self):
        with self.assertRaises(real_c3.AdapterError):
            real_c3._negative(CASE_N1, self.ctx, self.p1, lambda b: None, {"field_path": "none"}, N1_MESSAGE)


class ReviewFixTests(unittest.TestCase):
    """Independent-review findings: the harness's own mutators change exactly the named path, and validator/dump failures are harness
    failures (AdapterError, exit 2), never an oracle FAIL or a native refusal."""

    @classmethod
    def setUpClass(cls):
        cls.work = pathlib.Path(tempfile.mkdtemp(prefix="c3t-rev-"))
        cls.ctx = real_c3._prepare(None, cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def changed(self, mutator):
        original = json.loads(self.ctx["bundle_path"].read_bytes().decode("utf-8"))
        mutated = copy.deepcopy(original)
        mutator(mutated)
        return diff_paths(original, mutated)

    def test_harness_mutators_change_exactly_the_named_paths(self):
        decision_index = [i for i, r in enumerate(json.loads(self.ctx["bundle_path"].read_bytes())["records"]) if r["record_type"] == "runtime_decision"][0]
        self.assertEqual(self.changed(real_c3._mut_n1), ["records[%d].data.binding.tenant_id" % decision_index])
        self.assertEqual(self.changed(real_c3._mut_n3a), ["status"])
        n3b = self.changed(real_c3._mut_n3b)
        self.assertIn("status", n3b)
        self.assertTrue(all(x == "status" or x.startswith("import_reports[") for x in n3b), n3b)
        self.assertEqual(self.changed(real_c3._mut_n5), ["producer_profiles[0].revision"])

    def test_validator_exception_is_an_adapter_error_not_a_native_refusal_or_fail(self):
        with mock.patch.object(self.ctx["P"]["pack_validator"], "validate_evidence_pack", side_effect=RuntimeError("validator crashed")):
            with self.assertRaises(real_c3.AdapterError) as caught:
                real_c3._p1_from(self.ctx)
        self.assertIn("RuntimeError", str(caught.exception))
        self.assertIn("validator crashed", str(caught.exception))

    def test_dump_exception_is_an_adapter_error(self):
        with mock.patch.object(self.ctx["P"]["pack_loader"], "dump_evidence_pack", side_effect=OSError("disk")):
            with self.assertRaises(real_c3.AdapterError):
                real_c3._p1_from(self.ctx)

    def test_main_exit_code_2_for_a_validator_crash(self):
        import io
        import contextlib
        with mock.patch.object(self.ctx["P"]["pack_validator"], "validate_evidence_pack", side_effect=RuntimeError("validator crashed")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(real_c3.main(["--case", CASE_P1, "--workdir", str(self.work / "main-run")]), 2)


if __name__ == "__main__":
    unittest.main()
