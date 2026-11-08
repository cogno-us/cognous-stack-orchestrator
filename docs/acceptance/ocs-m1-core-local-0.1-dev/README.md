# OCS-M1 CORE-LOCAL/0.1-dev — M1-5 acceptance package

**Status: ACCEPTANCE RECOMMENDATION ONLY. This document is not an acceptance act, not a freeze, and not Chief Architect adoption. M1 is NOT ACCEPTED.**
CORE-LOCAL / SYNTHETIC / NONPRODUCTION. Developer evidence is builder-lineage; nothing here is independent qualification or certification. No Copilot review was requested or used.

Controlling sources: architecture [OCS-M1-ARCH-001 v0.9](https://github.com/cogno-us/cognous-open-control-stack/blob/main/architecture/OCS-M1_Canonical_Product_Architecture_v0.9.extracted.md) (sections 5, 8, 11, 13) and static plan [Hub #282](https://github.com/cogno-us/cognous-open-control-stack/issues/282) (unmodified). Ledger: [Hub #273](https://github.com/cogno-us/cognous-open-control-stack/issues/273).

## 1. Executive recommendation

**M1-5 ACCEPTANCE RECOMMENDATION: HOLD** (narrow and closable). Every critical product invariant holds and 10 of 12 mandatory requirements and 5 of 6 canonical scenarios have adequate evidence, but two mandatory conditions are not met as written:

| # | Unmet condition | Evidence | Consequence | Smallest corrective action | Blocks CORE-LOCAL? |
|---|---|---|---|---|---|
| H1 | **OCS-12 / T-OCS-E**: the stop condition (plan §1, §8.7; arch §13) names *an independent consumer* who installs from the published instructions. Every fresh-install run so far (M1-4 PR #161 and this sprint) was executed by the builder lineage in a clean environment (new clone, `env -i`, empty `HOME`). F4 was only partial-independence and predates the packaged installation. | `evidence/t_ocs_e_fresh_consumer_main.txt` | Installation is reproducible and developer-tested, but "independent consumer" is not shown. A developer run cannot be converted into an independent one. | One consumer outside the builder lineage, named by the Chief Architect, follows `development/refund-desk-local/README.md` on a fresh Linux host and records output; or the Chief Architect rules that a clean-environment builder run satisfies §11 T-OCS-E. | **Yes** (mandatory) |
| H2 | **OCS-11**: "Pack absence disclosed". Per-result output (`labels.not_verified`/`limitations`) names Verifier, Attestation and Registry as outside the interface but **does not name Evidence Pack**; Pack absence is disclosed only in READMEs. "Verifier ABSTAIN never PASS" holds vacuously (no Verifier exists in F1/F3). | `orchestration/adapters/refund_disposition/contract.py` `NOT_VERIFIED`; F3 README *Limitations*; section 4 below | Nothing is hidden or mis-claimed, but the machine-readable output omits one named stage. | Chief Architect rules documentation-level disclosure sufficient, **or** a bounded F1 change adds "Evidence Pack" to `NOT_VERIFIED` (changes a frozen F1 contract string and the byte-identical legacy-limitations test; separate sprint under CA21). | **Yes** (mandatory, as written) |

If the Chief Architect rules both H1 and H2 satisfied as they stand, nothing else in this package is an unmet mandatory condition.

**Chief Architect decision required:** ACCEPT or HOLD named CORE-LOCAL/0.1-dev at the source in section 2 (including rulings on H1 and H2). Field: section 11.

## 2. Exact integrated source manifest

| Item | Value |
|---|---|
| Orchestrator `main` assessed | `41f651d27e159f7b348e87f83475bf1bda7a6214` (merge of PR #161) |
| M1-1 / M1-2 / M1-3 / M1-4 merges | `2d4999b752e53d26f1a5e89b2310e9417d931043` ([#158](https://github.com/cogno-us/cognous-stack-orchestrator/pull/158)) · `ffd97cda085ea9afd5bf14a9c3de4c9d0ae0f2b1` ([#159](https://github.com/cogno-us/cognous-stack-orchestrator/pull/159)) · `41ac5f32d2d685e3f74a1ca828b0bef9e02de974` ([#160](https://github.com/cogno-us/cognous-stack-orchestrator/pull/160)) · `41f651d27e159f7b348e87f83475bf1bda7a6214` ([#161](https://github.com/cogno-us/cognous-stack-orchestrator/pull/161)) |
| F1 / F3 contracts | `refund-disposition/0.1.0-dev`, profile registry `refund-profiles/0.1.0-dev` (`refund-routine-v1`, `refund-high-v1`; manifest `refund-integration-pilot-v1` v1.1, digest `sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac`) · `refund-desk/0.1.0-dev` |
| Native development pins (not a formal source lock) | Control Plane `484fdbd297235dd24148ddb0703f2055a31eabff` · Runtime `f7a55e2a8494801e49193f9f46935f0a971c248d` · Replay `7eb7d76eda10ca1ff997bb86853e903e57da625c` · Institutional Governance `1ebe85be4cfe9e221ebd2618120687eb0b325d24` |
| Dependencies | repository hash-lock files `.github/locks/cryptography-pydantic-pytest-513753.txt`, `jsonschema-424038.txt`; observed Python 3.13.18 |
| Engineering Constitution | revision available at `cogno-us/cognous-engineering-constitution@87ce304130061e9cee8ca855854d625dddb3b805`; **project adoption UNVERIFIED** (this repository records "adoption: UNVERIFIED"; no adoption record found) |
| GitHub checks on the assessed head | Analyze (javascript-typescript) success; Analyze (actions) success. They do not analyse or execute the Python code or tests. `main` has rulesets `main-protect` and `tags-locked`; no required status checks. |

Reuse rule applied (CA07): earlier results are used only for source unchanged since; all executions listed here were re-run on or against this exact head, or are static reads of it.

## 3. OCS-01–OCS-12 crosswalk (all twelve are mandatory for CORE-LOCAL/0.1-dev)

Paths relative to the repository. F1 = `orchestration/adapters/refund_disposition/` (`contract.py`, `dispose.py`, `profiles.py`, `stack.py`, `workspace.py`); F3 = `applications/refund_desk/refund_desk/desk.py` (+`cli.py`); T1 = `tests/adapters/refund_disposition/`; T3 = `tests/applications/refund_desk/`; I = `development/refund-desk-local/`. Status vocabulary: PASS / FAIL / BLOCKED / NOT EXECUTED / N/A. "PASS" here means *adequate developer-tested evidence at the assessed head*, never independent qualification.

| ID | Requirement (identifier) | Implementing component / source | Executable test or observed demonstration | Evidence | Status | Remaining limitation |
|---|---|---|---|---|---|---|
| OCS-01 | Stable public callable + separate consuming CLI/app using only the public interface | F1 `__init__.py` `__all__` (10 names); F3 `desk.py:13-14` imports only public names | T3 `test_static::test_imports_follow_independence_rules` (AST); T3 `test_checks` A/B (API + CLI); T1 `test_m11_negatives::Surface` | §6, `evidence/t_ocs_e…` | **PASS** | F3 shares the repo; "fresh consumer" is shown by T-OCS-E (see H1). `CONTRACT_AND_EXPECTATIONS.md` line 7 lists the 8-name public surface of F1 at PR #155 (historical; M1-1 added `PROFILE_REGISTRY_VERSION`, `ProfileIdentity`) |
| OCS-02 | Typed validated proposal; malformed/cross-tenant/over-limit/unapproved refused before Runtime effect; no implicit caller grant | F1 `contract.py` `request_problems`; `profiles.py`; `dispose.py` pre-flight and CP `decide` | T1 `test_contract::RequestValidation`; `test_m11_checks::CheckB` (b1–b13); `test_m11_negatives::test_cross_tenant_request_invalid`, `test_policy_never_exceeds_manifest_cap`; T3 `test_m12_checks::CheckB` | independent native execute/commit counters, SQLite readback (`_m11_support.assert_no_native_activity`) | **PASS** | Over-limit/out-of-scope are native HOLDs after the CP call (still zero Runtime/effect). Cross-tenant tested as proposal-vs-facts tenant; native tenant-binding rejection of a *consistent* wrong tenant is not tested. Caller supplies synthetic facts; the profile id stands in for the action id |
| OCS-03 | Backward-compatible selectable approved profile; two distinct approved cases; default unchanged; unsupported selection refused/HOLD | F1 `profiles.py` closed registry; `dispose.py:168-206`; F3 `--profile`/`--case-reference` | T1 `test_m11_checks::CheckA`; `test_m11_negatives::test_registry_is_closed_and_frozen`; T3 `test_m12_checks::CheckA`; demo scenarios routine/high | §6 A, A2 | **PASS** | Both profiles bind the **same** pinned manifest and differ by action/scope/limits (not two manifests). Unsupported selection is **refused** (`profile_unsupported`, before CP) — stricter than the "HOLD" wording. "Default unchanged" is behavioural (profile=None path); no frozen pre-M1-1 golden output exists |
| OCS-04 | Native CP sole admission authority; HOLD/revoked/wrong scope ⇒ no Runtime dispatch or effect | F1 `dispose.py:211-247` (single Runtime call only after `authorized`) | T1 `test_f1_checks::CheckB`, `test_m11_checks::b7–b9`; T3 `test_checks::CheckB`, `test_m12_checks::test_no_forbidden_runtime_call_on_any_hold_or_refusal_via_one_counter_scope`; demo `hold`, `mismatch` | counters patch native `PinnedControlPlaneExecutor.execute` / `DurableRefundDestination.commit` | **PASS** | Counters are in-process measurements; "wrong issuer" is covered as institution/domain mismatch; no expired-grant test |
| OCS-05 | Admitted action ⇒ one SQLite effect; supported-scope repeat adds no row | F1 `dispose.py:221-256`; Runtime local destination | T1 `test_f1_checks::CheckA`; T3 `test_checks::CheckA`, `test_m13_checks::CheckAB` (commit delta 0, both profiles); demo `routine`,`high` | §6 A/A2; `evidence/` | **PASS** | A repeat re-enters Runtime `execute` (execute=2) and is absorbed by destination idempotency (commit stays 1). Idempotency is per destination database only (no distributed exactly-once) |
| OCS-06 | Separate CP / Runtime / observed state / claim basis / presentation; unsupported success ⇒ uncertain; no inferred absence | F1 `dispose.py` `map_runtime`; F3 `desk.py:238-253, 299-315` | T3 `test_unsupported_executed.py` (R1); `test_checks::CheckC`; T1 `test_f1_boundary` | §6 C | **PASS** | The downgrade is proven at presentation level with constructed F1 results; no real-stack path produces "unsupported executed". All evidence producer-reported |
| OCS-07 | Resolvable source/profile-pinned Replay evidence, digest, truthful failure reasons; independent read-only digest + SQLite agreement | F1 `dispose.py` `_evidence`; F3 `desk.py` evidence block incl. `replay_note` (M1-3) | T1/T3 CheckA recompute Replay and source digests; T3 `test_m13_checks`; **this sprint:** separate-process `verify_ocs07_readonly.py` (digest recompute, read-only SQLite, bundle effect_id/amount/unit == row) on routine and high | `evidence/ocs07_verifier_output.txt` (22/22 checks PASS) | **PASS** | The separate-process check was run by the builder lineage (not an independent party). A same-correlation repeat reports `import_failed` with the verbatim reason (Issue #157; pinned single-proposal importer) — surfaced, native outcome unchanged. "Digest" is a file digest |
| OCS-08 | Unresolved dispatch ⇒ UNKNOWN, no auto redispatch, effect-free reconciliation resolving only on observed state, no duplicate | F1 `dispose.py` (`prior_uncertain_dispatch`, `_reconcile`) | T1 `test_f1_checks::CheckC`, `test_f1_boundary`; T3 `test_checks::CheckC`, `test_m12_checks::CheckC`, `test_m13_checks::CheckC`; demo `uncertain` | §6 C; `evidence/` | **PASS** (committed-effect branch) | Resolution is tested only where the effect committed. The branch "CP record exists but effect never committed ⇒ reconcile stays unknown" has no test; reconcile of an undispatched case is refused (`no_prior_dispatch_record`, no row created, `effect_absence_established=false`, probed this sprint). Fault injection uses a private test hook (`simulate="lost_ack"`) |
| OCS-09 | Exact per-invocation workspace ownership; no unrelated deletion; visible cleanup failure; caller state preserved; no broad glob | F1 `workspace.py` (unique `mkdtemp`, removes exactly that path, refuses symlink, verifies absence); I `devtool.py cleanup` | T1 `test_contract::CleanupHonesty` (failure reported, sibling survives, symlink refused); T3 `test_m14_install::CleanupSafety`; **this sprint:** two-allocation probe and removal/glob grep | `evidence/ocs09_probe.txt` | **PASS** | Failure visibility is proven with a mocked `rmtree`; "no glob" rests on source reading + grep, not an automated static test; calls are serialised by a process lock |
| OCS-10 | Exact component/profile commits; wrong/tampered pin fails closed; not labelled a formal lock | F1 `stack.py:48-106`; `source_pins.json` ("NOT A SOURCE LOCK"); `profiles.py` digest; I `setup` | T1 `test_contract::ScopeAndPins`, `test_m11_negatives` digest tests; I `test_m14_install` drift refusal; **this sprint:** on-disk probes (HEAD drift, dirty tracked manifest file, committed manifest change) against real stack copies | `evidence/tocs_d_tamper_probe.txt` | **PASS** | Pins are development pins, not certified custody |
| OCS-11 | Distinguishable refused/held/unknown/failed; reason codes, native disposition, limitations, retry permission; Pack absence disclosed; Verifier ABSTAIN ≠ PASS | F1 `contract.py` dispositions, `NOT_VERIFIED`; F3 `desk.py` outcomes | T3 `test_present_unit`, `test_m12_unit`, `test_unsupported_executed`; T1 `test_m11_negatives` reason-set tests | §4, §6 | **PARTIAL — see H2** | Pack absence is in READMEs, not in result output; ABSTAIN criterion is vacuous (no Verifier in F1/F3) |
| OCS-12 | One bounded reproducible nonproduction install; action/refusal/reconcile/cleanup via public interface; undocumented steps reported | I `dev.sh`/`devtool.py`/`README.md` (M1-4) | T3 `test_m14_install` (13 stack-free + gated fresh workflow); **this sprint:** fresh `env -i` run on `41f651d`: setup 0, repeat setup 0, demo 5/5, evidence, cleanup | `evidence/t_ocs_e_fresh_consumer_main.txt` | **PARTIAL — see H1** | Run by builder lineage, not an independent consumer. The `uncertain` demo needs the F1 **test-tree** fault fixture and the private request builder (disclosed); the public CLI cannot create an uncertain state. pip's cache lands in `$HOME/.cache` (outside owned state, not removed by `cleanup`). F4 partial independence is not restated in the installer README |

**Totals:** mandatory requirements with adequate evidence **10 / 12** (OCS-01–OCS-10 PASS; OCS-11, OCS-12 PARTIAL); FAIL 0; BLOCKED 0.

## 4. Canonical scenarios (arch §11, plan §6)

| Scenario | Result | Basis |
|---|---|---|
| **T-OCS-A** routine authorized action | **PASS** | Fresh demo on `41f651d`: native CP `authorized`, one `applied` SQLite row, `effect_id` matches result and row, Replay `imported` (digest recomputed, row/bundle agreement by separate process), labels `synthetic_authority=true`, `authenticated=false`, `nonproduction=true`, `evidence_basis=producer_reported`, synthetic/nonproduction limitations present |
| **T-OCS-A2** second profile | **PASS** | `refund-high-v1`, customer-002, 150.00 USD, `case_reference` required; own effect id; `profile` block carries registry/manifest/digest/action identity; customer-001 under the high profile is a native HOLD (no fixed-customer bypass in either direction) |
| **T-OCS-B** refusal | **PASS** | revoked authority ⇒ HOLD `grant_revoked`; wrong scope ⇒ HOLD; over-limit/cross-tenant/unsupported profile covered by T1/T3 suites; unsupported profile refused `profile_unsupported`; zero rows and zero Runtime/commit by independent counters |
| **T-OCS-C** uncertain execution | **PASS** | lost ack ⇒ `uncertain`, repeat refused `prior_uncertain_dispatch` (exit 3, no new row), reconcile read-only (`observed`, 0 invocations, rows unchanged), `retry_permission=not_established`, `effect_absence_established=false`. Committed-effect branch only (see OCS-08) |
| **T-OCS-D** source/profile integrity | **PASS** | digest tampering ⇒ `profile_manifest_digest_mismatch` before any effect (T1); this sprint's on-disk probes: HEAD drift ⇒ `stack_component_not_pinned_revision`, modified tracked manifest file ⇒ `stack_component_tree_modified`, committed manifest change ⇒ `stack_component_not_pinned_revision`; each refused with Runtime not invoked, no execution claim, and the prior committed row byte-identical |
| **T-OCS-E** fresh developer consumption | **EXECUTED; independence condition unmet (H1)** | fresh run on `41f651d`: all steps exit as documented, no undocumented dependency beyond the documented ones, raw CP/SQLite/Replay inspection, owned cleanup (`cleanup --all` exit 3 plan, `--yes` exit 0) |

**Scenarios fully meeting expectations: 5 / 6** (T-OCS-E pending H1).

## 5. Critical invariants (all hold at `41f651d`)

| # | Invariant | Holds | Basis |
|---|---|---|---|
| 1 | Only native CP decides admission | yes | F1 `dispose.py:211-247`; no other path sets `authorized` |
| 2 | Only authorized Runtime effects commit | yes | single Runtime call after `authorized`; hold/pre-flight tests with native counters |
| 3 | F1/F3 invent no authority | yes | F3 `present()` reads F1 fields only; F1 evaluates no policy |
| 4 | Exactly two selectable profiles | yes | closed, frozen registry; ghost profile refused |
| 5 | Profile/source identity preserved | yes | `profile` block in results; pins verified per call |
| 6 | Wrong profile/source/authority fails closed | yes | §4 T-OCS-B/D |
| 7 | Local idempotency prevents duplicates | yes | commit delta 0, one row on repeat (both profiles) |
| 8 | UNKNOWN never authorizes automatic retry | yes | `prior_uncertain_dispatch`; `retry_permission=not_established` everywhere |
| 9 | Reconciliation causes no effect | yes | 0 invocations, rows byte-identical |
| 10 | Replay import failure does not change native outcome | yes | repeat: `executed`, `import_failed` + verbatim note |
| 11 | Evidence labelled producer-reported | yes | `labels.evidence_basis=producer_reported` |
| 12 | Synthetic authority not shown as authenticated | yes | labels `authenticated=false`; the inherited fixture field `identity.authenticated:true` is not an authentication claim, is not used to derive any label, and no test asserts that separation (note) |
| 13 | Cleanup touches only owned state | yes | F1 exact-path disposal; installer owner marker + fixed child list; every unsafe-target case in `CleanupSafety` refused with nothing removed |
| 14 | No optional module mandatory | yes | no Pack/Verifier/Attestation/Registry/ODES/GAX import (T1 `test_no_forbidden_imports`, T3 `test_static`); installer stdlib + public F1/F3 only |

## 6. Evidence and test links

- Fresh consumer run on integrated head: `evidence/t_ocs_e_fresh_consumer_main.txt` (clone, `env -i`, empty HOME; commands, exit codes, demo PASS lines, limitations/labels, evidence index, cleanup).
- Independent-process Replay/SQLite check: `evidence/verify_ocs07_readonly.py` and `evidence/ocs07_verifier_output.txt`.
- On-disk pin/manifest tamper probes: `evidence/tocs_d_tamper_probe.txt`.
- Workspace probes: `evidence/ocs09_probe.txt`.
- Reused developer suites at the assessed head (re-run by three read-only inspector agents in scratch copies, pinned stack, no skips): T1 `test_contract` 12, `test_f1_checks` 3, `test_f1_boundary` 5, `test_m11_checks` 20, `test_m11_negatives` 30 · T3 `test_static` 5, `test_checks` 13, `test_unsupported_executed` 5, `test_present_unit` 7, `test_m12_unit` 22, `test_m12_checks` 20, `test_m13_unit` 8, `test_m13_checks` 5, `test_m14_install` 13 stack-free (the gated fresh workflow was executed manually, see above).
- Predecessor adverse evidence preserved: PR #159 red/first-correction history, PR #160 red commit `2a47502`, PR #161 red commit `7269d2a`, Issue #157, G3 Q1–Q5 verdicts, F4 trial (unchanged, not relabelled).

## 7. Known limitations (disclosed, unchanged)
Linux-only developer installation; network needed for first `setup`; synthetic development-only authority with `authenticated=false` and no verified institutional authentication; producer-reported evidence; Replay single-proposal importer limitation (repeat ⇒ `import_failed`, Issue #157); local SQLite effect, per-database idempotency only; development source pins, not certified custody or a formal P1 lock; no production authorization; no independent institutional qualification performed; Constitution adoption UNVERIFIED; Verifier ALPHA/HOLD and P1-EXIT BLOCKED/DEFERRED remain separate; F1/F3 Python tests are not collected by hosted CI.

## 8. Non-blocking observations (no corrective sprint required for CORE-LOCAL unless the Chief Architect says so)
1. OCS-08 absent-after-attempt branch has no direct test. 2. OCS-02 native tenant-binding of a consistent wrong tenant untested. 3. OCS-09 "no glob" and two-invocation independence are probe/read evidence, not automated tests. 4. Unsupported selection is a refusal rather than a HOLD (stricter). 5. `setup` leaves pip's cache in `$HOME/.cache` (`--no-cache-dir` would avoid it; installer change deferred). 6. `CONTRACT_AND_EXPECTATIONS.md` line 7 is the historical PR #155 surface (kept, per evidence-preservation rule).

## 9. CI Scope Declaration
Hosted CI here is CodeQL (JavaScript/TypeScript and Actions analysis). It does not analyse or execute the Python code, the installer or any test cited above; there are no required status checks on `main`. Every test result in this package is builder-lineage developer evidence run locally against the pinned stack. This PR changes only documentation, evidence text, one stdlib helper script and the source-window test declarations (W-M1-5); no product, F1, F3, installer, native component, workflow or lock file is modified.

## 10. Rollback / reference baseline
Baseline: Orchestrator `main` `41f651d27e159f7b348e87f83475bf1bda7a6214`. Rollback of this package: revert its PR (delete `docs/acceptance/ocs-m1-core-local-0.1-dev/` and the W-M1-5 window); nothing else depends on it.

## 11. Reserved Chief Architect decision (left undecided)
```
Named profile: CORE-LOCAL/0.1-dev at Orchestrator 41f651d27e159f7b348e87f83475bf1bda7a6214 and the native pins in section 2
Ruling on H1 (independent consumer):   [ UNDECIDED ]
Ruling on H2 (Pack absence in output): [ UNDECIDED ]
M1 ACCEPTED / HOLD:                    [ UNDECIDED ]
Decided by / date:                     [ blank ]
```
Recommendation (not a decision): **HOLD** pending H1 and H2. Not production-qualified, not independently qualified, not certified.
