# Cognous Stack Orchestrator

**Engineering integration and evidence coordination — not an authority issuer or release selector.**

This repository connects **actual pinned component source interfaces** in bounded synthetic qualification tests. It does not authenticate institutional adoption, issue grants, certify a deployed environment, settle real payments, or replace the [Open Control Stack hub](https://github.com/cogno-us/cognous-open-control-stack) as the release-selection authority.

Status label: **merged** (not a lock entry). Role: engineering integration repository in the Tooling and qualification side group. It selects no revisions: the hub component lock does.

## At a glance

| | |
|---|---|
| What it is | Test harnesses, adapters, schemas and retained acceptance records that run actual pinned component interfaces against synthetic inputs. |
| Who it is for | Engineers qualifying component interfaces together, and reviewers reading what those synthetic qualifications do and do not show. |
| What it does not do | Issue authority, select a release, certify a deployment, or establish operational trust (issue [#30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30), **HOLD**). It has no installed command and no package. |
| Interfaces | Integration contracts in [CONTRACTS.md](CONTRACTS.md); profiles [bounded-v1-reference](profiles/bounded-v1-reference.yaml) and [integrated-preview](profiles/integrated-preview.yaml). |

## Where it fits

<!-- stack-map:start -->
<!-- Canonical block: identical text in every component README. Source: docs/stack-map.md in the hub. Refresh at the pin round. -->
The Open Control Stack groups its repositories by responsibility. The groups are a navigation map, not an execution sequence and not a requirement to install every component. The hub [component lock](https://github.com/cogno-us/cognous-open-control-stack/blob/main/component-lock.json) is the only source of selected revisions; [release status](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/release-status.md) states their evidence and limits. Last checked against `component-lock.json` at hub commit `dcc9bd7533ef`.

| Group | Members |
| --- | --- |
| **01 Knowledge & Provenance** | [Evidence Registry (The Index)](https://github.com/cogno-us/cognous-evidence-registry) · [Evidence Attestation (BitRep)](https://github.com/cogno-us/cognous-evidence-attestation) |
| **02 Institutional Governance** | [Institutional Governance (Alvorada)](https://github.com/cogno-us/cognous-institutional-governance) |
| **03 Declaration & Policy Control** | [Action Manifest](https://github.com/cogno-us/cognous-action-manifest) · [Control Plane](https://github.com/cogno-us/cognous-control-plane) |
| **04 Constrained Execution** | [Execution Runtime](https://github.com/cogno-us/cognous-execution-runtime) |
| **05 Replay & Evidence** | [Replay Bundle](https://github.com/cogno-us/cognous-replay-bundle) · [Governance Evidence Pack](https://github.com/cogno-us/cognous-governance-evidence-pack) · [ODES](https://github.com/cogno-us/open-decision-evidence-standard) |
| **Cross-cutting exchange** | [Governed Exchange (GAX/IMX)](https://github.com/cogno-us/cognous-governed-exchange) |
| **Tooling and qualification** (side group) | [Ergonomics (`cognous-ocs`)](https://github.com/cogno-us/cognous-open-control-stack-ergonomics) · [Verifier](https://github.com/cogno-us/cognous-open-control-stack-verifier) · [Orchestrator](https://github.com/cogno-us/cognous-stack-orchestrator) · [Qualification](https://github.com/cogno-us/cognous-stack-qualification) |

Status labels used in this README: **merged** (reviewed and merged in the owning repository; not by itself selected), **selected** (pinned in the hub lock), **known limit** (a limitation that is stated and kept visible) and **proposed** (draft or planned work, not a supported interface). Full map, names and commands: [stack map](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/stack-map.md), [naming](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/naming.md), [profiles and tools](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/profiles-and-tools.md). A signature, registry entry, message receipt or evidence summary does not grant execution authority.
<!-- stack-map:end -->

The orchestrator connects the components of groups 01 to 05 and the cross-cutting exchange in bounded synthetic tests. It sits in the **Tooling and qualification** side group, next to the hub (selection authority), the qualification repository (cross-component suites and records), the verifier and the ergonomics CLI. Its older directory names under `domains/` use an earlier vocabulary; the table in [Functional domains](#functional-domains) maps them to the hub group names.

## Start here

| You want to… | Read |
|---|---|
| Understand components, authority and the execution path | [Architecture](ARCHITECTURE.md) and [trust boundaries](docs/trust-boundaries.md) |
| Run or extend engineering qualifications | [Engineering cockpit](development/README.md) and [integration tests](tests/integration/README.md) |
| Reproduce the accepted synthetic refund handoff | [Connected refund handoff](development/scenarios/customer_refunds/connected/handoff/README.md) |
| Understand O6 source-level qualification and its limitations | [O6-Q4 evidence](development/acceptance/o6-q4/README.md) and [O6-Q6 recovery](development/acceptance/o6-q6/README.md) |
| Inspect retained synthetic recovery records through native Replay and Evidence Pack | [Read-only recovery inspection](acceptance/recovery-resolution-inspection/README.md) |
| Check the selected public release | Hub [component lock](https://github.com/cogno-us/cognous-open-control-stack/blob/main/component-lock.json) and [release status](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/release-status.md) |
| Assess whether a real deployment is trusted | [Operational evidence gate #30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30) (**HOLD: not established**) |
| See pending engineering and documentation | [Governor #14](https://github.com/cogno-us/cognous-stack-orchestrator/issues/14) and [documentation register #84](https://github.com/cogno-us/cognous-stack-orchestrator/issues/84) |

## Status: distinguish four different claims

1. **Selected release:** only the exact source revisions in the hub `component-lock.json`. Acceptance of newer component code does **not** change this.
2. **Accepted source qualification:** the component itself has an accepted revision and its recorded tests. This is not automatically a hub integration.
3. **Accepted orchestrator synthetic integration:** the O5-E and O6-Q2–Q6 workflows exercise stated actual-source interfaces with synthetic inputs and precisely bounded trust. They do **not** certify a live institutional workflow.
4. **Operational deployment assurance:** **not established**. Environment ownership, Registry provenance, issuer/key custody, trusted time and independent negative checks remain subject to [#30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30). Production effect activation is not authorized.

Use [qualification ledger](docs/qualification-ledger.md) for retained prior milestones. For the accepted newer engineering work, follow the scoped [O6-Q2](development/acceptance/o6-q2/README.md), [Q3](development/acceptance/o6-q3/README.md), [Q4](development/acceptance/o6-q4/README.md), [Q5](development/acceptance/o6-q5/README.md) and [Q6](development/acceptance/o6-q6/README.md) notes and their PR-head CI runs. The separately merged [read-only recovery inspection](acceptance/recovery-resolution-inspection/README.md) composes the native Runtime export, Replay importer and Evidence Pack transformation at its own exact pins. Its 33-test CI and inspected artifacts are recorded in [PR #97](https://github.com/cogno-us/cognous-stack-orchestrator/pull/97). It does not replace Q6 intake or select a hub release. All examples are synthetic.

## What is in this repository

Status labels are those of the stack map block above. There is no standalone install: the pinned component sources are fetched by the workflows or by the commands each page names.

| Path | What it holds | Label | Page |
|---|---|---|---|
| `ARCHITECTURE.md`, `CONTRACTS.md`, `AGENTS.md` | Execution path and authority separation; the integration contracts; rules for editing. | merged | [Architecture](ARCHITECTURE.md), [contracts](CONTRACTS.md), [agents](AGENTS.md) |
| `docs/` | Component matrix, trust boundaries, qualification ledger. | merged | [docs index](docs/README.md) |
| `development/` | Engineering cockpit, candidate integration contracts, schemas, scenarios, acceptance notes for O4d, O4e and O6-Q2 to Q6, link-check tool. | merged | [Engineering cockpit](development/README.md) |
| `development/schemas/` | Candidate non-authorizing reference envelope schema (`orchestration-reference-v0`). | proposed | [schema notes](development/schemas/README.md) |
| `development/documentation/` | Documentation map and the link check used by CI. | merged | [documentation map](development/documentation/README.md) |
| `orchestration/` | Experimental local consistency assessment (`provenance_context.py`), producer evidence, attestation and registry adapters, state-transition and dependency-registry notes. | merged | [orchestration notes](orchestration/README.md) |
| `profiles/` | `bounded-v1-reference.yaml` (historical qualified reference, informational pointer) and `integrated-preview.yaml` (a profile, not a deployment approval). | merged | [component matrix](docs/component-matrix.md) |
| `acceptance/recovery-resolution-inspection/` | Optional read-only recovery inspection chain 0.1. | merged | [inspection README](acceptance/recovery-resolution-inspection/README.md) |
| `tests/` | Contract, integration, adapter, overlay and scenario tests; overlay runs only on request. | merged | [integration tests](tests/integration/README.md), [overlay](tests/overlay/README.md) |
| `domains/` | Per-domain ownership notes (earlier vocabulary). | merged | [Functional domains](#functional-domains) |
| `integrations/iss/` | Disabled external-interface placeholder. | known limit | [ISS placeholder](integrations/iss/README.md) |
| `.github/workflows/` | One acceptance workflow per qualification step (O3, O4, O4b to O4e, O5, O6-Q2 to Q6, overlay, recovery inspection) and the documentation link check. | merged | [qualification ledger](docs/qualification-ledger.md) |

## Quick check

There is no standalone quick start: the qualifications need pinned component checkouts and run in CI. The smallest read-only check that runs from a clean checkout is the documentation link check (no network, no commands executed):

```bash
git clone https://github.com/cogno-us/cognous-stack-orchestrator
cd cognous-stack-orchestrator
python development/documentation/check_links.py
```

Expected: one line, `Checked 10 canonical Markdown files, 73 local links/anchors and 2 shell fences (syntax only); no external URLs fetched`, exit code 0 (the counts change when pages change). What this does not prove: it shows the entrypoint pages link to existing files and headings. It says nothing about any qualification result. To reproduce a qualification, follow the [connected refund handoff](development/scenarios/customer_refunds/connected/handoff/README.md) and the [integration tests guide](tests/integration/README.md).

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

The `domains/` directory and the older component matrix used five domain names. They map to the hub groups (see the [hub stack map](https://github.com/cogno-us/cognous-open-control-stack/blob/main/docs/stack-map.md)); the hub names are the ones to use.

| Orchestrator domain (`domains/`) | Hub group | Components |
|---|---|---|
| Knowledge and provenance | 01 Knowledge & Provenance | Registry and Evidence Attestation |
| Institutional governance | 02 Institutional Governance | Alvorada: proposed authority and review requirements |
| Action governance | 03 Declaration & Policy Control | Action Manifest and Control Plane |
| Governed execution | 04 Constrained Execution | Execution Runtime and optional adapters |
| Evidence and accountability | 05 Replay & Evidence, plus the cross-cutting exchange | Replay Bundle, Governance Evidence Pack, ODES; Governed Exchange |

Consult the [component matrix](docs/component-matrix.md), [integration contracts](CONTRACTS.md) and [bounded reference profile](profiles/bounded-v1-reference.yaml). The [integrated preview](profiles/integrated-preview.yaml) is a profile, not a deployment approval.

## Known limits

- **known limit** Operational deployment assurance is not established (issue [#30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30), HOLD); production effect activation is not authorized.
- **known limit** The qualifications use synthetic inputs and trusted-host test flags; a pass is not a live institutional workflow.
- **known limit** The ISS integration is a disabled placeholder and no proprietary source is mirrored here.
- **known limit** There is no installed command or package, and no standalone quick start beyond the link check above.

## Engineering and IP boundaries

Read [AGENTS.md](AGENTS.md) before editing. Preserve effect/attempt identity, source SHA pins, authority/evidence separation, negative tests and exact-head CI. No automatic change to release locks, C1–C8 contracts, trust roots, deployment state or institutional grants.

[ISS integration](integrations/iss/README.md) is a **disabled external-interface placeholder**. No proprietary ISS source is implemented or mirrored here.

## License

This repository is licensed under the [Apache License 2.0](LICENSE). The ISS integration remains a disabled external-interface placeholder; no proprietary ISS source is included or licensed here.
