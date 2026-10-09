"""Compose synthetic refund domain references. Never issues grants or effects."""
import importlib.util
from pathlib import Path
p=Path(__file__).with_name("evaluate.py")
s=importlib.util.spec_from_file_location("o5_refund_screen",p)
screen=importlib.util.module_from_spec(s)
s.loader.exec_module(screen)

def compose(request, references, *, tenant, seen=()):
    result=screen.evaluate(request,tenant,seen)
    faults=list(result["reasons"])
    refs=references if isinstance(references,dict) else {}
    expected={
        "registry":("source_status","consistent_observation"),
        "attestation":("verification","issuer_signature_only"),
        "institutional":("authority","not_established"),
        "exchange":("delivery","receipt_only"),
    }
    for component,(field,value) in expected.items():
        record=refs.get(component)
        if not isinstance(record,dict) or record.get(field)!=value:
            faults.append("invalid_"+component+"_reference")
        elif record.get("tenant_id")!=tenant or record.get("request_id")!=request.get("request_id"):
            faults.append("binding_mismatch_"+component)
    for name in ("decision_id","effect_id","executor_attempt_id"):
        if name in refs:
            faults.append("forbidden_"+name+"_assertion")
    return {"scenario":"customer_refund","request_id":request.get("request_id") if isinstance(request,dict) else None,
            "tenant_id":tenant,"screening":result["screening"],"faults":sorted(set(faults)),
            "registry_reference":"reported_unverified" if isinstance(refs.get("registry"),dict) else "missing",
            "attestation_assurance":"issuer_signature_only" if "invalid_attestation_reference" not in faults and "binding_mismatch_attestation" not in faults else "unverified",
            "institutional_authority":"not_established","transport_receipt":"not_authorization",
            "authorization":"not_established","effect":"disabled","settlement":"not_observed",
            "disposition":"hold"}
