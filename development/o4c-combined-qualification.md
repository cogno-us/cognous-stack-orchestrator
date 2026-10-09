# O4c combined acceptance candidate

Reference base: `b39dfc75dfce6bb33ebcd51eed550f78cc9282dd` (merged A/B/C/D). This is **test-only** and follows Governor [issue #14](https://github.com/cogno-us/cognous-stack-orchestrator/issues/14) and scoped qualification [#19](https://github.com/cogno-us/cognous-stack-orchestrator/issues/19).

The single CI job executes existing O3, O4, O4b, and all four O4c test directories plus new cross-boundary non-promotion cases. A green run establishes **local regression compatibility only**. It is NOT a test of real chain RPC authenticity, real-world institutional adoption, cross-repository deployment, independently observed effects, or qualified agentic execution.

The new tests require that absent attestation trust never verifies, missing chain observation remains unknown, an adoption *reference* leaves institutional effects held, and a message/effect *reference* never turns into verified authorization or effect occurrence. No issuer or cryptographic verification implementation is duplicated.
