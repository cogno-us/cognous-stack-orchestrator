from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
HARNESS = ROOT / "development/scenarios/customer_refunds/live_components/control/upstream_control.py"
spec = importlib.util.spec_from_file_location("o5_d_a_upstream_control", HARNESS)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

UP = m.load_upstream()
h = UP["helper"]


def trusted_tenant_case(tmp_path):
    p = h.tenant_proposal()
    r = h.tenant_resolver_for(p)
    # O5-D-A does not treat the upstream SyntheticResolver as trusted by default.
    # The qualification wrapper requires the test to make this synthetic owner
    # boundary explicit before the actual decision handler may be exercised.
    r.authenticated = True
    flow = h.tenant_workflow(tmp_path, p, resolver=r)
    return p, r, flow


def manifest_side_proposal(p):
    return UP["ManifestProposal"].model_validate(
        p.model_dump(mode="json", exclude_none=False)
    )


def test_actual_pinned_sources_and_manifest_model_are_exercised(tmp_path):
    p, _, flow = trusted_tenant_case(tmp_path)
    mp = manifest_side_proposal(p)

    assert UP["manifest_model"].manifest_id == p.manifest_id
    assert UP["manifest_digest"](UP["manifest_model"]) == p.manifest_digest
    assert UP["payload_digest"](mp.payload) == mp.payload_commitment
    assert UP["proposal_mismatches"](UP["manifest_model"], mp) == []

    decision = m.decide_with_trusted_owner(flow, p, now=h.NOW)
    assert decision.result == "authorized"
    assert decision.binding is not None
    assert decision.binding.tenant_id == h.TENANT


def test_missing_trusted_owner_resolver_fails_closed_before_decision(tmp_path):
    p = h.tenant_proposal()
    r = h.tenant_resolver_for(p)
    flow = h.tenant_workflow(tmp_path, p, resolver=r)

    with pytest.raises(PermissionError, match="trusted owner resolver required"):
        m.decide_with_trusted_owner(flow, p, now=h.NOW)
    assert flow.records.load().decisions == []


def test_missing_grant_holds_without_fabrication(tmp_path):
    p = h.tenant_proposal()
    r = h.tenant_resolver_for(p)
    r.authenticated = True
    r.contexts[h.PROFILE].pop("grant")

    decision = m.decide_with_trusted_owner(
        h.tenant_workflow(tmp_path, p, resolver=r), p, now=h.NOW
    )
    assert decision.result == "hold"
    assert "issued_grant_missing" in decision.reasons
    assert decision.binding is None


@pytest.mark.parametrize(
    ("location", "reason"),
    [
        ("context", "tenant_context_mismatch"),
        ("grant", "grant_tenant_mismatch"),
        ("grant_status", "grant_tenant_mismatch"),
        ("approval", "approval_tenant_mismatch"),
        ("policy", "policy_tenant_mismatch"),
    ],
)
def test_cross_tenant_authority_records_hold(tmp_path, location, reason):
    p, r, _ = trusted_tenant_case(tmp_path)
    grant = r.contexts[h.PROFILE]["grant"]
    wrong = "tenant-beta"
    if location == "context":
        r.contexts[h.PROFILE]["tenant_id"] = wrong
    elif location == "grant":
        grant["tenant_id"] = wrong
    elif location == "grant_status":
        r.statuses[grant["grant_id"]].tenant_id = wrong
    elif location == "approval":
        r.approvals[grant["approval_refs"][0]].tenant_id = wrong
    else:
        r.policies[h.POLICY_REF].tenant_id = wrong

    flow = h.tenant_workflow(tmp_path, p, resolver=r)
    decision = m.decide_with_trusted_owner(flow, p, now=h.NOW)
    assert decision.result == "hold"
    assert reason in decision.reasons
    assert decision.binding is None


def test_stale_required_evidence_holds(tmp_path):
    p, r, _ = trusted_tenant_case(tmp_path)
    r.evidence["urn:cognous:evidence:refund-entitlement"].observed_at = (
        h.NOW - timedelta(minutes=10)
    ).isoformat()

    decision = m.decide_with_trusted_owner(
        h.tenant_workflow(tmp_path, p, resolver=r), p, now=h.NOW
    )
    assert decision.result == "hold"
    assert "required_evidence_stale_or_future" in decision.reasons


def test_policy_version_change_holds(tmp_path):
    p, r, _ = trusted_tenant_case(tmp_path)
    r.policies[h.POLICY_REF].version = "2.0"

    decision = m.decide_with_trusted_owner(
        h.tenant_workflow(tmp_path, p, resolver=r), p, now=h.NOW
    )
    assert decision.result == "hold"
    assert "policy_stale_or_changed" in decision.reasons


def test_withdrawn_approval_holds(tmp_path):
    p, r, _ = trusted_tenant_case(tmp_path)
    approval_ref = r.contexts[h.PROFILE]["grant"]["approval_refs"][0]
    r.approvals[approval_ref].status = "revoked"

    decision = m.decide_with_trusted_owner(
        h.tenant_workflow(tmp_path, p, resolver=r), p, now=h.NOW
    )
    assert decision.result == "hold"
    assert "approval_not_active" in decision.reasons


def test_manifest_tenant_substitution_changes_actual_proposal_commitment(tmp_path):
    p, _, _ = trusted_tenant_case(tmp_path)
    original = manifest_side_proposal(p)
    changed = original.model_copy(update={"tenant_id": "tenant-beta"})

    assert UP["proposal_digest"](original) != UP["proposal_digest"](changed)
