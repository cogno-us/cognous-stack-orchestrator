import importlib.util
import pathlib
import unittest

path = pathlib.Path(__file__).resolve().parents[2] / "orchestration/producer_evidence.py"
spec = importlib.util.spec_from_file_location("producer_evidence", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

H = "0x" + "11" * 32
Z = "0x" + "00" * 32


def sample():
    return dict(
        registry_revision=module.REGISTRY_PIN,
        registry_observation=dict(event="EvidenceSubmitted",
          args=dict(id=H, claim=H, content="0x" + __import__("hashlib").sha256(b"item").hexdigest(),
                    manifest=H, statement=Z, relation=1),
          block_hash=H, transaction_hash=H, log_index=0, finality="provisional"),
        content_bytes=b"item")


class TestProducerEvidence(unittest.TestCase):
    def test_valid_shape_remains_untrusted(self):
        x = module.inspect_producer_evidence(**sample())
        self.assertEqual(x["content_binding"], "matched")
        self.assertEqual(x["source_authenticity"], "not_established")
        self.assertEqual(x["authority"], "not_established")

    def test_bad_revision(self):
        x = sample(); x["registry_revision"] = "main"
        self.assertEqual(module.inspect_producer_evidence(**x)["status"], "rejected")

    def test_missing_bytes(self):
        x = sample(); x["content_bytes"] = None
        self.assertEqual(module.inspect_producer_evidence(**x)["content_binding"], "unavailable")

    def test_wrong_bytes(self):
        x = sample(); x["content_bytes"] = b"altered"
        self.assertEqual(module.inspect_producer_evidence(**x)["content_binding"], "mismatch")

    def test_fake_finality(self):
        x = sample(); x["registry_observation"]["finality"] = "consensus_final"
        self.assertEqual(module.inspect_producer_evidence(**x)["status"], "rejected")

    def test_boolean_log_index(self):
        x = sample(); x["registry_observation"]["log_index"] = True
        self.assertEqual(module.inspect_producer_evidence(**x)["status"], "rejected")

    def test_malformed_event(self):
        x = sample(); x["registry_observation"]["args"]["statement"] = "broken"
        self.assertEqual(module.inspect_producer_evidence(**x)["status"], "rejected")

    def test_unknown_relation(self):
        x = sample(); x["registry_observation"]["args"]["relation"] = 4
        self.assertEqual(module.inspect_producer_evidence(**x)["status"], "rejected")

    def test_reported_verified_does_not_authenticate(self):
        x = sample(); x["registry_observation"]["args"]["statement"] = H
        x["attestation_revision"] = module.ATTESTATION_PIN
        x["attestation_verification"] = dict(result_version="bitrep-verification/1",
            statement_digest="sha256:" + "11" * 32,
            outcome="verified", assurance="issuer_signature_only")
        got = module.inspect_producer_evidence(**x)
        self.assertEqual(got["attestation"], "reported_signature_result_untrusted")
        self.assertEqual(got["issuer_trust"], "not_established")
        self.assertEqual(got["authority"], "not_established")

    def test_wrong_statement_digest(self):
        x = sample(); x["registry_observation"]["args"]["statement"] = H
        x["attestation_revision"] = module.ATTESTATION_PIN
        x["attestation_verification"] = dict(statement_digest="sha256:" + "22" * 32)
        self.assertEqual(module.inspect_producer_evidence(**x)["attestation"], "statement_binding_mismatch")

    def test_wrong_verifier_revision(self):
        x = sample(); x["attestation_revision"] = "b"*40
        self.assertEqual(module.inspect_producer_evidence(**x)["attestation"], "unsupported_verifier_revision")


if __name__ == "__main__":
    unittest.main()
