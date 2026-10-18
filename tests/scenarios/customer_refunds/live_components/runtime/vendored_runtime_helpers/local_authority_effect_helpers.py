# Vendored helper code. NOT a runtime module and not evidence about the runtime.
# Source: cogno-us/cognous-execution-runtime @ da9f52900ee2596dab087ec6c249ba84915d2b13 (the orchestrator's accepted runtime pin), tests/test_local_authority_effect.py, lines 1-12 and 20-209.
# Source file sha256: 7160700d4b25b7d8c2f2f57caf3cbf3ce7bbf3b509112445b7af69af60a6864b
# Why: runtime 2ee2e525 moved its tests to cognous-stack-qualification, so a newer runtime checkout no longer has this module and
# test_actual_runtime.py (suite O5-D-B) failed at collection (gap report F-6). test_actual_runtime.py imports the runtime's own copy
# when it exists (pinned default, unchanged) and falls back to this copy otherwise.
# Modifications: the module-level pytestmark skip block (source lines 13-19) is omitted; nothing else.
from __future__ import annotations

import dataclasses
import json
import multiprocessing as mp
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.local_authority_effect import (
    AtomicAuthorityEffectDestination,
    AtomicLocalControlPlaneExecutor,
)
from engine.safe_executor import (
    DurableRefundDestination,
    ExecutionEnvelope,
    ExecutionOperation,
    LocalExecutionPolicy,
    snapshot_envelope,
)

BASE = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)
INSTITUTION = "urn:cognous:institution:test"
DOMAIN = "refunds"
GRANT = "urn:cognous:grant:atomic"
APPROVAL = "urn:cognous:approval:atomic"
POLICY_REF = "urn:cognous:policy:atomic"
EVIDENCE = "urn:cognous:evidence:atomic"


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def operation(*, effect_no=1, grant=GRANT):
    payload = {"reason": "duplicate", "effect_no": effect_no}
    from engine.safe_executor import commitment
    return ExecutionOperation(
        actor="urn:cognous:identity:agent",
        principal="urn:cognous:principal:service",
        institution_id=INSTITUTION,
        authority_domain=DOMAIN,
        manifest_id="manifest-1",
        manifest_version="1.1",
        manifest_digest="sha256:" + "1" * 64,
        proposal_commitment="sha256:" + "2" * 64,
        action_id="urn:cognous:action:refund",
        adapter_id="urn:cognous:adapter:refund",
        target=f"urn:cognous:synthetic-account:{effect_no}",
        payload=payload,
        payload_commitment=commitment(payload),
        requested_permissions=("refund.issue",),
        amount=50.0,
        unit="USD",
        effects=1,
        authority_context_id="urn:cognous:authority-context:test",
        requirement_id="urn:cognous:requirement:test",
        grant_id=grant,
        grant_revision="1",
        effective_max_effects=1,
    )


def envelope(*, effect_no=1, effect_id=None, grant=GRANT):
    op = operation(effect_no=effect_no, grant=grant)
    return ExecutionEnvelope(
        version="0.2.0",
        decision_id=f"decision-{effect_no}",
        effect_id=effect_id or f"effect-{effect_no}",
        operation=op,
    )


def make_claim(env, *, claim_id="claim-1", budget_id="budget-1", max_effects=1,
               expires_at=None):
    from agent_control_plane.bounded import commitment
    from agent_control_plane.local_authority_effect import (
        LOCAL_AUTHORITY_EFFECT_PROFILE,
        LocalExecutionClaim,
    )

    snap = snapshot_envelope(env)
    approval_state = [{
        "approval_ref": APPROVAL,
        "role_id": "urn:cognous:role:reviewer",
        "approver": "urn:cognous:principal:human",
        "status": "active",
        "grant_id": snap.operation.grant_id,
        "grant_revision": snap.operation.grant_revision,
        "proposal_commitment": snap.operation.proposal_commitment,
        "policy_versions": [{"ref": POLICY_REF, "version": "1"}],
        "observed_at": BASE.isoformat(),
    }]
    policy_state = [{
        "ref": POLICY_REF,
        "version": "1",
        "status": "active",
        "observed_at": BASE.isoformat(),
    }]
    evidence_state = [{
        "obligation_id": EVIDENCE,
        "source_ref": "urn:cognous:source:entitlement",
        "required": True,
        "kind": "authorization",
        "max_age_seconds": 300,
        "unknown_behavior": "hold_effect",
        "state": "current",
        "observed_at": BASE.isoformat(),
    }]
    authority_state = {
        "grant_id": snap.operation.grant_id,
        "grant_revision": snap.operation.grant_revision,
        "grant_status": "active",
        "requirement_commitment": "sha256:" + "3" * 64,
        "approvals": approval_state,
        "policies": policy_state,
        "evidence": evidence_state,
    }
    raw = {
        "profile": LOCAL_AUTHORITY_EFFECT_PROFILE,
        "claim_id": claim_id,
        "decision_id": env.decision_id,
        "effect_id": env.effect_id,
        "institution_id": snap.operation.institution_id,
        "authority_domain": snap.operation.authority_domain,
        "actor": snap.operation.actor,
        "principal": snap.operation.principal,
        "grant_id": snap.operation.grant_id,
        "grant_revision": snap.operation.grant_revision,
        "grant_status": "active",
        "manifest_id": snap.operation.manifest_id,
        "manifest_version": snap.operation.manifest_version,
        "manifest_digest": snap.operation.manifest_digest,
        "action_id": snap.operation.action_id,
        "adapter_id": snap.operation.adapter_id,
        "target": snap.operation.target,
        "payload_commitment": snap.operation.payload_commitment,
        "requested_permissions": list(snap.operation.requested_permissions),
        "amount": snap.operation.amount,
        "unit": snap.operation.unit,
        "effects": snap.operation.effects,
        "authority_context_id": snap.operation.authority_context_id,
        "requirement_id": snap.operation.requirement_id,
        "requirement_commitment": "sha256:" + "3" * 64,
        "operation_commitment": AtomicAuthorityEffectDestination._operation_commitment(snap),
        "approval_state": approval_state,
        "approval_state_commitment": commitment(approval_state),
        "policy_state": policy_state,
        "policy_state_commitment": commitment(policy_state),
        "evidence_state": evidence_state,
        "evidence_state_commitment": commitment(evidence_state),
        "authority_state_commitment": commitment(authority_state),
        "budget_id": budget_id,
        "max_effects": max_effects,
        "not_before": (BASE - timedelta(minutes=1)).isoformat(),
        "expires_at": (expires_at or (BASE + timedelta(hours=1))).isoformat(),
        "issued_at": BASE.isoformat(),
        "decision_input_commitment": None,
        "decision_input_profile_version": None,
        "source": "trusted_control_plane_workflow",
        "authorizing_by_possession": False,
    }
    raw["claim_commitment"] = commitment(raw)
    return LocalExecutionClaim.model_validate(raw)


def policy(op):
    return LocalExecutionPolicy(
        allowed_institutions=frozenset({op.institution_id}),
        allowed_authority_domains=frozenset({op.authority_domain}),
        allowed_adapters=frozenset({op.adapter_id}),
        allowed_actions=frozenset({op.action_id}),
        allowed_target_prefixes=("urn:cognous:synthetic-account:",),
        allowed_units=frozenset({"USD"}),
        max_amount=1000.0,
        max_effects=1,
    )


def setup_atomic(tmp_path, *, env=None, claim_id="claim-1", budget_id="budget-1",
                 max_effects=1, clock=None):
    clock = clock or MutableClock(BASE)
    env = env or envelope()
    destination = AtomicAuthorityEffectDestination(tmp_path, clock=clock)
    claim = make_claim(
        env, claim_id=claim_id, budget_id=budget_id, max_effects=max_effects
    )
    destination.provision_claim(claim)
    return clock, env, destination, claim


def effect_rows(destination):
    with sqlite3.connect(destination.path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM effects ORDER BY effect_id")]
