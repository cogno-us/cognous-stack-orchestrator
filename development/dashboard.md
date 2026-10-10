# Cognous engineering dashboard — workflow, not a live status feed

**Authoritative live work:** [engineering control board #1](https://github.com/cogno-us/cognous-stack-orchestrator/issues/1), [Governor #14](https://github.com/cogno-us/cognous-stack-orchestrator/issues/14), and [documentation #84](https://github.com/cogno-us/cognous-stack-orchestrator/issues/84). Follow issue state and exact PR-head CI rather than interpreting this static file as the active task board.

## Current engineering map

| Workstream | Accepted evidence | Remaining boundary |
|---|---|---|
| Synthetic O5-E source-connected refund | [Combined PR #64](https://github.com/cogno-us/cognous-stack-orchestrator/pull/64) | Real institutional authority and destination settlement **not** established |
| O6-Q2–Q6 optional synthetic qualifications | [Qualification ledger](../docs/qualification-ledger.md) | Profiles not selected merely by source acceptance; no production qualification |
| Selected Open Control Stack release | Hub [component lock](https://github.com/cogno-us/cognous-open-control-stack/blob/main/component-lock.json) | Release selection is hub-owned, not orchestrator-owned |
| Operational trust | [Issue #30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30) | **HOLD** pending independent environment evidence |
| ISS integration | [Disabled placeholder](../integrations/iss/README.md) | No proprietary implementation mirrored or execution permission |
| Documentation consolidation | [Issue #84](https://github.com/cogno-us/cognous-stack-orchestrator/issues/84) | Deep link/CLI audit still in progress |

## Process

Use [the engineering cockpit](README.md), [AGENTS](../AGENTS.md) and the scoped issue before proposing a change. Document owning repo, exact source pins, authority and trust boundaries, positive and negative tests, PR head/CI and limitations. Never infer publication, new grants, release selection or real-world effects from merge or green CI.

**Historical note:** earlier V0 dashboard lane assignments (“scaffolded,” “not scoped,” and “requires contract acceptance”) described the initial planning phase. They do **not** describe accepted O5-E/O6 synthetic integration status in October 2026.
