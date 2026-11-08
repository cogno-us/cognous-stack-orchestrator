"""Refund Desk (F3) M1-3 stack-free unit checks (Amendment M3): evidence.replay_note passthrough.

DEVELOPMENT ONLY / SYNTHETIC / test-owner developer checks, NOT independent qualification.
Expectations are frozen in Amendment M3 of applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md. F1 dataclasses are constructed by the test.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_refund_desk_m12_support", Path(__file__).with_name("_m12_support.py"))
M = sys.modules.get("_refund_desk_m12_support") or importlib.util.module_from_spec(_spec)
sys.modules["_refund_desk_m12_support"] = M
if not hasattr(M, "HIGH"):
    _spec.loader.exec_module(M)

from orchestration.adapters.refund_disposition.contract import (CONTRACT_VERSION, NOT_VERIFIED, CleanupReport, DispositionResult,  # noqa: E402
                                                                EvidenceReferences, Labels, NativeFacts, ProfileIdentity, Refusal)
from refund_desk import present  # noqa: E402
from refund_desk.desk import DeskResult, failed_result, uncertain_result  # noqa: E402

CASE = "HV-M13-U1"
NOTE = "replay_import_failed: ImportContractError('single-proposal importer does not support multiple authorization bindings')"
EXECUTED = dict(cp_result="authorized", cp_reasons=(), runtime_status="reconciled", observed_state="applied", newly_executed=False, acknowledged=True,
                effect_id="eff-m13")


def f1(disposition="executed", *, evidence=None, profile=None, **native) -> DispositionResult:
    refusal = Refusal("request_invalid", "constructed reason", "adapter") if disposition == "refused" else None
    return DispositionResult(
        contract_version=CONTRACT_VERSION, disposition=disposition, correlation_id=CASE, tenant_id=M.TENANT, native=NativeFacts(**native),
        runtime_invoked=False, runtime_invocations=0, evidence=evidence or EvidenceReferences(), refusal=refusal, error=None, next_step="none",
        effect_absence_established=False, cleanup=CleanupReport(ok=True, scratch_path=None), labels=Labels(not_verified=NOT_VERIFIED), mode="dispose",
        profile=profile)


def ev(state, note, replay=None):
    return EvidenceReferences(replay_state=state, replay_note=note, replay=replay)


class ReplayNote(unittest.TestCase):
    def test_note_is_copied_verbatim_and_replay_stays_null(self):
        d = present(f1(evidence=ev("import_failed", NOTE), **EXECUTED), CASE).to_dict()
        self.assertEqual(d["evidence"]["replay_note"], NOTE)
        self.assertEqual(d["evidence"]["replay_state"], "import_failed")
        self.assertIsNone(d["evidence"]["replay"])
        self.assertEqual(set(d["evidence"]), {"replay_state", "replay", "source", "replay_note"})
        self.assertEqual(json.loads(json.dumps(d)), d)

    def test_missing_note_is_null(self):
        d = present(f1(evidence=ev("imported", None), **EXECUTED), CASE).to_dict()
        self.assertIn("replay_note", d["evidence"])
        self.assertIsNone(d["evidence"]["replay_note"])

    def test_note_is_not_trimmed_or_rewritten(self):
        odd = "  keep   exact\n text  "
        self.assertEqual(present(f1(evidence=ev("not_run", odd), **EXECUTED), CASE).to_dict()["evidence"]["replay_note"], odd)

    def test_import_failed_does_not_change_semantics(self):
        a = present(f1(evidence=ev("import_failed", NOTE), **EXECUTED), CASE).to_dict()
        b = present(f1(evidence=ev("import_failed", None), **EXECUTED), CASE).to_dict()
        for k in a:
            if k != "evidence":
                self.assertEqual(a[k], b[k], k)
        self.assertEqual(a["outcome"], "executed")
        self.assertIs(a["execution_claim"]["supported"], True)
        self.assertEqual(a["retry_permission"], "not_established")
        self.assertIs(a["effect_absence_established"], False)
        for k in ("replay_state", "replay", "source"):
            self.assertEqual(a["evidence"][k], b["evidence"][k])

    def test_note_on_non_executed_results(self):
        held = present(f1("held", evidence=ev("not_run", "Control Plane did not authorize; Runtime and Replay were not run"),
                          cp_result="hold", cp_reasons=("target_out_of_scope",)), CASE).to_dict()
        self.assertEqual(held["evidence"]["replay_note"], "Control Plane did not authorize; Runtime and Replay were not run")
        self.assertEqual(held["outcome"], "held")
        unk = present(f1("unknown", evidence=ev("not_run", "runtime_export_failed: X"), cp_result="authorized", cp_reasons=()), CASE).to_dict()
        self.assertEqual(unk["evidence"]["replay_note"], "runtime_export_failed: X")
        self.assertEqual(unk["outcome"], "uncertain")

    def test_unsupported_executed_stays_uncertain_and_forwards_note(self):
        d = present(f1(evidence=ev("import_failed", NOTE), cp_result="authorized", cp_reasons=(), runtime_status="executed", observed_state=None), CASE).to_dict()
        self.assertEqual(d["outcome"], "uncertain")
        self.assertEqual(d["evidence"]["replay_note"], NOTE)

    def test_defaults_and_fail_closed_results_carry_null_note(self):
        self.assertIsNone(DeskResult(case_id="x", outcome="failed", message="m").to_dict()["evidence"]["replay_note"])
        self.assertIsNone(failed_result("x", "boom").to_dict()["evidence"]["replay_note"])
        self.assertIsNone(uncertain_result("x", "boom").to_dict()["evidence"]["replay_note"])

    def test_profile_identity_unchanged(self):
        pid = ProfileIdentity(**M.IDENTITY[M.HIGH])
        d = present(f1(evidence=ev("import_failed", NOTE), profile=pid, **EXECUTED), CASE).to_dict()
        self.assertEqual(d["profile"], M.IDENTITY[M.HIGH])


if __name__ == "__main__":
    unittest.main()
