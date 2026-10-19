# Documentation index

Every Markdown page in this repository is listed here or is reached from a page listed here. The [README](../README.md) has the status claims and the quick check. Names and groups follow the hub [stack map](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/stack-map.md) and [naming](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/naming.md). Labels: merged, selected, known limit, proposed (defined in the stack map). Pages marked historical are retained records of earlier checkpoints; their counts, pins and instructions are valid for their own revision only.

## Reading paths

| If you want to | Read |
|---|---|
| Understand authority and the execution path | [Architecture](../ARCHITECTURE.md), [trust boundaries](trust-boundaries.md) |
| See which components are connected and how far | [Component matrix](component-matrix.md), [qualification ledger](qualification-ledger.md) |
| Run or extend engineering qualifications | [Engineering cockpit](../development/README.md), [integration tests](../tests/integration/README.md) |
| Reproduce the synthetic refund handoff | [Connected refund handoff](../development/scenarios/customer_refunds/connected/handoff/README.md) |
| Run the optional candidate overlay | [Overlay tests](../tests/overlay/README.md) |
| Find open engineering and documentation work | [Documentation map](../development/documentation/README.md) |

## Top level

| Page | Content | Label |
|---|---|---|
| [ARCHITECTURE.md](../ARCHITECTURE.md) | Execution path and authority separation. | merged |
| [CONTRACTS.md](../CONTRACTS.md) | Integration contracts. | merged |
| [AGENTS.md](../AGENTS.md) | Rules for editing this repository. | merged |
| [RECOVERY_RESOLUTION_PROPOSAL.md](../RECOVERY_RESOLUTION_PROPOSAL.md) | Recovery resolution contract proposal (draft for review). | proposed |
| [RECOVERY_RESOLUTION_DECISIONS.md](../RECOVERY_RESOLUTION_DECISIONS.md) | Proposed owner decisions for the synthetic recovery work. | proposed |

## docs/

| Page | Content | Label |
|---|---|---|
| [component-matrix.md](component-matrix.md) | Responsibility map and bounded integration status per component. | merged |
| [qualification-ledger.md](qualification-ledger.md) | Navigation ledger of qualification milestones and their evidence. | merged |
| [trust-boundaries.md](trust-boundaries.md) | Trust and authority boundaries. | merged |

## Engineering cockpit and documentation

| Page | Content | Label |
|---|---|---|
| [development/README.md](../development/README.md) | Engineering cockpit and operating model. | merged |
| [development/dashboard.md](../development/dashboard.md) | Engineering dashboard workflow (not a live status feed). | merged |
| [development/documentation/README.md](../development/documentation/README.md) | Documentation map and consolidation rules; link check tool. | merged |
| [development/programme-2-gap-report.md](../development/programme-2-gap-report.md) | Programme 2 cross-component gap report (engineering measurement, not a qualification). | merged |
| [development/schemas/README.md](../development/schemas/README.md) | Candidate non-authorizing reference envelope schema. | proposed |

## Candidate contracts and interface mappings (historical, O1 to O4)

| Page | Content | Label |
|---|---|---|
| [development/integration-contract-v0.md](../development/integration-contract-v0.md) | V0 integration contract. | proposed |
| [development/v0-contract-acceptance-packet.md](../development/v0-contract-acceptance-packet.md) | Acceptance packet for the V0 contract (ready for review, not accepted). | proposed |
| [development/v0-source-interface-review.md](../development/v0-source-interface-review.md) | V0 gate review of source interfaces and authority boundaries. | merged |
| [development/component-contract-crosswalk-v0.md](../development/component-contract-crosswalk-v0.md) | Component contract and revision crosswalk. | merged |
| [development/field-mapping-review-v0.md](../development/field-mapping-review-v0.md) | Field-level source mapping review candidate (not ratified). | proposed |
| [development/evidence-registry-chain-mapping-v0.md](../development/evidence-registry-chain-mapping-v0.md) | Evidence Registry chain mapping. | merged |
| [development/o1-founder-scope-approval.md](../development/o1-founder-scope-approval.md) | Founder direction and merge disposition. | merged |
| [development/repository-name-registry.md](../development/repository-name-registry.md) | Repository names as of 2026-10-09 (a naming index, not a lock); the hub naming page is current. | merged |
| [development/o4b-producer-boundary.md](../development/o4b-producer-boundary.md) | O4b producer evidence boundary (candidate). | merged |
| [development/o4c-combined-qualification.md](../development/o4c-combined-qualification.md) | O4c combined acceptance candidate. | merged |
| [development/interfaces/exchange/README.md](../development/interfaces/exchange/README.md) | Exchange reference handoff (read-only compatibility mapping). | merged |
| [development/interfaces/institutional/README.md](../development/interfaces/institutional/README.md) | Institutional authority context mapping. | merged |

## Acceptance records (retained evidence; do not edit)

| Page | Content | Label |
|---|---|---|
| [development/acceptance/o4d/postmerge-qualification.md](../development/acceptance/o4d/postmerge-qualification.md) | O4d post-merge qualification. | merged |
| [development/acceptance/o4d/source-owner-interface-acceptance-matrix.md](../development/acceptance/o4d/source-owner-interface-acceptance-matrix.md) | O4d source-owner interface acceptance matrix. | merged |
| [development/acceptance/o4e/README.md](../development/acceptance/o4e/README.md) | O4e environment trust and evidence admission. | merged |
| [development/acceptance/o4e/EVIDENCE_SUBMISSION.md](../development/acceptance/o4e/EVIDENCE_SUBMISSION.md) | O4e evidence submission. | merged |
| [development/acceptance/o6-q/source-pin-reconciliation.md](../development/acceptance/o6-q/source-pin-reconciliation.md) | O6 source pin reconciliation. | merged |
| [development/acceptance/o6-q2/README.md](../development/acceptance/o6-q2/README.md) | O6-Q2 pinned source candidate. | merged |
| [development/acceptance/o6-q3/README.md](../development/acceptance/o6-q3/README.md) | O6-Q3 three-profile trace. | merged |
| [development/acceptance/o6-q4/README.md](../development/acceptance/o6-q4/README.md) | O6-Q4 handoff and fence. | merged |
| [development/acceptance/o6-q5/README.md](../development/acceptance/o6-q5/README.md) | O6-Q5 release admission (read-only; intentional HOLD). | merged |
| [development/acceptance/o6-q6/README.md](../development/acceptance/o6-q6/README.md) | O6-Q6 restart and adapter reconciliation. | merged |
| [acceptance/recovery-resolution-inspection/README.md](../acceptance/recovery-resolution-inspection/README.md) | Optional read-only recovery inspection chain 0.1. | merged |

## Synthetic customer refund scenario

| Page | Content | Label |
|---|---|---|
| [README](../development/scenarios/customer_refunds/README.md) | Scenario overview. | merged |
| [control](../development/scenarios/customer_refunds/control/README.md) | Control step. | merged |
| [runtime](../development/scenarios/customer_refunds/runtime/README.md) | Runtime step. | merged |
| [replay](../development/scenarios/customer_refunds/replay/README.md) | Replay step. | merged |
| [connected contracts](../development/scenarios/customer_refunds/connected/contracts/README.md) | Connected contract matrix. | merged |
| [connected handoff](../development/scenarios/customer_refunds/connected/handoff/README.md) | Connected handoff. | merged |
| [connected replay](../development/scenarios/customer_refunds/connected/replay/README.md) | Connected replay. | merged |
| [live components, runtime](../development/scenarios/customer_refunds/live_components/runtime/README.md) | Live-component runtime. | merged |
| [live components, evidence](../development/scenarios/customer_refunds/live_components/evidence/README.md) | Live-component evidence. | merged |

## Code, adapters, tests and placeholders

| Page | Content | Label |
|---|---|---|
| [orchestration/README.md](../orchestration/README.md) | O4 read-only source boundary (experimental local consistency assessment). | merged |
| [orchestration/adapters/attestation/trust_qualification/README.md](../orchestration/adapters/attestation/trust_qualification/README.md) | Attestation trust qualification adapter. | merged |
| [orchestration/dependency-registry/README.md](../orchestration/dependency-registry/README.md) | Dependency registry notes. | merged |
| [orchestration/state-transitions/README.md](../orchestration/state-transitions/README.md) | State transition notes. | merged |
| [orchestration/workflow-contracts/README.md](../orchestration/workflow-contracts/README.md) | Workflow contract notes. | merged |
| [tests/contract/README.md](../tests/contract/README.md) | Reference envelope contract tests. | merged |
| [tests/integration/README.md](../tests/integration/README.md) | Integration tests: how to choose a test. | merged |
| [tests/overlay/README.md](../tests/overlay/README.md) | Candidate component overlay (opt-in, report only). | merged |
| [domains/knowledge-provenance/README.md](../domains/knowledge-provenance/README.md) | Domain note: hub group 01. | merged |
| [domains/institutional-governance/README.md](../domains/institutional-governance/README.md) | Domain note: hub group 02. | merged |
| [domains/action-governance/README.md](../domains/action-governance/README.md) | Domain note: hub group 03. | merged |
| [domains/governed-execution/README.md](../domains/governed-execution/README.md) | Domain note: hub group 04. | merged |
| [domains/evidence-accountability/README.md](../domains/evidence-accountability/README.md) | Domain note: hub group 05. | merged |
| [integrations/iss/README.md](../integrations/iss/README.md) | Disabled external-interface placeholder. | known limit |
| [.github/PULL_REQUEST_TEMPLATE.md](../.github/PULL_REQUEST_TEMPLATE.md) | Pull request template. | merged |
