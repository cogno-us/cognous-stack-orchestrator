import importlib.util
import pathlib
import unittest
p = pathlib.Path(__file__).resolve().parents[3] / "development/scenarios/customer_refunds/evaluate.py"
s = importlib.util.spec_from_file_location("refund", p)
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)
def example():
    return {"request_id":"r1","tenant_id":"t1","order_ref":"o1","payment_ref":"p1",
            "purchase_evidence_ref":"e1","amount_minor":5000,"purchase_age_days":12,
            "currency":"USD","policy_version":"fixture-v1","approval_state":"active",
            "issuer_state":"verified_issuer_only","registry_state":"consistent"}
class RefundTests(unittest.TestCase):
    def test_eligible_never_executes(self):
        x = m.evaluate(example(),"t1")
        self.assertEqual(x["screening"],"eligible_for_review")
        self.assertEqual((x["disposition"],x["authority"],x["effect"],x["settlement"]),
                         ("hold","not_established","disabled","not_observed"))
    def test_fail_closed_cases(self):
        cases = [("tenant_id","other","tenant_mismatch"),("amount_minor",20000,"amount"),
                 ("purchase_age_days",31,"window"),("currency","EUR","currency"),
                 ("purchase_evidence_ref","","missing_purchase_evidence_ref"),
                 ("policy_version","changed","policy"),("approval_state","withdrawn","approval"),
                 ("issuer_state","revoked","issuer"),("registry_state","reorg","registry")]
        for key,value,reason in cases:
            with self.subTest(key=key):
                q = example(); q[key] = value
                r = m.evaluate(q,"t1")
                self.assertIn(reason,r["reasons"])
                self.assertEqual(r["disposition"],"hold")
    def test_duplicate(self):
        self.assertIn("duplicate",m.evaluate(example(),"t1",("r1",))["reasons"])
if __name__=="__main__": unittest.main()
