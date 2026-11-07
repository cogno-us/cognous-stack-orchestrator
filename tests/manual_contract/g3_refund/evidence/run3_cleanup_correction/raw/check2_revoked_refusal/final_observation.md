# G3 final development observation - check2_revoked_refusal: revoked synthetic root, refusal chain

DEVELOPMENT ONLY / SYNTHETIC. Not a single SUCCESS verdict; the facts below are separate.

- CP `hold` with `grant_revoked`; every downstream stage NOT RUN; no SQLite effect row; no Registry write.

| stage | component@rev | status | outcome | input -> output identity | assertion source | evidence | limitation |
|---|---|---|---|---|---|---|---|
| G2 authority + CP decide() | institutional-governance + control-plane@1ebe85be4cfe | **EXECUTED** | hold ['grant_revoked'] | urn:cognous:authority:g2-synthetic-refund-root-1@r2 -> None | synthetic fixture facts + IG lineage; CP decision is the authority | CP run record retained | synthetic developer-mode; HOLD never bypassed |
| Runtime execute | execution-runtime@ | **NOT RUN** | not invoked because CP returned hold | None -> None |  |  | no artifact generated |
| Replay import | replay-bundle@ | **NOT RUN** | not invoked because CP returned hold | None -> None |  |  | no artifact generated |
| Pack import | governance-evidence-pack@ | **NOT RUN** | not invoked because CP returned hold | None -> None |  |  | no artifact generated |
| Verifier | verifier@ | **NOT RUN** | not invoked because CP returned hold | None -> None |  |  | no artifact generated |
| G1 attestation | evidence-attestation@ | **NOT RUN** | not invoked because CP returned hold | None -> None |  |  | no artifact generated |
| G1b Registry | evidence-registry@ | **NOT RUN** | not invoked because CP returned hold | None -> None |  |  | no artifact generated |

## Nonclaims
- authorization is SYNTHETIC developer-mode (resolver authenticated=false; identity/mandate flags are fixture assertions)
- the Runtime write is a REAL local SQLite INSERT, but the effect evidence is PRODUCER-REPORTED, not independently observed
- the Verifier is ALPHA/HOLD and abstains; it never accepts a Pack
- the signature is valid only under a synthetic ephemeral snapshot and is not chain-bound
- Registry inclusion is PROVISIONAL on a disposable local chain: no durable custody, no consensus finality
- no independent qualification, no production authority, no ODES/GAX, no source-lock change
