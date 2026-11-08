"""Stack-independent contract tests for the F1 library (request validation, status mapping, cleanup honesty, pins, scope).
DEVELOPMENT ONLY / SYNTHETIC. Runs without an assembled stack."""
from __future__ import annotations

import ast
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import _support as S  # noqa: F401  (sets sys.path)
from orchestration.adapters.refund_disposition import contract, dispose as D, workspace
from orchestration.adapters.refund_disposition import (AuthorityFacts, DispositionRequest, RefundProposal, SyntheticEnvironment, dispose_refund,
                                                       reconcile_refund)

PKG = Path(contract.__file__).resolve().parent
REPO = PKG.parents[2]


def req(**over):
    base = dict(proposal=RefundProposal(tenant_id="t", customer_id="c", refund_reason="r", amount=5.0),
                authority=AuthorityFacts("a", {"origins": [{"institution_id": "i", "authority_domain": "d"}]},
                                         {"tenant_id": "t", "context_ref": "urn:x", "approval": {}}), correlation_id="c1",
                evaluation_time=datetime(2026, 10, 5, 19, tzinfo=timezone.utc),
                environment=SyntheticEnvironment(Path("/nonexistent-stack"), Path("/nonexistent-state")))
    base.update(over)
    return DispositionRequest(**base)


class RequestValidation(unittest.TestCase):
    def test_valid_shape_has_no_problems(self):
        self.assertEqual(contract.request_problems(req()), [])

    def test_refused_before_any_native_call(self):
        bad = [req(correlation_id="../x"), req(evaluation_time=datetime(2026, 1, 1)), req(proposal=RefundProposal("t", "c", "r", -1.0)),
               req(proposal=RefundProposal("t", "c", "r", 5.0, unit="usd")), req(proposal=RefundProposal("other", "c", "r", 5.0)),
               req(authority=AuthorityFacts("a", {"origins": [{}]}, {"tenant_id": "t", "context_ref": "u", "approval": {}})),
               req(authority=AuthorityFacts("a", {"origins": [{"institution_id": "i", "authority_domain": "d"}]}, {"tenant_id": "t"}))]
        for r in bad:
            res = dispose_refund(r)
            self.assertEqual(res.disposition, "refused", r)
            self.assertEqual(res.refusal.code, "request_invalid")
            self.assertFalse(res.runtime_invoked)
            self.assertEqual(res.labels.retry_permission, "not_established")
        self.assertEqual(dispose_refund("not a request").disposition, "refused")

    def test_unpinned_stack_is_a_structured_refusal_not_an_exception(self):
        with tempfile.TemporaryDirectory() as td:
            res = dispose_refund(req(environment=SyntheticEnvironment(Path(td), Path(td) / "state")))
        self.assertEqual(res.disposition, "refused")
        self.assertTrue(res.refusal.code.startswith("stack_"), res.refusal)
        self.assertFalse(res.runtime_invoked)
        self.assertTrue(res.cleanup.ok)

    def test_reconcile_without_prior_record_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(reconcile_refund(req(environment=SyntheticEnvironment(Path(td), Path(td) / "s"))).disposition, "refused")


class StatusMapping(unittest.TestCase):
    def test_unknown_is_never_success_and_only_established_applied_is_executed(self):
        m = D.map_runtime
        self.assertEqual(m("executed", "applied", True, True), "executed")
        self.assertEqual(m("executed", "applied", False, True), "unknown")  # executed without acknowledgment is not trusted
        self.assertEqual(m("reconciled", "applied", False, False), "executed")
        self.assertEqual(m("observed", "applied", False, False), "executed")
        for status in ("unknown", "partial", "something_new"):
            self.assertEqual(m(status, "applied", True, True), "unknown")
        for state in ("absent", "unknown", "partial", None):
            self.assertEqual(m("reconciled", state, False, False), "unknown")  # absence never becomes success or failure
            self.assertEqual(m("observed", state, False, False), "unknown")
        self.assertEqual(m("failed", "unknown", False, False), "failed")
        self.assertEqual(m("denied", "unknown", False, False), "denied")

    def test_result_contract_constants(self):
        self.assertEqual(contract.RETRY_PERMISSION, "not_established")
        self.assertEqual(set(contract.DISPOSITIONS), {"executed", "held", "denied", "refused", "unknown", "failed"})
        r = D._result(req(), "unknown")
        self.assertIs(r.effect_absence_established, False)
        self.assertEqual(r.next_step, "reconcile_read_only")
        self.assertEqual(r.labels.evidence_basis, "producer_reported")
        self.assertIs(r.labels.authenticated, False)


class CleanupHonesty(unittest.TestCase):
    def test_failed_disposal_is_reported_and_unrelated_resources_survive(self):
        with tempfile.TemporaryDirectory() as td:
            unrelated = Path(td) / "unrelated"
            unrelated.mkdir()
            (unrelated / "keep.txt").write_text("keep")
            work = workspace.allocate()
            try:
                with mock.patch.object(shutil, "rmtree", side_effect=PermissionError("denied")):
                    rep = workspace.dispose(work)
                self.assertFalse(rep.ok)
                self.assertTrue(work.exists() and any("rmtree" in e for e in rep.errors))
            finally:
                shutil.rmtree(work)  # the exact path this test allocated, nothing else
            self.assertTrue((unrelated / "keep.txt").exists())
            self.assertTrue(workspace.dispose(None).ok)

    def test_symlink_in_place_of_workspace_is_refused_not_followed(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.mkdir()
            (target / "keep.txt").write_text("keep")
            link = Path(td) / "link"
            link.symlink_to(target, target_is_directory=True)
            rep = workspace.dispose(link)
            self.assertFalse(rep.ok)
            self.assertTrue((target / "keep.txt").exists())

    def test_cleanup_failure_is_surfaced_on_the_result_without_changing_the_disposition(self):
        allocated: list[Path] = []
        real_allocate = workspace.allocate

        def tracking_allocate() -> Path:
            p = real_allocate()
            allocated.append(p)
            return p

        with tempfile.TemporaryDirectory() as td:
            try:
                with mock.patch.object(D.workspace, "allocate", tracking_allocate), \
                        mock.patch.object(D.workspace, "dispose", side_effect=lambda w: contract.CleanupReport(False, str(w), ("simulated disposal failure",))):
                    res = dispose_refund(req(environment=SyntheticEnvironment(Path(td), Path(td) / "s")))
                self.assertEqual(res.disposition, "refused")  # the stack check refuses; disposition is not altered by the cleanup failure
                self.assertFalse(res.cleanup.ok)
                self.assertIn("simulated disposal failure", res.cleanup.errors)
                self.assertEqual(len(allocated), 1)
                self.assertTrue(allocated[0].exists())  # not silently reported as removed
            finally:
                for p in allocated:
                    shutil.rmtree(p)  # exactly the paths this test allocated


class ScopeAndPins(unittest.TestCase):
    def test_pins_equal_the_frozen_g3_manifest(self):
        g3 = json.loads((REPO / "tests/manual_contract/g3_refund/source_manifest.json").read_text())
        mine = json.loads((PKG / "source_pins.json").read_text())
        self.assertEqual(mine["components"], {k: v["commit"] for k, v in g3["components"].items()})

    def test_no_downstream_components_services_or_cli_are_imported(self):
        banned = {"agent_governance_evidence_pack", "cognous_verify", "http", "socket", "argparse", "click", "typer", "flask", "fastapi"}
        found = set()
        for f in PKG.glob("*.py"):
            for node in ast.walk(ast.parse(f.read_text())):
                if isinstance(node, ast.Import):
                    found.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    found.add(node.module.split(".")[0])
        self.assertFalse(found & banned, found & banned)
        self.assertFalse((PKG / "__main__.py").exists())  # library only: no CLI entrypoint

    def test_no_fault_injection_in_the_application_facing_contract(self):
        import dataclasses
        import inspect
        import orchestration.adapters.refund_disposition as pkg
        self.assertNotIn("dev_fault", {f.name for f in dataclasses.fields(DispositionRequest)})
        self.assertEqual(list(inspect.signature(pkg.dispose_refund).parameters), ["request"])
        self.assertEqual(list(inspect.signature(pkg.reconcile_refund).parameters), ["request"])
        self.assertFalse([n for n in pkg.__all__ if "fault" in n.lower() or "inject" in n.lower()])
        self.assertFalse(hasattr(contract, "DEV_FAULTS"))
        self.assertFalse((PKG / "fault_seam.py").exists())
        self.assertNotIn("simulate", (PKG / "contract.py").read_text())


if __name__ == "__main__":
    unittest.main()
