import copy
import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).resolve().parents[4] / "development/scenarios/customer_refunds/control/qualification.py"
SPEC = importlib.util.spec_from_file_location("refund_control", PATH)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def request():
    return {
        "request_id": "refund-001",
        "tenant_id": "tenant-merchant-a",
        "order_ref": "order-opaque-001",
        "payment_ref": "payment-opaque-001",
        "purchase_evidence_ref": "evidence-opaque-001",
        "amount_minor": 5000,
        "currency": "USD",
        "policy_version": "1.0",
        "customer_id": "customer-001",
        "refund_reason": "duplicate",
        "actor": "urn:cognous:identity:refund-agent-1",
        "principal": "urn:cognous:principal:refund-service",
    }


def authority(req=None):
    req = req or request()
    digest = m.request_digest(req)
    return {
        "tenant_id": req["tenant_id"],
        "request_digest": digest,
        "delegated_authority": {
            "status": "active",
            "tenant_id": req["tenant_id"],
            "scope": m.PERMISSION,
            "grant_id": "urn:cognous:grant:fixture-only",
            "revision": "1",
        },
        "policy": {
            "ref": m.POLICY_REF,
            "version": req["policy_version"],
            "status": "active",
            "tenant_id": req["tenant_id"],
        },
        "approval": {
            "approval_ref": "urn:cognous:approval:fixture-only",
            "status": "active",
            "tenant_id": req["tenant_id"],
            "request_digest": digest,
        },
    }


class RefundControlQualification(unittest.TestCase):
    def test_accepted_pins_are_exact(self):
        self.assertEqual(m.ORCHESTRATOR_BASE, "0aaaa11d1795e4e0cbf081826e9e1d1b3d5ca850")
        self.assertEqual(m.MANIFEST_PIN, "8d1572d4f926c968a8704cb912a6e9d49166f74a")
        self.assertEqual(m.CONTROL_PLANE_PIN, "e66e5f163c5d5c112ff345a2f332b4c3893ee183")

    def test_clean_fixture_maps_contract_but_remains_hold(self):
        req = request()
        out = m.qualify_refund(req, authority(req))
        self.assertEqual(out["contract_faults"], [])
        self.assertIsNotNone(out["authority_binding_candidate"])
        self.assertTrue(out["authority_binding_candidate"]["fixture_only"])
        self.assertEqual(out["proposal"]["tenant_id"], req["tenant_id"])
        self.assertEqual(out["proposal"]["action_id"], m.ACTION_ID)
        self.assertEqual(out["proposal"]["requested_permissions"], [m.PERMISSION])
        self.assertEqual(out["decision"]["result"], "hold")
        self.assertIn("live_authorization_absent", out["decision"]["reasons"])
        self.assertIsNone(out["decision"]["binding"])
        self.assertEqual((out["effect"], out["settlement"]), ("disabled", "not_observed"))

    def test_missing_delegated_authority_fails_closed(self):
        req = request()
        auth = authority(req)
        del auth["delegated_authority"]
        out = m.qualify_refund(req, auth)
        self.assertIn("delegated_authority_missing", out["contract_faults"])
        self.assertIsNone(out["authority_binding_candidate"])
        self.assertEqual(out["decision"]["result"], "hold")

    def test_stale_policy_fails_closed(self):
        req = request()
        auth = authority(req)
        auth["policy"]["status"] = "superseded"
        auth["policy"]["version"] = "0.9"
        out = m.qualify_refund(req, auth)
        self.assertIn("policy_stale_or_changed", out["contract_faults"])
        self.assertEqual(out["decision"]["result"], "hold")

    def test_revoked_approval_fails_closed(self):
        req = request()
        auth = authority(req)
        auth["approval"]["status"] = "revoked"
        out = m.qualify_refund(req, auth)
        self.assertIn("approval_not_active", out["contract_faults"])
        self.assertEqual(out["decision"]["result"], "hold")

    def test_tenant_mismatch_fails_closed(self):
        req = request()
        auth = authority(req)
        auth["tenant_id"] = "tenant-other"
        out = m.qualify_refund(req, auth)
        self.assertIn("tenant_mismatch", out["contract_faults"])
        self.assertEqual(out["decision"]["result"], "hold")

    def test_changed_request_digest_fails_closed(self):
        original = request()
        auth = authority(original)
        changed = copy.deepcopy(original)
        changed["amount_minor"] = 6000
        out = m.qualify_refund(changed, auth)
        self.assertIn("request_digest_changed", out["contract_faults"])
        self.assertIn("approval_operation_binding_mismatch", out["contract_faults"])
        self.assertEqual(out["decision"]["result"], "hold")

    def test_component_execution_is_truthfully_labelled(self):
        req = request()
        out = m.qualify_refund(req, authority(req))
        availability = m.component_availability()
        if availability["control_plane"]:
            self.assertEqual(out["component_execution"]["control_plane"], "actual_component")
            self.assertTrue(out["component_execution"]["control_plane_validated"])
        else:
            self.assertEqual(out["component_execution"]["control_plane"], "fixture_stub")
            self.assertFalse(out["component_execution"]["control_plane_validated"])
        self.assertIn(
            out["component_execution"]["manifest"],
            {"fixture_stub", "actual_component", "actual_component_rejected_fixture"},
        )


if __name__ == "__main__":
    unittest.main()
