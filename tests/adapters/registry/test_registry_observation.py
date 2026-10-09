import importlib.util
import pathlib
import sys
import unittest

path = pathlib.Path(__file__).resolve().parents[3] / "orchestration/adapters/registry/observation.py"
spec = importlib.util.spec_from_file_location("registry_observation", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

H1 = "0x" + "11" * 32
H2 = "0x" + "22" * 32
H3 = "0x" + "33" * 32
H4 = "0x" + "44" * 32
A1 = "0x" + "aa" * 20
A2 = "0x" + "bb" * 20
CONTENT = b"claim bytes"
COMMITMENT = "0x" + __import__("hashlib").sha256(CONTENT).hexdigest()


def trusted():
    return module.TrustedRegistryDeployment(
        chain_id=31337,
        contract_address=A1,
        source_revision=module.REGISTRY_REVISION,
        runtime_bytecode_hash=H4,
    )


def snapshot():
    return {
        "chainId": 31337,
        "contractAddress": A1,
        "sourceRevision": module.REGISTRY_REVISION,
        "sourcePath": module.REGISTRY_SOURCE_PATH,
        "reconstructionPath": module.RECONSTRUCTOR_SOURCE_PATH,
        "runtimeBytecodeHash": H4,
        "blockNumber": 12,
        "blockHash": H3,
        "finality": "provisional",
        "claims": {
            H1: {"author": A1, "content": COMMITMENT, "parent": "0x" + "00" * 32,
                 "lifecycle": 1, "successor": "0x" + "00" * 32},
        },
        "evidence": {
            H2: {"submitter": A2, "claim": H1, "content": H1, "manifest": H2,
                 "statement": "0x" + "00" * 32, "relation": 1},
        },
        "history": [
            {"event": "Registered", "id": H1, "blockHash": H1, "blockNumber": 10,
             "transactionHash": H2, "logIndex": 0, "transactionIndex": 0},
            {"event": "EvidenceSubmitted", "id": H2, "blockHash": H3, "blockNumber": 12,
             "transactionHash": H4, "logIndex": 0, "transactionIndex": 0},
        ],
    }


class RegistryObservationTests(unittest.TestCase):
    def test_accepts_matching_source_but_keeps_assurance_bounded(self):
        got = module.observe_registry_snapshot(
            trusted=trusted(), snapshot=snapshot(), content_bytes={COMMITMENT.lower(): CONTENT})
        self.assertEqual(got["status"], "accepted_provisional")
        self.assertEqual(got["chain_finality"], "provisional")
        self.assertEqual(got["source_authenticity"], "not_independently_established")
        self.assertEqual(got["authority"], "not_established")
        self.assertEqual(got["content_bindings"][f"claim:{H1}"], "matched")

    def test_wrong_chain_rejected(self):
        x = snapshot(); x["chainId"] = 31338
        self.assertIn("wrong_chain_id", module.observe_registry_snapshot(trusted=trusted(), snapshot=x)["reasons"])

    def test_wrong_address_rejected(self):
        x = snapshot(); x["contractAddress"] = A2
        self.assertIn("wrong_contract_address", module.observe_registry_snapshot(trusted=trusted(), snapshot=x)["reasons"])

    def test_source_revision_mismatch_rejected(self):
        x = snapshot(); x["sourceRevision"] = "0" * 40
        self.assertIn("source_revision_mismatch", module.observe_registry_snapshot(trusted=trusted(), snapshot=x)["reasons"])

    def test_runtime_bytecode_mismatch_rejected(self):
        x = snapshot(); x["runtimeBytecodeHash"] = H1
        self.assertIn("runtime_bytecode_mismatch", module.observe_registry_snapshot(trusted=trusted(), snapshot=x)["reasons"])

    def test_replacement_block_detected(self):
        got = module.observe_registry_snapshot(
            trusted=trusted(), snapshot=snapshot(), previous_checkpoint={"blockNumber": 12, "blockHash": H2})
        self.assertEqual(got["status"], "failed")
        self.assertEqual(got["reorg_status"], "replacement_detected")
        self.assertIn("replacement_block_detected", got["reasons"])

    def test_missing_bytes_are_explicit_not_false(self):
        got = module.observe_registry_snapshot(trusted=trusted(), snapshot=snapshot())
        self.assertEqual(got["status"], "accepted_provisional")
        self.assertEqual(got["content_bindings"][f"claim:{H1}"], "content_unavailable")

    def test_wrong_bytes_are_commitment_mismatch(self):
        got = module.observe_registry_snapshot(
            trusted=trusted(), snapshot=snapshot(), content_bytes={COMMITMENT.lower(): b"altered"})
        self.assertEqual(got["content_bindings"][f"claim:{H1}"], "commitment_mismatch")

    def test_malformed_event_rejected(self):
        x = snapshot(); x["history"][0]["event"] = "TruthCertified"
        got = module.observe_registry_snapshot(trusted=trusted(), snapshot=x)
        self.assertEqual(got["status"], "failed")
        self.assertIn("malformed_event_name", got["reasons"])

    def test_duplicate_event_identity_rejected(self):
        x = snapshot(); x["history"][1].update({"blockHash": H1, "transactionHash": H2, "logIndex": 0})
        self.assertIn("duplicate_event_log_identity", module.observe_registry_snapshot(trusted=trusted(), snapshot=x)["reasons"])

    def test_overstated_finality_rejected(self):
        x = snapshot(); x["finality"] = "final"
        self.assertIn("invalid_or_overstated_finality", module.observe_registry_snapshot(trusted=trusted(), snapshot=x)["reasons"])

    def test_depth_label_is_preserved_as_not_consensus_finality(self):
        x = snapshot(); x["finality"] = "depth:6;not-consensus-finality"
        got = module.observe_registry_snapshot(trusted=trusted(), snapshot=x)
        self.assertEqual(got["status"], "accepted_provisional")
        self.assertEqual(got["chain_finality"], "depth:6;not-consensus-finality")

    def test_snapshot_unavailable_is_unknown(self):
        got = module.observe_registry_snapshot(trusted=trusted(), snapshot=None)
        self.assertEqual(got["status"], "unknown")
        self.assertEqual(got["observation"], "not_accepted")

    def test_missing_required_projection_is_unknown(self):
        x = snapshot(); del x["history"]
        got = module.observe_registry_snapshot(trusted=trusted(), snapshot=x)
        self.assertEqual(got["status"], "unknown")

    def test_evidence_with_missing_claim_projection_rejected(self):
        x = snapshot(); x["claims"] = {}; x["history"] = [x["history"][1]]
        self.assertIn("evidence_claim_missing_from_projection", module.observe_registry_snapshot(trusted=trusted(), snapshot=x)["reasons"])


if __name__ == "__main__":
    unittest.main()
