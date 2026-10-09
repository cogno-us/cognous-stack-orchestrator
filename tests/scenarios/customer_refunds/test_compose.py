import importlib.util
import pathlib
import unittest
p=pathlib.Path(__file__).resolve().parents[3]/"development/scenarios/customer_refunds/compose.py"
s=importlib.util.spec_from_file_location("compose",p)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)
def req():
    return dict(request_id="r",tenant_id="t",order_ref="o",payment_ref="p",purchase_evidence_ref="e",amount_minor=5000,purchase_age_days=5,currency="USD",policy_version="fixture-v1",approval_state="active",issuer_state="verified_issuer_only",registry_state="consistent")
def refs():
    return dict(registry=dict(source_status="consistent_observation",tenant_id="t",request_id="r"),attestation=dict(verification="issuer_signature_only",tenant_id="t",request_id="r"),institutional=dict(authority="not_established",tenant_id="t",request_id="r"),exchange=dict(delivery="receipt_only",tenant_id="t",request_id="r"))
class Integration(unittest.TestCase):
    def test_consistent_references_never_authorize(self):
        x=m.compose(req(),refs(),tenant="t")
        self.assertEqual(x["faults"],[])
        self.assertEqual((x["disposition"],x["authorization"],x["effect"],x["settlement"]),("hold","not_established","disabled","not_observed"))
    def test_cross_tenant_attestation(self):
        f=refs();f["attestation"]["tenant_id"]="other"
        self.assertIn("binding_mismatch_attestation",m.compose(req(),f,tenant="t")["faults"])
    def test_missing_registry(self):
        f=refs();del f["registry"]
        self.assertIn("invalid_registry_reference",m.compose(req(),f,tenant="t")["faults"])
    def test_receipt_cannot_assert_effect(self):
        f=refs();f["effect_id"]="fake"
        x=m.compose(req(),f,tenant="t")
        self.assertIn("forbidden_effect_id_assertion",x["faults"])
        self.assertEqual(x["settlement"],"not_observed")
    def test_invalid_institutional_promotion(self):
        f=refs();f["institutional"]["authority"]="granted"
        self.assertIn("invalid_institutional_reference",m.compose(req(),f,tenant="t")["faults"])
    def test_revoked_issuer(self):
        q=req();q["issuer_state"]="revoked"
        self.assertIn("issuer",m.compose(q,refs(),tenant="t")["faults"])
    def test_duplicate(self):
        self.assertIn("duplicate",m.compose(req(),refs(),tenant="t",seen=("r",))["faults"])
    def test_missing_approval(self):
        q=req();q["approval_state"]="withdrawn"
        self.assertIn("approval",m.compose(q,refs(),tenant="t")["faults"])
if __name__=="__main__": unittest.main()
