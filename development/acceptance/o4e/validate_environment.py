"""Fail-closed structural gate on non-secret operator trust declarations.

Does not authenticate RPC/checkpoint/snapshot or qualify production.
"""
import re

H20 = re.compile(r"^0x[0-9a-f]{40}$")
H32 = re.compile(r"^0x[0-9a-f]{64}$")
SHA = re.compile(r"^sha256:[0-9a-f]{64}$")


def assess_environment(record):
    errors = []
    if not isinstance(record, dict):
        return {"status": "hold", "reasons": ["invalid_record"], "authority": "not_established"}
    if record.get("profile") != "cognous-o4e-operator-trust/1":
        errors.append("unsupported_profile")
    if record.get("classification") != "example_only":
        errors.append("live_trust_not_qualified_by_config")
    reg = record.get("registry")
    reg = reg if isinstance(reg, dict) else {}
    if type(reg.get("chain_id")) is not int or reg["chain_id"] <= 0:
        errors.append("invalid_chain")
    if not isinstance(reg.get("contract_address"), str) or not H20.fullmatch(reg["contract_address"]):
        errors.append("invalid_contract")
    if not isinstance(reg.get("runtime_bytecode_sha256"), str) or not SHA.fullmatch(reg["runtime_bytecode_sha256"]):
        errors.append("invalid_bytecode_hash")
    ck = reg.get("trusted_checkpoint")
    ck = ck if isinstance(ck, dict) else {}
    if type(ck.get("block_number")) is not int or ck["block_number"] < 0:
        errors.append("invalid_checkpoint_height")
    if not isinstance(ck.get("block_hash"), str) or not H32.fullmatch(ck["block_hash"]):
        errors.append("invalid_checkpoint_hash")
    if ck.get("source") != "independent_operator_checkpoint":
        errors.append("checkpoint_trust_not_identified")
    if reg.get("rpc_authentication") != "operator_configured_and_independently_verified":
        errors.append("rpc_trust_not_configured")
    if reg.get("reorg_policy") != "hold_on_conflict":
        errors.append("unsafe_reorg_policy")
    att = record.get("attestation")
    att = att if isinstance(att, dict) else {}
    if not isinstance(att.get("trust_snapshot_sha256"), str) or not SHA.fullmatch(att["trust_snapshot_sha256"]):
        errors.append("invalid_trust_snapshot")
    if att.get("trust_snapshot_owner") != "operator_configured":
        errors.append("trust_snapshot_not_operator_owned")
    if att.get("trusted_time_source") != "operator_controlled":
        errors.append("time_not_trusted")
    if att.get("key_lifecycle_policy") != "reject_revoked_expired_unknown":
        errors.append("unsafe_key_lifecycle")
    for field in ("audience", "subject"):
        if not isinstance(att.get(field), str) or not att[field].strip():
            errors.append("missing_" + field)
    c = record.get("controls")
    c = c if isinstance(c, dict) else {}
    if c.get("mode") != "qualification_only" or c.get("effect_dispatch") != "disabled" or c.get("institutional_grants") != "disabled" or c.get("fail_closed") is not True:
        errors.append("unsafe_execution_controls")
    return {"status": "hold", "reasons": sorted(set(errors)) or ["configuration_only_no_independent_authentication"], "authority": "not_established", "effects": "disabled"}
