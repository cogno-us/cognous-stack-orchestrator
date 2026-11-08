"""Shared support for the M1-1 developer checks. DEVELOPMENT ONLY / SYNTHETIC / builder-lineage; not independent qualification."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import _support as S
from _support import AT, effect_rows, native_counters, require_stack, sha256_file  # noqa: F401
from orchestration.adapters.refund_disposition import (AuthorityFacts, DispositionRequest, RefundProposal, SyntheticEnvironment)

M11_FIXTURES = Path(__file__).resolve().parent / "m11_fixtures"
HIGH_AUTHORITY_ID = "urn:cognous:authority:m11-high-refund-root-1"
HIGH_TENANT = "m11-tenant"
ROUTINE_TENANT = "tenant-alpha"
HIGH_REQUIREMENT = "urn:cognous:authority-requirement:refund-high-v1"
ROUTINE_REQUIREMENT = "urn:cognous:authority-requirement:refund-routine-v1"
HIGH_ACTION = "urn:cognous:action:refund-issue-high-v1"
ROUTINE_ACTION = "urn:cognous:action:refund-issue-routine-v1"
MANIFEST_ID = "refund-integration-pilot-v1"
MANIFEST_VERSION = "1.1"
MANIFEST_DIGEST = "sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac"
REGISTRY_VERSION = "refund-profiles/0.1.0-dev"
ACCOUNT = "urn:cognous:synthetic-account:"
IDENTITY = {
    "refund-routine-v1": dict(profile_id="refund-routine-v1", action_id=ROUTINE_ACTION, requirement_id=ROUTINE_REQUIREMENT),
    "refund-high-v1": dict(profile_id="refund-high-v1", action_id=HIGH_ACTION, requirement_id=HIGH_REQUIREMENT),
}


def m11_fixture(name: str) -> dict:
    return json.loads((M11_FIXTURES / name).read_text(encoding="utf-8"))


def make_routine_request(root: Path, state_dir: Path, *, profile: str | None = None, case_reference=None, customer: str = "customer-001",
                         amount: float = 50.0, unit: str = "USD", bundle: str = "root_lineage.json", tenant: str = ROUTINE_TENANT,
                         facts_mutator=None, lineage_mutator=None, correlation: str = "m11-check") -> DispositionRequest:
    facts, lineage = S.fixture(root, "synthetic_facts.json"), S.fixture(root, bundle)
    if facts_mutator:
        facts_mutator(facts)
    if lineage_mutator:
        lineage_mutator(lineage)
    return DispositionRequest(
        proposal=RefundProposal(tenant_id=tenant, customer_id=customer, refund_reason="duplicate", amount=amount, unit=unit, case_reference=case_reference),
        authority=AuthorityFacts(authority_id=S.AUTHORITY_ID, lineage_bundle=lineage, facts=facts),
        correlation_id=correlation, evaluation_time=AT, environment=SyntheticEnvironment(stack_root=root, state_dir=state_dir), profile=profile)


def make_high_request(root: Path, state_dir: Path, *, case_reference="CASE-M11-0001", customer: str = "customer-002", amount: float = 150.0,
                      tenant: str = HIGH_TENANT, lineage: str = "high_lineage_valid.json", facts_mutator=None, lineage_mutator=None,
                      correlation: str = "m11-check", profile="refund-high-v1", unit: str = "USD", facts_name: str = "high_facts.json") -> DispositionRequest:
    facts, lin = copy.deepcopy(m11_fixture(facts_name)), copy.deepcopy(m11_fixture(lineage))
    if facts_mutator:
        facts_mutator(facts)
    if lineage_mutator:
        lineage_mutator(lin)
    return DispositionRequest(
        proposal=RefundProposal(tenant_id=tenant, customer_id=customer, refund_reason="duplicate", amount=amount, unit=unit, case_reference=case_reference),
        authority=AuthorityFacts(authority_id=HIGH_AUTHORITY_ID, lineage_bundle=lin, facts=facts),
        correlation_id=correlation, evaluation_time=AT, environment=SyntheticEnvironment(stack_root=root, state_dir=state_dir), profile=profile)


def src_text(result, kind: str) -> str | None:
    for f in result.evidence.source:
        if f.kind == kind:
            return Path(f.path).read_text(encoding="utf-8")
    return None


def assert_no_native_activity(tc: unittest.TestCase, r, n: dict, state: Path) -> None:
    tc.assertIs(r.runtime_invoked, False)
    tc.assertEqual(r.runtime_invocations, 0)
    tc.assertEqual((n["execute"], n["commit"]), (0, 0))
    tc.assertFalse(S.db_path(state).exists(), "no SQLite database file may exist")
    tc.assertEqual(effect_rows(state), [])
    tc.assertEqual(S.grant_rows(state), [])
    tc.assertEqual(r.evidence.replay_state, "not_run")


def assert_common_labels(tc: unittest.TestCase, r) -> None:
    tc.assertIs(r.labels.authenticated, False)
    tc.assertEqual(r.labels.evidence_basis, "producer_reported")
    tc.assertTrue(r.labels.nonproduction)
    tc.assertTrue(r.labels.non_authorizing)
    tc.assertEqual(r.labels.retry_permission, "not_established")
    tc.assertIs(r.effect_absence_established, False)


def assert_cleanup_ok(tc: unittest.TestCase, r) -> None:
    tc.assertTrue(r.cleanup.ok, r.cleanup)
    if r.cleanup.scratch_path is not None:
        tc.assertFalse(Path(r.cleanup.scratch_path).exists())


def expected_identity(profile_id: str):
    from orchestration.adapters.refund_disposition import ProfileIdentity
    return ProfileIdentity(registry_version=REGISTRY_VERSION, manifest_id=MANIFEST_ID, manifest_version=MANIFEST_VERSION,
                           manifest_digest=MANIFEST_DIGEST, **IDENTITY[profile_id])


def state_dir_ctx(prefix: str):
    return tempfile.TemporaryDirectory(prefix=prefix)


def make_high_profile_routine_facts_request(root: Path, state_dir: Path, *, high_lineage: bool, correlation: str = "m11-check") -> DispositionRequest:
    """B8a (high_lineage=True): high profile + routine facts + HIGH lineage. B8b (False): high profile + routine facts + routine lineage."""
    import dataclasses
    req = make_routine_request(root, state_dir, profile="refund-high-v1", case_reference="CASE-M11-0008", customer="customer-002", amount=150.0,
                               correlation=correlation)
    if high_lineage:
        req = dataclasses.replace(req, authority=AuthorityFacts(authority_id=HIGH_AUTHORITY_ID, lineage_bundle=copy.deepcopy(m11_fixture("high_lineage_valid.json")),
                                                                 facts=req.authority.facts))
    return req


def assert_manifest_bindings(tc: unittest.TestCase, r) -> None:
    """Structure-aware: CP authorized decision binding, Runtime export operation and Replay bundle records all carry the result.profile identity."""
    p = r.profile
    tc.assertIsNotNone(p)
    want = {"manifest_id": p.manifest_id, "manifest_version": p.manifest_version, "manifest_digest": p.manifest_digest,
            "action_id": p.action_id, "requirement_id": p.requirement_id}
    cp = json.loads(src_text(r, "cp_run_record"))
    auth = [d for d in cp["decisions"] if d["result"] == "authorized"]
    tc.assertTrue(auth)
    for d in auth:
        tc.assertEqual({k: d["binding"][k] for k in want}, want)
    export_text = src_text(r, "runtime_export")
    tc.assertIsNotNone(export_text, "runtime export must be present")
    op = json.loads(export_text)["execution_envelope"]["operation"]
    tc.assertEqual({k: op[k] for k in want}, want)
    if r.evidence.replay is not None:
        bundle = json.loads(Path(r.evidence.replay.path).read_text(encoding="utf-8"))
        hits = 0
        for rec in bundle["records"]:
            data = rec.get("data", {})
            for holder in (data, data.get("binding"), data.get("operation")):
                if isinstance(holder, dict) and "manifest_digest" in holder:
                    tc.assertEqual({k: holder[k] for k in want}, want)
                    hits += 1
        tc.assertGreaterEqual(hits, 3)  # decision record, CP binding record and Runtime operation record


class PolicySpy:
    """Captures the keyword arguments of every native LocalExecutionPolicy construction made through the Runtime stack."""

    def __init__(self, root: Path):
        from unittest import mock
        from orchestration.adapters.refund_disposition.stack import load_stack
        self.S = load_stack(root)
        self.seen: list[dict] = []
        real = self.S.engine_safe_executor.LocalExecutionPolicy

        def spy(*a, **k):
            self.seen.append(k)
            return real(*a, **k)
        self._patch = mock.patch.object(self.S.engine_safe_executor, "LocalExecutionPolicy", spy)

    def __enter__(self):
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


def manifest_action(manifest: dict, action_id: str) -> dict:
    return next(a for a in manifest["actions"] if a["action_id"] == action_id)


def expected_policy(manifest: dict, action_id: str) -> dict:
    a = manifest_action(manifest, action_id)
    tool = next(t for t in manifest["tools"] if t["tool_name"] == a["tool_name"])
    ctx, lim = a["authority_context"], a["effect_limits"]
    return dict(max_amount=float(lim["max_amount"]), max_effects=lim["max_effects"], target_match="exact",
                allowed_target_prefixes=(a["target_policy"]["allowed_targets"][0],), allowed_units=frozenset({lim["unit"]}),
                allowed_institutions=frozenset({ctx["institution_id"]}), allowed_authority_domains=frozenset({ctx["authority_domain"]}),
                allowed_adapters=frozenset({tool["adapter_id"]}), allowed_actions=frozenset({action_id}))


def assert_policy_equals(tc: unittest.TestCase, got: dict, want: dict) -> None:
    tc.assertEqual(float(got["max_amount"]), want["max_amount"])
    tc.assertEqual(got["max_effects"], want["max_effects"])
    tc.assertEqual(got["target_match"], "exact")
    tc.assertEqual(tuple(got["allowed_target_prefixes"]), want["allowed_target_prefixes"])
    for k in ("allowed_units", "allowed_institutions", "allowed_authority_domains", "allowed_adapters", "allowed_actions"):
        tc.assertEqual(set(got[k]), set(want[k]), k)


def load_pinned_manifest(root: Path) -> dict:
    return json.loads((root / "control_plane/tests/fixtures/refund_integration_v1_1.manifest.json").read_text(encoding="utf-8"))
