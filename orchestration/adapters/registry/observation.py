"""Read-only Cognous Evidence Registry observation adapter.

This adapter validates a caller-supplied reconstruction against an explicitly trusted
local deployment configuration.  It performs no RPC, credential handling, signing,
consensus verification, authority resolution, or effects.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Mapping

REGISTRY_REVISION = "d5e45d275cb301d9684b543e93b05997991d1cf2"
REGISTRY_SOURCE_PATH = "chain/contracts/IndexProtocol.sol"
RECONSTRUCTOR_SOURCE_PATH = "chain/reconstruct.mjs"
PROTOCOL_SOURCE_PATH = "chain/PROTOCOL.md"
POLICY_LABEL = "index-lifecycle/1"

HEX20 = re.compile(r"^0x[0-9a-fA-F]{40}$")
HEX32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
DEPTH = re.compile(r"^depth:([0-9]+);not-consensus-finality$")


@dataclass(frozen=True)
class TrustedRegistryDeployment:
    """Operator-provided deployment identity; values are trusted configuration.

    ``runtime_bytecode_hash`` is the expected sha256 digest of the runtime bytecode
    obtained through a separately trusted deployment process.  The adapter only
    compares the supplied observation to this configured value; it does not prove
    where either value came from.
    """

    chain_id: int
    contract_address: str
    source_revision: str
    runtime_bytecode_hash: str
    source_path: str = REGISTRY_SOURCE_PATH
    reconstruction_path: str = RECONSTRUCTOR_SOURCE_PATH
    policy: str = POLICY_LABEL

    def validate(self) -> list[str]:
        errors: list[str] = []
        if type(self.chain_id) is not int or self.chain_id <= 0:
            errors.append("invalid_trusted_chain_id")
        if not isinstance(self.contract_address, str) or not HEX20.fullmatch(self.contract_address):
            errors.append("invalid_trusted_contract_address")
        if self.source_revision != REGISTRY_REVISION or not SHA40.fullmatch(self.source_revision):
            errors.append("unsupported_trusted_source_revision")
        if self.source_path != REGISTRY_SOURCE_PATH:
            errors.append("unsupported_trusted_source_path")
        if self.reconstruction_path != RECONSTRUCTOR_SOURCE_PATH:
            errors.append("unsupported_trusted_reconstruction_path")
        if self.policy != POLICY_LABEL:
            errors.append("unsupported_trusted_policy")
        if not isinstance(self.runtime_bytecode_hash, str) or not HEX32.fullmatch(self.runtime_bytecode_hash):
            errors.append("invalid_trusted_bytecode_hash")
        return errors


def _failure(*reasons: str, reorg_status: str = "not_evaluated") -> dict[str, Any]:
    return {
        "status": "failed",
        "reasons": sorted(set(reasons)),
        "source_identity": "rejected",
        "observation": "not_accepted",
        "reorg_status": reorg_status,
        "chain_finality": "not_established",
        "source_authenticity": "not_independently_established",
        "authority": "not_established",
        "independent_verification": "not_established",
    }


def _unknown(reason: str) -> dict[str, Any]:
    return {
        "status": "unknown",
        "reasons": [reason],
        "source_identity": "not_fully_observed",
        "observation": "not_accepted",
        "reorg_status": "unknown",
        "chain_finality": "not_established",
        "source_authenticity": "not_independently_established",
        "authority": "not_established",
        "independent_verification": "not_established",
    }


def _valid_nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _validate_event_identity(entry: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if entry.get("event") not in {"Registered", "EvidenceSubmitted", "LifecycleChanged"}:
        errors.append("malformed_event_name")
    if not isinstance(entry.get("id"), str) or not HEX32.fullmatch(entry["id"]):
        errors.append("malformed_event_id")
    for field in ("blockHash", "transactionHash"):
        if not isinstance(entry.get(field), str) or not HEX32.fullmatch(entry[field]):
            errors.append("malformed_" + field)
    for field in ("blockNumber", "logIndex"):
        if not _valid_nonnegative_int(entry.get(field)):
            errors.append("malformed_" + field)
    if "transactionIndex" in entry and not _valid_nonnegative_int(entry.get("transactionIndex")):
        errors.append("malformed_transactionIndex")
    if entry.get("event") == "LifecycleChanged":
        if type(entry.get("lifecycle")) is not int or entry.get("lifecycle") not in (1, 2, 3):
            errors.append("malformed_lifecycle")
        if not isinstance(entry.get("successor"), str) or not HEX32.fullmatch(entry["successor"]):
            errors.append("malformed_successor")
        if not isinstance(entry.get("reason"), str) or not HEX32.fullmatch(entry["reason"]):
            errors.append("malformed_reason")
    return errors


def _commitment_status(commitment: str, content: bytes | None) -> str:
    if content is None:
        return "content_unavailable"
    if not isinstance(content, bytes):
        return "invalid_content_type"
    return "matched" if hashlib.sha256(content).hexdigest() == commitment[2:].lower() else "commitment_mismatch"


def observe_registry_snapshot(
    *,
    trusted: TrustedRegistryDeployment,
    snapshot: Mapping[str, Any] | None,
    content_bytes: Mapping[str, bytes | None] | None = None,
    previous_checkpoint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one read-only reconstruction against trusted deployment identity.

    ``snapshot`` is expected to be the source reconstructor projection plus explicit
    deployment identity supplied by the caller.  A successful result means only that
    the supplied projection is internally/source-config consistent.  It is not an RPC
    authenticity proof, consensus-finality proof, truth judgment, attestation result,
    institutional grant, or execution authorization.
    """
    config_errors = trusted.validate()
    if config_errors:
        return _failure(*config_errors)
    if snapshot is None:
        return _unknown("snapshot_unavailable")
    if not isinstance(snapshot, Mapping):
        return _failure("invalid_snapshot")

    required = (
        "chainId", "contractAddress", "sourceRevision", "sourcePath",
        "reconstructionPath", "runtimeBytecodeHash", "blockNumber", "blockHash",
        "finality", "history", "claims", "evidence",
    )
    missing = [field for field in required if field not in snapshot]
    if missing:
        return _unknown("missing_snapshot_fields:" + ",".join(sorted(missing)))

    errors: list[str] = []
    if snapshot["chainId"] != trusted.chain_id:
        errors.append("wrong_chain_id")
    address = snapshot["contractAddress"]
    if not isinstance(address, str) or address.lower() != trusted.contract_address.lower():
        errors.append("wrong_contract_address")
    if snapshot["sourceRevision"] != trusted.source_revision:
        errors.append("source_revision_mismatch")
    if snapshot["sourcePath"] != trusted.source_path:
        errors.append("source_path_mismatch")
    if snapshot["reconstructionPath"] != trusted.reconstruction_path:
        errors.append("reconstruction_path_mismatch")
    bytecode_hash = snapshot["runtimeBytecodeHash"]
    if not isinstance(bytecode_hash, str) or bytecode_hash.lower() != trusted.runtime_bytecode_hash.lower():
        errors.append("runtime_bytecode_mismatch")
    if not _valid_nonnegative_int(snapshot["blockNumber"]):
        errors.append("invalid_block_number")
    if not isinstance(snapshot["blockHash"], str) or not HEX32.fullmatch(snapshot["blockHash"]):
        errors.append("invalid_block_hash")

    finality = snapshot["finality"]
    if finality == "provisional":
        finality_status = "provisional"
    elif isinstance(finality, str) and DEPTH.fullmatch(finality):
        finality_status = finality
    else:
        errors.append("invalid_or_overstated_finality")
        finality_status = "not_established"

    claims = snapshot["claims"]
    evidence = snapshot["evidence"]
    history = snapshot["history"]
    if not isinstance(claims, Mapping):
        errors.append("invalid_claims_projection")
        claims = {}
    if not isinstance(evidence, Mapping):
        errors.append("invalid_evidence_projection")
        evidence = {}
    if not isinstance(history, list):
        errors.append("invalid_history_projection")
        history = []

    seen: set[tuple[str, str, int]] = set()
    last_order: tuple[int, int, int] | None = None
    registered_ids: set[str] = set()
    evidence_ids: set[str] = set()
    for raw in history:
        if not isinstance(raw, Mapping):
            errors.append("malformed_event")
            continue
        errors.extend(_validate_event_identity(raw))
        if any(k not in raw for k in ("blockHash", "transactionHash", "logIndex", "blockNumber")):
            continue
        if not (isinstance(raw.get("blockHash"), str) and isinstance(raw.get("transactionHash"), str)
                and _valid_nonnegative_int(raw.get("logIndex")) and _valid_nonnegative_int(raw.get("blockNumber"))):
            continue
        identity = (raw["blockHash"].lower(), raw["transactionHash"].lower(), raw["logIndex"])
        if identity in seen:
            errors.append("duplicate_event_log_identity")
        seen.add(identity)
        tx_index = raw.get("transactionIndex", 0)
        if not _valid_nonnegative_int(tx_index):
            tx_index = 0
        order = (raw["blockNumber"], tx_index, raw["logIndex"])
        if last_order is not None and order < last_order:
            errors.append("event_order_violation")
        last_order = order
        if _valid_nonnegative_int(snapshot.get("blockNumber")) and raw["blockNumber"] > snapshot["blockNumber"]:
            errors.append("event_beyond_observation_block")
        event_id = raw.get("id")
        if raw.get("event") == "Registered" and isinstance(event_id, str):
            registered_ids.add(event_id)
        elif raw.get("event") == "EvidenceSubmitted" and isinstance(event_id, str):
            evidence_ids.add(event_id)
        elif raw.get("event") == "LifecycleChanged" and isinstance(event_id, str) and event_id not in claims:
            errors.append("lifecycle_without_claim_projection")

    for claim_id in registered_ids:
        if claim_id not in claims:
            errors.append("registered_claim_missing_from_projection")
    for evidence_id in evidence_ids:
        if evidence_id not in evidence:
            errors.append("submitted_evidence_missing_from_projection")

    for claim_id, claim in claims.items():
        if not isinstance(claim_id, str) or not HEX32.fullmatch(claim_id) or not isinstance(claim, Mapping):
            errors.append("malformed_claim_projection")
            continue
        for field in ("content", "parent", "successor"):
            if not isinstance(claim.get(field), str) or not HEX32.fullmatch(claim[field]):
                errors.append("malformed_claim_" + field)
        if not isinstance(claim.get("author"), str) or not HEX20.fullmatch(claim["author"]):
            errors.append("malformed_claim_author")
        if type(claim.get("lifecycle")) is not int or claim.get("lifecycle") not in (1, 2, 3):
            errors.append("malformed_claim_lifecycle")

    for evidence_id, item in evidence.items():
        if not isinstance(evidence_id, str) or not HEX32.fullmatch(evidence_id) or not isinstance(item, Mapping):
            errors.append("malformed_evidence_projection")
            continue
        for field in ("claim", "content", "manifest", "statement"):
            if not isinstance(item.get(field), str) or not HEX32.fullmatch(item[field]):
                errors.append("malformed_evidence_" + field)
        if not isinstance(item.get("submitter"), str) or not HEX20.fullmatch(item["submitter"]):
            errors.append("malformed_evidence_submitter")
        if type(item.get("relation")) is not int or item.get("relation") not in (1, 2):
            errors.append("malformed_evidence_relation")
        if item.get("claim") not in claims:
            errors.append("evidence_claim_missing_from_projection")

    reorg_status = "no_checkpoint"
    if previous_checkpoint is not None:
        if not isinstance(previous_checkpoint, Mapping):
            errors.append("invalid_previous_checkpoint")
            reorg_status = "unknown"
        else:
            pnum = previous_checkpoint.get("blockNumber")
            phash = previous_checkpoint.get("blockHash")
            if not _valid_nonnegative_int(pnum) or not isinstance(phash, str) or not HEX32.fullmatch(phash):
                errors.append("invalid_previous_checkpoint")
                reorg_status = "unknown"
            elif pnum == snapshot.get("blockNumber") and phash.lower() != str(snapshot.get("blockHash", "")).lower():
                errors.append("replacement_block_detected")
                reorg_status = "replacement_detected"
            elif pnum > snapshot.get("blockNumber", -1):
                errors.append("observation_regressed_before_checkpoint")
                reorg_status = "regressed"
            else:
                reorg_status = "unknown"  # parent hashes are not verified: checkpoint is not linked to the observed block

    if errors:
        return _failure(*errors, reorg_status=reorg_status)

    provided = content_bytes or {}
    content_results: dict[str, str] = {}
    for kind, collection in (("claim", claims), ("evidence", evidence)):
        for object_id, item in collection.items():
            commitment = item["content"]
            content_results[f"{kind}:{object_id}"] = _commitment_status(commitment, provided.get(commitment.lower()))

    return {
        "status": "accepted_provisional",
        "reasons": [],
        "source_identity": "matches_trusted_configuration",
        "observation": "shape_checked_projection",
        "reorg_status": reorg_status,
        "chain_finality": finality_status,
        "content_bindings": content_results,
        "source_revision": trusted.source_revision,
        "source_paths": [PROTOCOL_SOURCE_PATH, trusted.source_path, trusted.reconstruction_path],
        "observed_block": {"number": snapshot["blockNumber"], "hash": snapshot["blockHash"]},
        "source_authenticity": "not_independently_established",
        "authority": "not_established",
        "independent_verification": "not_established",
    }
