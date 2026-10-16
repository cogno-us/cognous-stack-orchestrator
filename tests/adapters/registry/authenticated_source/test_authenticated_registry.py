import hashlib
import importlib.util
import pathlib
import sys
import unittest

path = pathlib.Path(__file__).resolve().parents[4] / "orchestration/adapters/registry/authenticated_source/observer.py"
spec = importlib.util.spec_from_file_location("authenticated_registry", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

ADDRESS = "0x" + "aa" * 20
OTHER_ADDRESS = "0x" + "bb" * 20
BLOCK10 = "0x" + "10" * 32
BLOCK12 = "0x" + "12" * 32
BLOCK12_ALT = "0x" + "13" * 32
TX = "0x" + "22" * 32
CODE = bytes.fromhex("6001600055")
CODE_HASH = hashlib.sha256(CODE).hexdigest()


def log_entry(**overrides):
    item = {
        "address": ADDRESS,
        "blockHash": BLOCK10,
        "blockNumber": "0xa",
        "transactionHash": TX,
        "transactionIndex": "0x0",
        "logIndex": "0x0",
        "removed": False,
        "data": "0x",
        "topics": [],
    }
    item.update(overrides)
    return item


def receipt(**overrides):
    item = {
        "transactionHash": TX,
        "blockHash": BLOCK10,
        "blockNumber": "0xa",
        "status": "0x1",
        "to": ADDRESS,
        "logs": [log_entry()],
    }
    item.update(overrides)
    return item


class FakeRpc:
    def __init__(
        self,
        *,
        chain_id=31337,
        checkpoint_hash=BLOCK10,
        end_hashes=None,
        logs=None,
        receipt_value=None,
        code=None,
        fail_method=None,
    ):
        self.chain_id = chain_id
        self.checkpoint_hash = checkpoint_hash
        self.end_hashes = list(end_hashes or [BLOCK12, BLOCK12])
        self.logs = list(logs if logs is not None else [log_entry()])
        self.receipt_value = receipt() if receipt_value is None else receipt_value
        self.code = "0x" + (CODE if code is None else code).hex()
        self.fail_method = fail_method
        self.end_reads = 0

    def call(self, method, params):
        if method == self.fail_method:
            raise module.RegistryObservationError("rpc_unavailable")
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_blockNumber":
            return "0xc"
        if method == "eth_getCode":
            return self.code
        if method == "eth_getLogs":
            return self.logs
        if method == "eth_getTransactionReceipt":
            return self.receipt_value
        if method == "eth_getBlockByNumber":
            number = int(params[0], 16)
            if number == 10:
                return {"number": "0xa", "hash": self.checkpoint_hash}
            if number == 12:
                value = self.end_hashes[min(self.end_reads, len(self.end_hashes) - 1)]
                self.end_reads += 1
                return {"number": "0xc", "hash": value}
            return {"number": hex(number), "hash": "0x" + f"{number:064x}"}
        raise AssertionError(f"unexpected method {method}")


def trusted(*, confirmations=0, checkpoint=True, address=ADDRESS, code_hash=CODE_HASH):
    cp = module.TrustedCheckpoint(10, BLOCK10) if checkpoint else None
    return module.TrustedRegistrySource(
        chain_id=31337,
        contract_address=address,
        runtime_bytecode_sha256=code_hash,
        rpc_endpoint_id="trusted-rpc-a",
        confirmations=confirmations,
        checkpoint=cp,
    )


class AuthenticatedRegistryTests(unittest.TestCase):
    def test_accepts_matching_deployment_receipt_log_and_checkpoint(self):
        got = module.observe_authenticated_registry(trusted=trusted(), rpc=FakeRpc())
        self.assertEqual(got["status"], "accepted_provisional")
        self.assertEqual(got["source_revision"], module.REGISTRY_REVISION)
        self.assertEqual(got["source_blob_sha"], module.REGISTRY_SOURCE_BLOB)
        self.assertEqual(got["verified_log_count"], 1)
        self.assertEqual(got["trust_model"], "operator-configured-rpc+independent-checkpoint")
        self.assertEqual(got["independent_verification"], "checkpoint_anchor_only")
        self.assertIn("checkpoint_not_linked_to_observed_block", got["limitations"])
        self.assertEqual(got["authority"], "not_established")
        self.assertEqual(got["effect"], "not_established")

    def test_operator_rpc_only_is_explicit_trust_limitation(self):
        got = module.observe_authenticated_registry(trusted=trusted(checkpoint=False), rpc=FakeRpc())
        self.assertEqual(got["status"], "accepted_provisional")
        self.assertEqual(got["trust_model"], "operator-configured-rpc")
        self.assertEqual(got["independent_verification"], "not_established")

    def test_confirmation_depth_never_claims_consensus_finality(self):
        rpc = FakeRpc(end_hashes=[BLOCK10, BLOCK10])
        got = module.observe_authenticated_registry(
            trusted=trusted(confirmations=2, checkpoint=False), rpc=rpc
        )
        self.assertEqual(got["status"], "accepted_provisional")
        self.assertEqual(got["chain_finality"], "depth:2;not-consensus-finality")

    def test_wrong_chain_rejected(self):
        got = module.observe_authenticated_registry(trusted=trusted(), rpc=FakeRpc(chain_id=1))
        self.assertIn("wrong_chain_id", got["reasons"])

    def test_different_contract_runtime_rejected(self):
        got = module.observe_authenticated_registry(trusted=trusted(), rpc=FakeRpc(code=b"other"))
        self.assertIn("runtime_bytecode_mismatch", got["reasons"])

    def test_log_from_different_contract_rejected(self):
        got = module.observe_authenticated_registry(
            trusted=trusted(), rpc=FakeRpc(logs=[log_entry(address=OTHER_ADDRESS)])
        )
        self.assertIn("log_contract_mismatch", got["reasons"])

    def test_removed_log_rejected(self):
        got = module.observe_authenticated_registry(
            trusted=trusted(), rpc=FakeRpc(logs=[log_entry(removed=True)])
        )
        self.assertIn("removed_log", got["reasons"])

    def test_inconsistent_receipt_block_hash_rejected(self):
        bad_receipt = receipt(blockHash=BLOCK12)
        got = module.observe_authenticated_registry(
            trusted=trusted(), rpc=FakeRpc(receipt_value=bad_receipt)
        )
        self.assertIn("receipt_block_hash_mismatch", got["reasons"])

    def test_log_missing_from_receipt_rejected(self):
        bad_receipt = receipt(logs=[])
        got = module.observe_authenticated_registry(
            trusted=trusted(), rpc=FakeRpc(receipt_value=bad_receipt)
        )
        self.assertIn("log_missing_from_receipt", got["reasons"])

    def test_receipt_log_with_same_identity_but_different_content_rejected(self):
        cases = {
            "receipt_log_contract_mismatch": log_entry(address=OTHER_ADDRESS),
            "receipt_log_content_mismatch": log_entry(topics=["0x" + "77" * 32]),
        }
        for reason, receipt_log in cases.items():
            with self.subTest(reason=reason):
                got = module.observe_authenticated_registry(
                    trusted=trusted(), rpc=FakeRpc(receipt_value=receipt(logs=[receipt_log]))
                )
                self.assertEqual(got["status"], "failed")
                self.assertIn(reason, got["reasons"])
        for field, value in (("data", "0x01"), ("removed", True)):
            with self.subTest(field=field):
                got = module.observe_authenticated_registry(
                    trusted=trusted(),
                    rpc=FakeRpc(receipt_value=receipt(logs=[log_entry(**{field: value})])),
                )
                self.assertEqual(got["status"], "failed")
                self.assertIn("receipt_log_content_mismatch", got["reasons"])

    def test_log_block_hash_mismatch_rejected(self):
        got = module.observe_authenticated_registry(
            trusted=trusted(checkpoint=False), rpc=FakeRpc(checkpoint_hash=BLOCK12)
        )
        self.assertIn("log_block_hash_mismatch", got["reasons"])

    def test_dishonest_endpoint_conflicting_with_independent_checkpoint_rejected(self):
        got = module.observe_authenticated_registry(
            trusted=trusted(), rpc=FakeRpc(checkpoint_hash=BLOCK12_ALT, logs=[])
        )
        self.assertEqual(got["status"], "failed")
        self.assertIn("trusted_checkpoint_mismatch", got["reasons"])

    def test_replacement_block_during_observation_rejected(self):
        got = module.observe_authenticated_registry(
            trusted=trusted(), rpc=FakeRpc(end_hashes=[BLOCK12, BLOCK12_ALT])
        )
        self.assertEqual(got["reorg_status"], "replacement_detected")
        self.assertIn("replacement_block_detected", got["reasons"])

    def test_unavailable_network_returns_unknown_not_success(self):
        got = module.observe_authenticated_registry(
            trusted=trusted(), rpc=FakeRpc(fail_method="eth_chainId")
        )
        self.assertEqual(got["status"], "unknown")
        self.assertEqual(got["reasons"], ["rpc_unavailable"])

    def test_invalid_trusted_config_fails_closed_before_rpc(self):
        bad = module.TrustedRegistrySource(
            chain_id=0,
            contract_address=ADDRESS,
            runtime_bytecode_sha256=CODE_HASH,
            rpc_endpoint_id="trusted-rpc-a",
        )
        got = module.observe_authenticated_registry(trusted=bad, rpc=FakeRpc())
        self.assertIn("invalid_trusted_chain_id", got["reasons"])


if __name__ == "__main__":
    unittest.main()
