import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).resolve().parents[2] / "orchestration/provenance_context.py"
spec = importlib.util.spec_from_file_location("provenance_context", PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assess_reference = mod.assess_reference
H = "0x" + "11" * 32
Z = "0x" + "00" * 32


def base():
    return {
        "registry_event": {"event": "EvidenceSubmitted", "args": {
            "id": H, "claim": H, "content": "0x" + __import__("hashlib").sha256(b"sample").hexdigest(),
            "manifest": H, "statement": Z, "relation": 1}},
        "reconstruction": {"blockHash": H, "transactionHash": H, "finality": "provisional"},
        "content_bytes": b"sample", "attestation_statement": None,
        "attestation_result": None, "authority_context": None,
    }


class ReadOnlyBoundary(unittest.TestCase):
    def test_consistent_bytes_never_authorize(self):
        got = assess_reference(**base())
        self.assertEqual(got["content_binding"], "matched")
        self.assertEqual(got["authority"], "not_established")
        self.assertEqual(got["effect"], "not_attempted")

    def test_missing_bytes_unknown_not_false(self):
        x = base(); x["content_bytes"] = None
        self.assertEqual(assess_reference(**x)["content_binding"], "unavailable")

    def test_substituted_bytes(self):
        x = base(); x["content_bytes"] = b"wrong"
        self.assertEqual(assess_reference(**x)["content_binding"], "mismatch")

    def test_challenge_is_not_truth_verdict(self):
        x = base(); x["registry_event"]["args"]["relation"] = 2
        self.assertEqual(assess_reference(**x)["evidence_relation"], "challenge_assertion")

    def test_invalid_relation_fails(self):
        x = base(); x["registry_event"]["args"]["relation"] = 9
        self.assertEqual(assess_reference(**x)["status"], "rejected_input")

    def test_wrong_event_fails(self):
        x = base(); x["registry_event"]["event"] = "Registered"
        self.assertEqual(assess_reference(**x)["status"], "rejected_input")

    def test_absent_log_identity_fails(self):
        x = base(); del x["reconstruction"]["blockHash"]
        self.assertEqual(assess_reference(**x)["status"], "rejected_input")

    def test_false_finality_rejected(self):
        x = base(); x["reconstruction"]["finality"] = "consensus_final"
        self.assertEqual(assess_reference(**x)["status"], "rejected_input")

    def test_depth_is_not_consensus_finality(self):
        x = base(); x["reconstruction"]["finality"] = "depth:6;not-consensus-finality"
        self.assertEqual(assess_reference(**x)["authority"], "not_established")

    def test_unverified_statement_commitment(self):
        x = base(); x["registry_event"]["args"]["statement"] = H
        self.assertEqual(assess_reference(**x)["attestation"], "commitment_only")

    def test_reported_signature_not_authenticated(self):
        x = base(); x["registry_event"]["args"]["statement"] = H
        x["attestation_result"] = {"statement_digest": "sha256:" + "11" * 32,
                                   "outcome": "verified", "assurance": "issuer_signature_only"}
        x["attestation_statement"] = {"statement": {"issuer": "unknown"}}
        got = assess_reference(**x)
        self.assertEqual(got["attestation"], "reported_issuer_signature_only_untrusted")
        self.assertEqual(got["issuer_trust"], "not_established")
        self.assertEqual(got["authority"], "not_established")

    def test_wrong_statement_digest_not_promoted(self):
        x = base(); x["registry_event"]["args"]["statement"] = H
        x["attestation_result"] = {"statement_digest": "sha256:" + "22" * 32,
                                   "outcome": "verified", "assurance": "issuer_signature_only"}
        x["attestation_statement"] = {}
        self.assertEqual(assess_reference(**x)["attestation"], "unmatched_reported_attestation")

    def test_proposed_context_not_grant(self):
        x = base(); x["authority_context"] = {"schema_version": "0.1.0",
                                               "interface_status": "proposed_pending_governor_review"}
        got = assess_reference(**x)
        self.assertEqual(got["institutional_context"], "proposed_requirements_only")
        self.assertEqual(got["authority"], "not_established")

    def test_claimed_active_context_not_trusted(self):
        x = base(); x["authority_context"] = {"schema_version": "0.1.0",
                                               "interface_status": "active"}
        self.assertEqual(assess_reference(**x)["institutional_context"], "unrecognized_context")


if __name__ == "__main__":
    unittest.main()
