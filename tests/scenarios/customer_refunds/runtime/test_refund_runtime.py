import importlib.util
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]
MODULE = ROOT / "development/scenarios/customer_refunds/runtime/refund_runtime.py"
SPEC = importlib.util.spec_from_file_location("refund_runtime", MODULE)
runtime = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime
SPEC.loader.exec_module(runtime)


def intent(**changes):
    base = dict(
        tenant_id="tenant-a",
        request_id="request-1",
        order_ref="order-1",
        payment_ref="payment-1",
        effect_id="effect-1",
        amount_minor=2500,
        currency="USD",
    )
    base.update(changes)
    return runtime.RefundIntent(**base)


class RefundRuntimeQualification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.destination = runtime.SyntheticRefundRuntime(self.temp.name)

    def permit(self, value=None):
        value = value or intent()
        return runtime.fixture_control_plane_permit(value, decision_id="decision-1")

    def test_attempt_key_binds_tenant_request_order_and_payment(self):
        original = intent()
        key = original.attempt_key
        self.assertNotEqual(key, intent(tenant_id="tenant-b").attempt_key)
        self.assertNotEqual(key, intent(request_id="request-2").attempt_key)
        self.assertNotEqual(key, intent(order_ref="order-2").attempt_key)
        self.assertNotEqual(key, intent(payment_ref="payment-2").attempt_key)
        self.assertEqual(key, intent(effect_id="another-effect").attempt_key)

    def test_absent_authenticated_permit_fails_closed_without_effect(self):
        result = self.destination.execute(intent(), permit=None, attempt_id="attempt-1")
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "missing_authenticated_control_plane_permit")
        self.assertFalse(result["attempted"])
        self.assertFalse(result["processor_call"])
        self.assertEqual(result["settlement"], "not_observed")
        state = self.destination.state()
        self.assertEqual(state["intents"], [])
        self.assertEqual(len(state["attempts"]), 1)
        self.assertEqual(state["attempts"][0]["outcome"], "refused")

    def test_unauthenticated_or_non_current_permit_refuses(self):
        p = self.permit()
        p["authenticated_control_plane_permit"] = False
        r = self.destination.execute(intent(), permit=p, attempt_id="attempt-u")
        self.assertEqual(r["reason"], "unauthenticated_control_plane_permit")
        self.assertEqual(self.destination.state()["intents"], [])

        p = self.permit(intent(request_id="request-2", effect_id="effect-2"))
        p["authority_current"] = False
        r = self.destination.execute(
            intent(request_id="request-2", effect_id="effect-2"),
            permit=p,
            attempt_id="attempt-nc",
        )
        self.assertEqual(r["reason"], "authority_not_current")
        self.assertEqual(self.destination.state()["intents"], [])

    def test_permit_binding_mismatch_refuses_cross_tenant(self):
        i = intent()
        p = self.permit(i)
        p["tenant_id"] = "tenant-other"
        r = self.destination.execute(i, permit=p, attempt_id="attempt-x")
        self.assertEqual(r["reason"], "permit_binding_mismatch_tenant_id")
        self.assertEqual(self.destination.state()["intents"], [])

    def test_permit_binding_mismatch_refuses_amount_or_currency(self):
        i = intent()
        for field, value in (
            ("amount_minor", 999_999),
            ("amount_minor", 2500.0),
            ("currency", "EUR"),
        ):
            with self.subTest(field=field, value=value):
                p = self.permit(i)
                p[field] = value
                r = self.destination.execute(i, permit=p, attempt_id=f"attempt-{field}-{value}")
                self.assertEqual(r["status"], "refused")
                self.assertEqual(r["reason"], "permit_binding_mismatch_" + field)
                self.assertEqual(self.destination.state()["intents"], [])
        p = self.permit(i)
        del p["amount_minor"]
        r = self.destination.execute(i, permit=p, attempt_id="attempt-amount-absent")
        self.assertEqual(r["reason"], "permit_binding_mismatch_amount_minor")
        self.assertEqual(self.destination.state()["intents"], [])

    def test_synthetic_success_never_claims_processor_call_or_settlement(self):
        i = intent()
        r = self.destination.execute(i, permit=self.permit(i), attempt_id="attempt-ok")
        self.assertEqual(r["status"], "simulated_applied")
        self.assertTrue(r["simulated_effect"])
        self.assertTrue(r["attempted"])
        self.assertFalse(r["processor_call"])
        self.assertEqual(r["settlement"], "not_observed")
        self.assertEqual(r["runtime_revision"], runtime.EXECUTION_RUNTIME_REVISION)
        state = self.destination.state()
        self.assertEqual(len(state["intents"]), 1)
        self.assertEqual(state["intents"][0]["effect_id"], "effect-1")
        self.assertEqual(state["intents"][0]["state"], "simulated_applied")

    def test_duplicate_retry_is_durably_suppressed(self):
        i = intent()
        self.destination.execute(i, permit=self.permit(i), attempt_id="attempt-first")

        # Reopen to prove suppression is durable rather than process-local.
        reopened = runtime.SyntheticRefundRuntime(self.temp.name)
        duplicate = reopened.execute(i, permit=self.permit(i), attempt_id="attempt-retry")
        self.assertEqual(duplicate["status"], "refused")
        self.assertEqual(duplicate["reason"], "duplicate_intent")
        state = reopened.state()
        self.assertEqual(len(state["intents"]), 1)
        self.assertEqual(state["intents"][0]["effect_id"], i.effect_id)
        self.assertEqual(
            [a["outcome"] for a in state["attempts"]],
            ["simulated_applied", "suppressed"],
        )

    def test_same_business_scope_with_substituted_effect_id_is_still_duplicate(self):
        first = intent(effect_id="effect-original")
        self.destination.execute(first, permit=self.permit(first), attempt_id="attempt-first")
        changed = intent(effect_id="effect-substituted")
        r = self.destination.execute(changed, permit=self.permit(changed), attempt_id="attempt-second")
        self.assertEqual(r["reason"], "duplicate_intent")
        self.assertEqual(len(self.destination.state()["intents"]), 1)

    def test_cancel_before_execution_wins_and_no_effect_is_created(self):
        i = intent()
        cancel = self.destination.cancel(i, reason="customer_cancelled")
        self.assertEqual(cancel["status"], "cancelled_before_effect")
        r = self.destination.execute(i, permit=self.permit(i), attempt_id="attempt-after-cancel")
        self.assertEqual(r["status"], "refused")
        self.assertEqual(r["reason"], "cancelled")
        self.assertEqual(self.destination.state()["intents"], [])

    def test_cancel_after_commit_does_not_rewrite_history(self):
        i = intent()
        self.destination.execute(i, permit=self.permit(i), attempt_id="attempt-before-cancel")
        cancel = self.destination.cancel(i)
        self.assertEqual(cancel["status"], "post_commit_no_rollback")
        state = self.destination.state()
        self.assertEqual(len(state["intents"]), 1)
        self.assertEqual(state["intents"][0]["state"], "simulated_applied")

    def test_authority_withdrawal_before_execution_wins(self):
        i = intent()
        p = self.permit(i)
        self.destination.withdraw_authority("decision-1")
        r = self.destination.execute(i, permit=p, attempt_id="attempt-after-withdraw")
        self.assertEqual(r["status"], "refused")
        self.assertEqual(r["reason"], "authority_withdrawn")
        self.assertEqual(self.destination.state()["intents"], [])

    def test_authority_withdrawal_after_commit_is_not_rollback(self):
        i = intent()
        p = self.permit(i)
        self.destination.execute(i, permit=p, attempt_id="attempt-before-withdraw")
        withdrawal = self.destination.withdraw_authority("decision-1")
        self.assertEqual(withdrawal["status"], "withdrawn_after_effect_no_rollback")
        state = self.destination.state()
        self.assertEqual(len(state["intents"]), 1)
        self.assertEqual(state["intents"][0]["effect_id"], i.effect_id)

    def test_refusal_is_durable_across_reopen(self):
        i = intent()
        p = self.permit(i)
        p["decision"] = "hold"
        self.destination.execute(i, permit=p, attempt_id="attempt-held")
        reopened = runtime.SyntheticRefundRuntime(self.temp.name)
        state = reopened.state()
        self.assertEqual(len(state["attempts"]), 1)
        self.assertEqual(state["attempts"][0]["outcome"], "refused")
        self.assertEqual(state["attempts"][0]["reason"], "control_plane_refused")
        self.assertEqual(state["intents"], [])

    def test_attempt_identity_cannot_be_reused_for_distinct_request(self):
        first = intent()
        p = self.permit(first)
        self.destination.execute(first, permit=p, attempt_id="same-attempt")
        second = intent(request_id="request-2", effect_id="effect-2")
        with self.assertRaisesRegex(PermissionError, "attempt_identity_already_exists"):
            self.destination.execute(second, permit=self.permit(second), attempt_id="same-attempt")
        self.assertEqual(len(self.destination.state()["intents"]), 1)


if __name__ == "__main__":
    unittest.main()
