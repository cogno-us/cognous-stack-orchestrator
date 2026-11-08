"""Refund Desk (F3) stack-free unit checks of the application's `present()` mapping over CONSTRUCTED F1 results.

DEVELOPMENT ONLY / SYNTHETIC / test-owner developer checks, NOT independent qualification.
Expectations are frozen in applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md; this module adds review-driven negative/edge cases.
The F1 dataclasses are constructed by the test (test-owned); no stack, no native component and no fault fixture is used.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_refund_desk_test_support", Path(__file__).with_name("_support.py"))
S = sys.modules.get("_refund_desk_test_support") or importlib.util.module_from_spec(_spec)
sys.modules["_refund_desk_test_support"] = S
if not hasattr(S, "REPO"):
    _spec.loader.exec_module(S)

from orchestration.adapters.refund_disposition.contract import (CONTRACT_VERSION, CleanupReport, DispositionResult, EvidenceReferences,  # noqa: E402
                                                                NativeFacts, Refusal)
from refund_desk import present  # noqa: E402

CASE = "HV-2026-1102-0099"


def f1(disposition: str, *, mode: str = "dispose", refusal_code: str | None = None, **native) -> DispositionResult:
    refusal = Refusal(refusal_code, "constructed reason for " + refusal_code, "adapter") if refusal_code else None
    return DispositionResult(
        contract_version=CONTRACT_VERSION, disposition=disposition, correlation_id=CASE, tenant_id="harborview-retail",
        native=NativeFacts(**native), runtime_invoked=disposition in ("executed", "unknown", "failed"), runtime_invocations=1 if disposition in ("executed", "unknown", "failed") else 0,
        evidence=EvidenceReferences(), refusal=refusal, error="constructed error" if disposition == "failed" else None,
        next_step="none", effect_absence_established=False, cleanup=CleanupReport(ok=True, scratch_path=None), mode=mode)


class PresentMapping(unittest.TestCase):
    def go(self, *a, **k) -> dict:
        d = present(f1(*a, **k), CASE).to_dict()
        json.dumps(d)
        self.assertEqual(d["retry_permission"], "not_established")
        self.assertIs(d["effect_absence_established"], False)
        return d

    def test_non_executed_dispositions_never_claim_execution(self):
        cases = [
            ("unknown", {"runtime_status": "unknown", "acknowledged": False}),
            ("unknown", {"runtime_status": "partial", "observed_state": "partial"}),  # partial presented as unknown by F1
            ("unknown", {"runtime_status": "unknown", "observed_state": "applied"}),  # even a stray applied is not a claim without `executed`
            ("failed", {"runtime_status": "failed", "runtime_error": "boom"}),
            ("denied", {"runtime_status": "denied"}),
            ("refused", {"refusal_code": "request_invalid"}),
            ("held", {"cp_result": "hold", "cp_reasons": ("grant_revoked",)}),
        ]
        for disp, kw in cases:
            with self.subTest(disposition=disp, **{k: v for k, v in kw.items() if k != "refusal_code"}):
                d = self.go(disp, **kw)
                self.assertNotEqual(d["outcome"], "executed", d)
                self.assertIs(d["execution_claim"]["supported"], False, d)

    def test_outcome_mapping(self):
        expect = {"unknown": "uncertain", "failed": "failed", "denied": "denied", "held": "held"}
        for disp, out in expect.items():
            with self.subTest(disposition=disp):
                self.assertEqual(self.go(disp)["outcome"], out)
        self.assertEqual(self.go("refused", refusal_code="request_invalid")["outcome"], "refused")

    def test_only_prior_uncertain_dispatch_refusal_is_uncertain(self):
        d = self.go("refused", refusal_code="prior_uncertain_dispatch")
        self.assertEqual(d["outcome"], "uncertain")
        self.assertIs(d["execution_claim"]["supported"], False)
        self.assertEqual(d["permitted_next_actions"], ["reconcile"])
        for code in ("request_invalid", "unsupported_action", "other_refusal"):
            with self.subTest(code=code):
                self.assertEqual(self.go("refused", refusal_code=code)["outcome"], "refused")

    def test_executed_requires_applied_observation(self):
        for observed in (None, "absent", "unknown", "partial", "pending"):
            with self.subTest(observed_state=observed):
                d = self.go("executed", runtime_status="executed", observed_state=observed, acknowledged=True, newly_executed=True)
                self.assertIs(d["execution_claim"]["supported"], False, d)
        d = self.go("executed", runtime_status="unknown", observed_state="applied")
        self.assertIs(d["execution_claim"]["supported"], False, "applied with a non-executed runtime status is not a supported claim")

    def test_executed_reconciled_or_observed_with_applied_is_supported(self):
        for status in ("executed", "reconciled", "observed"):
            with self.subTest(runtime_status=status):
                d = self.go("executed", runtime_status=status, observed_state="applied", acknowledged=status != "observed", newly_executed=status == "executed")
                self.assertEqual(d["outcome"], "executed")
                self.assertIs(d["execution_claim"]["supported"], True)
                self.assertIn(f"runtime_status={status}", d["execution_claim"]["basis"])
                self.assertEqual(d["permitted_next_actions"], [])

    def test_reconcile_mode_unknown_stays_uncertain(self):
        d = self.go("unknown", mode="reconcile", runtime_status="unknown", observed_state=None)
        self.assertEqual(d["outcome"], "uncertain")
        self.assertIs(d["execution_claim"]["supported"], False)
        self.assertEqual(d["permitted_next_actions"], ["reconcile"])

    def test_permitted_next_actions(self):
        for disp, kw in (("executed", {"runtime_status": "executed", "observed_state": "applied"}), ("held", {}), ("denied", {}), ("failed", {}),
                         ("refused", {"refusal_code": "request_invalid"})):
            with self.subTest(disposition=disp):
                self.assertEqual(self.go(disp, **kw)["permitted_next_actions"], [])
        self.assertEqual(self.go("unknown")["permitted_next_actions"], ["reconcile"])


if __name__ == "__main__":
    unittest.main()
