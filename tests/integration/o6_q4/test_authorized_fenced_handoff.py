"""Synthetic O5-E handoff -> actual O6 GAX fence -> Runtime -> revocation evidence.

All sources must be present at explicit accepted SHAs; no local source surrogate.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
Q3 = ROOT / "tests/integration/o6_q3/test_three_profile_trace.py"
HANDOFF = ROOT / "development/scenarios/customer_refunds/connected/handoff/connected_handoff.py"


def _import(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Exact-source checks and actual profile imports happen in Q3, without substitutes.
q3 = _import(Q3, "o6_q4_actual_profile_imports")
assert os.environ["COGNOUS_O6_Q2_RUNTIME_CANDIDATE"] == (
    "1b0a9e32d010797711004ae612051a277b07912a"
)
handoff = _import(HANDOFF, "o6_q4_actual_o5e_handoff")
from engine.revocation_closeout import OrderingEvidence, RevocationCloseoutStore
from experiments.odex_gax_imx_reference.generation_fence import (
    GenerationFenceClaim, GenerationFenceRefusal, LineageGenerationFence
)


class ClaimedRuntimeCommit:
    """Test-owned adapter: invoked inside actual GAX fence, calls actual Runtime."""
    def __init__(self, executor, envelope, claim_id):
        self.executor = executor
        self.envelope = envelope
        self.claim_id = claim_id
        self.calls = 0

    def commit(self, snapshot, *, simulate=None):
        assert snapshot.effect_id == self.envelope.effect_id
        self.calls += 1
        return self.executor.execute(envelope=self.envelope, claim_id=self.claim_id)


def _fence(tmp_path, effect_id):
    path = tmp_path / "lineage.sqlite"
    fence = LineageGenerationFence(path)
    conversation = "conversation:refund-actual-handoff"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE heads(conversation_id TEXT PRIMARY KEY, state_version INTEGER NOT NULL)")
        conn.execute("INSERT INTO heads VALUES (?,?)", (conversation, 5))
    return path, fence, conversation


def _decision(tmp_path):
    proposal, resolver, flow, destination = handoff.tenant_case(tmp_path)
    manifest_proposal = handoff.manifest_side_proposal(proposal)
    assert handoff.UP["manifest_digest"](handoff.UP["manifest_model"]) == proposal.manifest_digest
    assert handoff.UP["proposal_mismatches"](handoff.UP["manifest_model"], manifest_proposal) == []
    decision = handoff.decide_with_trusted_owner(flow, proposal)
    assert decision.result == "authorized" and decision.binding is not None
    executor, claim, envelope = handoff.provision_connected(proposal, flow, destination, decision)
    assert handoff.UP["verify_local_execution_claim"](claim)
    assert envelope.effect_id == claim.effect_id == decision.effect_id
    return proposal, flow, destination, decision, executor, claim, envelope


def _dispatch(tmp_path, values, runtime_adapter, effect_id, generation=5, override=None):
    custody = q3._authenticated_digest(values, raw_override=override)
    if not custody.accepted:
        return SimpleNamespace(status="hold", attempted=False, reason=custody.reason)
    assert custody.assurance == "non_authorizing_digest_custody"
    path, fence, conversation = _fence(tmp_path, effect_id)
    claim = GenerationFenceClaim(
        conversation_id=conversation, effect_id=effect_id, generation=generation
    )
    result = fence.commit_if_current(
        runtime_adapter, SimpleNamespace(effect_id=effect_id), claim
    )
    return result


def test_issued_claim_passes_generation_fence_and_retains_original_attempt(tmp_path):
    values = q3._custody_evidence()
    _, _, destination, decision, executor, claim, envelope = _decision(tmp_path)
    adapter = ClaimedRuntimeCommit(executor, envelope, claim.claim_id)
    result = _dispatch(tmp_path, values, adapter, envelope.effect_id)
    assert result.status == "executed" and result.attempted
    assert result.attempt_id
    assert adapter.calls == 1
    assert len(handoff.effect_rows(destination)) == 1
    assert [r["attempt_id"] for r in handoff.attempt_rows(destination)] == [result.attempt_id]

    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    ledger = RevocationCloseoutStore(tmp_path / "revoke", clock=lambda: now)
    ledger.record_item(
        effect_id=envelope.effect_id, attempt_id=result.attempt_id,
        decision_id=decision.decision_id, grant_id=claim.grant_id,
        grant_revision=claim.grant_revision, state="executing",
        ordering=OrderingEvidence(5, "test:runtime-effect-before-revocation"),
    )
    rows = ledger.record_revocation(
        grant_id=claim.grant_id, grant_revision=claim.grant_revision,
        revocation=OrderingEvidence(6, "test:revoked"),
        owner="synthetic-operator", deadline=now+timedelta(hours=1),
        reconciliation_ref="test:original-attempt",
    )
    assert len(rows) == 1 and rows[0].status == "in_doubt"
    assert rows[0].effect_id == result.effect_id
    unknown = ledger.close_original_attempt(
        attempt_id=result.attempt_id, observation_state="unknown",
        observation=OrderingEvidence(7, "test:unknown-observation"),
        observation_ref="test:unknown-observation",
    )
    assert unknown.effect_id == envelope.effect_id
    assert not unknown.closed and not unknown.retry_eligible
    assert RevocationCloseoutStore(tmp_path / "revoke").closeout(result.attempt_id).retry_eligible is False
    assert len(handoff.effect_rows(destination)) == 1
    assert len(handoff.attempt_rows(destination)) == 1


def test_missing_grant_cannot_create_claim_or_fenced_effect(tmp_path):
    proposal, _, flow, destination = handoff.tenant_case(tmp_path, with_grant=False)
    decision = handoff.decide_with_trusted_owner(flow, proposal)
    assert decision.result == "hold" and decision.binding is None
    with pytest.raises(PermissionError):
        handoff.envelope_from_connected_handoff(proposal, decision, None)
    assert handoff.effect_rows(destination) == []
    assert handoff.attempt_rows(destination) == []


def test_digest_mutation_and_supersession_prevent_runtime_effect(tmp_path):
    values = q3._custody_evidence()
    _, _, destination, _, executor, claim, envelope = _decision(tmp_path)
    adapter = ClaimedRuntimeCommit(executor, envelope, claim.claim_id)
    refused = _dispatch(tmp_path, values, adapter, envelope.effect_id, override=b"rewritten-policy")
    assert refused.status == "hold" and refused.reason == "authority_digest_mismatch"
    assert adapter.calls == 0
    path, fence, conversation = _fence(tmp_path / "superseded", envelope.effect_id)
    with pytest.raises(GenerationFenceRefusal, match="superseded_lineage_generation"):
        fence.commit_if_current(
            adapter, SimpleNamespace(effect_id=envelope.effect_id),
            GenerationFenceClaim(conversation_id=conversation, effect_id=envelope.effect_id, generation=4)
        )
    assert fence.refusals(conversation)[0]["effect_id"] == envelope.effect_id
    assert LineageGenerationFence(path).counters(conversation)["total_refusals"] == 1
    assert adapter.calls == 0
    assert handoff.effect_rows(destination) == []


def test_withdrawn_approval_is_runtime_refusal_after_valid_custody_and_fence(tmp_path):
    values = q3._custody_evidence()
    _, _, destination, decision, executor, claim, envelope = _decision(tmp_path)
    destination.set_approval_status(claim.approval_state[0].approval_ref, status="revoked")
    adapter = ClaimedRuntimeCommit(executor, envelope, claim.claim_id)
    result = _dispatch(tmp_path, values, adapter, envelope.effect_id)
    assert result.status == "denied" and result.attempted is False
    assert result.attempt_id is None
    assert result.effect_id == decision.effect_id
    assert "approval state invalid" in (result.error or "")
    assert adapter.calls == 1
    assert handoff.effect_rows(destination) == []
    assert handoff.attempt_rows(destination) == []
