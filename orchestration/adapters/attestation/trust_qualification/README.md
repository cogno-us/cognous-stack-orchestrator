# O4d-B operational attestation trust qualification

Issue: [#22](https://github.com/cogno-us/cognous-stack-orchestrator/issues/22)

## Scope

This package qualifies the operator-controlled trust inputs around the already
accepted attestation verifier bridge. It does **not** implement signature
verification, canonicalization, key enrollment, institutional authority, grants,
effects, or production credential management.

Accepted orchestrator base:

- `cogno-us/cognous-stack-orchestrator@3df758ec5e0a65af28f6f9f3be5c9263458ab83b`
- bridge: `orchestration/adapters/attestation/verifier.py`
- bridge source blob at the accepted base: `2964ba564912e96f993d6102c81c3ad6a6d559b8`

Accepted upstream verifier:

- repository: `cogno-us/cognous-evidence-attestation`
- revision: `5b5077dafde232a7801cb425c4efddcffb468723`
- `utils/trust.py` blob `b001689ed7c6554d3e3dce3b91285d30e99d7822`
- `utils/verification.py` blob `1672b5105b5a17d141402da62483736a1d266e2f`
- `models/verification.py` blob `97f3d30aed2ffed41f31253e3bb3242691bdbbf2`

Cryptography and canonical signing bytes remain exclusively in that pinned
upstream verifier and the accepted bridge.

## Qualified deployment inputs

`qualify_attestation_trust` requires an operator configuration that pins:

- exact accepted verifier repository and revision;
- absolute operator-selected trust snapshot path;
- raw SHA-256 of the snapshot bytes (checked on the qualification read, then
  passed to the accepted bridge, which rechecks it against the bytes it reads
  and copies into its isolated verifier directory);
- explicit operator trust-source marker;
- explicit trusted-clock source marker;
- expected issuer, key ID and deployment audience.

The attestation cannot supply or replace the trust path, verifier revision, or
trusted-clock provenance. The independent consumer reference must agree on
audience, subject and content digest before delegation to the accepted bridge.

Successful bridge verification is reported only as `issuer_signature_only` under the
configured snapshot and trusted time: a valid signature shows that the configured key signed, not who the issuer is.
The result field named `issuer_authenticity` keeps that historical name and means only this.
Qualification always reports
`authority=not_established`, `grant=not_inferred`, and `effect=not_observed`.

## Negative matrix

| Case | Expected behavior |
| --- | --- |
| missing operator configuration | unknown; bridge not called |
| incomplete/untrusted configuration source | unknown; bridge not called |
| absent/invalid trusted time | unknown; bridge not called |
| attacker/wire-selected time source | unknown; bridge not called |
| verifier repository/revision substitution | unknown; bridge not called |
| relative, missing or symlinked trust path | unknown; bridge not called |
| snapshot bytes changed under an old digest pin | unknown `trust_snapshot_pin_mismatch` |
| snapshot bytes replaced after qualification read, before bridge read | unknown `trust_snapshot_pin_mismatch` from the bridge recheck; upstream verifier not run |
| snapshot audience differs from deployment audience | unknown |
| configured issuer/key absent or duplicated in snapshot | unknown |
| attestation issuer/key differs from deployment identity | rejected |
| attestation audience differs from deployment audience | rejected |
| independent audience/subject/content differs | rejected |
| revoked key from accepted bridge | preserve `rejected/key_revoked` |
| expired key from accepted bridge | preserve `rejected/key_expired` |
| rotation without a new operator snapshot digest | unknown; no silent fallback |
| rotation with an explicit new snapshot pin and key ID | delegated to accepted bridge |
| attacker-supplied trust path field | cannot replace configured operator path |

## Tests

Exact-head CI uses the repository's existing `O4c-B scoped contract tests`
workflow because issue ownership does not permit editing `.github/workflows/`.
It discovers this directory under `tests/adapters/attestation/**`.

The default CI suite exercises operator configuration, source pins, identity
binding, snapshot rotation/fail-closed behavior and propagation of accepted
bridge lifecycle outcomes through an injected bridge seam. Two optional live
tests execute revoked/expired-key behavior through the actual accepted upstream
verifier when `COGNOUS_EVIDENCE_ATTESTATION_ROOT` points to revision
`5b5077dafde232a7801cb425c4efddcffb468723`.

## Limitations

- This package does not authenticate how the operator obtains or provisions the
  snapshot file; the raw digest pin only prevents unnoticed substitution after
  configuration. The pin is enforced on each read of the snapshot path
  (qualification and bridge); the bytes given to the upstream verifier are the
  bridge's own digest-checked read.
- Trusted time is supplied by the deployment caller and labeled by configured
  provenance; secure clock hardware, NTP hardening and clock-attestation are
  outside this issue.
- The upstream verifier implements conservative current-time revocation
  semantics. Historical validation policies beyond that pinned behavior are not
  introduced here.
- Key custody, CA/HSM/KMS integration, institutional issuer onboarding,
  production credential separation and source-owner ratification remain
  external gates.
- Default exact-head CI does not provision the private/pinned upstream checkout;
  live cryptographic lifecycle tests therefore remain conditional unless the
  runner explicitly supplies `COGNOUS_EVIDENCE_ATTESTATION_ROOT`.
  Update (E-9 fix): the workflows that run these tests (O4c-B, O4d-B and the
  O4c/O4d combined workflows) now check out the pinned upstream revision, set
  `COGNOUS_EVIDENCE_ATTESTATION_ROOT`, and run them through
  `.github/scripts/run_unittest_no_skips.py`, which fails the job on any skipped
  test, on zero tests run, or if the variable is unset. This does not change
  what the qualification establishes.
- Neither a verified signature nor this qualification establishes an
  institutional grant, execution permission, effect, or independent effect
  observation.
