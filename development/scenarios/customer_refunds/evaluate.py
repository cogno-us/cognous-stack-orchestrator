"""Synthetic refund eligibility screening; never authorizes payment."""
def evaluate(req, tenant, seen=()):
    reasons = []
    if not isinstance(req, dict):
        req = {}
        reasons.append("malformed")
    for k in ("request_id", "order_ref", "payment_ref", "purchase_evidence_ref"):
        if not isinstance(req.get(k), str) or not req[k]:
            reasons.append("missing_" + k)
    if req.get("tenant_id") != tenant: reasons.append("tenant_mismatch")
    if req.get("request_id") in seen: reasons.append("duplicate")
    a = req.get("amount_minor")
    if type(a) is not int or not 0 < a <= 10000: reasons.append("amount")
    d = req.get("purchase_age_days")
    if type(d) is not int or not 0 <= d <= 30: reasons.append("window")
    if req.get("currency") != "USD": reasons.append("currency")
    if req.get("policy_version") != "fixture-v1": reasons.append("policy")
    if req.get("approval_state") != "active": reasons.append("approval")
    if req.get("issuer_state") != "verified_issuer_only": reasons.append("issuer")
    if req.get("registry_state") != "consistent": reasons.append("registry")
    return {"screening": "eligible_for_review" if not reasons else "blocked",
            "reasons": sorted(set(reasons)), "authority": "not_established",
            "disposition": "hold", "effect": "disabled", "settlement": "not_observed"}
