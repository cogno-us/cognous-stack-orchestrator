"""Post-merge cross-boundary non-promotion qualification."""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


registry = load("o4c_registry", "orchestration/adapters/registry/observation.py")
attestation = load("o4c_attestation", "orchestration/adapters/attestation/verifier.py")
institution = load("o4c_institution", "development/interfaces/institutional/authority_context_mapping.py")
exchange = load("o4c_exchange", "development/interfaces/exchange/reference_handoff.py")


class CrossBoundaryQualification(unittest.TestCase):
    def test_no_adapter_exports_effect_dispatch(self):
        for module in (registry, attestation, institution, exchange):
            for forbidden in ("issue_grant", "authorize", "execute_effect", "dispatch_message"):
                self.assertFalse(callable(getattr(module, forbidden, None)), (module.__name__, forbidden))

    def test_attestation_unconfigured_trust_is_not_verification(self):
        result = attestation.verify_attestation_binding(
            verifier_checkout="/nonexistent-verifier",
            verifier_revision=attestation.ATTESTATION_REVISION,
            trust_snapshot_path=None,
            trusted_time=None,
            attestation={},
            expected={},
        )
        self.assertNotEqual(result.get("status"), "verified")
        self.assertEqual(result["authority"], "not_established")

    def test_registry_unobserved_source_not_authenticated(self):
        trusted = registry.TrustedRegistryDeployment(
            chain_id=1,
            contract_address="0x" + "11" * 20,
            source_revision=registry.REGISTRY_REVISION,
            runtime_bytecode_hash="0x" + "22" * 32,
        )
        result = registry.observe_registry_snapshot(trusted=trusted, snapshot=None)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["authority"], "not_established")

    def test_institutional_adoption_reference_cannot_grant(self):
        context = {
            "schema_version": "0.1.0",
            "interface_status": "proposed_pending_governor_review",
            "institution": {"institution_id": "hospital", "authority_domain": "healthcare"},
            "principal": "operator",
            "acting_identity": "service",
            "requirement": {"requirement_id": "req-1", "evidence": []},
        }
        binding = {
            "tenant_id": "t1", "actor_id": "actor1", "institution_id": "hospital",
            "principal": "operator", "acting_identity": "service", "claimed_issuer": None,
        }
        result = institution.map_authority_context_requirements(
            source_revision=institution.SOURCE_REVISION,
            tenant_id="t1",
            actor_id="actor1",
            identity_binding=binding,
            authority_context=context,
            institutional_adoption_ref="claimed-adoption",
        )
        self.assertEqual(result["authority"], "not_established")
        self.assertEqual(result["effect_disposition"], "hold_effect")

    def test_exchange_unknown_receipt_never_authorizes(self):
        evidence = {
            "transport_profile": exchange.TRANSPORT_PROFILE,
            "transport_version": exchange.TRANSPORT_VERSION,
            "message_id": "msg-1",
            "delivery_attempts": [],
            "sender_acknowledgements": [],
            "recipient_acknowledgements": [],
            "producer_refs": {"decision_id": "dec-1", "effect_id": "effect-1"},
        }
        result = exchange.map_exchange_evidence(evidence)
        self.assertEqual(result["assurance"]["authorization"], "not_established")
        self.assertEqual(result["assurance"]["effect_occurrence"], "not_established")
        self.assertEqual(result["producer_refs"]["effect"]["status"], "reported_reference")


if __name__ == "__main__":
    unittest.main()
