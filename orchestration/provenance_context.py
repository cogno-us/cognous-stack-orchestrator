"""Read-only O4 candidate. No blockchain, signature, institution or execution authority."""
from __future__ import annotations
import hashlib
import re
from typing import Any

_HEX32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
_HEX_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
_ZERO = "0x" + "00" * 32


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def assess_reference(
    *,
    registry_event: dict[str, Any],
    reconstruction: dict[str, Any],
    content_bytes: bytes | None,
    attestation_statement: dict[str, Any] | None,
    attestation_result: dict[str, Any] | None,
    authority_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Classify *supplied* source records; never fetch, authenticate, grant or dispatch.

    The caller MUST independently establish source identity, deployment trust, log
    canonicality, trust snapshot, verifier authenticity and institutional adoption.
    In the absence of that evidence this result is only a local consistency check.
    """
    errors: list[str] = []
    if registry_event.get("event") != "EvidenceSubmitted":
        errors.append("unsupported_registry_event")
    e = registry_event.get("args", {})
    for key in ("id", "claim", "content", "manifest", "statement"):
        if not isinstance(e.get(key), str) or not _HEX32.fullmatch(e[key]):
            errors.append("invalid_event_" + key)
    if e.get("relation") not in (1, 2) or isinstance(e.get("relation"), bool):
        errors.append("invalid_relation")
    if not isinstance(reconstruction.get("blockHash"), str) or not _HEX32.fullmatch(reconstruction["blockHash"]):
        errors.append("missing_block_identity")
    if reconstruction.get("finality") not in ("provisional",) and not (
        isinstance(reconstruction.get("finality"), str)
        and re.fullmatch(r"depth:[0-9]+;not-consensus-finality", reconstruction["finality"])
    ):
        errors.append("unsupported_finality")
    if not isinstance(reconstruction.get("transactionHash"), str) or not _HEX32.fullmatch(reconstruction["transactionHash"]):
        errors.append("missing_transaction_identity")
    if errors:
        return {"status": "rejected_input", "reasons": sorted(set(errors)),
                "authority": "not_established", "effect": "not_attempted"}

    content_matches = content_bytes is not None and _digest(content_bytes) == "sha256:" + e["content"][2:].lower()
    content_status = "unavailable" if content_bytes is None else "matched" if content_matches else "mismatch"
    statement_committed = e["statement"].lower() != _ZERO
    assertion_status = "not_submitted"
    if statement_committed:
        assertion_status = "commitment_only"
        if attestation_statement is not None and attestation_result is not None:
            stmt = attestation_statement.get("statement", {})
            expected = e["statement"][2:].lower()
            fingerprint = attestation_result.get("statement_digest")
            # Digest and verifier result are caller-supplied. Verify matching
            # declared digest only, never treat it as an authenticated signature.
            if not isinstance(fingerprint, str) or not _HEX_SHA.fullmatch(fingerprint) or fingerprint[7:] != expected:
                assertion_status = "unmatched_reported_attestation"
            elif attestation_result.get("outcome") == "verified" and attestation_result.get("assurance") == "issuer_signature_only":
                assertion_status = "reported_issuer_signature_only_untrusted"
            else:
                assertion_status = "reported_attestation_not_verified"

    context_status = "not_provided"
    if authority_context is not None:
        if (authority_context.get("schema_version") == "0.1.0"
                and authority_context.get("interface_status") == "proposed_pending_governor_review"):
            context_status = "proposed_requirements_only"
        else:
            context_status = "unrecognized_context"

    return {
        "status": "local_consistency_only",
        "content_binding": content_status,
        "registry_claim_ref": e["claim"],
        "registry_evidence_ref": e["id"],
        "evidence_relation": "support_assertion" if e["relation"] == 1 else "challenge_assertion",
        "registry_finality": reconstruction["finality"],
        "attestation": assertion_status,
        "institutional_context": context_status,
        "chain_authenticity": "not_established",
        "issuer_trust": "not_established",
        "institutional_adoption": "not_established",
        "authority": "not_established",
        "effect": "not_attempted",
        "independent_effect_verification": "not_established",
    }
