from __future__ import annotations

import dataclasses
import importlib.util
import multiprocessing as mp
from pathlib import Path
import time

import pytest

ROOT = Path(__file__).resolve().parents[5]
HARNESS = ROOT / "development/scenarios/customer_refunds/connected/handoff/connected_handoff.py"
spec = importlib.util.spec_from_file_location("o5_e_a_connected_handoff", HARNESS)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

UP = m.UP
h = m.h


def _connected_authorized(tmp_path):
    proposal, resolver, flow, destination = m.tenant_case(tmp_path)
    manifest_proposal = m.manifest_side_proposal(proposal)
    assert UP["manifest_digest"](UP["manifest_model"]) == proposal.manifest_digest
    assert UP["payload_digest"](manifest_proposal.payload) == manifest_proposal.payload_commitment
    assert UP["proposal_mismatches"](UP["manifest_model"], manifest_proposal) == []

    decision = m.decide_with_trusted_owner(flow, proposal)
    assert decision.result == "authorized", decision.reasons
    executor, claim, envelope = m.provision_connected(
        proposal, flow, destination, decision
    )
    return proposal, resolver, flow, destination, decision, executor, claim, envelope


def test_exact_pins_and_missing_authenticated_grant_hold_before_runtime_dispatch(tmp_path):
    assert m._head(UP["manifest_repo"]) == m.ACTION_MANIFEST_PIN
    assert m._head(UP["control_repo"]) == m.CONTROL_PLANE_PIN
    assert m._head(UP["runtime_repo"]) == m.EXECUTION_RUNTIME_PIN

    proposal, _, flow, destination = m.tenant_case(tmp_path, with_grant=False)
    decision = m.decide_with_trusted_owner(flow, proposal)
    assert decision.result == "hold"
    assert "issued_grant_missing" in decision.reasons
    assert decision.binding is None

    # The actual Control Plane handoff refuses to materialize/provision a claim
    # from the persisted HOLD. No claim, effect, or attempt identifier is invented.
    executor = UP["Executor"](
        workflow=flow,
        destination=destination,
        policy=m.runtime_policy(
            UP["ExecutionOperation"](
                actor=proposal.actor,
                principal=proposal.principal,
                institution_id=h.INSTITUTION,
                authority_domain="customer-refunds",
                manifest_id=proposal.manifest_id,
                manifest_version=proposal.manifest_version,
                manifest_digest=proposal.manifest_digest,
                proposal_commitment="hold:no-binding",
                action_id=proposal.action_id,
                adapter_id=proposal.adapter_id,
                target=proposal.target,
                payload=proposal.payload,
                payload_commitment=proposal.payload_commitment,
                requested_permissions=tuple(proposal.requested_permissions),
                amount=proposal.amount,
                unit=proposal.unit,
                effects=proposal.effects,
                authority_context_id=proposal.authority_context_ref,
                requirement_id=proposal.requirement_id,
                grant_id="hold:no-grant",
                grant_revision="hold",
                effective_max_effects=1,
                tenant_id=proposal.tenant_id,
            )
        ),
    )
    with pytest.raises(PermissionError, match="decision is not authorized"):
        executor.provision_claim(proposal=proposal, decision=decision, now=h.NOW)

    observation = destination.observe(decision.effect_id)
    assert observation["effect_id"] == decision.effect_id
    assert observation["state"] == "absent"
    assert m.effect_rows(destination) == []
    assert m.attempt_rows(destination) == []


def test_unauthenticated_owner_cannot_even_create_a_control_plane_decision(tmp_path):
    proposal, _, flow, destination = m.tenant_case(
        tmp_path, with_grant=True, trusted_owner=False
    )
    with pytest.raises(PermissionError, match="trusted owner resolver required"):
        m.decide_with_trusted_owner(flow, proposal)
    assert flow.records.load().decisions == []
    assert m.effect_rows(destination) == []
    assert m.attempt_rows(destination) == []


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        ("tenant", "tenant_id"),
        ("amount", "amount"),
        ("payload", "operation_commitment"),
    ],
)
def test_connected_runtime_rejects_tenant_and_request_substitution(tmp_path, mutation, needle):
    _, _, _, destination, decision, executor, claim, envelope = _connected_authorized(
        tmp_path
    )
    op = envelope.operation
    if mutation == "tenant":
        changed_op = dataclasses.replace(op, tenant_id="tenant-beta")
    elif mutation == "amount":
        changed_op = dataclasses.replace(op, amount=op.amount + 1.0)
    else:
        changed_payload = dict(op.payload)
        changed_payload["refund_reason"] = "changed-after-handoff"
        changed_op = dataclasses.replace(op, payload=changed_payload)
    changed = dataclasses.replace(envelope, operation=changed_op)

    result = executor.execute(envelope=changed, claim_id=claim.claim_id)
    assert result.status == "denied"
    assert result.attempted is False
    assert result.attempt_id is None
    assert needle in (result.error or "")
    assert result.decision_id == decision.decision_id
    assert result.effect_id == decision.effect_id
    assert destination.claim_state(claim.claim_id) == "issued"
    assert m.effect_rows(destination) == []
    assert m.attempt_rows(destination) == []


def test_connected_approval_withdrawal_after_handoff_refuses_without_effect(tmp_path):
    _, _, _, destination, decision, executor, claim, envelope = _connected_authorized(
        tmp_path
    )
    approval_ref = claim.approval_state[0].approval_ref
    destination.set_approval_status(approval_ref, status="revoked")

    result = executor.execute(envelope=envelope, claim_id=claim.claim_id)
    assert result.status == "denied"
    assert result.attempted is False
    assert result.attempt_id is None
    assert "approval state invalid" in (result.error or "")
    assert result.decision_id == decision.decision_id
    assert result.effect_id == decision.effect_id
    assert destination.claim_state(claim.claim_id) == "issued"
    assert m.effect_rows(destination) == []
    assert m.attempt_rows(destination) == []


def test_connected_policy_change_after_handoff_refuses_without_effect(tmp_path):
    _, _, _, destination, decision, executor, claim, envelope = _connected_authorized(
        tmp_path
    )
    policy_ref = claim.policy_state[0].ref
    destination.set_policy_state(policy_ref, version="2.0")

    result = executor.execute(envelope=envelope, claim_id=claim.claim_id)
    assert result.status == "denied"
    assert result.attempted is False
    assert result.attempt_id is None
    assert "policy state invalid" in (result.error or "")
    assert result.decision_id == decision.decision_id
    assert result.effect_id == decision.effect_id
    assert destination.claim_state(claim.claim_id) == "issued"
    assert m.effect_rows(destination) == []
    assert m.attempt_rows(destination) == []


def test_connected_duplicate_is_suppressed_and_runtime_generates_attempt_identity(tmp_path):
    _, _, _, destination, decision, executor, claim, envelope = _connected_authorized(
        tmp_path
    )
    assert envelope.attempt_id is None
    assert claim.decision_id == decision.decision_id == envelope.decision_id
    assert claim.effect_id == decision.effect_id == envelope.effect_id

    first = executor.execute(envelope=envelope, claim_id=claim.claim_id)
    assert first.status == "executed"
    assert first.attempted is True
    assert first.attempt_id is not None
    assert first.decision_id == decision.decision_id
    assert first.effect_id == decision.effect_id
    rows_after_first = m.attempt_rows(destination)
    assert [row["attempt_id"] for row in rows_after_first] == [first.attempt_id]
    assert len(m.effect_rows(destination)) == 1

    duplicate = executor.execute(envelope=envelope, claim_id=claim.claim_id)
    assert duplicate.status == "denied"
    assert duplicate.attempted is False
    assert duplicate.attempt_id is None
    assert m.attempt_rows(destination) == rows_after_first
    assert len(m.effect_rows(destination)) == 1


class _BlockingDestination(UP["Destination"]):
    def __init__(self, root, *, reached):
        super().__init__(root, clock=lambda: h.NOW)
        self._reached = reached

    def _transaction_stage(self, stage: str) -> None:
        if stage == "after_begin":
            self._reached.set()
            time.sleep(60)


def _blocked_connected_worker(root, envelope, claim_id, reached):
    destination = _BlockingDestination(Path(root), reached=reached)
    executor = UP["Executor"](
        workflow=object(),
        destination=destination,
        policy=m.runtime_policy(envelope.operation),
    )
    executor.execute(envelope=envelope, claim_id=claim_id)


def test_connected_local_cancellation_before_commit_leaves_no_attempt_or_effect(tmp_path):
    _, _, _, destination, decision, _, claim, envelope = _connected_authorized(
        tmp_path
    )
    ctx = mp.get_context("spawn")
    reached = ctx.Event()
    proc = ctx.Process(
        target=_blocked_connected_worker,
        args=(str(tmp_path / "runtime"), envelope, claim.claim_id, reached),
    )
    proc.start()
    assert reached.wait(10)

    proc.terminate()
    proc.join(10)
    assert proc.exitcode is not None
    assert proc.is_alive() is False

    reopened = UP["Destination"](tmp_path / "runtime", clock=lambda: h.NOW)
    assert reopened.claim_state(claim.claim_id) == "issued"
    assert m.effect_rows(reopened) == []
    assert m.attempt_rows(reopened) == []

    recovery = reopened.reconcile_claim(
        claim.claim_id, UP["snapshot_envelope"](envelope)
    )
    assert recovery["status"] == "hold"
    assert recovery["retry_eligible"] is False
    assert recovery["effect_id"] == decision.effect_id
