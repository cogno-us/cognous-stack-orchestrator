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
