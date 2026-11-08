"""Versioned contract for the F1 refund-disposition library (DEVELOPMENT ONLY / SYNTHETIC / NONPRODUCTION / NON-AUTHORIZING).

Pure data: standard library only, no native import. The adapter composes native components; it decides nothing. The Control Plane decides
authorization, the Runtime executes permitted effects, Replay reconstructs evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

CONTRACT_VERSION = "refund-disposition/0.1.0-dev"
PROFILE_REGISTRY_VERSION = "refund-profiles/0.1.0-dev"
DEFAULT_PROFILE = "refund-routine-v1"
RETRY_PERMISSION = "not_established"  # constant by contract: no result ever grants a retry

Disposition = Literal["executed", "held", "denied", "refused", "unknown", "failed"]
DISPOSITIONS = ("executed", "held", "denied", "refused", "unknown", "failed")
NextStep = Literal["none", "resolve_authority_hold", "correct_request", "correct_request_or_runtime_policy",
                   "reconcile_read_only", "operator_inspection_no_retry_established"]

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")

NOT_VERIFIED = (
    "authority is a synthetic developer-mode fixture decision (resolver authenticated=false); not institutional authority",
    "the effect is a real local SQLite write reported by the producer; it is not independently observed",
    "no independent qualification or certification; the Verifier, Attestation and Registry are not part of this interface",
    "idempotency holds per destination database only; there is no cross-database exactly-once claim",
)


@dataclass(frozen=True)
class SyntheticEnvironment:
    """Where the pinned development stack lives and where this caller keeps state. Both are caller-owned; the adapter never deletes them."""

    stack_root: Path  # directory holding control_plane, runtime, replay, institutional_governance at their pins
    state_dir: Path  # destination SQLite, Control Plane run record and evidence files live here and persist across calls


@dataclass(frozen=True)
class RefundProposal:
    """The one synthetic refund action this profile supports. Action, adapter, permission and requirement identities are fixed."""

    tenant_id: str
    customer_id: str
    refund_reason: str
    amount: float
    unit: str = "USD"
    actor: str = "urn:cognous:identity:refund-agent-1"
    principal: str = "urn:cognous:principal:refund-service"
    case_reference: str | None = None  # required by profile refund-high-v1, forbidden by refund-routine-v1 (checked against the profile)


@dataclass(frozen=True)
class AuthorityFacts:
    """Synthetic authority inputs for the native IG -> CP path. Both documents are passed through to the pinned IG resolver unevaluated."""

    authority_id: str
    lineage_bundle: dict  # IG root-lineage document
    facts: dict  # IG synthetic facts document (tenant, context_ref, approval, role mapping, ...)


@dataclass(frozen=True)
class DispositionRequest:
    proposal: RefundProposal
    authority: AuthorityFacts
    correlation_id: str
    evaluation_time: datetime  # explicit and timezone-aware: no default clock is invented
    environment: SyntheticEnvironment
    profile: str | None = None  # approved profile id from the closed registry; None means the historical fixed profile refund-routine-v1


def request_problems(request: Any) -> list[str]:
    """Structural problems only. No policy is evaluated here; a problem means the request is REFUSED before any native call."""
    if not isinstance(request, DispositionRequest):
        return ["request_not_a_DispositionRequest"]
    out: list[str] = []
    p, a, e = request.proposal, request.authority, request.environment
    if not isinstance(p, RefundProposal):
        return ["proposal_not_a_RefundProposal"]
    if not isinstance(a, AuthorityFacts):
        return ["authority_not_AuthorityFacts"]
    if not isinstance(e, SyntheticEnvironment):
        return ["environment_not_SyntheticEnvironment"]
    for name in ("tenant_id", "customer_id", "refund_reason", "actor", "principal"):
        v = getattr(p, name)
        if not isinstance(v, str) or not v.strip():
            out.append(f"proposal_{name}_missing")
    if isinstance(p.amount, bool) or not isinstance(p.amount, (int, float)) or not (p.amount > 0) or p.amount != p.amount or p.amount == float("inf"):
        out.append("proposal_amount_invalid")
    if not isinstance(p.unit, str) or not _CURRENCY.fullmatch(p.unit):
        out.append("proposal_unit_invalid")
    if not isinstance(a.authority_id, str) or not a.authority_id:
        out.append("authority_id_missing")
    if not isinstance(a.lineage_bundle, dict) or not a.lineage_bundle:
        out.append("authority_lineage_bundle_missing")
    if not isinstance(a.facts, dict) or not a.facts:
        out.append("authority_facts_missing")
    elif a.facts.get("tenant_id") != p.tenant_id:
        out.append("tenant_mismatch_between_proposal_and_authority_facts")
    elif not isinstance(a.facts.get("context_ref"), str) or not isinstance(a.facts.get("approval"), dict):
        out.append("authority_facts_missing_context_ref_or_approval")
    if isinstance(a.lineage_bundle, dict) and a.lineage_bundle:
        origins = a.lineage_bundle.get("origins")
        o = origins[0] if isinstance(origins, list) and origins else None
        if not isinstance(o, dict) or not isinstance(o.get("institution_id"), str) or not isinstance(o.get("authority_domain"), str):
            out.append("authority_lineage_origin_missing_institution_or_domain")
    if p.case_reference is not None and not isinstance(p.case_reference, str):
        out.append("proposal_case_reference_invalid")
    if request.profile is not None and not isinstance(request.profile, str):
        out.append("profile_not_a_string")
    if not isinstance(request.correlation_id, str) or not _ID.fullmatch(request.correlation_id):
        out.append("correlation_id_invalid")
    t = request.evaluation_time
    if not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None:
        out.append("evaluation_time_must_be_timezone_aware")
    if not isinstance(e.stack_root, Path) or not isinstance(e.state_dir, Path):
        out.append("environment_paths_must_be_Path")
    return out


@dataclass(frozen=True)
class Labels:
    """Fixed labels by contract; not derived from the resolver's output."""

    synthetic_authority: bool = True
    authenticated: bool = False
    evidence_basis: str = "producer_reported"
    nonproduction: bool = True
    non_authorizing: bool = True
    retry_permission: str = RETRY_PERMISSION
    not_verified: tuple[str, ...] = NOT_VERIFIED


@dataclass(frozen=True)
class FileReference:
    kind: str  # cp_run_record | runtime_export | replay_bundle
    path: str
    sha256: str  # sha256 of the exact file bytes, "sha256:<hex>"
    detail: dict = field(default_factory=dict)  # facts copied from the artifact, e.g. Replay bundle_id and status


@dataclass(frozen=True)
class EvidenceReferences:
    source: tuple[FileReference, ...] = ()
    replay: FileReference | None = None
    replay_state: str = "not_run"  # not_run | imported | import_failed
    replay_note: str | None = None


@dataclass(frozen=True)
class NativeFacts:
    cp_result: str | None = None  # authorized | hold
    cp_reasons: tuple[str, ...] = ()
    decision_id: str | None = None
    effect_id: str | None = None
    runtime_status: str | None = None  # verbatim native ExecutionResult.status
    runtime_error: str | None = None
    acknowledged: bool | None = None
    newly_executed: bool | None = None
    observed_state: str | None = None  # verbatim native observed_state; "absent" is never inferred by the adapter


@dataclass(frozen=True)
class Refusal:
    code: str
    reason: str
    source: str  # adapter | control_plane | runtime | replay


@dataclass(frozen=True)
class CleanupReport:
    ok: bool
    scratch_path: str | None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileIdentity:
    """Which approved profile and exact native manifest/action a result is bound to. Identification only; it grants nothing."""

    profile_id: str
    registry_version: str
    manifest_id: str
    manifest_version: str
    manifest_digest: str
    action_id: str
    requirement_id: str


@dataclass(frozen=True)
class DispositionResult:
    contract_version: str
    disposition: Disposition
    correlation_id: str | None
    tenant_id: str | None
    native: NativeFacts
    runtime_invoked: bool  # adapter-counted attempt at its only Runtime call site (self-reported; independent counters live in the tests)
    runtime_invocations: int
    evidence: EvidenceReferences
    refusal: Refusal | None
    error: str | None
    next_step: NextStep
    effect_absence_established: bool  # always False: absence of acknowledgment or of evidence is never absence of effect
    cleanup: CleanupReport
    labels: Labels = field(default_factory=Labels)
    mode: str = "dispose"  # dispose | reconcile
    profile: ProfileIdentity | None = None  # populated once the approved-profile pre-flight passed (including holds and unknown)
