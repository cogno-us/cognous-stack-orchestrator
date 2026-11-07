# G3 final development observation - check1_positive_chain: valid synthetic root, complete chain

DEVELOPMENT ONLY / SYNTHETIC. Not a single SUCCESS verdict; the facts below are separate.

- Synthetic authorization: CP `authorized` under the G2 synthetic root (resolver authenticated=false).
- Actual isolated local write: 1 row `applied` in a unique SQLite file (now disposed) - PRODUCER-REPORTED, not independently observed.
- Verifier: `abstain` (exit 3) - not an accepted execution verdict.
- Signature validity under synthetic trust: True (issuer_signature_only).
- Provisional Registry inclusion: PRESENT_PROVISIONAL (disposable chain; no custody/finality).

| stage | component@rev | status | outcome | input -> output identity | assertion source | evidence | limitation |
|---|---|---|---|---|---|---|---|
| G2 authority + CP decide() | institutional-governance + control-plane@1ebe85be4cfe | **EXECUTED** | authorized [] | urn:cognous:authority:g2-synthetic-refund-root-1@r1 -> None | synthetic fixture facts + IG lineage; CP decision is the authority | CP run record retained | resolver authenticated=false; authorized = synthetic developer-mode decision |
| Runtime execute (one local INSERT) | execution-runtime@f7a55e2a8494 | **EXECUTED** | executed / applied (1 row) | sha256:34d2eacdbacac12bdb3fb533b6d3444b480b31d4bf109df3e769258be194048c -> runtime_export.json sha256:c1fd201fd11e | producer-reported (Runtime export; repository_revision caller-asserted) | export + local SQLite read-back | real isolated local write; NOT independently observed; database disposed after capture |
| Replay import | replay-bundle@7eb7d76eda10 | **EXECUTED** | reconstruction_complete | CP run + proposal + Runtime export -> bundle a61743f0-6d8f-4b91-b8c3-8ace9810a5ba | Replay import over producer-reported records | complete | destination observation is producer_reported; independent_effect_verification false |
| Pack import (opt-in generation) | governance-evidence-pack@1906c1fb1da4 | **EXECUTED** | validated_complete | cp2-replay-7eb7d76e-tenant-binding-dev-0.1 -> agep-b225bb53cc1b454a sha256:441313c92a88 | Pack validator status is a producer string | complete | independent verification unavailable |
| Verifier pack_cli | verifier (ALPHA/HOLD)@2ffe37c5ea12 | **EXECUTED** | exit 3 / abstain; executor kinds present | pack sha256:441313c92a88 -> report sha256:a4f80bba5ccf | Verifier recomputation over one file | present kinds are source-asserted | source identity never checkable; unsupported claims: 6 |
| G1 attestation (ephemeral key) + G1b Registry | evidence-attestation + evidence-registry@0729159669d6 | **EXECUTED** | PRESENT_PROVISIONAL; signature issuer_signature_only | report sha256:a4f80bba5ccf -> claim 0xe7e297991121 evidence 0xc369e3ab6754 | G1 statement signed by an ephemeral synthetic key; commitments recomputed from retained bytes | reconstructed; provisional | not chain-bound; disposable chain; no custody or finality |

## Nonclaims
- authorization is SYNTHETIC developer-mode (resolver authenticated=false; identity/mandate flags are fixture assertions)
- the Runtime write is a REAL local SQLite INSERT, but the effect evidence is PRODUCER-REPORTED, not independently observed
- the Verifier is ALPHA/HOLD and abstains; it never accepts a Pack
- the signature is valid only under a synthetic ephemeral snapshot and is not chain-bound
- Registry inclusion is PROVISIONAL on a disposable local chain: no durable custody, no consensus finality
- no independent qualification, no production authority, no ODES/GAX, no source-lock change
