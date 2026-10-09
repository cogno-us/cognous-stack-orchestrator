import copy
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("admission", ROOT / "development/acceptance/o4e/evidence_admission.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
REF = {"url": "https://example.org/evidence/file", "sha256": "a" * 64}
FIELDS = ("rpc_authentication", "independent_checkpoint", "receipt_log_provenance", "deployed_bytecode", "attestation_trust_snapshot", "trusted_clock", "upstream_verifier", "key_lifecycle")

def complete():
    return {
        "schema": "cognous-o4e-evidence/1", "environment_id": "nonproduction-1",
        "operator_identity": "operator-example", "deployment_revision": "sha-example",
        "observed_at_utc": "2026-10-09T00:00:00Z",
        "references": {k: copy.deepcopy(REF) for k in FIELDS},
        "negative_tests": {k: copy.deepcopy(REF) for k in mod.REQUIRED_NEGATIVES},
    }

class TestEvidenceAdmission(unittest.TestCase):
    def test_complete_still_unverified_and_held(self):
        result = mod.assess(complete())
        self.assertEqual(result["evidence"], "submitted_unverified")
        self.assertEqual(result["status"], "hold")
        self.assertEqual(result["authority"], "not_established")
        self.assertEqual(result["effect"], "disabled")
    def test_missing_each_reference(self):
        for k in FIELDS:
            p = complete()
            del p["references"][k]
            self.assertIn("references." + k, mod.assess(p)["missing"])
    def test_missing_each_negative(self):
        for k in mod.REQUIRED_NEGATIVES:
            p = complete()
            del p["negative_tests"][k]
            self.assertIn("negative_tests." + k, mod.assess(p)["missing"])
    def test_reject_url_credentials_and_query_secrets(self):
        for url in ("http://example.org/x", "https://user:secret@example.org/x", "https://example.org/x?token=abc", "file:///tmp/a"):
            p = complete()
            p["references"]["trusted_clock"]["url"] = url
            self.assertIn("references.trusted_clock", mod.assess(p)["missing"])
    def test_reject_missing_digest(self):
        p = complete()
        p["references"]["deployed_bytecode"]["sha256"] = ""
        self.assertIn("references.deployed_bytecode", mod.assess(p)["missing"])
    def test_invalid_packet(self):
        self.assertEqual(mod.assess(None)["missing"], ["packet"])

if __name__ == "__main__":
    unittest.main()
