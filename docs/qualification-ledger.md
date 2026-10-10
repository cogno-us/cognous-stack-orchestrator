# Qualification ledger — current status and historical evidence

This is a navigation ledger, **not** a release lock, institutional authority grant, or operational deployment certificate. For currently selected revisions use the [hub component lock](https://github.com/cogno-us/cognous-open-control-stack/blob/main/component-lock.json) and [support status](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/release-status.md); accepted synthetic orchestration does not select a newer release.

| Scope | Accepted evidence | What it establishes |
|---|---|---|
| Historical bounded V1 hub reference | [Hub PR #63](https://github.com/cogno-us/cognous-open-control-stack/pull/63), [source-derived CI 37858259590](https://github.com/cogno-us/cognous-open-control-stack/actions/runs/37858259590) | Historical checkpoint with 71 scoped tests at its recorded head. The former “release authorization pending” label belongs to that checkpoint, not the current hub status. |
| O5-E actual-source synthetic connected refund | [Combined PR #64](https://github.com/cogno-us/cognous-stack-orchestrator/pull/64), [CI 38002063275](https://github.com/cogno-us/cognous-stack-orchestrator/actions/runs/38002063275) | Pinned Manifest, Control Plane, Runtime, Replay and Evidence Pack connected in a bounded **synthetic** test. No real settlement or authenticated institutional grant. |
| O6-Q2 source-candidate regression | [PR #75](https://github.com/cogno-us/cognous-stack-orchestrator/pull/75), [CI 38046644074](https://github.com/cogno-us/cognous-stack-orchestrator/actions/runs/38046644074) | Newer Runtime regression plus independent GAX and Attestation source tests; **not** yet a single three-profile trajectory. |
| O6-Q3 optional profile synthetic composition | [PR #77](https://github.com/cogno-us/cognous-stack-orchestrator/pull/77), [CI 38061972573](https://github.com/cogno-us/cognous-stack-orchestrator/actions/runs/38061972573) | Same-process test-owned composition of digest custody, generation fence and revocation store. |
| O6-Q4 actual-source synthetic handoff and fence | [PR #79](https://github.com/cogno-us/cognous-stack-orchestrator/pull/79), [CI 38062399523](https://github.com/cogno-us/cognous-stack-orchestrator/actions/runs/38062399523) | Control Plane-issued synthetic claim exercised through actual pinned GAX and Runtime interfaces; no production execution chain. |
| O6-Q5 read-only candidate admission | [PR #81](https://github.com/cogno-us/cognous-stack-orchestrator/pull/81), [CI 38064050656](https://github.com/cogno-us/cognous-stack-orchestrator/actions/runs/38064050656) | Lock/candidate drift controls, intentional **HOLD**, no release promotion. |
| O6-Q6 restart and adapter reconciliation | [PR #83](https://github.com/cogno-us/cognous-stack-orchestrator/pull/83), [CI 38065062081](https://github.com/cogno-us/cognous-stack-orchestrator/actions/runs/38065062081) | Opt-in original-attempt recovery with no blind retry; observation provenance is caller-supplied, not independently authenticated. |
| External ISS client interface | [Disabled placeholder](../integrations/iss/README.md) | Not implemented here or qualified for execution. |
| Operational environment trust | [Issue #30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30) | **HOLD / NOT ESTABLISHED**; no independent deployment evidence accepted. |

## How to read the evidence

Use the **exact PR head, source pins, test commands, CI run ID and accepted merge commit** within each linked qualification; do not add populations from distinct historical campaigns. Replay/Evidence Pack validation does not independently verify settlement. A signature or GAX receipt does not grant institutional permission. C0 revalidation is not destination commit atomicity; optional C1 remains same-host and not selected by default; no C2/C3 claim.

See [test navigation](../tests/integration/README.md) and [engineering cockpit](../development/README.md) for reproduction guidance.
