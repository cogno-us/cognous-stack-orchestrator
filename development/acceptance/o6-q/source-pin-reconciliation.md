# O6-Q source acceptance versus release selection — 2026-10-10

Tracking: [orchestrator issue #72](https://github.com/cogno-us/cognous-stack-orchestrator/issues/72). This is an inventory of source-side acceptance, **not** a connected O6 test result or approval to update the release lock.

## Source of truth and evidence

- Orchestrator inventory base: `667589e8954c6a17195e4209e09f8d41860e4524` (O5-E connected synthetic qualification).
- Hub: `cogno-us/cognous-open-control-stack`, main `2a23a2fbb3f5469872170c07a11b57656c6c3d2f`. Read `component-lock.json` from that exact commit; this inventory does not edit it.
- Runtime: [PR #42](https://github.com/cogno-us/cognous-execution-runtime/pull/42), qualified head `9662302f51d2193a574727c46cdab2485ea7e530`, accepted squash `1b0a9e32d010797711004ae612051a277b07912a`. Five successful workflows at qualified head.
- GAX/IMX: [PR #17](https://github.com/cogno-us/cognous-governed-exchange/pull/17), qualified head `a779b47a255a9b06fe217faceab6270392c1ec3c`, accepted squash `814927dac65a2078d5efee6bbf07c46091844822`. Three successful workflows at qualified head.
- Attestation: [PR #11](https://github.com/cogno-us/cognous-evidence-attestation/pull/11), qualified head `2804255b02ab2ed4f61b4d09da41c3492484aa73`, accepted squash `5786b91696ffa276650c4f7b424c9662ebf96fac`. One successful scoped workflow at qualified head.

## Selected versus newly accepted

| Source component | Hub's selected/accepted component-lock SHA | Latest bounded O6 accepted SHA | Compatibility status |
| --- | --- | --- | --- |
| Execution Runtime (`moltbot_safe`) | `c3c3ee7188b9367cf70b08074b9c40a5c70c94ac` (`accepted_sha` and `core_interop_sha`) | `1b0a9e32d010797711004ae612051a277b07912a` | New revocation closeout is opt-in; NOT selected or O6-connected qualified |
| Governed Exchange (`gax_imx_transport`) | `a1cbc7b28f702283b0e4f3192bb43e4a9e618ebf` | `814927dac65a2078d5efee6bbf07c46091844822` | New local generation fence is opt-in; NOT selected or O6-connected qualified |
| Evidence Attestation (`bitrep`) | `5b5077dafde232a7801cb425c4efddcffb468723` | `5786b91696ffa276650c4f7b424c9662ebf96fac` | New non-authorizing digest custody is opt-in; NOT selected or O6-connected qualified |

Other selected release components remain governed by the unchanged `component-lock.json`. **Do not** infer that source main/merge SHA equals selected release SHA. O5-E connected synthetic refund tests were conducted against their own declared pinned sources, not these newly merged O6 profile SHAs.

## Connected qualification required before promotion

1. Freeze an exact candidate dependency manifest using the accepted O6 merge commits alongside the existing selected versions. No changing accepted C1–C8 semantics.
2. Execute actual source interfaces, not orchestrator-local substitutes: (a) per-item multi-grant revocation attribution and in-doubt original-attempt settlement observation; (b) superseded generation rejection at local effect commit, negative mutation control and restart persistence; (c) independent publisher/witness digest custody rejection with invalid epoch, revoked/stale keys and substituted authority bytes.
3. Carry stable tenant, request, grant, action/effect/attempt and evidence references only when actually present; missing fields remain unknown. Distinguish authority check, refusal, dispatch, transport receipt, destination observation and independent verification.
4. Require scoped negative tests: replayed/colliding IDs, changed grant/policy, concurrent generation update, missing persisted refusal, disabled evidence writers, forged witness, unknown provider outcome and prohibited blind retry.
5. Run candidate exact-head CI and record workflow URLs, source SHAs, test counts, negative controls and remaining limitations. No CI of this connected candidate has been executed by this reconciliation document.

## Release and security boundary

C0 pre-effect revalidation is **not** destination commit atomicity; C1 remains optional/same-host; C2/C3 are unqualified. Neither source acceptance nor a signed digest proves adopted institutional authority, genuine provider settlement, independently validated live custody or operator deployment trust. [Operator trust #30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30) remains OPEN. No credentials, grants, live effects, publication, raw declined payloads or lock modifications are authorized by this inventory.

Disposition: **SOURCE ACCEPTED / RELEASE UNCHANGED / O6 CONNECTED CANDIDATE NOT YET TESTED**.
