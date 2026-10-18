"""O5-E-A connected pinned-source refund handoff.

This module composes the actual pinned Action Manifest, Control Plane, and
Execution Runtime source interfaces. It does not create production authority,
credentials, or payment effects.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

ACTION_MANIFEST_PIN = "8d1572d4f926c968a8704cb912a6e9d49166f74a"
CONTROL_PLANE_PIN = "6093aca7b945698e89c0d8ac7c75306375e1a298"
EXECUTION_RUNTIME_BASE_PIN = "62a5cc156ecb439b4103b757fd265f276bb30374"
EXECUTION_RUNTIME_CANDIDATE_PIN = "1b0a9e32d010797711004ae612051a277b07912a"
# Candidate testing is strictly opt-in: no arbitrary SHA, branch, or fallback.
_candidate_pin = os.environ.get("COGNOUS_O6_Q2_RUNTIME_CANDIDATE", "")
if _candidate_pin not in ("", EXECUTION_RUNTIME_CANDIDATE_PIN):
    raise RuntimeError("unsupported O6-Q2 runtime candidate pin")
EXECUTION_RUNTIME_PIN = _candidate_pin or EXECUTION_RUNTIME_BASE_PIN


def _head(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"upstream source unavailable at {path}: {exc}") from exc


def require_pinned_sources() -> tuple[Path, Path, Path]:
    manifest = Path(os.environ["COGNOUS_ACTION_MANIFEST_SRC"]).resolve()
    control = Path(os.environ["COGNOUS_CONTROL_PLANE_SRC"]).resolve()
    runtime = Path(os.environ["COGNOUS_EXECUTION_RUNTIME_ROOT"]).resolve()
    actual = {
        "action_manifest": _head(manifest),
        "control_plane": _head(control),
        "execution_runtime": _head(runtime),
    }
    expected = {
        "action_manifest": ACTION_MANIFEST_PIN,
        "control_plane": CONTROL_PLANE_PIN,
        "execution_runtime": EXECUTION_RUNTIME_PIN,
    }
    if actual != expected:
        raise RuntimeError(f"upstream pin mismatch: expected={expected} actual={actual}")

    # Source packages come only from the exact pinned checkouts.
    sys.path.insert(0, str(runtime))
    sys.path.insert(0, str(runtime / "tests"))
    sys.path.insert(0, str(control / "src"))
    sys.path.insert(0, str(manifest / "src"))
    return manifest, control, runtime


def load_upstream():
    manifest_repo, control_repo, runtime_repo = require_pinned_sources()

    from agent_action_manifest.binding import (
        manifest_digest,
        payload_digest,
        proposal_digest,
        proposal_mismatches,
    )
    from agent_action_manifest.models import AgentActionManifest, RuntimeActionProposalV12
    from agent_control_plane.local_authority_effect import verify_local_execution_claim
    from engine.atomic_local_control_plane_executor import AtomicLocalControlPlaneExecutor
    from engine.local_authority_effect import AtomicAuthorityEffectDestination
    from engine.safe_executor import (
        EXECUTION_ENVELOPE_VERSION,
        ExecutionEnvelope,
        ExecutionOperation,
        LocalExecutionPolicy,
        snapshot_envelope,
    )

    helper_path = control_repo / "tests" / "test_bounded_authorization.py"
    spec = importlib.util.spec_from_file_location("o5_e_a_pinned_control", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("pinned Control Plane refund helper cannot be loaded")
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)

    manifest_path = manifest_repo / "examples" / "refund_integration_v1_1.manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("pinned Action Manifest refund example is unavailable")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    model = AgentActionManifest.model_validate(raw)
    canonical_manifest = model.model_dump(mode="json", exclude_none=False)

    # Force the pinned Control Plane test helper to consume the real pinned
    # Action Manifest model projection rather than its repository-local copy.
    def actual_manifest():
        return json.loads(json.dumps(canonical_manifest))

    helper.manifest = actual_manifest

    return {
        "manifest_repo": manifest_repo,
        "control_repo": control_repo,
        "runtime_repo": runtime_repo,
        "helper": helper,
        "manifest_model": model,
        "ManifestProposal": RuntimeActionProposalV12,
        "manifest_digest": manifest_digest,
        "payload_digest": payload_digest,
        "proposal_digest": proposal_digest,
        "proposal_mismatches": proposal_mismatches,
        "verify_local_execution_claim": verify_local_execution_claim,
        "Executor": AtomicLocalControlPlaneExecutor,
        "Destination": AtomicAuthorityEffectDestination,
        "ExecutionEnvelope": ExecutionEnvelope,
        "ExecutionOperation": ExecutionOperation,
        "ExecutionPolicy": LocalExecutionPolicy,
        "EXECUTION_ENVELOPE_VERSION": EXECUTION_ENVELOPE_VERSION,
        "snapshot_envelope": snapshot_envelope,
    }


UP = load_upstream()
h = UP["helper"]


def manifest_side_proposal(proposal):
    return UP["ManifestProposal"].model_validate(
        proposal.model_dump(mode="json", exclude_none=False)
    )


def tenant_case(tmp_path: Path, *, with_grant: bool = True, trusted_owner: bool = True):
    proposal = h.tenant_proposal()
    resolver = h.tenant_resolver_for(proposal)
    resolver.authenticated = trusted_owner
    if not with_grant:
        grant = resolver.contexts[h.PROFILE].pop("grant")
        resolver.statuses.pop(grant["grant_id"], None)
        for approval_ref in grant.get("approval_refs", []):
            resolver.approvals.pop(approval_ref, None)
    flow = h.tenant_workflow(tmp_path / "control", proposal, resolver=resolver)
    destination = UP["Destination"](tmp_path / "runtime", clock=lambda: h.NOW)
    return proposal, resolver, flow, destination


def decide_with_trusted_owner(flow, proposal):
    # SyntheticResolver is useful fixture machinery, but it is not authenticated
    # institutional authority by itself. Qualification requires an explicit
    # test-owned trust flag before invoking the actual decision handler.
    if getattr(flow.resolver, "authenticated", False) is not True:
        raise PermissionError("trusted owner resolver required")
    return flow.decide(proposal, now=h.NOW)


def runtime_policy(operation):
    return UP["ExecutionPolicy"](
        allowed_institutions=frozenset({operation.institution_id}),
        allowed_authority_domains=frozenset({operation.authority_domain}),
        allowed_adapters=frozenset({operation.adapter_id}),
        allowed_actions=frozenset({operation.action_id}),
        allowed_target_prefixes=("urn:cognous:synthetic-account:",),
        allowed_units=frozenset({operation.unit}),
        max_amount=1000.0,
        max_effects=1,
    )


def envelope_from_connected_handoff(proposal, decision, claim):
    if decision.binding is None:
        raise PermissionError("cannot build execution envelope from a non-authorized decision")
    tenant_id = getattr(claim, "tenant_id", None)
    operation = UP["ExecutionOperation"](
        actor=proposal.actor,
        principal=proposal.principal,
        institution_id=claim.institution_id,
        authority_domain=claim.authority_domain,
        manifest_id=proposal.manifest_id,
        manifest_version=proposal.manifest_version,
        manifest_digest=proposal.manifest_digest,
        proposal_commitment=decision.binding.proposal_commitment,
        action_id=proposal.action_id,
        adapter_id=proposal.adapter_id,
        target=proposal.target,
        payload=copy.deepcopy(proposal.payload),
        payload_commitment=proposal.payload_commitment,
        requested_permissions=tuple(proposal.requested_permissions),
        amount=proposal.amount,
        unit=proposal.unit,
        effects=proposal.effects,
        authority_context_id=proposal.authority_context_ref,
        requirement_id=proposal.requirement_id,
        grant_id=claim.grant_id,
        grant_revision=claim.grant_revision,
        effective_max_effects=claim.max_effects,
        tenant_id=tenant_id,
    )
    return UP["ExecutionEnvelope"](
        version=UP["EXECUTION_ENVELOPE_VERSION"],
        decision_id=decision.decision_id,
        effect_id=decision.effect_id,
        operation=operation,
    )


def provision_connected(proposal, flow, destination, decision):
    executor = UP["Executor"](
        workflow=flow,
        destination=destination,
        policy=runtime_policy(
            # Policy is replaced immediately after the claim-derived envelope is built;
            # this placeholder uses only proposal-visible fields and cannot authorize.
            UP["ExecutionOperation"](
                actor=proposal.actor,
                principal=proposal.principal,
                institution_id=h.INSTITUTION,
                authority_domain="customer-refunds",
                manifest_id=proposal.manifest_id,
                manifest_version=proposal.manifest_version,
                manifest_digest=proposal.manifest_digest,
                proposal_commitment=decision.binding.proposal_commitment if decision.binding else "",
                action_id=proposal.action_id,
                adapter_id=proposal.adapter_id,
                target=proposal.target,
                payload=copy.deepcopy(proposal.payload),
                payload_commitment=proposal.payload_commitment,
                requested_permissions=tuple(proposal.requested_permissions),
                amount=proposal.amount,
                unit=proposal.unit,
                effects=proposal.effects,
                authority_context_id=proposal.authority_context_ref,
                requirement_id=proposal.requirement_id,
                grant_id=decision.binding.grant_id if decision.binding else "urn:cognous:grant:absent",
                grant_revision=decision.binding.grant_revision if decision.binding else "absent",
                effective_max_effects=decision.binding.effective_max_effects if decision.binding else 1,
                tenant_id=getattr(decision.binding, "tenant_id", None) if decision.binding else proposal.tenant_id,
            )
        ),
    )
    claim = executor.provision_claim(
        proposal=proposal,
        decision=decision,
        now=h.NOW,
    )
    if not UP["verify_local_execution_claim"](claim):
        raise AssertionError("actual Control Plane execution claim did not verify")
    envelope = envelope_from_connected_handoff(proposal, decision, claim)
    executor.policy = runtime_policy(envelope.operation)
    return executor, claim, envelope


def effect_rows(destination) -> list[dict]:
    with sqlite3.connect(destination.path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM effects ORDER BY effect_id")]


def attempt_rows(destination) -> list[dict]:
    with sqlite3.connect(destination.path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM attempts ORDER BY created_at,attempt_id")]
