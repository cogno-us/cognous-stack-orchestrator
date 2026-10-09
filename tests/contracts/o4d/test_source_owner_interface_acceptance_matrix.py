import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = ROOT / "development" / "acceptance" / "o4d" / "source_owner_interface_acceptance_matrix.json"

EXPECTED = {
    "registry": ("cogno-us/cognous-evidence-registry", "d5e45d275cb301d9684b543e93b05997991d1cf2", "orchestration/adapters/registry/observation.py"),
    "attestation": ("cogno-us/cognous-evidence-attestation", "5b5077dafde232a7801cb425c4efddcffb468723", "orchestration/adapters/attestation/verifier.py"),
    "institutional_governance": ("cogno-us/cognous-institutional-governance", "1386fd236f13896029e5ab47ba5b9c3127509c3d", "development/interfaces/institutional/authority_context_mapping.py"),
    "governed_exchange": ("cogno-us/cognous-governed-exchange", "a1cbc7b28f702283b0e4f3192bb43e4a9e618ebf", "development/interfaces/exchange/reference_handoff.py"),
}

class OwnerContractMatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        cls.domains = {row["name"]: row for row in cls.matrix["domains"]}

    def test_exact_o4c_base_and_four_source_pins(self):
        self.assertEqual(self.matrix["orchestrator_base"], "3df758ec5e0a65af28f6f9f3be5c9263458ab83b")
        self.assertEqual(set(self.domains), set(EXPECTED))
        for name, (repo, revision, consumer) in EXPECTED.items():
            row = self.domains[name]
            self.assertEqual(row["repository"], repo)
            self.assertEqual(row["revision"], revision)
            self.assertEqual(row["consumer_path"], consumer)
            self.assertEqual(len(revision), 40)
            self.assertTrue(row["source_paths"])

    def test_owner_approval_is_never_self_asserted(self):
        self.assertFalse(self.matrix["ratification"]["self_ratified"])
        self.assertEqual(self.matrix["ratification"]["o1_technical_ratification_2"], "open")
        self.assertEqual(self.matrix["ratification"]["governor_gate_14"], "open")
        for row in self.domains.values():
            self.assertTrue(row["owner_approval"].startswith("pending_attributable_"))
            self.assertNotIn(row["owner_approval"], {"approved", "accepted", "ratified"})

    def test_negative_examples_cover_unknown_or_rejected_boundaries(self):
        permitted = {"unknown", "rejected", "unknown_authority_hold_effect", "rejected_hold_effect", "invalid", "receipt_only"}
        for row in self.domains.values():
            self.assertGreaterEqual(len(row["negative_examples"]), 2)
            for example in row["negative_examples"]:
                self.assertIn(example["expected_status"], permitted)
                self.assertTrue(example["forbidden_inferences"])

    def test_no_domain_promotes_reference_or_receipt_to_authority(self):
        forbidden = {"authority", "grant", "permission", "institutional_authorization", "execution", "verification", "independent_verification"}
        seen = set()
        for row in self.domains.values():
            for example in row["negative_examples"]:
                seen.update(example["forbidden_inferences"])
        self.assertTrue(seen & forbidden)
        exchange = self.domains["governed_exchange"]["negative_examples"]
        receipt = next(x for x in exchange if x["case"] == "durable_receipt")
        self.assertEqual(receipt["expected_status"], "receipt_only")
        self.assertIn("institutional_authorization", receipt["forbidden_inferences"])

if __name__ == "__main__":
    unittest.main()
