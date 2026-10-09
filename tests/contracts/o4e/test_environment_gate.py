import copy
import importlib.util
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
module_path = ROOT / "development/acceptance/o4e/validate_environment.py"
spec = importlib.util.spec_from_file_location("env_gate", module_path)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
BASE = json.loads((ROOT / "development/acceptance/o4e/environment-trust.example.json").read_text())


class TestO4eGate(unittest.TestCase):
    def test_example_is_never_qualified_authority(self):
        result = gate.assess_environment(BASE)
        self.assertEqual(result["status"], "hold")
        self.assertEqual(result["authority"], "not_established")
        self.assertEqual(result["reasons"], ["configuration_only_no_independent_authentication"])

    def check_reject(self, mutate, reason):
        obj = copy.deepcopy(BASE)
        mutate(obj)
        self.assertIn(reason, gate.assess_environment(obj)["reasons"])

    def test_wrong_chain(self):
        self.check_reject(lambda x: x["registry"].update(chain_id=True), "invalid_chain")

    def test_invalid_contract(self):
        self.check_reject(lambda x: x["registry"].update(contract_address="0xdead"), "invalid_contract")

    def test_untrusted_rpc(self):
        self.check_reject(lambda x: x["registry"].update(rpc_authentication="unknown"), "rpc_trust_not_configured")

    def test_missing_independent_checkpoint(self):
        self.check_reject(lambda x: x["registry"]["trusted_checkpoint"].update(source="caller_supplied"), "checkpoint_trust_not_identified")

    def test_bad_reorg_policy(self):
        self.check_reject(lambda x: x["registry"].update(reorg_policy="accept_all"), "unsafe_reorg_policy")

    def test_bad_snapshot(self):
        self.check_reject(lambda x: x["attestation"].update(trust_snapshot_sha256=""), "invalid_trust_snapshot")

    def test_untrusted_time(self):
        self.check_reject(lambda x: x["attestation"].update(trusted_time_source="local_clock_unverified"), "time_not_trusted")

    def test_key_revocation_relaxed(self):
        self.check_reject(lambda x: x["attestation"].update(key_lifecycle_policy="ignore_revocation"), "unsafe_key_lifecycle")

    def test_enable_effects_rejected(self):
        self.check_reject(lambda x: x["controls"].update(effect_dispatch="enabled"), "unsafe_execution_controls")

    def test_live_claim_without_evidence_is_held(self):
        self.check_reject(lambda x: x.update(classification="production"), "live_trust_not_qualified_by_config")


if __name__ == "__main__":
    unittest.main()
