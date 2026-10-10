# Integration tests — bounded actual-source qualification

The statement “No five-domain tests run” described the original scaffold and is **historical**, not current. This repository now includes accepted **synthetic** integration tests against actual pinned source implementations. They do not amount to one independently authenticated five-domain production deployment.

## Choose a test

| Purpose | Test or evidence guide |
|---|---|
| Source-pinned connected Manifest/Control Plane/Runtime refund | [O5-E handoff](../../development/scenarios/customer_refunds/connected/handoff/README.md) |
| Connected Replay and Evidence Pack, with negative settlement controls | [O5-E evidence](../../development/scenarios/customer_refunds/connected/replay/README.md) |
| Combined O6 Runtime, GAX and Attestation synthetic trace | [O6-Q3](../../development/acceptance/o6-q3/README.md) |
| Control Plane handoff under local GAX fence and Runtime evidence | [O6-Q4](../../development/acceptance/o6-q4/README.md) |
| Read-only candidate-admission HOLD | [O6-Q5](../../development/acceptance/o6-q5/README.md) |
| Original-attempt closeout, restarts, adapter declarations and no retry | [O6-Q6](../../development/acceptance/o6-q6/README.md) |

## How to reproduce

Each linked guide identifies accepted upstream SHAs and the corresponding `.github/workflows/` job. Use the **exact versioned checkouts** and CI environment; run the named test in a disposable workspace. A different component HEAD is not equivalent evidence. Keep historical test counts and workflows tied to their original revisions.

For a refund timeout, retain the same effect and attempt identities, record `unknown`, reconcile the original attempt and **do not retry because delivery or observation is absent**. A valid signature, reconstruction or local destination row is not independently verified external payment settlement.

The [hub component lock](https://github.com/cogno-us/cognous-open-control-stack/blob/main/component-lock.json) independently selects the current release. Newer tests do not promote it. Operator deployment trust [#30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30) remains unqualified.
