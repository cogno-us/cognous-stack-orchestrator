# O6-Q4 bounded authenticated-source handoff to optional local generation fence

Issue [#78](https://github.com/cogno-us/cognous-stack-orchestrator/issues/78).

Run exact frozen source implementations: O5-E Action Manifest `8d1572d4f926c968a8704cb912a6e9d49166f74a`, Control Plane `e66e5f163c5d5c112ff345a2f332b4c3893ee183`, O6 Runtime `1b0a9e32d010797711004ae612051a277b07912a`, GAX `814927dac65a2078d5efee6bbf07c46091844822`, Attestation `5786b91696ffa276650c4f7b424c9662ebf96fac`. The tests import actual source directly, with SHA checks from the accepted O5-E and O6-Q3 loaders.

Sequence: digest custody checked separately and described as non-authorizing; actual Action Manifest proposal and Control Plane synthetic issued claim verified; test-only adapter invokes actual Runtime executor **within** GAX local generation commit fence; retained real Runtime-generated attempt/effect IDs are used in O6 revocation closeout and unknown destination observation. Cases cover missing-grant HOLD, tampered digest, superseded generation persisted refusal, approval withdrawal and original-attempt no-retry after unknown.

This is *not* a production authorization or generalized GAX->Runtime adapter. The Control Plane resolver authentication is a **synthetic test-owned flag**, not independently proved institutional adoption or real grant issuance. The Attestation digest signature is about integrity, not actor permission. GAX and Runtime own separate SQLite boundaries; there is no asserted cross-database atomicity, externally verified settlement, destination commit linearizability or C2/C3 guarantee. The test combines a source-side Runtime synthetic destination with synthetic orchestration, no external payment provider, and no live effects. C0 remains non-atomic and optional C1 unchanged. Hub component-lock remains unchanged; operator deployment trust #30 remains open.

Exact-head CI success is required before claiming acceptance, merge or changing any release status.
