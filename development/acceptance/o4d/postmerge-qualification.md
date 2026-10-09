# O4d post-merge local test gate

Source commit: `acdb0f8a63bffffe3635d1f4a43451929063e1e7`.

The single CI job runs existing O3/O4/O4b/O4c tests plus O4d-A Registry source observation, O4d-B operational Attestation trust, and O4d-C source interface mapping.

**Passing CI is scoped to local package and contract regression only.** It does not independently validate RPC provider honesty, blockchain consensus finality, current production credentials, source-owner ratification, institutional adoption, production deployment, or effect observation.

If this CI passes, the next Governor gate remains open under issues [#14](https://github.com/cogno-us/cognous-stack-orchestrator/issues/14) and [#2](https://github.com/cogno-us/cognous-stack-orchestrator/issues/2). This document cannot confer institutional authorization.
