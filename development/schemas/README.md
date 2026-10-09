# O3 candidate schema — non-authorizing reference envelope

`orchestration-reference-v0.schema.json` is **proposed and not ratified**. It stores source-owned references, cryptographic digest *strings*, explicit loss and correlation identifiers. It does not assert content authentication from the mere presence of a digest and it contains no authorization verdict, execution permission or universal verification state.

**Validation boundary:** JSON Schema checks object shape only. The source SHA, digest, tenant, actor, attestation, grant, transport and effect references must be checked by source-owning adapters and authoritative systems. `recorded_state=source_verified` is a reported status, **not** a verifier; consumers must not trust a caller's assertion of that value without independent verification. All optional reference fields are pointers, not capabilities.

Separate identifiers: `transport_attempt_ref` is not `executor_attempt_ref`; `effect_ref` is not `observation_ref`; `independent_verification_ref` must remain null or absent unless an actual verifier exists. No semantic evidence is inferred by schema validation. The ISS placeholder remains disabled.

Run checks with Python 3.11+ and `jsonschema` installed: `python -m unittest discover -s tests/contract -p 'test_*.py' -v`. CI may run the same command. Gate O1 issue #2 remains pending for cross-component semantic ratification.
