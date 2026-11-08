"""Regression R1: F1 `executed` without supported applied-effect observation must be presented as UNCERTAIN (stack-free).

DEVELOPMENT ONLY / SYNTHETIC / test-owner developer checks, NOT independent qualification.
Regression R1 frozen at b1b10311 (Amendment R1 in CONTRACT_AND_EXPECTATIONS.md) before the implementation change.
Uses constructed F1 DispositionResult objects only; no stack, no native component.
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
                                                                FileReference, NativeFacts, Refusal)
from refund_desk import present  # noqa: E402

CASE = "HV-2026-1102-0098"
SUPPORTED_STATUSES = ("executed", "reconciled", "observed")
BAD_WORDS = ("observed as applied", "failed", "denied", "held", "nothing happened", "no effect", "succeeded")
REQUIRED = ("uncertain", "no retry", "absence of an effect is not established", "f1 reported executed", "do not support an applied effect",
            "treated as uncertain")


def evidence(with_replay: bool) -> EvidenceReferences:
    src = (FileReference("cp_run_record", "/nonexistent/cp.json", "sha256:" + "a" * 64),)
    if not with_replay:
        return EvidenceReferences(source=src)
    return EvidenceReferences(source=src, replay=FileReference("replay_bundle", "/nonexistent/replay.json", "sha256:" + "b" * 64,
                                                               {"status": "reconstruction_complete"}), replay_state="imported")


def f1(disposition: str, *, refusal_code: str | None = None, with_replay: bool = False, **native) -> DispositionResult:
    refusal = Refusal(refusal_code, "constructed reason for " + refusal_code, "adapter") if refusal_code else None
    invoked = disposition in ("executed", "unknown", "failed")
    return DispositionResult(
        contract_version=CONTRACT_VERSION, disposition=disposition, correlation_id=CASE, tenant_id="harborview-retail", native=NativeFacts(**native),
        runtime_invoked=invoked, runtime_invocations=1 if invoked else 0, evidence=evidence(with_replay), refusal=refusal,
        error="constructed error" if disposition == "failed" else None, next_step="none", effect_absence_established=False,
        cleanup=CleanupReport(ok=True, scratch_path=None))


def unsupported_variants():
    for observed in (None, "absent", "unknown", "partial", "pending"):
        yield dict(runtime_status="executed", observed_state=observed)
    for status in ("unknown", "partial", "denied", "failed", "something_new", None):
        yield dict(runtime_status=status, observed_state="applied")
    yield dict(runtime_status="unknown", observed_state="absent")
    yield dict(runtime_status=None, observed_state=None)
    yield dict(runtime_status="something_new", observed_state="pending")


class UnsupportedExecutedIsUncertain(unittest.TestCase):
    def test_unsupported_executed_presents_as_uncertain(self):
        import refund_desk.cli as cli

        for kw in unsupported_variants():
            for ack in (True, False):
                for newly in (True, False):
                    for replay in (False, True):
                        with self.subTest(**kw, acknowledged=ack, newly_executed=newly, replay=replay):
                            r = f1("executed", with_replay=replay, acknowledged=ack, newly_executed=newly, effect_id="eff-1", cp_result="authorized", **kw)
                            d = present(r, CASE).to_dict()
                            self.assertEqual(json.loads(json.dumps(d)), d)
                            self.assertEqual(d["outcome"], "uncertain", d["message"])
                            self.assertIs(d["execution_claim"]["supported"], False)
                            self.assertEqual(d["permitted_next_actions"], ["reconcile"])
                            self.assertIs(d["effect_absence_established"], False)
                            self.assertEqual(d["retry_permission"], "not_established")
                            self.assertIsNone(d["refusal"])
                            n = d["native"]
                            self.assertEqual(n["disposition"], "executed")
                            self.assertEqual((n["runtime_status"], n["observed_state"], n["acknowledged"], n["newly_executed"]),
                                             (kw["runtime_status"], kw["observed_state"], ack, newly))
                            ev = d["evidence"]
                            self.assertEqual(ev["replay_state"], r.evidence.replay_state)
                            self.assertEqual([(s["path"], s["sha256"]) for s in ev["source"]], [(s.path, s.sha256) for s in r.evidence.source])
                            if replay:
                                self.assertEqual((ev["replay"]["path"], ev["replay"]["sha256"], ev["replay"]["status"]),
                                                 (r.evidence.replay.path, r.evidence.replay.sha256, "reconstruction_complete"))
                            else:
                                self.assertIsNone(ev["replay"])
                            self.assertEqual(list(d["labels"]["not_verified"]), list(r.labels.not_verified))
                            for s in r.labels.not_verified:
                                self.assertIn(s, d["limitations"])
                            msg = d["message"].lower()
                            for req in REQUIRED:
                                self.assertIn(req, msg, d["message"])
                            for bad in BAD_WORDS:
                                self.assertNotIn(bad, msg, d["message"])
                            self.assertEqual(cli._EXIT["uncertain"], 3)


class ExecutedWithRefusal(unittest.TestCase):
    def test_executed_with_refusal_object_is_uncertain_and_refusal_dropped(self):
        for code in ("prior_uncertain_dispatch", "request_invalid", "control_plane_hold"):
            # Unsupported pairs only. executed+applied+supported with a stray refusal object is outside R1 (R1 preserves a supported
            # claim) and is deliberately not asserted here.
            for status, observed in (("executed", "absent"), ("unknown", "applied"), ("unknown", "absent")):
                with self.subTest(code=code, runtime_status=status, observed_state=observed):
                    d = present(f1("executed", refusal_code=code, runtime_status=status, observed_state=observed), CASE).to_dict()
                    self.assertEqual(d["outcome"], "uncertain", d["message"])
                    self.assertIs(d["execution_claim"]["supported"], False)
                    self.assertEqual(d["permitted_next_actions"], ["reconcile"])
                    self.assertIsNone(d["refusal"])


class CliUnsupportedExecuted(unittest.TestCase):
    def test_cli_main_unsupported_executed_exits_3(self):
        import contextlib
        import io
        from unittest import mock

        import refund_desk.cli as cli
        import refund_desk.desk as desk

        r = f1("executed", runtime_status="executed", observed_state="absent", acknowledged=True, newly_executed=True, effect_id="eff-1")
        with S.tempdir("f3-ux-") as td, S.tempdir("f3-ux-stack-") as fake, mock.patch.object(desk, "dispose_refund", lambda *a, **k: r):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli.main(S.cli_args("process", S.CASE_A, Path(td)) + ["--stack-root", fake])
        d = json.loads(buf.getvalue())
        self.assertEqual(rc, 3, d)
        self.assertEqual(d["outcome"], "uncertain")
        self.assertIs(d["execution_claim"]["supported"], False)
        self.assertEqual(d["permitted_next_actions"], ["reconcile"])


class Controls(unittest.TestCase):
    def test_supported_executed_stays_executed(self):
        for status in SUPPORTED_STATUSES:
            with self.subTest(runtime_status=status):
                d = present(f1("executed", runtime_status=status, observed_state="applied", acknowledged=True, newly_executed=True), CASE).to_dict()
                self.assertEqual(d["outcome"], "executed")
                self.assertIs(d["execution_claim"]["supported"], True)
                self.assertEqual(d["permitted_next_actions"], [])

    def test_other_dispositions_keep_outcomes(self):
        cases = [("held", {}, "held"), ("refused", {"refusal_code": "request_invalid"}, "refused"), ("denied", {}, "denied"),
                 ("failed", {}, "failed"), ("unknown", {"runtime_status": "unknown"}, "uncertain"),
                 ("refused", {"refusal_code": "prior_uncertain_dispatch"}, "uncertain")]
        for disp, kw, out in cases:
            with self.subTest(disposition=disp, **kw):
                d = present(f1(disp, **kw), CASE).to_dict()
                self.assertEqual(d["outcome"], out)
                self.assertIs(d["execution_claim"]["supported"], False)


if __name__ == "__main__":
    unittest.main()
