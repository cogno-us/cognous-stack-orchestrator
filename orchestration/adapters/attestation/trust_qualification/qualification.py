"""Operator-controlled trust qualification for the accepted attestation bridge.

This module does not verify signatures, canonicalize attestations, enroll keys,
or infer institutional authority. It binds deployment configuration to the
already accepted verifier bridge and records which operator snapshot/time/identity
were used for that verification attempt.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from orchestration.adapters.attestation import verifier as accepted_bridge

QUALIFICATION_VERSION = "cognous-attestation-trust-qualification/1"
CONFIG_VERSION = "cognous-attestation-trust-config/1"
TRUST_SOURCE = "operator-configured"
TRUSTED_TIME_SOURCE = "operator-trusted-clock"

_REQUIRED_CONFIG = (
    "config_version",
    "verifier_repository",
    "verifier_revision",
    "trust_snapshot_path",
    "trust_snapshot_sha256",
    "trust_source",
    "trusted_time_source",
    "expected_issuer",
    "expected_key_id",
    "expected_audience",
)


def _base(*, status: str, reason: str) -> dict[str, Any]:
    return {
        "qualification_version": QUALIFICATION_VERSION,
        "status": status,
        "reason": reason,
        "authority": "not_established",
        "grant": "not_inferred",
        "effect": "not_observed",
        "verifier_repository": accepted_bridge.ATTESTATION_REPOSITORY,
        "verifier_revision": accepted_bridge.ATTESTATION_REVISION,
    }


def _strict_json(raw: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate member")
            result[key] = value
        return result

    def invalid(_: str) -> None:
        raise ValueError("non-JSON constant")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def _valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value[7:]
    return len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def _validate_config(config: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(config, Mapping):
        return None, "operator_trust_configuration_absent"
    if any(key not in config for key in _REQUIRED_CONFIG):
        return None, "operator_trust_configuration_incomplete"
    if config.get("config_version") != CONFIG_VERSION:
        return None, "unsupported_trust_configuration_version"
    if config.get("verifier_repository") != accepted_bridge.ATTESTATION_REPOSITORY:
        return None, "verifier_repository_pin_mismatch"
    if config.get("verifier_revision") != accepted_bridge.ATTESTATION_REVISION:
        return None, "verifier_revision_pin_mismatch"
    if config.get("trust_source") != TRUST_SOURCE:
        return None, "untrusted_snapshot_source"
    if config.get("trusted_time_source") != TRUSTED_TIME_SOURCE:
        return None, "untrusted_time_source"
    if not _valid_sha256(config.get("trust_snapshot_sha256")):
        return None, "invalid_trust_snapshot_pin"
    for field in ("expected_issuer", "expected_key_id", "expected_audience"):
        if not isinstance(config.get(field), str) or not config[field]:
            return None, field + "_absent"
    return dict(config), None


def _load_pinned_snapshot(config: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    raw_path = config["trust_snapshot_path"]
    if not isinstance(raw_path, (str, os.PathLike)):
        return None, "trusted_snapshot_path_invalid"
    path = Path(raw_path)
    if not path.is_absolute():
        return None, "trusted_snapshot_path_not_absolute"
    try:
        if not path.is_file() or path.is_symlink():
            return None, "trusted_snapshot_unavailable"
        raw = path.read_bytes()
    except OSError:
        return None, "trusted_snapshot_unavailable"
    if len(raw) > 1024 * 1024:
        return None, "trusted_snapshot_too_large"
    raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if raw_digest != config["trust_snapshot_sha256"]:
        return None, "trust_snapshot_pin_mismatch"
    try:
        registry = _strict_json(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, "trusted_snapshot_invalid"
    if not isinstance(registry, dict):
        return None, "trusted_snapshot_invalid"
    if registry.get("registry_version") != "bitrep-trust/1":
        return None, "trusted_snapshot_version_mismatch"
    if registry.get("audience") != config["expected_audience"]:
        return None, "trusted_snapshot_audience_mismatch"
    keys = registry.get("keys")
    if not isinstance(keys, list):
        return None, "trusted_snapshot_invalid"
    matches = [
        key for key in keys
        if isinstance(key, dict)
        and key.get("issuer") == config["expected_issuer"]
        and key.get("key_id") == config["expected_key_id"]
    ]
    if len(matches) != 1:
        return None, "configured_issuer_key_not_unique_in_snapshot"
    return {
        "path": str(path.resolve()),
        "raw_sha256": raw_digest,
        "registry_version": registry.get("registry_version"),
        "audience": registry.get("audience"),
    }, None


def qualify_attestation_trust(
    *,
    deployment_config: Mapping[str, Any] | None,
    verifier_checkout: str | os.PathLike[str],
    trusted_time: int | None,
    attestation: Mapping[str, Any],
    expected: Mapping[str, Any],
    bridge_verify: Callable[..., dict[str, Any]] = accepted_bridge.verify_attestation_binding,
) -> dict[str, Any]:
    """Qualify operator trust inputs and delegate cryptography to the accepted bridge.

    deployment_config is operator-controlled deployment state. Attestation and
    expected content remain untrusted/independent inputs respectively. No caller
    argument can substitute the trust path, verifier revision, or trusted-time
    provenance selected by deployment_config.
    """
    config, reason = _validate_config(deployment_config)
    if reason:
        return _base(status="unknown", reason=reason)
    assert config is not None

    if type(trusted_time) is not int or trusted_time < 0:
        return _base(status="unknown", reason="trusted_time_absent_or_invalid")
    if not isinstance(attestation, Mapping):
        return _base(status="rejected", reason="malformed_attestation")
    if not isinstance(expected, Mapping):
        return _base(status="unknown", reason="independent_reference_absent_or_invalid")
    statement = attestation.get("statement")
    if not isinstance(statement, Mapping):
        return _base(status="rejected", reason="statement_missing")

    if statement.get("issuer") != config["expected_issuer"]:
        return _base(status="rejected", reason="issuer_identity_mismatch")
    if statement.get("key_id") != config["expected_key_id"]:
        return _base(status="rejected", reason="key_identity_mismatch")
    if statement.get("audience") != config["expected_audience"]:
        return _base(status="rejected", reason="deployment_audience_mismatch")
    if expected.get("audience") != config["expected_audience"]:
        return _base(status="rejected", reason="independent_audience_mismatch")
    if expected.get("subject") != statement.get("subject"):
        return _base(status="rejected", reason="independent_subject_mismatch")
    if expected.get("content_digest") != statement.get("content_digest"):
        return _base(status="rejected", reason="independent_content_digest_mismatch")

    snapshot, reason = _load_pinned_snapshot(config)
    if reason:
        return _base(status="unknown", reason=reason)
    assert snapshot is not None

    result = bridge_verify(
        verifier_checkout=verifier_checkout,
        verifier_revision=config["verifier_revision"],
        trust_snapshot_path=snapshot["path"],
        trusted_time=trusted_time,
        attestation=attestation,
        expected=expected,
        trust_snapshot_sha256=snapshot["raw_sha256"],
    )
    if not isinstance(result, dict):
        return _base(status="failure", reason="accepted_bridge_output_invalid")

    qualified = dict(result)
    qualified.update(
        {
            "qualification_version": QUALIFICATION_VERSION,
            "operator_trust": {
                "config_version": config["config_version"],
                "trust_source": config["trust_source"],
                "trusted_time_source": config["trusted_time_source"],
                "trust_snapshot_sha256": snapshot["raw_sha256"],
                "issuer": config["expected_issuer"],
                "key_id": config["expected_key_id"],
                "audience": config["expected_audience"],
                "trusted_time": trusted_time,
            },
            "authority": "not_established",
            "grant": "not_inferred",
            "effect": "not_observed",
        }
    )
    return qualified
