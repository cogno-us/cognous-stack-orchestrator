# Cognous Stack Orchestrator

**Engineering integration and evidence coordination — not an authority issuer or release selector.**

This repository connects **actual pinned component source interfaces** in bounded synthetic qualification tests. It does not authenticate institutional adoption, issue grants, certify a deployed environment, settle real payments, or replace the [Open Control Stack hub](https://github.com/cogno-us/cognous-open-control-stack) as the release-selection authority.

## Start here

| You want to… | Read |
|---|---|
| Understand components, authority and the execution path | [Architecture](ARCHITECTURE.md) and [trust boundaries](docs/trust-boundaries.md) |
| Run or extend engineering qualifications | [Engineering cockpit](development/README.md) and [integration tests](tests/integration/README.md) |
| Reproduce the accepted synthetic refund handoff | [Connected refund handoff](development/scenarios/customer_refunds/connected/handoff/README.md) |
| Understand O6 source-level qualification and its limitations | [O6-Q4 evidence](development/acceptance/o6-q4/README.md) and [O6-Q6 recovery](development/acceptance/o6-q6/README.md) |
| Check the selected public release | Hub [component lock](https://github.com/cogno-us/cognous-open-control-stack/blob/main/component-lock.json) and [release status](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/release-status.md) |
| Assess whether a real deployment is trusted | [Operational evidence gate #30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30) (**HOLD: not established**) |
| See pending engineering and documentation | [Governor #14](https://github.com/cogno-us/cognous-stack-orchestrator/issues/14) and [documentation register #84](https://github.com/cogno-us/cognous-stack-orchestrator/issues/84) |

## Status: distinguish four different claims

1. **Selected release:** only the exact source revisions in the hub `component-lock.json`. Acceptance of newer component code does **not** change this.
2. **Accepted source qualification:** the component itself has an accepted revision and its recorded tests. This is not automatically a hub integration.
3. **Accepted orchestrator synthetic integration:** the O5-E and O6-Q2–Q6 workflows exercise stated actual-source interfaces with synthetic inputs and precisely bounded trust. They do **not** certify a live institutional workflow.
4. **Operational deployment assurance:** **not established**. Environment ownership, Registry provenance, issuer/key custody, trusted time and independent negative checks remain subject to [#30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30). Production effect activation is not authorized.

Use [qualification ledger](docs/qualification-ledger.md) for retained prior milestones. For the accepted newer engineering work, follow the scoped [O6-Q2](development/acceptance/o6-q2/README.md), [Q3](development/acceptance/o6-q3/README.md), [Q4](development/acceptance/o6-q4/README.md), [Q5](development/acceptance/o6-q5/README.md) and [Q6](development/acceptance/o6-q6/README.md) notes and their PR-head CI runs. All examples are synthetic.

## One synthetic refund, five separate facts

Consider a request to refund a synthetic payment. The records answer different questions; they are not interchangeable.

| Stage | Example record | What it **does not** prove |
|---|---|---|
| Declaration | Manifest binds refund target, amount, payload digest | Permission to refund |
| Authority check | Control Plane tests current independently supplied context, grant, approval and policy | That a fixture is a real adopted institutional grant |
| Execution | Runtime attempts an effect using an identified claim and effect/attempt IDs | Provider settlement from a tool receipt or timeout |
| Observation / recovery | Destination observation resolves **the original attempt** or retains `unknown` / HOLD | That absence permits retry |
| Evidence | Replay, Evidence Pack and optional ODES/GAX artifacts preserve correlations | Independent verification, new authorization or real-world finality |

Example: if an attempt times out after the provider *may* have accepted it, record the original effect/attempt as unresolved. **Do not issue a second refund merely because a read returns absent or unknown.** The optional Q6 intake keeps the original attempt and fails closed on missing provenance. An attestation of a policy digest proves neither that a person adopted the policy nor that the payment settled.

## Functional domains

- **Knowledge and provenance:** Registry and Evidence Attestation
- **Institutional governance:** Alvorada, proposed authority and review requirements
- **Action governance:** Action Manifest and Control Plane
- **Governed execution:** Execution Runtime and optional adapters
- **Evidence and accountability:** Replay Bundle, Evidence Pack, ODES and Governed Exchange

Consult the [component matrix](docs/component-matrix.md), [integration contracts](CONTRACTS.md) and [bounded reference profile](profiles/bounded-v1-reference.yaml). The [integrated preview](profiles/integrated-preview.yaml) is a profile, not a deployment approval.

## Engineering and IP boundaries

Read [AGENTS.md](AGENTS.md) before editing. Preserve effect/attempt identity, source SHA pins, authority/evidence separation, negative tests and exact-head CI. No automatic change to release locks, C1–C8 contracts, trust roots, deployment state or institutional grants.

[ISS integration](integrations/iss/README.md) is a **disabled external-interface placeholder**. No proprietary ISS source is implemented or mirrored here.
