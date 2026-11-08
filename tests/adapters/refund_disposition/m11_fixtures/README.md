# M1-1 synthetic IG fixtures, profile refund-high-v1
DEVELOPMENT ONLY. SYNTHETIC. NOT INSTITUTIONAL AUTHORITY. NOT AUTHENTICATED (authenticated=false in the
product sense; the IG fact `identity.authenticated` is only a synthetic fixture assertion). Non-authorizing evidence.
Action: urn:cognous:action:refund-issue-high-v1 (pinned CP manifest refund_integration_v1_1). Tier T2.
Tenant m11-tenant; authority urn:cognous:authority:m11-high-refund-root-1; institution/domain as the manifest.
Scope: refund_issue_high_consequence, refund.issue.high, customer-002, <=1000.00 USD, 1 effect.
Use with evaluation_time 2026-10-05T19:00:00+00:00 (same as the G2 IG fixtures).

- high_lineage_valid.json: one asserted origin for the authority id above; no mutations.
- high_lineage_revoked.json: same origin plus a `revoke` mutation (r1 -> r2); expected CP hold `grant_revoked`.
- high_facts.json: requirement refund-high-v1 (evidence: []), approval role `urn:cognous:role:refund-authorizer`
  and alias `refund-authorizer`, which is a synthetic alias and not a real reviewer or approval.
  `evidence: []` means no evidence obligation is checked; it must not be read as evidence satisfied.
Ids are prefixed urn:cognous:m11-synthetic:. Validated on frozen F1 with high-profile constants:
150.00 and 1000.00 execute; 1000.01 holds amount_exceeded, grant_scope_mismatch, requirement_scope_mismatch.
