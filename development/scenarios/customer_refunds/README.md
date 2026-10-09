# O5 — Customer refund qualification scenario

Status: synthetic reference only. Parent gates #30 and #14; work item #34.

Customer service receives a synthetic request with tenant ID, opaque order/customer/payment references, amount in minor currency units, refund reason, policy version, evidence reference and idempotency key. Cognous checks provenance, issuer attestation, merchant policy, human approval status and proposed Authority Context. These observations never themselves constitute a merchant grant.

Fixture policy: USD only; positive amount up to 10,000 cents; 30-day purchase window; explicit current human approval. These are illustrative settings, not an adopted merchant policy.

Positive path: eligible for accountable review; default HOLD, no payment dispatch, no settlement claim. Negative cases: cross-tenant request, missing purchase evidence, excess amount, expired purchase window, policy change, approval withdrawal, duplicate request, revoked issuer key, reorg or unavailable provider. All HOLD and leave an auditable refusal reason.

An actual refund requires an independently validated delegated grant, atomic authorization-to-effect handoff, payment processor evidence and settlement reconciliation. No real customer data or payment credentials are in scope. Local fixture CI cannot satisfy operational evidence gate #30.
