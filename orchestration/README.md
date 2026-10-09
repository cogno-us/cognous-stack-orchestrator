# O4 read-only source boundary

`provenance_context.py` is an **experimental local consistency assessment**, not a Registry node, attestations verifier, institutional resolver or runnable execution orchestration service. It has no I/O, credentials, blockchain RPC, signing, policy evaluation, or effect dispatch.

It consumes *caller-supplied* `EvidenceSubmitted` event fields, log identity, exact content bytes, optional reported attestation result and proposed Authority Context marker. Source authenticity, chain finality, independent verifier trust and institutional adoption all remain **not established**, regardless of the reported fields. The result must not be passed into the Control Plane as a valid grant.

Its narrow input is intentionally a test-oriented source projection, not an accepted adapter format or canonical contract. Exact upstream source canonicalization, transaction receipt validation, cryptographic attestation verification and organization/tenant mapping are future separately reviewed work.

Run: `python -m unittest discover -s tests/integration -p 'test_*.py' -v`. No third-party package required for this test file.
