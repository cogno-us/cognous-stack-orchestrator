# O5-C-A — Refund Manifest / Control Plane qualification

Issue: #38. This path is a **synthetic, fixture-only contract qualification**. It does not issue institutional grants, execute refund effects, access payment systems, or establish settlement.

Accepted source pins used by this qualification:

- Action Manifest: `ff5490828b2bf7f6a976da209f3f533701855687`
- Control Plane: `e66e5f163c5d5c112ff345a2f332b4c3893ee183`
- Orchestrator starting base: `0aaaa11d1795e4e0cbf081826e9e1d1b3d5ca850`

The adapter maps the synthetic O5 refund request into the accepted Manifest refund declaration and tenant-aware runtime proposal shape. Authority inputs are treated only as fixture observations. A clean fixture can qualify the mapping, but the returned Control Plane disposition remains `hold` because this repository does not contain a live authenticated institutional authority resolver.

Fail-closed cases covered here include missing delegated authority, stale/changed policy, revoked approval, tenant mismatch, and request-digest substitution. The adapter never fabricates a grant, decision ID, effect ID, execution acknowledgement, observation, or settlement result.

If the accepted upstream Python packages are present in the test environment, tests exercise their proposal/binding models. In the ordinary orchestrator CI checkout those packages are absent; that path is reported explicitly as `fixture_stub`, not as live integration.
