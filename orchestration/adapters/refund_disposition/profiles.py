"""Closed registry of approved synthetic action profiles (M1-1; DEVELOPMENT ONLY / SYNTHETIC / NONPRODUCTION / NON-AUTHORIZING).

Controlling plan: Issue cogno-us/cognous-open-control-stack#282 (OCS-M1-ARCH-001 v0.9), requirements OCS-02 and OCS-03.

A profile only NAMES an action inside the already-pinned native Control Plane manifest. The caller selects a profile id; it never supplies manifest bytes, a
path, a grant, a scope or a limit, and selection grants no authority: native Control Plane admission, IG facts and the Runtime policy still decide. Every
value F1 needs for the selected action (adapter, requirement, permissions, payload fields, institution, domain, target, amount/unit/effect limits) is READ
from the native manifest action at call time, and the Runtime policy is built from the same values, so it can only narrow, never widen.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contract import DEFAULT_PROFILE, PROFILE_REGISTRY_VERSION, ProfileIdentity

MANIFEST_ID = "refund-integration-pilot-v1"
MANIFEST_VERSION = "1.1"
# B.commitment(manifest) of control_plane/tests/fixtures/refund_integration_v1_1.manifest.json (git blob 8f5c0788edf2f6940fa6012365b676ba2b0a32be at the CP pin)
MANIFEST_DIGEST = "sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac"
MANIFEST_RELPATH = "tests/fixtures/refund_integration_v1_1.manifest.json"
ACCOUNT_PREFIX = "urn:cognous:synthetic-account:"
_SUPPORTED_PAYLOAD_FIELDS = ("customer_id", "refund_reason", "case_reference")  # the only fields F1 can supply from the typed request


@dataclass(frozen=True)
class ApprovedProfile:
    profile_id: str
    action_id: str
    manifest_id: str
    manifest_version: str
    manifest_digest: str
    manifest_relpath: str


REGISTRY: dict[str, ApprovedProfile] = {
    "refund-routine-v1": ApprovedProfile("refund-routine-v1", "urn:cognous:action:refund-issue-routine-v1", MANIFEST_ID, MANIFEST_VERSION,
                                         MANIFEST_DIGEST, MANIFEST_RELPATH),
    "refund-high-v1": ApprovedProfile("refund-high-v1", "urn:cognous:action:refund-issue-high-v1", MANIFEST_ID, MANIFEST_VERSION,
                                      MANIFEST_DIGEST, MANIFEST_RELPATH),
}

# Honest disclosures for the high profile's synthetic review/evidence semantics (appended to the historical `not_verified` strings).
DISCLOSURES: dict[str, tuple[str, ...]] = {
    "refund-high-v1": (
        "the reviewer role of this profile is a synthetic fact alias, not authenticated institutional reviewer authority (authenticated=false)",
        "the manifest's evidence obligations are not evaluated natively (requirement evidence is empty); authorization is not verified supporting evidence",
    ),
}


class ProfileRefusal(Exception):
    def __init__(self, code: str, reason: str) -> None:
        super().__init__(f"{code}: {reason}")
        self.code, self.reason = code, reason


@dataclass(frozen=True)
class Derived:
    action_name: str
    adapter_id: str
    requirement_id: str
    permissions: tuple[str, ...]
    payload_required: tuple[str, ...]
    payload_optional: tuple[str, ...]
    allowed_target: str
    institution_id: str
    authority_domain: str
    profile_ref: str
    max_amount: float
    unit: str
    max_effects: int


def effective_profile_id(requested: str | None) -> str:
    return DEFAULT_PROFILE if requested is None else requested


def is_supported(requested: Any) -> bool:
    return requested is None or (isinstance(requested, str) and requested in REGISTRY)


def _one(items: list, what: str):
    if len(items) != 1:
        raise ProfileRefusal("profile_manifest_invalid", f"expected exactly one {what}, found {len(items)}")
    return items[0]


def _str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProfileRefusal("profile_manifest_invalid", f"{what} missing or not a non-empty string")
    return value


def derive(manifest: dict, profile: ApprovedProfile) -> Derived:
    """Read every profile-dependent value from the native manifest action. Fails closed (raises ProfileRefusal) on anything missing or ambiguous."""
    action = _one([a for a in manifest.get("actions", []) if isinstance(a, dict) and a.get("action_id") == profile.action_id], "action " + profile.action_id)
    tool_name = _str(action.get("tool_name"), "action tool_name")
    tool = _one([t for t in manifest.get("tools", []) if isinstance(t, dict) and t.get("tool_name") == tool_name and t.get("allowed") is True],
                "allowed tool for the action")
    scopes = tuple(_str(r.get("scope"), "authority_required scope") for r in action.get("authority_required", []) if isinstance(r, dict) and r.get("required", True))
    if not scopes:
        raise ProfileRefusal("profile_manifest_invalid", "action declares no required authority scope")
    tp = action.get("target_policy") or {}
    targets = tp.get("allowed_targets")
    if tp.get("allow_any_target") is not False or not isinstance(targets, list) or len(targets) != 1:
        raise ProfileRefusal("profile_manifest_invalid", "target_policy must declare exactly one allowed target and no wildcard")
    limits = action.get("effect_limits") or {}
    max_amount, max_effects = limits.get("max_amount"), limits.get("max_effects")
    if isinstance(max_amount, bool) or not isinstance(max_amount, (int, float)) or not max_amount > 0:
        raise ProfileRefusal("profile_manifest_invalid", "effect_limits.max_amount missing or not positive")
    if isinstance(max_effects, bool) or not isinstance(max_effects, int) or max_effects < 1:
        raise ProfileRefusal("profile_manifest_invalid", "effect_limits.max_effects missing or invalid")
    ctx = action.get("authority_context") or {}
    pp = action.get("payload_policy") or {}
    required, optional = tuple(pp.get("required_fields", [])), tuple(pp.get("optional_fields", []))
    if any(f not in _SUPPORTED_PAYLOAD_FIELDS for f in required + optional):
        raise ProfileRefusal("profile_manifest_invalid", "payload_policy names a field this F1 profile cannot supply")
    return Derived(
        action_name=_str(action.get("action_name"), "action_name"), adapter_id=_str(tool.get("adapter_id"), "tool adapter_id"),
        requirement_id=_str(ctx.get("requirement_id"), "authority_context.requirement_id"), permissions=scopes, payload_required=required,
        payload_optional=optional, allowed_target=_str(targets[0], "allowed target"), institution_id=_str(ctx.get("institution_id"), "institution_id"),
        authority_domain=_str(ctx.get("authority_domain"), "authority_domain"), profile_ref=_str(ctx.get("profile_ref"), "profile_ref"),
        max_amount=float(max_amount), unit=_str(limits.get("unit"), "effect_limits.unit"), max_effects=max_effects)


def load_and_check(S: Any, profile: ApprovedProfile) -> tuple[dict, Derived]:
    """Pre-flight for one approved profile against the pinned native stack: exact source identity, native validation, derivation. No Control Plane decision,
    no Runtime call and no write happens here."""
    path = Path(S.root) / "control_plane" / profile.manifest_relpath
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProfileRefusal("profile_manifest_invalid", f"approved manifest unreadable: {exc!r}") from exc
    if not isinstance(manifest, dict) or manifest.get("manifest_id") != profile.manifest_id or manifest.get("manifest_version") != profile.manifest_version:
        raise ProfileRefusal("profile_manifest_invalid", "manifest id/version differ from the approved profile")
    if S.B.commitment(manifest) != profile.manifest_digest:
        raise ProfileRefusal("profile_manifest_digest_mismatch", "manifest content digest differs from the approved profile digest")
    errors = S.B.manifest_errors(manifest)  # native Control Plane validation (E001-E025); the Control Plane re-validates on every decide()
    if errors:
        raise ProfileRefusal("profile_manifest_invalid", "native manifest validation failed: " + ",".join(map(str, errors[:5])))
    return manifest, derive(manifest, profile)


def payload_problems(profile: ApprovedProfile, derived: Derived, case_reference: Any) -> list[str]:
    """Request-shape problems against the profile's native payload policy. Only `case_reference` varies between the approved profiles."""
    out: list[str] = []
    declared = "case_reference" in derived.payload_required + derived.payload_optional
    present = case_reference is not None
    if "case_reference" in derived.payload_required and (not isinstance(case_reference, str) or not case_reference.strip()):
        out.append("case_reference_required_for_profile")
    elif present and not declared:
        out.append("case_reference_not_allowed_for_profile")
    elif present and (not isinstance(case_reference, str) or not case_reference.strip()):
        out.append("case_reference_invalid")
    return out


def identity(profile: ApprovedProfile, derived: Derived) -> ProfileIdentity:
    return ProfileIdentity(profile_id=profile.profile_id, registry_version=PROFILE_REGISTRY_VERSION, manifest_id=profile.manifest_id,
                           manifest_version=profile.manifest_version, manifest_digest=profile.manifest_digest, action_id=profile.action_id,
                           requirement_id=derived.requirement_id)
