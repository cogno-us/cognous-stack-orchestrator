from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "development/scenarios/customer_refunds/connected/contracts/trace_contract.py"
spec = importlib.util.spec_from_file_location("o5_e_c_trace_contract", MODULE)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def trace():
    return {
        "contract_version": m.CONTRACT_VERSION,
        "trajectory_id": "refund-connected-hold-001",
        "tenant_id": "merchant-demo",
        "source_revisions": deepcopy(m.SOURCE_REVISIONS),
        "request": {
            "request_id": "request-001",
            "intent_id": "intent-001",
            "tenant_id": "merchant-demo",
            "policy_ref": "policy:refund",
            "policy_version": "1",
            "policy_digest": "sha256:policy-v1",
            "approval_id": "approval-001",
        },
        "decision": {
            "decision_id": "decision-001",
            "request_id": "request-001",
            "intent_id": "intent-001",
            "tenant_id": "merchant-demo",
            "result": "HOLD",
            "reasons": ["missing_grant"],
            "policy_digest": "sha256:policy-v1",
            "grant_id": None,
            "approval_id": "approval-001",
            "approval_status": "active",
        },
        "execution_attempt": {
            "attempt_id": "attempt-001",
            "effect_id": "effect-001",
            "decision_id": "decision-001",
            "request_id": "request-001",
            "intent_id": "intent-001",
            "tenant_id": "merchant-demo",
            "state": "not_dispatched",
        },
        "evidence": {
            "evidence_id": "evidence-001",
            "request_id": "request-001",
            "decision_id": "decision-001",
            "attempt_id": "attempt-001",
            "tenant_id": "merchant-demo",
            "state": "recorded",
            "independent_effect_verification": False,
        },
        "transport": {
            "receipt_id": "receipt-001",
            "request_id": "request-001",
            "attempt_id": "attempt-001",
            "tenant_id": "merchant-demo",
            "delivery_state": "not_sent",
            "authenticity": "verified",
        },
        "settlement": {
            "observation_id": "observation-001",
            "request_id": "request-001",
            "effect_id": "effect-001",
            "tenant_id": "merchant-demo",
            "state": "not_observed",
            "independent": False,
        },
    }


def test_valid_hold_preserves_separate_stage_identities_and_interfaces():
    t = m.validate_trace(trace())
    ids = [t["request"]["request_id"], t["decision"]["decision_id"], t["execution_attempt"]["attempt_id"], t["evidence"]["evidence_id"], t["transport"]["receipt_id"], t["settlement"]["observation_id"]]
    assert len(ids) == len(set(ids))
    p = m.interface_projection(t)
    assert p["a_control_runtime"]["decision"]["result"] == "HOLD"
    assert p["b_replay_evidence"]["settlement"]["state"] == "not_observed"


def test_exact_o5_d_source_mapping_is_required():
    t = trace(); t["source_revisions"]["replay"] = "local-fixture"
    with pytest.raises(m.ContractError, match="source_revision_mismatch"):
        m.validate_trace(t)


def test_missing_grant_without_hold_reason_fails():
    t = trace(); t["decision"]["reasons"] = ["duplicate_intent"]
    with pytest.raises(m.ContractError, match="missing_grant_requires_hold_reason"):
        m.validate_trace(t)


def test_altered_policy_digest_fails():
    t = trace(); t["decision"]["policy_digest"] = "sha256:changed"
    with pytest.raises(m.ContractError, match="altered_policy"):
        m.validate_trace(t)


def test_withdrawn_approval_requires_explicit_hold_reason():
    t = trace(); t["decision"]["approval_status"] = "withdrawn"
    with pytest.raises(m.ContractError, match="withdrawn_approval_requires_hold_reason"):
        m.validate_trace(t)
    t["decision"]["reasons"].append("approval_withdrawn")
    m.validate_trace(t)


def test_duplicate_intent_stays_hold_and_does_not_create_new_identity():
    t = trace(); t["decision"]["reasons"].append("duplicate_intent")
    t["decision"]["grant_id"] = "grant-synthetic"
    t["decision"]["reasons"].remove("missing_grant")
    assert m.validate_trace(t)["decision"]["result"] == "HOLD"


def test_unknown_delivery_requires_hold_and_cannot_be_promoted_by_receipt():
    t = trace(); t["execution_attempt"]["state"] = "unknown_delivery"; t["transport"]["delivery_state"] = "unknown"; t["transport"]["authenticity"] = "unverified"
    with pytest.raises(m.ContractError, match="unknown_delivery_requires_hold_reason"):
        m.validate_trace(t)
    t["decision"]["reasons"].append("unknown_delivery")
    assert m.validate_trace(t)["settlement"]["state"] == "not_observed"


def test_forged_receipt_claim_fails_closed():
    t = trace(); t["transport"]["authenticity"] = "unverified"; t["transport"]["delivery_state"] = "refused"
    with pytest.raises(m.ContractError, match="forged_receipt"):
        m.validate_trace(t)


def test_forged_settlement_claim_is_rejected():
    t = trace(); t["settlement"]["state"] = "settled"; t["settlement"]["independent"] = True
    with pytest.raises(m.ContractError, match="forged_settlement"):
        m.validate_trace(t)


@pytest.mark.parametrize("stage", ["request", "decision", "execution_attempt", "evidence", "transport", "settlement"])
def test_tenant_mismatch_fails_at_every_stage(stage):
    t = trace(); t[stage]["tenant_id"] = "merchant-other"
    with pytest.raises(m.ContractError, match="tenant_mismatch"):
        m.validate_trace(t)


def test_stage_identity_collision_is_rejected():
    t = trace(); t["transport"]["receipt_id"] = t["decision"]["decision_id"]
    with pytest.raises(m.ContractError, match="stage_identity_collision"):
        m.validate_trace(t)


def test_evidence_may_not_claim_independent_effect_verification():
    t = trace(); t["evidence"]["independent_effect_verification"] = True
    with pytest.raises(m.ContractError, match="independent_effect_verification_not_established"):
        m.validate_trace(t)
