"""Offline O4e evidence completeness gate; never authenticates evidence or grants authority."""
import re
from urllib.parse import urlsplit

HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_NEGATIVES = ("wrong_chain", "wrong_contract", "reorg", "rpc_unavailable", "revoked_key", "expired_key", "uncertain_time")

def evidence_ref(value):
    if not isinstance(value, dict):
        return False
    url = value.get("url")
    digest = value.get("sha256")
    if not isinstance(url, str) or not isinstance(digest, str) or not HEX64.fullmatch(digest):
        return False
    p = urlsplit(url)
    return p.scheme == "https" and bool(p.netloc) and not p.username and not p.password and not p.query and not p.fragment

def assess(packet):
    missing = []
    if not isinstance(packet, dict):
        return {"status": "hold", "authority": "not_established", "effect": "disabled", "evidence": "unverified", "missing": ["packet"]}
    if packet.get("schema") != "cognous-o4e-evidence/1":
        missing.append("schema")
    for name in ("environment_id", "operator_identity", "deployment_revision", "observed_at_utc"):
        if not isinstance(packet.get(name), str) or not packet[name].strip():
            missing.append(name)
    refs = packet.get("references") if isinstance(packet.get("references"), dict) else {}
    for name in ("rpc_authentication", "independent_checkpoint", "receipt_log_provenance", "deployed_bytecode", "attestation_trust_snapshot", "trusted_clock", "upstream_verifier", "key_lifecycle"):
        if not evidence_ref(refs.get(name)):
            missing.append("references." + name)
    neg = packet.get("negative_tests") if isinstance(packet.get("negative_tests"), dict) else {}
    for name in REQUIRED_NEGATIVES:
        if not evidence_ref(neg.get(name)):
            missing.append("negative_tests." + name)
    return {"status": "hold", "authority": "not_established", "effect": "disabled", "evidence": "submitted_unverified" if not missing else "incomplete", "missing": sorted(missing)}
