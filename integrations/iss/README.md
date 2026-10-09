# ISS Integration — disabled placeholder

Source: private [TurwinAI/COGNOUS-client](https://github.com/TurwinAI/COGNOUS-client).

The inspected project documentation describes org-bound API credentials, a governed chat API (`POST /v1/chat/completions`), session processing, and evidence lookup (`GET /v1/evidence/{correlation_id}`). Those published-in-repo descriptions are **not an integration contract or verified interoperability**.

## Intended boundary

- ISS is an optional external cognition/analysis service; never an institutional grant issuer through this adapter.
- Map tenant/org/workspace identities explicitly, not by string coincidence.
- Accept proposed actions only as **untrusted proposals** that must pass Manifest and Control Plane checks.
- Carry correlation IDs and evidence references with explicit provenance; avoid equivalence between ISS evidence and destination verification.
- Keep secrets out of files, logs, tests and public repositories; do not vendor private source.
- No ISS invocation until credentials, contract version, security review, negative tests and an authorized deployment profile exist.

Implementation status: **NOT STARTED**.
