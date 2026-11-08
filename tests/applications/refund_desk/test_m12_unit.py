"""Refund Desk (F3) M1-2 stack-free unit checks (Amendment M2): result contract, limitations, request forwarding and CLI parser.

DEVELOPMENT ONLY / SYNTHETIC / test-owner developer checks, NOT independent qualification.
Expectations are frozen in Amendment M2 of applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md.
F1 dataclasses are constructed by the test (test-owned); no stack, no native component and no fault fixture is used.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_file_location("_refund_desk_m12_support", Path(__file__).with_name("_m12_support.py"))
M = sys.modules.get("_refund_desk_m12_support") or importlib.util.module_from_spec(_spec)
sys.modules["_refund_desk_m12_support"] = M
if not hasattr(M, "HIGH"):
    _spec.loader.exec_module(M)
S = M.S

from orchestration.adapters.refund_disposition.contract import (CONTRACT_VERSION, NOT_VERIFIED, CleanupReport, DispositionResult,  # noqa: E402
                                                                EvidenceReferences, Labels, NativeFacts, ProfileIdentity, Refusal)
from refund_desk import present  # noqa: E402

CASE = "HV-M12-U1"
LEGACY_KEYS = {"app_contract", "f1_contract_version", "case_id", "outcome", "message", "control_plane", "native", "execution_claim", "effect", "evidence",
               "refusal", "permitted_next_actions", "retry_permission", "effect_absence_established", "labels", "limitations", "cleanup"}


def identity(pid: str) -> ProfileIdentity:
    return ProfileIdentity(**M.IDENTITY[pid])


def f1(disposition: str = "held", *, profile: ProfileIdentity | None = None, with_profile_arg: bool = True, extra_nv: tuple = (), **native) -> DispositionResult:
    kw = {}
    if with_profile_arg:
        kw["profile"] = profile
    labels = Labels(not_verified=NOT_VERIFIED + extra_nv)
    code = "request_invalid" if disposition == "refused" else None
    return DispositionResult(
        contract_version=CONTRACT_VERSION, disposition=disposition, correlation_id=CASE, tenant_id=M.TENANT, native=NativeFacts(**native),
        runtime_invoked=False, runtime_invocations=0, evidence=EvidenceReferences(),
        refusal=Refusal(code, "constructed reason", "adapter") if code else None, error=None, next_step="none", effect_absence_established=False,
        cleanup=CleanupReport(ok=True, scratch_path=None), labels=labels, mode="dispose", **kw)


HELD = dict(cp_result="hold", cp_reasons=("target_out_of_scope",))


class ResultContract(unittest.TestCase):
    def test_profile_block_and_requested_profile_keys(self):
        d = present(f1(profile=identity(M.HIGH), **HELD), CASE).to_dict()
        self.assertTrue(LEGACY_KEYS <= set(d))
        self.assertIn("profile", d)
        self.assertIn("requested_profile", d)
        self.assertEqual(d["profile"], M.IDENTITY[M.HIGH])
        self.assertEqual(set(d["profile"]), M.IDENTITY_KEYS)

    def test_profile_null_when_f1_returned_none_and_requested_null_when_omitted(self):
        d = present(f1(profile=None, **HELD), CASE).to_dict()
        self.assertIn("profile", d)
        self.assertIsNone(d["profile"])
        self.assertIsNone(d["requested_profile"])

    def test_legacy_construction_without_the_new_fields(self):
        r = f1(with_profile_arg=False, **HELD)  # DispositionResult built exactly as before M1-1 (no profile argument)
        d = present(r, CASE).to_dict()
        self.assertIsNone(d["profile"])
        self.assertIsNone(d["requested_profile"])
        self.assertEqual(d["outcome"], "held")

    def test_json_round_trip(self):
        for prof in (None, identity(M.ROUTINE), identity(M.HIGH)):
            d = present(f1(profile=prof, **HELD), CASE).to_dict()
            self.assertEqual(json.loads(json.dumps(d, sort_keys=True)), d)

    def test_existing_keys_unchanged_for_default(self):
        d = present(f1(profile=identity(M.ROUTINE), **HELD), CASE).to_dict()
        self.assertEqual(set(d), LEGACY_KEYS | {"profile", "requested_profile"})
        self.assertEqual(d["app_contract"], "refund-desk/0.1.0-dev")
        self.assertEqual(d["control_plane"], {"result": "hold", "reasons": ["target_out_of_scope"]})
        self.assertEqual(d["refusal"]["code"], "control_plane_hold")
        self.assertEqual(d["refusal"]["reasons"], ["target_out_of_scope"])

    def test_native_reason_codes_shown_verbatim(self):
        for code in ("target_out_of_scope", "amount_exceeded"):
            d = present(f1(profile=identity(M.HIGH), cp_result="hold", cp_reasons=(code,)), CASE).to_dict()
            self.assertEqual(d["control_plane"]["reasons"], [code])
            self.assertEqual(d["refusal"]["reasons"], [code])
            self.assertTrue(d["refusal"]["explanation"])


class Limitations(unittest.TestCase):
    def test_default_and_routine_limitations_byte_identical_to_legacy(self):
        legacy = list(NOT_VERIFIED) + list(M.LEGACY_APP_NOTES)
        for prof in (None, identity(M.ROUTINE)):
            d = present(f1(profile=prof, **HELD), CASE).to_dict()
            self.assertEqual(d["limitations"], legacy)
        d = present(f1(with_profile_arg=False, **HELD), CASE).to_dict()
        self.assertEqual(d["limitations"], legacy)
        self.assertEqual(d["labels"]["not_verified"], list(NOT_VERIFIED))

    def test_non_default_profile_replaces_only_the_third_note(self):
        nv = NOT_VERIFIED + M.HIGH_DISCLOSURES
        d = present(f1(profile=identity(M.HIGH), extra_nv=M.HIGH_DISCLOSURES, **HELD), CASE).to_dict()
        lim = d["limitations"]
        self.assertEqual(lim[:-1], list(nv) + list(M.LEGACY_APP_NOTES[:2]), "F1 strings verbatim and the first two notes unchanged")
        self.assertEqual(len(lim), len(nv) + 3)
        self.assertNotEqual(lim[-1], M.LEGACY_APP_NOTES[2])
        self.assertTrue(lim[-1].startswith("Application note:"))
        self.assertFalse(any("100.00 USD" in s for s in lim), lim)
        self.assertEqual(d["labels"]["not_verified"], list(nv))
        for s in M.HIGH_DISCLOSURES:
            self.assertIn(s, lim)

    def test_legacy_third_note_still_the_pre_m12_text(self):
        self.assertIn("100.00 USD", M.LEGACY_APP_NOTES[2])


class RequestForwarding(unittest.TestCase):
    """The application forwards profile/case_reference to F1 unvalidated, using only a profile id and synthetic fixtures."""

    def capture(self, spec: dict, call: str = "process_refund"):
        import refund_desk.desk as desk

        seen = []

        def fake(request):
            seen.append(request)
            return f1(profile=None, **HELD)

        target = "dispose_refund" if call == "process_refund" else "reconcile_refund"
        with S.tempdir("m12-u-") as td, S.tempdir("m12-u-stack-") as fake_stack, mock.patch.object(desk, target, fake):
            d = getattr(desk, call)(M.make_case(spec), S.make_config(Path(fake_stack), Path(td))).to_dict()
        self.assertEqual(len(seen), 1)
        return seen[0], d

    def test_omitted_is_historical(self):
        req, d = self.capture(M.A1)
        self.assertIsNone(req.profile)
        self.assertIsNone(req.proposal.case_reference)
        self.assertIsNone(d["requested_profile"])

    def test_high_forwards_profile_and_case_reference(self):
        for call in ("process_refund", "reconcile_case"):
            with self.subTest(call=call):
                req, d = self.capture(M.A2, call)
                self.assertEqual(req.profile, M.HIGH)
                self.assertEqual(req.proposal.case_reference, "CASE-M12-0001")
                self.assertEqual(req.proposal.customer_id, M.C2)
                self.assertEqual(d["requested_profile"], M.HIGH)

    def test_arbitrary_values_are_not_validated_by_the_application(self):
        for spec in (M.B1, dict(M.A2, profile="", case_reference="  "), dict(M.A1, profile="any thing", case_reference="x" * 200)):
            with self.subTest(profile=spec["profile"]):
                req, d = self.capture(spec)
                self.assertEqual(req.profile, spec["profile"])
                self.assertEqual(req.proposal.case_reference, spec["case_reference"])
                self.assertEqual(d["requested_profile"], spec["profile"])

    def test_legacy_refund_case_construction_and_new_trailing_defaults(self):
        import dataclasses

        from refund_desk import RefundCase

        c = RefundCase("id", "t", "c", 1.0, "r")
        self.assertIsNone(c.profile)
        self.assertIsNone(c.case_reference)
        names = [f.name for f in dataclasses.fields(RefundCase)]
        self.assertEqual(names[:7], ["case_id", "tenant_id", "customer_account", "amount", "reason", "currency", "authority"])
        self.assertEqual(names[7:], ["profile", "case_reference"])

    def test_fail_closed_keeps_requested_profile(self):
        import refund_desk.desk as desk

        def boom(*a, **k):
            raise RuntimeError("synthetic F1 failure")

        with S.tempdir("m12-u-fc-") as td, S.tempdir("m12-u-fc-stack-") as fake, mock.patch.object(desk, "dispose_refund", boom):
            d = desk.process_refund(M.make_case(M.A2), S.make_config(Path(fake), Path(td))).to_dict()
        self.assertEqual(d["outcome"], "uncertain")
        self.assertEqual(d["requested_profile"], M.HIGH)
        self.assertIsNone(d["profile"])
        self.assertEqual(d["permitted_next_actions"], ["reconcile"])

    def test_fail_closed_failure_result_via_cli_keeps_requested_profile(self):
        with S.tempdir("m12-u-cli-") as td:
            p = S.run_cli(M.cli_args("process", M.A2, Path(td)), root=None)  # no stack root -> failed (exit 1), JSON only
            self.assertEqual(p.returncode, 1, (p.stdout, p.stderr))
            d = json.loads(p.stdout)
            self.assertEqual(d["outcome"], "failed")
            self.assertEqual(d["requested_profile"], M.HIGH)
            self.assertIsNone(d["profile"])
            p = S.run_cli(M.cli_args("process", M.A1, Path(td)), root=None)
            self.assertIsNone(json.loads(p.stdout)["requested_profile"])


class CliParser(unittest.TestCase):
    def parser(self):
        import refund_desk.cli as cli

        return cli._parser()

    BASE = ["process", "--case-id", "x", "--tenant", "t", "--customer-account", "c", "--amount", "1", "--reason", "r", "--state-dir", "/tmp/x"]

    def action(self, p, flag):
        return next((a for a in p._actions if flag in a.option_strings), None)

    def test_profile_and_case_reference_accepted(self):
        p = self.parser()
        a = p.parse_args(self.BASE + ["--profile", "refund-high-v1", "--case-reference", "CASE-1"])
        self.assertEqual(a.profile, "refund-high-v1")
        self.assertEqual(a.case_reference, "CASE-1")
        a = p.parse_args(self.BASE)
        self.assertIsNone(a.profile)
        self.assertIsNone(a.case_reference)

    def test_profile_is_not_restricted_by_choices(self):
        p = self.parser()
        self.assertIsNone(self.action(p, "--profile").choices)
        self.assertEqual(p.parse_args(self.BASE + ["--profile", "refund-ghost-v1"]).profile, "refund-ghost-v1")
        self.assertIsNone(self.action(p, "--case-reference").choices)

    def test_no_manifest_path_grant_policy_or_fault_option(self):
        banned = ("manifest", "path", "grant", "policy", "fault", "inject", "simulate")
        opts = [o for a in self.parser()._actions for o in a.option_strings]
        self.assertIn("--profile", opts)
        self.assertIn("--case-reference", opts)
        for o in opts:
            self.assertFalse(any(b in o.lower().replace("default", "") for b in banned), o)
        text = (lambda r: (r.stdout + r.stderr).lower())(S.run_cli(["--help"], root=None))
        self.assertFalse(any(b in text for b in ("--manifest", "--policy", "--grant", "--fault", "--inject", "--simulate")), text)


if __name__ == "__main__":
    unittest.main()
