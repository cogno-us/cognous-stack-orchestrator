# O4b producer evidence boundary (candidate)

The module `orchestration/producer_evidence.py` is a **strict local inspector**, NOT an authenticated producer adapter. It pins the historically selected Registry revision `d5e45d275cb301d9684b543e93b05997991d1cf2` and Evidence Attestation revision `5b5077dafde232a7801cb425c4efddcffb468723`. These historical pins do not prove the branch currently inspected or integration into the orchestrator.

It checks supplied EvidenceSubmitted field shapes, identity strings, exact bytes and a reported verifier outcome. It cannot establish chain authenticity, cryptographic issuer trust, or current institutional authority from untrusted input. Its outputs always mark those properties **not_established**. No claim of verification or executable delegation is made.

**Critical remaining work:** independently authenticated source receipts and canonical deployment identity, real upstream BitRep verification invocation with operator-trusted snapshot, source-owned identity mapping, and actual accepted Authority Context resolver. Do not call this a verified producer until those separate requirements are implemented and qualified.

Tests: `python -m unittest discover -s tests/integration -p 'test_*.py' -v`.
