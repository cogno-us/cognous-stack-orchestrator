"""Pinned bridge to the Cognous Evidence Attestation v1 verifier.

This adapter deliberately delegates signature/canonicalization work to the exact
accepted upstream source. It does not infer institutional authority from a valid
issuer signature.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping

ATTESTATION_REPOSITORY = "cogno-us/cognous-evidence-attestation"
ATTESTATION_REVISION = "5b5077dafde232a7801cb425c4efddcffb468723"
RESULT_VERSION = "cognous-orchestrator-attestation-bridge/1"

# Git blob IDs at ATTESTATION_REVISION. Only these upstream modules are copied
# into the isolated execution directory; no cryptographic implementation is
# copied into this repository.
PINNED_SOURCE_BLOBS = {
    "models/__init__.py": "3c159a665535afa10f8749a7c189adbf36f741fb",
    "models/verification.py": "97f3d30aed2ffed41f31253e3bb3242691bdbbf2",
    "utils/__init__.py": "db3e3278dabf73020f4a939cd10bdded2bc377e8",
    "utils/trust.py": "b001689ed7c6554d3e3dce3b91285d30e99d7822",
    "utils/verification.py": "1672b5105b5a17d141402da62483736a1d266e2f",
}

_RUNNER = r'''
import json, os, sys
root = sys.argv[1]
now = int(sys.argv[2])
sys.path.insert(0, root)
from models.verification import AttestationEnvelope
from utils.trust import load_registry, strict_json, TrustUnavailable
from utils.verification import verify_attestation
try:
    raw = sys.stdin.buffer.read()
    att = AttestationEnvelope.model_validate(strict_json(raw))
    registry = load_registry()
    result = verify_attestation(att, registry, now)
    print(json.dumps({"kind":"result","verification":result.model_dump()}, sort_keys=True))
except TrustUnavailable as exc:
    print(json.dumps({"kind":"trust_unavailable","reason":str(exc)}, sort_keys=True))
except Exception as exc:
    print(json.dumps({"kind":"invalid_input","reason":exc.__class__.__name__}, sort_keys=True))
'''


def _base(*, status: str, reason: str) -> dict[str, Any]:
    return {
        "result_version": RESULT_VERSION,
        "status": status,
        "reason": reason,
        "verifier_repository": ATTESTATION_REPOSITORY,
        "verifier_revision": ATTESTATION_REVISION,
        "authority": "not_established",
        "independent_authenticity": "not_claimed",
    }


def _git_blob_id(path: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "hash-object", "--no-filters", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env={"PATH": os.environ.get("PATH", "")},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("source_hash_unavailable") from exc
    if proc.returncode != 0:
        raise RuntimeError("source_hash_failed")
    return proc.stdout.strip()


def _copy_pinned_source(checkout: Path, destination: Path) -> None:
    for relative, expected_blob in PINNED_SOURCE_BLOBS.items():
        source = checkout / relative
        if not source.is_file() or source.is_symlink():
            raise RuntimeError("pinned_source_missing")
        if _git_blob_id(source) != expected_blob:
            raise RuntimeError("pinned_source_mismatch")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _valid_expected(expected: Mapping[str, Any]) -> bool:
    required = ("statement", "statement_digest", "content_digest", "audience", "subject")
    if not all(key in expected for key in required):
        return False
    return (
        isinstance(expected["statement"], dict)
        and isinstance(expected["statement_digest"], str)
        and isinstance(expected["content_digest"], str)
        and isinstance(expected["audience"], str)
        and isinstance(expected["subject"], str)
    )


def verify_attestation_binding(
    *,
    verifier_checkout: str | os.PathLike[str],
    verifier_revision: str,
    trust_snapshot_path: str | os.PathLike[str] | None,
    trusted_time: int | None,
    attestation: Mapping[str, Any],
    expected: Mapping[str, Any],
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Verify a signed attestation and independently bind what the consumer uses.

    trust_snapshot_path and trusted_time are operator configuration. The
    attestation is untrusted wire input. expected must come from an independent
    consumer/source reference; caller-supplied verification JSON is never used.
    """
    if verifier_revision != ATTESTATION_REVISION:
        return _base(status="rejected", reason="unsupported_verifier_revision")
    if trust_snapshot_path is None:
        return _base(status="unknown", reason="trusted_snapshot_absent")
    if type(trusted_time) is not int or trusted_time < 0:
        return _base(status="unknown", reason="trusted_time_absent_or_invalid")
    if not isinstance(attestation, Mapping):
        return _base(status="rejected", reason="malformed_attestation")
    if not isinstance(expected, Mapping) or not _valid_expected(expected):
        return _base(status="unknown", reason="independent_reference_absent_or_invalid")

    checkout = Path(verifier_checkout).resolve()
    trust_path = Path(trust_snapshot_path).resolve()
    if not trust_path.is_file() or trust_path.is_symlink():
        return _base(status="unknown", reason="trusted_snapshot_unavailable")
    try:
        trust_bytes = trust_path.read_bytes()
    except OSError:
        return _base(status="unknown", reason="trusted_snapshot_unavailable")
    if len(trust_bytes) > 1024 * 1024:
        return _base(status="failure", reason="trusted_snapshot_too_large")

    try:
        attestation_bytes = json.dumps(
            attestation, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    except (TypeError, UnicodeEncodeError, ValueError):
        return _base(status="rejected", reason="malformed_attestation")
    if len(attestation_bytes) > 64 * 1024:
        return _base(status="rejected", reason="attestation_too_large")

    try:
        with tempfile.TemporaryDirectory(prefix="cognous-attestation-") as tmp:
            isolated = Path(tmp) / "upstream"
            isolated.mkdir()
            _copy_pinned_source(checkout, isolated)
            isolated_trust = Path(tmp) / "trust.json"
            isolated_trust.write_bytes(trust_bytes)
            env = {
                "PATH": os.environ.get("PATH", ""),
                "BITREP_TRUST_REGISTRY": str(isolated_trust),
                "PYTHONHASHSEED": "0",
            }
            proc = subprocess.run(
                [sys.executable, "-I", "-c", _RUNNER, str(isolated), str(trusted_time)],
                input=attestation_bytes,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
                env=env,
            )
    except RuntimeError as exc:
        return _base(status="failure", reason=str(exc))
    except subprocess.TimeoutExpired:
        return _base(status="failure", reason="verifier_timeout")
    except OSError:
        return _base(status="failure", reason="verifier_process_unavailable")

    if proc.returncode != 0:
        return _base(status="failure", reason="verifier_process_failed")
    try:
        message = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _base(status="failure", reason="verifier_output_invalid")
    if not isinstance(message, dict):
        return _base(status="failure", reason="verifier_output_invalid")
    if message.get("kind") == "trust_unavailable":
        return _base(status="unknown", reason="trusted_snapshot_invalid_or_stale")
    if message.get("kind") == "invalid_input":
        return _base(status="rejected", reason="malformed_attestation")
    verification = message.get("verification")
    if message.get("kind") != "result" or not isinstance(verification, dict):
        return _base(status="failure", reason="verifier_output_invalid")

    result = _base(status="rejected", reason="upstream_rejected")
    result["upstream_verification"] = verification
    if (
        verification.get("outcome") != "verified"
        or verification.get("assurance") != "issuer_signature_only"
    ):
        result["reason"] = str(verification.get("reason") or "upstream_rejected")
        return result

    statement = attestation.get("statement")
    if not isinstance(statement, dict):
        result["reason"] = "statement_missing"
        return result
    if verification.get("statement_digest") != expected["statement_digest"]:
        result["reason"] = "statement_digest_mismatch"
        return result
    for field in ("content_digest", "audience", "subject"):
        if statement.get(field) != expected[field]:
            result["reason"] = field + "_mismatch"
            return result
    if statement != expected["statement"]:
        result["reason"] = "statement_mismatch"
        return result

    result["status"] = "verified"
    result["reason"] = "issuer_signature_and_binding_verified"
    result["issuer_authenticity"] = "verified_under_configured_snapshot_and_time"
    return result
