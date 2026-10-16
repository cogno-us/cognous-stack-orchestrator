"""Authenticated, read-only observation of the pinned Evidence Registry deployment.

Authentication is deliberately bounded: an operator chooses a trusted deployment
and RPC endpoint, and may additionally pin an independently obtained block
checkpoint. Receipt/log/block consistency is checked against that trust root. A
successful result is not consensus finality, truth, an attestation result, an
institutional grant, or an execution authorization.

Pinned upstream source:
  cogno-us/cognous-evidence-registry@
  d5e45d275cb301d9684b543e93b05997991d1cf2
  chain/contracts/IndexProtocol.sol (blob 7105d02810a58935cd6f5d514829f0a632088e5f)
  chain/reconstruct.mjs             (blob 797f46414acef9936e8c572f9a52e9d45e26126a)
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Protocol, Sequence
from urllib import request

REGISTRY_REVISION = "d5e45d275cb301d9684b543e93b05997991d1cf2"
REGISTRY_SOURCE_PATH = "chain/contracts/IndexProtocol.sol"
REGISTRY_SOURCE_BLOB = "7105d02810a58935cd6f5d514829f0a632088e5f"
RECONSTRUCTOR_SOURCE_PATH = "chain/reconstruct.mjs"
RECONSTRUCTOR_SOURCE_BLOB = "797f46414acef9936e8c572f9a52e9d45e26126a"

HEX20 = re.compile(r"^0x[0-9a-fA-F]{40}$")
HEX32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RegistryObservationError(RuntimeError):
    """Transport/source observation failure mapped to an explicit unknown result."""


class JsonRpc(Protocol):
    def call(self, method: str, params: Sequence[Any]) -> Any: ...


@dataclass(frozen=True)
class TrustedCheckpoint:
    """Block hash obtained through a channel independent of the queried RPC."""

    block_number: int
    block_hash: str

    def validate(self) -> list[str]:
        errors: list[str] = []
        if type(self.block_number) is not int or self.block_number < 0:
            errors.append("invalid_checkpoint_block_number")
        if not isinstance(self.block_hash, str) or not HEX32.fullmatch(self.block_hash):
            errors.append("invalid_checkpoint_block_hash")
        return errors


@dataclass(frozen=True)
class TrustedRegistrySource:
    """Explicit operator trust configuration for one Registry deployment."""

    chain_id: int
    contract_address: str
    runtime_bytecode_sha256: str
    rpc_endpoint_id: str
    source_revision: str = REGISTRY_REVISION
    source_path: str = REGISTRY_SOURCE_PATH
    confirmations: int = 0
    checkpoint: TrustedCheckpoint | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if type(self.chain_id) is not int or self.chain_id <= 0:
            errors.append("invalid_trusted_chain_id")
        if not isinstance(self.contract_address, str) or not HEX20.fullmatch(self.contract_address):
            errors.append("invalid_trusted_contract_address")
        if not isinstance(self.runtime_bytecode_sha256, str) or not SHA256.fullmatch(
            self.runtime_bytecode_sha256
        ):
            errors.append("invalid_trusted_runtime_bytecode_sha256")
        if not isinstance(self.rpc_endpoint_id, str) or not self.rpc_endpoint_id.strip():
            errors.append("missing_rpc_endpoint_id")
        if self.source_revision != REGISTRY_REVISION:
            errors.append("unsupported_source_revision")
        if self.source_path != REGISTRY_SOURCE_PATH:
            errors.append("unsupported_source_path")
        if type(self.confirmations) is not int or self.confirmations < 0:
            errors.append("invalid_confirmation_depth")
        if self.checkpoint is not None:
            errors.extend(self.checkpoint.validate())
        return errors


class UrlJsonRpcClient:
    """Minimal read-only JSON-RPC transport. Credentials are not embedded or logged."""

    def __init__(self, url: str, *, timeout_seconds: float = 10.0):
        self._url = url
        self._timeout = timeout_seconds
        self._next_id = 1

    def call(self, method: str, params: Sequence[Any]) -> Any:
        body = json.dumps(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": list(params)}
        ).encode("utf-8")
        self._next_id += 1
        req = request.Request(
            self._url,
            data=body,
            method="POST",
            headers={"content-type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RegistryObservationError("rpc_unavailable") from exc
        if not isinstance(payload, Mapping) or payload.get("error") is not None:
            raise RegistryObservationError("rpc_error")
        if "result" not in payload:
            raise RegistryObservationError("rpc_malformed_response")
        return payload["result"]


def _hex_int(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ValueError("invalid_" + field)
    try:
        parsed = int(value, 16)
    except ValueError as exc:
        raise ValueError("invalid_" + field) from exc
    if parsed < 0:
        raise ValueError("invalid_" + field)
    return parsed


def _failure(reasons: Sequence[str], *, trust_model: str, reorg_status: str = "not_evaluated") -> dict[str, Any]:
    return {
        "status": "failed",
        "reasons": sorted(set(reasons)),
        "observation": "not_accepted",
        "source_authentication": "rejected",
        "trust_model": trust_model,
        "reorg_status": reorg_status,
        "chain_finality": "not_established",
        "authority": "not_established",
        "effect": "not_established",
        "independent_verification": "not_established",
    }


def _unknown(reason: str, *, trust_model: str) -> dict[str, Any]:
    return {
        "status": "unknown",
        "reasons": [reason],
        "observation": "not_accepted",
        "source_authentication": "not_established",
        "trust_model": trust_model,
        "reorg_status": "unknown",
        "chain_finality": "not_established",
        "authority": "not_established",
        "effect": "not_established",
        "independent_verification": "not_established",
    }


def _trust_model(trusted: TrustedRegistrySource) -> str:
    return (
        "operator-configured-rpc"
        if trusted.checkpoint is None
        else "operator-configured-rpc+independent-checkpoint"
    )


def _address(value: Any) -> str | None:
    if not isinstance(value, str) or not HEX20.fullmatch(value):
        return None
    return value.lower()


def _hash(value: Any) -> str | None:
    if not isinstance(value, str) or not HEX32.fullmatch(value):
        return None
    return value.lower()


def _log_identity(log: Mapping[str, Any]) -> tuple[str, str, int] | None:
    block_hash = _hash(log.get("blockHash"))
    tx_hash = _hash(log.get("transactionHash"))
    try:
        log_index = _hex_int(log.get("logIndex"), "log_index")
    except ValueError:
        return None
    if block_hash is None or tx_hash is None:
        return None
    return block_hash, tx_hash, log_index


def _log_content(log: Mapping[str, Any]) -> tuple[str | None, tuple[str, ...] | None, str | None, Any]:
    topics = log.get("topics")
    if isinstance(topics, list) and all(isinstance(t, str) for t in topics):
        normalized_topics: tuple[str, ...] | None = tuple(t.lower() for t in topics)
    else:
        normalized_topics = None
    data = log.get("data")
    return (
        _address(log.get("address")),
        normalized_topics,
        data.lower() if isinstance(data, str) else None,
        log.get("removed", False),
    )


def observe_authenticated_registry(*, trusted: TrustedRegistrySource, rpc: JsonRpc) -> dict[str, Any]:
    """Observe one deployment without producing grants, effects, or truth status."""

    trust_model = _trust_model(trusted)
    config_errors = trusted.validate()
    if config_errors:
        return _failure(config_errors, trust_model=trust_model)

    try:
        if _hex_int(rpc.call("eth_chainId", []), "chain_id") != trusted.chain_id:
            return _failure(["wrong_chain_id"], trust_model=trust_model)

        head = _hex_int(rpc.call("eth_blockNumber", []), "head_block")
        observed_number = head - trusted.confirmations
        if observed_number < 0:
            return _failure(["insufficient_confirmation_depth"], trust_model=trust_model)
        block_tag = hex(observed_number)

        before = rpc.call("eth_getBlockByNumber", [block_tag, False])
        if not isinstance(before, Mapping):
            return _failure(["observation_block_unavailable"], trust_model=trust_model)
        observed_hash = _hash(before.get("hash"))
        if observed_hash is None:
            return _failure(["malformed_observation_block_hash"], trust_model=trust_model)

        code = rpc.call("eth_getCode", [trusted.contract_address, block_tag])
        if not isinstance(code, str) or not code.startswith("0x") or len(code) <= 2:
            return _failure(["contract_code_unavailable"], trust_model=trust_model)
        try:
            code_bytes = bytes.fromhex(code[2:])
        except ValueError:
            return _failure(["malformed_runtime_bytecode"], trust_model=trust_model)
        code_hash = hashlib.sha256(code_bytes).hexdigest()
        if code_hash.lower() != trusted.runtime_bytecode_sha256.lower():
            return _failure(["runtime_bytecode_mismatch"], trust_model=trust_model)

        if trusted.checkpoint is not None:
            if trusted.checkpoint.block_number > observed_number:
                return _failure(["checkpoint_ahead_of_observation"], trust_model=trust_model)
            checkpoint = rpc.call(
                "eth_getBlockByNumber", [hex(trusted.checkpoint.block_number), False]
            )
            if not isinstance(checkpoint, Mapping):
                return _failure(["checkpoint_block_unavailable"], trust_model=trust_model)
            if _hash(checkpoint.get("hash")) != trusted.checkpoint.block_hash.lower():
                return _failure(["trusted_checkpoint_mismatch"], trust_model=trust_model)

        logs = rpc.call(
            "eth_getLogs",
            [{"address": trusted.contract_address, "fromBlock": "0x0", "toBlock": block_tag}],
        )
        if not isinstance(logs, list):
            return _failure(["malformed_log_response"], trust_model=trust_model)

        errors: list[str] = []
        verified_logs: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int]] = set()
        last_order: tuple[int, int, int] | None = None
        checked_blocks: dict[int, str] = {}

        for raw in logs:
            if not isinstance(raw, Mapping):
                errors.append("malformed_log")
                continue
            if raw.get("removed") is True:
                errors.append("removed_log")
            if _address(raw.get("address")) != trusted.contract_address.lower():
                errors.append("log_contract_mismatch")

            identity = _log_identity(raw)
            if identity is None:
                errors.append("malformed_log_identity")
                continue
            if identity in seen:
                errors.append("duplicate_log_identity")
            seen.add(identity)

            try:
                block_number = _hex_int(raw.get("blockNumber"), "log_block_number")
                tx_index = _hex_int(raw.get("transactionIndex", "0x0"), "transaction_index")
                log_index = _hex_int(raw.get("logIndex"), "log_index")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            order = (block_number, tx_index, log_index)
            if last_order is not None and order < last_order:
                errors.append("log_order_violation")
            last_order = order
            if block_number > observed_number:
                errors.append("log_beyond_observation_block")

            block_hash = checked_blocks.get(block_number)
            if block_hash is None:
                event_block = rpc.call("eth_getBlockByNumber", [hex(block_number), False])
                if not isinstance(event_block, Mapping):
                    errors.append("log_block_unavailable")
                    continue
                block_hash = _hash(event_block.get("hash"))
                if block_hash is None:
                    errors.append("malformed_log_block_hash")
                    continue
                checked_blocks[block_number] = block_hash
            if block_hash != identity[0]:
                errors.append("log_block_hash_mismatch")

            receipt = rpc.call("eth_getTransactionReceipt", [identity[1]])
            if not isinstance(receipt, Mapping):
                errors.append("receipt_unavailable")
                continue
            if _hash(receipt.get("transactionHash")) != identity[1]:
                errors.append("receipt_transaction_mismatch")
            if _hash(receipt.get("blockHash")) != identity[0]:
                errors.append("receipt_block_hash_mismatch")
            try:
                receipt_number = _hex_int(receipt.get("blockNumber"), "receipt_block_number")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if receipt_number != block_number:
                errors.append("receipt_block_number_mismatch")
            if receipt.get("status") is not None:
                try:
                    if _hex_int(receipt.get("status"), "receipt_status") != 1:
                        errors.append("receipt_unsuccessful")
                except ValueError as exc:
                    errors.append(str(exc))
            if receipt.get("to") is not None and _address(receipt.get("to")) != trusted.contract_address.lower():
                errors.append("receipt_contract_mismatch")

            receipt_logs = receipt.get("logs")
            if not isinstance(receipt_logs, list):
                errors.append("receipt_logs_unavailable")
                continue
            receipt_matches = [
                item
                for item in receipt_logs
                if isinstance(item, Mapping) and _log_identity(item) == identity
            ]
            if not receipt_matches:
                errors.append("log_missing_from_receipt")
            else:
                raw_content = _log_content(raw)
                if raw_content[1] is None or raw_content[2] is None:
                    errors.append("malformed_log_content")
                for item in receipt_matches:
                    item_content = _log_content(item)
                    if item_content[0] != trusted.contract_address.lower():
                        errors.append("receipt_log_contract_mismatch")
                    if item_content[1:] != raw_content[1:]:
                        errors.append("receipt_log_content_mismatch")

            verified_logs.append(
                {
                    "block_hash": identity[0],
                    "transaction_hash": identity[1],
                    "log_index": log_index,
                    "block_number": block_number,
                }
            )

        after = rpc.call("eth_getBlockByNumber", [block_tag, False])
        if not isinstance(after, Mapping) or _hash(after.get("hash")) != observed_hash:
            errors.append("replacement_block_detected")
            reorg_status = "replacement_detected"
        else:
            reorg_status = "stable_during_observation"

        if errors:
            return _failure(errors, trust_model=trust_model, reorg_status=reorg_status)

        finality = (
            "provisional"
            if trusted.confirmations == 0
            else f"depth:{trusted.confirmations};not-consensus-finality"
        )
        return {
            "status": "accepted_provisional",
            "reasons": [],
            "observation": "receipt-log-block-provenance-consistent",
            "source_authentication": "matches-explicit-trusted-deployment-and-rpc-provenance",
            "trust_model": trust_model,
            "rpc_endpoint_id": trusted.rpc_endpoint_id,
            "chain_id": trusted.chain_id,
            "contract_address": trusted.contract_address.lower(),
            "runtime_bytecode_sha256": code_hash,
            "source_revision": trusted.source_revision,
            "source_path": trusted.source_path,
            "source_blob_sha": REGISTRY_SOURCE_BLOB,
            "reconstructor_path": RECONSTRUCTOR_SOURCE_PATH,
            "reconstructor_blob_sha": RECONSTRUCTOR_SOURCE_BLOB,
            "observed_block": {"number": observed_number, "hash": observed_hash},
            "trusted_checkpoint": (
                None
                if trusted.checkpoint is None
                else {"number": trusted.checkpoint.block_number, "hash": trusted.checkpoint.block_hash.lower()}
            ),
            "verified_log_count": len(verified_logs),
            "verified_logs": verified_logs,
            "reorg_status": reorg_status,
            "chain_finality": finality,
            "authority": "not_established",
            "effect": "not_established",
            "independent_verification": (
                "checkpoint_anchor_only" if trusted.checkpoint is not None else "not_established"
            ),
            "limitations": [
                "rpc_operator_and_transport_remain_trusted_outside_independent_checkpoint_conflicts",
                "confirmation_depth_is_not_consensus_finality",
                "receipt_log_and_block_consistency_does_not_establish_truth_or_institutional_authority",
                "no_grants_or_effects_are_issued",
            ],
        }
    except RegistryObservationError as exc:
        return _unknown(str(exc), trust_model=trust_model)
    except (OSError, ValueError, TypeError, KeyError):
        return _unknown("rpc_or_source_observation_error", trust_model=trust_model)
