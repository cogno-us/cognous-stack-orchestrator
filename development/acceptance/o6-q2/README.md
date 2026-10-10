# O6-Q2 candidate qualification scope

Issue: [#74](https://github.com/cogno-us/cognous-stack-orchestrator/issues/74). This workflow checks actual source revisions in three independent jobs, never alters `component-lock.json` and never activates optional profiles.

## Freeze and execution

- `runtime-connected-refund`: O5-E already accepted Action Manifest `8d1572d4f926c968a8704cb912a6e9d49166f74a`, Control Plane `e66e5f163c5d5c112ff345a2f332b4c3893ee183`, Replay `2069a0ba1398812c3a8669331a7d8b87c80c4a48` and Evidence Pack `87293cfcbe8dfa2368d5bf77019945ba8ef1ae71`. Replace only Runtime fixture source with newly merged O6 `1b0a9e32d010797711004ae612051a277b07912a`. Execute the actual-source connected refund handoff, Replay/Evidence Pack suite, contract adversarial tests and the O6 Runtime revocation suite. **This is a connected synthetic refund candidate with a newer Runtime source, not connected use of its new optional revocation profile.**
- `gax-generation-fence-source`: checkout merged `814927dac65a2078d5efee6bbf07c46091844822`, assert git head, execute its actual `tests/test_generation_fence.py`.
- `attestation-digest-custody-source`: checkout merged `5786b91696ffa276650c4f7b424c9662ebf96fac`, assert git head, execute its actual `tests/test_authority_digest_custody_profile.py`.

Each test assertion is executable in CI. A successful run confirms only the test's exact declared scope. It **does not** prove these three newly accepted profiles operate together, propagate the same authority/effect IDs or implement end-to-end multi-component recovery. Additional actual-source cross-component traces and negative mutation cases are required before describing that stronger claim.

## Boundaries

Synthetic refund, no payment processor. No institutional grants, authority issuance, live payment effects, secrets, production trust roots, release change, C2/C3 transaction coordination, trusted timestamping or independently proven destination settlement. C0 check-to-commit non-atomic; optional C1 same-host and not enabled. Source acceptance is distinct from hub runtime selection and deployment evidence #30.

## Evidence rule

Do not declare this candidate passed until all three jobs complete with success at the exact PR head. Preserve the original selected release lock; record a workflow URL, head SHA, source SHAs, failing case (if any), and limitations in the Governor ledger.
