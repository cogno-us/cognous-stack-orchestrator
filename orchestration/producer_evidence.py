"""O4b producer-evidence adapter: strict trust separation, no authority or effects."""
from __future__ import annotations
import hashlib
import re
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
HEX32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REGISTRY_PIN = "d5e45d275cb301d9684b543e93b05997991d1cf2"
ATTESTATION_PIN = "5b5077dafde232a7801cb425c4efddcffb468723"


def inspect_producer_evidence(
    *,
    registry_revision: str,
    registry_observation: dict[str, Any],
    content_bytes: bytes | None,
    attestation_revision: str | None = None,
    attestation_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect caller-supplied records; require external authenticated source proofs.

    The function cannot authenticate a blockchain node or verifier by itself.
    It NEVER emits a grant, authority success, executable decision or effect proof.
    """
    reasons: list[str] = []
    if registry_revision != REGISTRY_PIN or not SHA.fullmatch(registry_revision):
        reasons.append("unsupported_registry_revision")
    if not isinstance(registry_observation, dict):
        reasons.append("invalid_observation")
        registry_observation = {}
    event = registry_observation.get("event")
    args = registry_observation.get("args")
    if event != "EvidenceSubmitted" or not isinstance(args, dict):
        reasons.append("unsupported_event")
        args = {}
    for field in ("id", "claim", "content", "manifest", "statement"):
        if not isinstance(args.get(field), str) or not HEX32.fullmatch(args[field]):
            reasons.append("invalid_" + field)
    relation = args.get("relation")
    if type(relation) is not int or relation not in (1, 2):
        reasons.append("invalid_relation")
    for field in ("block_hash", "transaction_hash"):
        if not isinstance(registry_observation.get(field), str) or not HEX32.fullmatch(registry_observation[field]):
            reasons.append("missing_" + field)
    if not isinstance(registry_observation.get("log_index"), int) or type(registry_observation.get("log_index")) is bool or registry_observation["log_index"] < 0:
        reasons.append("invalid_log_index")
    if registry_observation.get("finality") not in ("provisional",) and not (
        isinstance(registry_observation.get("finality"), str)
        and re.fullmatch(r"depth:[0-9]+;not-consensus-finality", registry_observation["finality"])
    ):
        reasons.append("untrusted_finality_label")
    if reasons:
        return {"status": "rejected", "reasons": sorted(set(reasons)),
                "source_authenticity": "not_established", "authority": "not_established",
                "effect": "not_attempted"}
    content_state = "unavailable"
    if content_bytes is not None:
        if not isinstance(content_bytes, bytes):
            return {"status": "rejected", "reasons": ["invalid_content_type"],
                    "source_authenticity": "not_established", "authority": "not_established",
                    "effect": "not_attempted"}
        content_state = ("matched" if hashlib.sha256(content_bytes).hexdigest()
                         == args["content"][2:].lower() else "mismatch")

    statement_state = "not_submitted" if args["statement"].lower() == "0x" + "00" * 32 else "unverified_commitment"
    if attestation_revision is not None or attestation_verification is not None:
        if attestation_revision != ATTESTATION_PIN:
            statement_state = "unsupported_verifier_revision"
        elif not isinstance(attestation_verification, dict):
            statement_state = "no_verifier_result"
        else:
            fingerprint = attestation_verification.get("statement_digest")
            if not isinstance(fingerprint, str) or not DIGEST.fullmatch(fingerprint) or fingerprint[7:] != args["statement"][2:].lower():
                statement_state = "statement_binding_mismatch"
            elif (attestation_verification.get("result_version") == "bitrep-verification/1"
                  and attestation_verification.get("outcome") == "verified"
                  and attestation_verification.get("assurance") == "issuer_signature_only"):
                statement_state = "reported_signature_result_untrusted"
            else:
                statement_state = "rejected_or_unsupported_reported_result"

    return {"status": "inspected_untrusted", "content_binding": content_state,
            "attestation": statement_state, "source_authenticity": "not_established",
            "chain_finality": "not_established", "issuer_trust": "not_established",
            "institutional_adoption": "not_established", "authority": "not_established",
            "effect": "not_attempted", "independent_verification": "not_established"}
