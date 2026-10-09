# Integration contracts — proposal, not accepted schema

1. Pin each component revision and interface version before interoperation claims.
2. Carry stable correlation, tenant, actor, proposal, action, effect, attempt, policy and evidence references where legitimately present. Mark missing values unknown; never fabricate identifiers.
3. Maintain separate knowledge, signature/attestation, grant, policy decision, execution, observation and verification statuses.
4. Fail closed for unresolved action identity, tenant binding, current grant, changed payload/target/adapter or stale critical evidence.
5. Do not blindly retry an effect after unknown delivery; reconcile using destination evidence and stable effect IDs.
6. Do not elevate an ISS response, ODES envelope, Replay reconstruction or Evidence Pack validation into permission or proof of independently verified effects.
7. Optional adapters must not modify the mandatory bounded reference chain by default.
8. Do not copy proprietary ISS, Architecture of Mind or private IGPG implementation material into integration artifacts.

Changes to accepted C1–C8 contracts belong in the original control-stack governance process, not this scaffold.
