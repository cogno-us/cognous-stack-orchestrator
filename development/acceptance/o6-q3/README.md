# O6-Q3 actual-source optional profile composition

[Engineering issue #76](https://github.com/cogno-us/cognous-stack-orchestrator/issues/76).

The bounded synthetic test runs **actual source implementations from three pinned O6 merge commits in one Python process**:
- Runtime revocation sidecar `1b0a9e32d010797711004ae612051a277b07912a`
- GAX lineage generation commit fence `814927dac65a2078d5efee6bbf07c46091844822`
- Attestation publisher/witness digest custody `5786b91696ffa276650c4f7b424c9662ebf96fac`

The test-owned synthetic gate first calls the genuine attestation verifier, refuses tampered authority bytes, attempts a superseded local generation commit (fail-closed with durable minimal refusal), then commits only the current generation to a **test-owned in-memory synthetic destination**. It carries the same effect identifier into the genuine Runtime revocation disposition store and retained original attempt, records an in-doubt revocation and verifies a restart-persistent unknown observation with `retry_eligible=False`. Negative cases include an invalid digest commitment, generation mismatches, bounded refusal counters across restart and disabled disposition evidence writer.

**Important boundary:** This is a connected *test-owned composition of three optional source implementations*, not an upstream product workflow or authorized real-world execution. The synthetic destination stub does not represent a payment provider or authenticated independently observed settlement. The digest custody verifier reports `non_authorizing_digest_custody`; no approval/grant is derived from it. The Runtime and GAX stores are separate local SQLite files, with no asserted cross-database atomicity or distributed lock. The test does not connect to the existing O5-E Control Plane/Action Manifest authenticated issuance path.

The workflow checks out exact merge revisions, and the test itself verifies each source `git rev-parse HEAD`. Success cannot be claimed before the exact-head CI succeeds. No release-selection/lock updates, live credentials or production effects. C0 is not destination atomicity; C1 optional and same-host; no C2/C3. Operational trust #30 remains open.
