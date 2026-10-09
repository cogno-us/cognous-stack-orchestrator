# Cognous Stack Orchestrator

**Status: architecture scaffold / no runtime integration qualified.**

Private orchestration and integration repository for Cognous's five functional domains. This repository coordinates workflows and contracts; it **does not grant institutional authority**, substitute for the Control Plane, or certify component behavior.

## Domains

1. **Knowledge & Provenance** — Cognous Evidence Registry and Cognous Evidence Attestation
2. **Institutional Governance** — Cognous Institutional Governance (Alvorada)
3. **Action Governance** — Action Manifest and Control Plane
4. **Governed Execution** — Cognous Execution Runtime
5. **Evidence & Accountability** — Replay Bundle, Governance Evidence Pack, optional ODES exchange

The bounded V1 reference chain, **Declare → Control → Replay → Evidence**, remains separately qualified within [cognous-open-control-stack](https://github.com/cogno-us/cognous-open-control-stack). This scaffold does not expand those claims.

## ISS integration

The interface under [integrations/iss](integrations/iss/README.md) is a **disabled placeholder** for the private [TurwinAI/COGNOUS-client](https://github.com/TurwinAI/COGNOUS-client). No proprietary ISS implementation or source is mirrored here. Any future proposal from ISS must pass independently recorded action authorization.

## Navigation

- [Architecture](ARCHITECTURE.md)
- [Contracts and authority boundaries](CONTRACTS.md)
- [Component matrix](docs/component-matrix.md)
- [Trust boundaries](docs/trust-boundaries.md)
- [Qualification ledger](docs/qualification-ledger.md)
- [Reference profile](profiles/bounded-v1-reference.yaml)
- [Integrated preview candidate](profiles/integrated-preview.yaml)

## Current guarantees

**None asserted by this new repository.** The linked component projects have independent maturity and evidence; no end-to-end five-domain execution has been qualified here.
