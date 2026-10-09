"""Candidate institutional Authority Context mapping for O4c-C.

This module validates a narrow projection of Cognous Institutional Governance
Authority Context 0.1.0. It does not authenticate an institution, issuer,
adoption record, grant, credential, or runtime decision, and it never authorizes
an effect.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

SOURCE_REPOSITORY = "cogno-us/cognous-institutional-governance"
SOURCE_REVISION = "1386fd236f13896029e5ab47ba5b9c3127509c3d"
SOURCE_SCHEMA_PATH = "process/implementation/public-stack-v0.1/authority-context.schema.json"
SOURCE_PROFILE_PATH = "process/implementation/public-stack-v0.1/AUTHORITY_CONTEXT.md"
SOURCE_SCHEMA_VERSION = "0.1.0"
SOURCE_INTERFACE_STATUS = "proposed_pending_governor_review"


class IdentityBinding(TypedDict):
    tenant_id: str
    actor_id: str
    institution_id: str
    principal: str
    acting_identity: str
    claimed_issuer: str | None


class MappingResult(TypedDict):
    status: Literal["requirements_mapped_hold", "rejected"]
    reasons: list[str]
    governance_state: Literal["proposed_requirements_only"]
    grant_state: Literal["requirements_only", "claimed_grant_external_authentication_required"]
    adoption_state: Literal["missing", "reference_present_unverified"]
    authority: Literal["not_established"]
    effect_disposition: Literal["hold_effect"]
    source_revision: str
    source_schema_path: str
    requirement_id: str | None
    institution_id: str | None
    authority_domain: str | None
    principal: str | None
    acting_identity: str | None
    claimed_issuer: str | None


def _reject(reasons: list[str], *, requirement_id: str | None = None,
            institution_id: str | None = None, authority_domain: str | None = None,
            principal: str | None = None, acting_identity: str | None = None,
            claimed_issuer: str | None = None) -> MappingResult:
    return {
        "status": "rejected",
        "reasons": sorted(set(reasons)),
        "governance_state": "proposed_requirements_only",
        "grant_state": "claimed_grant_external_authentication_required" if claimed_issuer else "requirements_only",
        "adoption_state": "missing",
        "authority": "not_established",
        "effect_disposition": "hold_effect",
        "source_revision": SOURCE_REVISION,
        "source_schema_path": SOURCE_SCHEMA_PATH,
        "requirement_id": requirement_id,
        "institution_id": institution_id,
        "authority_domain": authority_domain,
        "principal": principal,
        "acting_identity": acting_identity,
        "claimed_issuer": claimed_issuer,
    }


def map_authority_context_requirements(
    *,
    source_revision: str,
    tenant_id: str,
    actor_id: str,
    identity_binding: IdentityBinding,
    authority_context: dict[str, Any],
    institutional_adoption_ref: str | None,
) -> MappingResult:
    """Map source requirements while preserving the external authority boundary.

    institutional_adoption_ref is only a caller-supplied reference. Presence
    does not authenticate adoption and therefore cannot move the result beyond
    hold_effect.
    """
    reasons: list[str] = []
    if source_revision != SOURCE_REVISION:
        reasons.append("unsupported_source_revision")
    if not isinstance(authority_context, dict):
        return _reject(reasons + ["invalid_authority_context"])

    if authority_context.get("schema_version") != SOURCE_SCHEMA_VERSION:
        reasons.append("unsupported_schema_version")
    if authority_context.get("interface_status") != SOURCE_INTERFACE_STATUS:
        reasons.append("interface_not_proposed_pending_governor_review")
    if "runtime_decision" in authority_context or "allowed" in authority_context:
        reasons.append("prohibited_runtime_authorization_field")

    institution = authority_context.get("institution")
    requirement = authority_context.get("requirement")
    if not isinstance(institution, dict):
        institution = {}
        reasons.append("missing_institution")
    if not isinstance(requirement, dict):
        requirement = {}
        reasons.append("missing_requirement")

    institution_id = institution.get("institution_id")
    authority_domain = institution.get("authority_domain")
    principal = authority_context.get("principal")
    acting_identity = authority_context.get("acting_identity")
    requirement_id = requirement.get("requirement_id")
    grant = authority_context.get("grant")
    claimed_issuer = grant.get("issuer") if isinstance(grant, dict) else None

    for value, reason in (
        (tenant_id, "invalid_tenant_id"),
        (actor_id, "invalid_actor_id"),
        (institution_id, "invalid_institution_id"),
        (authority_domain, "invalid_authority_domain"),
        (principal, "invalid_principal"),
        (acting_identity, "invalid_acting_identity"),
        (requirement_id, "invalid_requirement_id"),
    ):
        if not isinstance(value, str) or not value:
            reasons.append(reason)

    if not isinstance(identity_binding, dict):
        reasons.append("invalid_identity_binding")
        identity_binding = {}
    if identity_binding.get("tenant_id") != tenant_id:
        reasons.append("tenant_binding_mismatch")
    if identity_binding.get("actor_id") != actor_id:
        reasons.append("actor_binding_mismatch")
    if identity_binding.get("institution_id") != institution_id:
        reasons.append("institution_binding_mismatch")
    if identity_binding.get("principal") != principal:
        reasons.append("principal_binding_mismatch")
    if identity_binding.get("acting_identity") != acting_identity:
        reasons.append("acting_identity_binding_mismatch")

    if isinstance(grant, dict):
        if identity_binding.get("claimed_issuer") != claimed_issuer:
            reasons.append("issuer_binding_mismatch")
        if grant.get("requirement_id") != requirement_id:
            reasons.append("grant_requirement_mismatch")
        if grant.get("grantee") != principal:
            reasons.append("grant_principal_mismatch")
        if grant.get("acting_identity") != acting_identity:
            reasons.append("grant_acting_identity_mismatch")
    elif identity_binding.get("claimed_issuer") is not None:
        reasons.append("issuer_claim_without_grant")

    evidence = requirement.get("evidence")
    if not isinstance(evidence, list):
        reasons.append("missing_evidence_requirements")
    else:
        for item in evidence:
            if not isinstance(item, dict):
                reasons.append("invalid_evidence_requirement")
                continue
            if item.get("kind") == "authorization" and item.get("required") is True:
                if item.get("unknown_behavior") != "hold_effect":
                    reasons.append("invalid_required_authorization_unknown_behavior")

    if reasons:
        return _reject(
            reasons,
            requirement_id=requirement_id if isinstance(requirement_id, str) else None,
            institution_id=institution_id if isinstance(institution_id, str) else None,
            authority_domain=authority_domain if isinstance(authority_domain, str) else None,
            principal=principal if isinstance(principal, str) else None,
            acting_identity=acting_identity if isinstance(acting_identity, str) else None,
            claimed_issuer=claimed_issuer if isinstance(claimed_issuer, str) else None,
        )

    return {
        "status": "requirements_mapped_hold",
        "reasons": ["institutional_adoption_not_authenticated", "grant_issuer_not_authenticated"],
        "governance_state": "proposed_requirements_only",
        "grant_state": "claimed_grant_external_authentication_required" if claimed_issuer else "requirements_only",
        "adoption_state": "reference_present_unverified" if institutional_adoption_ref else "missing",
        "authority": "not_established",
        "effect_disposition": "hold_effect",
        "source_revision": SOURCE_REVISION,
        "source_schema_path": SOURCE_SCHEMA_PATH,
        "requirement_id": requirement_id,
        "institution_id": institution_id,
        "authority_domain": authority_domain,
        "principal": principal,
        "acting_identity": acting_identity,
        "claimed_issuer": claimed_issuer,
    }
