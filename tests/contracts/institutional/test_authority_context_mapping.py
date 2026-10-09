import copy
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
PATH = ROOT / "development/interfaces/institutional/authority_context_mapping.py"
SPEC = importlib.util.spec_from_file_location("authority_context_mapping", PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def context(with_grant=True):
    x = {
        "schema_version": "0.1.0",
        "interface_status": "proposed_pending_governor_review",
        "context_id": "urn:example:context:routine",
        "institution": {
            "institution_id": "urn:example:institution:service",
            "authority_domain": "customer-service",
            "authority_basis_ref": "urn:example:local-mandate:service",
            "authority_mode": "principle_inspired",
        },
        "principal": "urn:example:principal:service",
        "acting_identity": "urn:example:identity:service-bot",
        "requirement": {
            "requirement_id": "urn:example:requirement:refund",
            "evidence": [{
                "obligation_id": "urn:example:obligation:eligibility",
                "kind": "authorization",
                "source_ref": "urn:example:records:eligibility",
                "max_age_seconds": 60,
                "required": True,
                "unknown_behavior": "hold_effect",
            }],
        },
    }
    if with_grant:
        x["grant"] = {
            "grant_id": "urn:example:grant:refund",
            "revision": "1",
            "requirement_id": "urn:example:requirement:refund",
            "issuer": "urn:example:human:owner",
            "issuer_role": "urn:example:role:service-owner",
            "issuance_record_ref": "urn:example:record:issuance",
            "grantee": "urn:example:principal:service",
            "acting_identity": "urn:example:identity:service-bot",
        }
    return x


def binding(with_grant=True):
    return {
        "tenant_id": "tenant-a",
        "actor_id": "actor-a",
        "institution_id": "urn:example:institution:service",
        "principal": "urn:example:principal:service",
        "acting_identity": "urn:example:identity:service-bot",
        "claimed_issuer": "urn:example:human:owner" if with_grant else None,
    }


def assess(ctx=None, ident=None, **overrides):
    args = {
        "source_revision": module.SOURCE_REVISION,
        "tenant_id": "tenant-a",
        "actor_id": "actor-a",
        "identity_binding": binding(),
        "authority_context": context(),
        "institutional_adoption_ref": None,
    }
    if ctx is not None:
        args["authority_context"] = ctx
    if ident is not None:
        args["identity_binding"] = ident
    args.update(overrides)
    return module.map_authority_context_requirements(**args)


class TestInstitutionalMapping(unittest.TestCase):
    def test_valid_claim_mapping_still_holds_and_establishes_no_authority(self):
        got = assess()
        self.assertEqual(got["status"], "requirements_mapped_hold")
        self.assertEqual(got["governance_state"], "proposed_requirements_only")
        self.assertEqual(got["grant_state"], "claimed_grant_external_authentication_required")
        self.assertEqual(got["adoption_state"], "missing")
        self.assertEqual(got["authority"], "not_established")
        self.assertEqual(got["effect_disposition"], "hold_effect")

    def test_requirement_only_context_is_not_a_grant(self):
        ctx = context(False)
        ident = binding(False)
        got = assess(ctx, ident)
        self.assertEqual(got["grant_state"], "requirements_only")
        self.assertEqual(got["authority"], "not_established")
        self.assertEqual(got["effect_disposition"], "hold_effect")

    def test_adoption_reference_remains_unverified_and_holds(self):
        got = assess(institutional_adoption_ref="urn:example:adoption:record")
        self.assertEqual(got["adoption_state"], "reference_present_unverified")
        self.assertIn("institutional_adoption_not_authenticated", got["reasons"])
        self.assertEqual(got["authority"], "not_established")
        self.assertEqual(got["effect_disposition"], "hold_effect")

    def test_wrong_source_revision_rejected(self):
        got = assess(source_revision="0" * 40)
        self.assertEqual(got["status"], "rejected")
        self.assertIn("unsupported_source_revision", got["reasons"])

    def test_non_proposed_interface_rejected(self):
        ctx = context()
        ctx["interface_status"] = "active"
        got = assess(ctx)
        self.assertIn("interface_not_proposed_pending_governor_review", got["reasons"])

    def test_runtime_authorization_field_rejected(self):
        ctx = context()
        ctx["allowed"] = True
        got = assess(ctx)
        self.assertIn("prohibited_runtime_authorization_field", got["reasons"])

    def test_tenant_mismatch_rejected(self):
        ident = binding()
        ident["tenant_id"] = "tenant-b"
        got = assess(ident=ident)
        self.assertIn("tenant_binding_mismatch", got["reasons"])

    def test_actor_mismatch_rejected(self):
        ident = binding()
        ident["actor_id"] = "actor-b"
        got = assess(ident=ident)
        self.assertIn("actor_binding_mismatch", got["reasons"])

    def test_institution_mismatch_rejected(self):
        ident = binding()
        ident["institution_id"] = "urn:example:institution:other"
        got = assess(ident=ident)
        self.assertIn("institution_binding_mismatch", got["reasons"])

    def test_principal_mismatch_rejected(self):
        ident = binding()
        ident["principal"] = "urn:example:principal:other"
        got = assess(ident=ident)
        self.assertIn("principal_binding_mismatch", got["reasons"])

    def test_acting_identity_mismatch_rejected(self):
        ident = binding()
        ident["acting_identity"] = "urn:example:identity:other"
        got = assess(ident=ident)
        self.assertIn("acting_identity_binding_mismatch", got["reasons"])

    def test_issuer_mismatch_rejected(self):
        ident = binding()
        ident["claimed_issuer"] = "urn:example:human:other"
        got = assess(ident=ident)
        self.assertIn("issuer_binding_mismatch", got["reasons"])

    def test_grant_requirement_mismatch_rejected(self):
        ctx = context()
        ctx["grant"]["requirement_id"] = "urn:example:requirement:other"
        got = assess(ctx)
        self.assertIn("grant_requirement_mismatch", got["reasons"])

    def test_grant_principal_mismatch_rejected(self):
        ctx = context()
        ctx["grant"]["grantee"] = "urn:example:principal:other"
        got = assess(ctx)
        self.assertIn("grant_principal_mismatch", got["reasons"])

    def test_grant_acting_identity_mismatch_rejected(self):
        ctx = context()
        ctx["grant"]["acting_identity"] = "urn:example:identity:other"
        got = assess(ctx)
        self.assertIn("grant_acting_identity_mismatch", got["reasons"])

    def test_issuer_claim_without_grant_rejected(self):
        ctx = context(False)
        ident = binding(False)
        ident["claimed_issuer"] = "urn:example:human:owner"
        got = assess(ctx, ident)
        self.assertIn("issuer_claim_without_grant", got["reasons"])

    def test_required_authorization_evidence_cannot_fail_open(self):
        ctx = context()
        ctx["requirement"]["evidence"][0]["unknown_behavior"] = "preserve_if_other_basis_suffices"
        got = assess(ctx)
        self.assertIn("invalid_required_authorization_unknown_behavior", got["reasons"])
        self.assertEqual(got["effect_disposition"], "hold_effect")

    def test_mapping_does_not_mutate_input(self):
        ctx = context()
        before = copy.deepcopy(ctx)
        assess(ctx)
        self.assertEqual(ctx, before)


if __name__ == "__main__":
    unittest.main()
