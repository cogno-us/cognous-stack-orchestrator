# Documentation map and consolidation rules

Tracking issue: [#84](https://github.com/cogno-us/cognous-stack-orchestrator/issues/84). This is an entrypoint map; documentation sources remain in their owning repositories.

## Canonical navigation

| Question | Canonical answer |
|---|---|
| What is Cognous and what are its five areas? | [Orchestrator overview](../../README.md) |
| How do engineering tasks and reviews work? | [Engineering cockpit](../README.md) and [AGENTS](../../AGENTS.md) |
| Which source revisions are selected in the supported public integration? | Hub [component-lock.json](https://github.com/cogno-us/cognous-open-control-stack/blob/main/component-lock.json) |
| What can the selected release claim? | Hub [release-status](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/release-status.md) |
| What happened in synthetic connected refund tests? | [O5-E connected handoff](../scenarios/customer_refunds/connected/handoff/README.md), [O6-Q4 integration](../acceptance/o6-q4/README.md) |
| How do ambiguous external outcomes get treated? | Hub [recovery semantics](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/recovery-semantics.md), [O6-Q6](../acceptance/o6-q6/README.md) |
| Can the system operate in production? | [Environment admission #30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30): **not established** |
| Where are original research and domain protocols? | Owning repositories; do not copy or silently paraphrase normative contracts |

## What to retain versus simplify

**Keep immutable:** historical CI evidence, exact accepted SHA values and counts, accepted protocol/contract texts, previously executed qualification baselines, relevant caveats and archival example input/output.

**Simplify:** duplicate introductions, stale release language, navigation walls, long repeated component inventories, unlabeled historical quickstarts, and examples missing a clear outcome or verification boundary. Replace duplicate how-tos with a concise summary and link to one canonical procedure.

**Never imply:** passing synthetic tests means a selected release was updated, signature means institutional grant, receipt means effect committed, absence means retry safe, or evidence packaging means independent settlement verification.

## Repository-level inventory (2026-10-10)

The file-tree audit counted README/guide/help-style Markdown names, **not** every Markdown document. These counts are discovery metadata, not proof that each page is current or accurate.

| Owning repository | Matching entrypoints | Guidance |
|---|---:|---|
| Stack Orchestrator | 33 | This PR refreshes root/developer navigation; deep scenarios retain scoped evidence |
| Open Control Stack hub | 7 | Owns quickstarts, selected release status, public architecture and evidence index |
| Control Plane | 1 | Owns policy/decision API examples |
| Execution Runtime | 32 | Includes upstream apps, extensions and vendored docs; **do not mass-rewrite vendor content** |
| Governed Exchange | 2 | Owns lineage/fence and local transport guidance |
| Evidence Attestation | 1 | Owns custody verifier API/negative controls |
| Action Manifest | 1 | Owns declaration and binding examples |
| Replay Bundle | 1 | Owns reconstruction API/examples |
| Governance Evidence Pack | 1 | Owns rendering and derivative-evidence boundaries |
| Institutional Governance | 35 | Owns Alvorada constitutional guidance and domain examples; preserve proposed-vs-adopted status |

## Editorial pass sequence

1. **Entrypoints:** reader pathways, current status, one synthetic refund example, historical labels. Review root README and engineering cockpit.
2. **Hub:** remove duplication between public README and quickstarts, establish release-selection vs source acceptance terminology, mark historical sample SHAs and constraints.
3. **Component owning repos:** check each README's install command/example against source CLI, pin status against hub lock, and links to canonical support status. One reviewable PR per repo.
4. **Deep how-tos/domain content:** consolidate only when a page is duplicated or incorrect; retain historical records and source-owned contracts.
5. **Verification:** internal links, command parsing in disposable/test context, exact-head CI, no runtime/lock changes, no claims beyond evidence. Report unresolved items rather than guessing.

Each owning-repository PR should list pages inspected, pages changed, retained canonical owners and examples tested. A docs-only update is **not** a runtime qualification.
