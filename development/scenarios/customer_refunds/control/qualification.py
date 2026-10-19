"""O5-C-A fixture-only refund Manifest / Control Plane qualification.

No function in this module authorizes or executes a refund.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

ORCHESTRATOR_BASE = "0aaaa11d1795e4e0cbf081826e9e1d1b3d5ca850"
MANIFEST_PIN = "8d1572d4f926c968a8704cb912a6e9d49166f74a"
CONTROL_PLANE_PIN = "2bac7875391cad0a431fa0d75208b7ade39743e3"

MANIFEST_ID = "refund-integration-pilot-v1"
MANIFEST_VERSION = "1.1"
ACTION_ID = "urn:cognous:action:refund-issue-routine-v1"
ADAPTER_ID = "urn:cognous:adapter:synthetic-refund-v1"
TARGET = "urn:cognous:synthetic-account:customer-001"
AUTHORITY_PROFILE = "urn:cognous:alvorada:public-stack-profile:0.1.0"
REQUIREMENT_ID = "urn:cognous:authority-requirement:refund-routine-v1"
PERMISSION = "refund.issue.routine"
POLICY_REF = "urn:cognous:policy:refund-policy"

FIXTURE_PATH = Path(__file__).with_name("refund_integration_v1_1.manifest.json")
FIXTURE_MANIFEST = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def commitment(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def request_digest(request: dict) -> str:
    """Bind the decision fixture to exact consequential O5 request material."""
    keys = (
        "request_id", "tenant_id", "order_ref", "payment_ref",
        "amount_minor", "currency", "policy_version",
        "customer_id", "refund_reason",
    )
    return commitment({key: request.get(key) for key in keys})


def build_manifest_proposal(request: dict) -> dict:
    """Map a synthetic O5 request to the accepted tenant-aware proposal shape."""
    payload = {
        "customer_id": request.get("customer_id"),
        "refund_reason": request.get("refund_reason"),
    }
    amount_minor = request.get("amount_minor")
    amount = amount_minor / 100 if type(amount_minor) is int else -1
    proposal = {
        "tenant_id": request.get("tenant_id"),
        "manifest_id": MANIFEST_ID,
        "manifest_version": MANIFEST_VERSION,
        "manifest_digest": commitment(FIXTURE_MANIFEST),
        "actor": request.get("actor"),
        "principal": request.get("principal"),
        "action_id": ACTION_ID,
        "adapter_id": ADAPTER_ID,
        "target": TARGET,
        "payload": payload,
        "payload_commitment": commitment(payload),
        "requested_permissions": [PERMISSION],
        "amount": amount,
        "unit": request.get("currency"),
        "effects": 1,
        "authority_context_ref": AUTHORITY_PROFILE,
        "requirement_id": REQUIREMENT_ID,
        "correlation_id": request.get("request_id"),
        "run_id": None,
        "expected_side_effects": [],
        "evidence_refs": [request.get("purchase_evidence_ref")] if request.get("purchase_evidence_ref") else [],
        "risk_metadata": {},
        "not_before": None,
        "expires_at": None,
    }
    return proposal


def _proposal_faults(proposal: dict) -> list[str]:
    faults = []
    required_strings = (
        "tenant_id", "actor", "principal", "correlation_id",
    )
    for key in required_strings:
        if not isinstance(proposal.get(key), str) or not proposal[key]:
            faults.append("proposal_" + key + "_missing")
    if proposal["payload"].get("customer_id") is None:
        faults.append("proposal_customer_id_missing")
    if not isinstance(proposal["payload"].get("refund_reason"), str) or not proposal["payload"]["refund_reason"]:
        faults.append("proposal_refund_reason_missing")
    if proposal["amount"] < 0 or proposal["amount"] > 100.0:
        faults.append("proposal_amount_out_of_scope")
    if proposal["unit"] != "USD":
        faults.append("proposal_currency_out_of_scope")
    if not proposal["evidence_refs"]:
        faults.append("proposal_purchase_evidence_missing")
    return faults


def _authority_faults(request: dict, authority: dict) -> list[str]:
    faults = []
    if not isinstance(authority, dict):
        return ["authority_fixture_missing"]

    tenant = request.get("tenant_id")
    if authority.get("tenant_id") != tenant:
        faults.append("tenant_mismatch")

    expected_digest = request_digest(request)
    if authority.get("request_digest") != expected_digest:
        faults.append("request_digest_changed")

    delegation = authority.get("delegated_authority")
    if not isinstance(delegation, dict) or delegation.get("status") != "active":
        faults.append("delegated_authority_missing")
    else:
        if delegation.get("tenant_id") != tenant:
            faults.append("delegated_authority_tenant_mismatch")
        if delegation.get("scope") != PERMISSION:
            faults.append("delegated_authority_scope_mismatch")

    policy = authority.get("policy")
    if not isinstance(policy, dict):
        faults.append("policy_missing")
    else:
        if policy.get("ref") != POLICY_REF:
            faults.append("policy_binding_mismatch")
        if policy.get("version") != request.get("policy_version") or policy.get("status") != "active":
            faults.append("policy_stale_or_changed")
        if policy.get("tenant_id") != tenant:
            faults.append("policy_tenant_mismatch")

    approval = authority.get("approval")
    if not isinstance(approval, dict):
        faults.append("approval_missing")
    else:
        if approval.get("status") != "active":
            faults.append("approval_not_active")
        if approval.get("tenant_id") != tenant:
            faults.append("approval_tenant_mismatch")
        if approval.get("request_digest") != expected_digest:
            faults.append("approval_operation_binding_mismatch")

    return faults


def component_availability() -> dict:
    """Report whether accepted upstream packages are importable in this checkout."""
    available = {"manifest": False, "control_plane": False}
    try:
        import agent_action_manifest.binding  # noqa: F401
        import agent_action_manifest.models  # noqa: F401
        available["manifest"] = True
    except Exception:
        pass
    try:
        import agent_control_plane.bounded  # noqa: F401
        available["control_plane"] = True
    except Exception:
        pass
    return available


def validate_with_available_components(proposal: dict) -> dict:
    """Call accepted package APIs when installed; otherwise name the fixture stub."""
    availability = component_availability()
    result = {
        "manifest": "fixture_stub",
        "control_plane": "fixture_stub",
        "manifest_faults": [],
        "control_plane_validated": False,
    }

    if availability["manifest"]:
        from agent_action_manifest.models import AgentActionManifest, RuntimeActionProposalV12
        from agent_action_manifest.binding import proposal_mismatches
        # The copied fixture is byte-equivalent JSON content from the accepted pin.
        try:
            manifest = AgentActionManifest.model_validate(FIXTURE_MANIFEST)
            model = RuntimeActionProposalV12.model_validate(proposal)
            result["manifest_faults"] = proposal_mismatches(manifest, model)
            result["manifest"] = "actual_component"
        except Exception as exc:
            result["manifest"] = "actual_component_rejected_fixture"
            result["manifest_faults"] = [type(exc).__name__]

    if availability["control_plane"]:
        from agent_control_plane.bounded import TenantRuntimeProposal
        TenantRuntimeProposal.model_validate(proposal)
        result["control_plane"] = "actual_component"
        result["control_plane_validated"] = True

    return result


def qualify_refund(request: dict, authority: dict) -> dict:
    """Qualify mapping/binding; always return HOLD because live authority is absent."""
    if not isinstance(request, dict):
        request = {}
    proposal = build_manifest_proposal(request)
    faults = _proposal_faults(proposal) + _authority_faults(request, authority)
    component_result = validate_with_available_components(proposal)

    # Upstream component rejection is itself fail-closed.
    if component_result["manifest_faults"]:
        faults.extend("manifest:" + item for item in component_result["manifest_faults"])

    unique_faults = sorted(set(faults))
    candidate = None
    if not unique_faults:
        candidate = {
            "fixture_only": True,
            "tenant_id": request["tenant_id"],
            "request_digest": request_digest(request),
            "proposal_commitment": commitment(proposal),
            "grant_id": authority["delegated_authority"].get("grant_id"),
            "grant_revision": authority["delegated_authority"].get("revision"),
            "policy_ref": authority["policy"].get("ref"),
            "policy_version": authority["policy"].get("version"),
            "approval_ref": authority["approval"].get("approval_ref"),
        }

    reasons = list(unique_faults)
    reasons.append("live_authorization_absent")
    return {
        "scenario": "customer_refund",
        "source_pins": {
            "manifest": MANIFEST_PIN,
            "control_plane": CONTROL_PLANE_PIN,
            "orchestrator_base": ORCHESTRATOR_BASE,
        },
        "proposal": deepcopy(proposal),
        "request_digest": request_digest(request),
        "contract_faults": unique_faults,
        "authority_binding_candidate": candidate,
        "component_execution": component_result,
        "decision": {
            "result": "hold",
            "reasons": sorted(set(reasons)),
            "binding": None,
        },
        "effect": "disabled",
        "settlement": "not_observed",
    }
