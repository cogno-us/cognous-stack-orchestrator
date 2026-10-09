# O4e operator evidence submission

Tracked by [#30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30) and implementation [#32](https://github.com/cogno-us/cognous-stack-orchestrator/issues/32).

Create a private or permissioned non-secret evidence packet with schema `cognous-o4e-evidence/1`, `environment_id`, `operator_identity`, `deployment_revision`, `observed_at_utc`, and two maps: `references` and `negative_tests`.

Each evidence reference is an HTTPS URL without embedded credentials, query parameters or fragments, and a lowercase SHA-256 content digest. Required source reference names: `rpc_authentication`, `independent_checkpoint`, `receipt_log_provenance`, `deployed_bytecode`, `attestation_trust_snapshot`, `trusted_clock`, `upstream_verifier`, and `key_lifecycle`. Required negative-test names: `wrong_chain`, `wrong_contract`, `reorg`, `rpc_unavailable`, `revoked_key`, `expired_key`, and `uncertain_time`.

The validator checks **structural completeness, not authenticity or deployment truth**. URLs and digests may be fabricated; the checker never fetches them and always outputs `status=hold`, `authority=not_established`, `effect=disabled`. `submitted_unverified` is a review queue label, **not acceptance**. The owner/operator must separately supply actual independently confirmed operational evidence, reviewer disposition and a distinct signed acceptance. Never commit private keys, bearer tokens or confidential endpoints.
