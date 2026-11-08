# M1-5 closeout — H1 and H2 status and decision packet

**This is a status and recommendation record. It is not an acceptance act. M1 is NOT ACCEPTED; the original M1-5 package ([`README.md`](README.md), recommendation HOLD) is preserved unchanged.** No Copilot review was requested or used. Constitution adoption: UNVERIFIED (`cogno-us/cognous-engineering-constitution` revision `87ce304130061e9cee8ca855854d625dddb3b805` exists; no project adoption record found).

Integrated `main`: `bbd127aff13ed844ad15780efdc34b65aa1c7c42` (merge of PR #162). Assessed product source: `41f651d27e159f7b348e87f83475bf1bda7a6214`. Verified: the two commits between them change only the acceptance package (`README.md` and five `evidence/` files) and six scope-window test files; nothing under `orchestration/`, `applications/`, `development/`, `.github/` (so `SOURCES.json` and `source_pins.json` are unchanged). Hosted checks on `bbd127a`: Analyze (javascript-typescript) success, Analyze (actions) success (they do not run the Python code or tests). Governing sources: architecture OCS-M1-ARCH-001 v0.9 and [Hub #282](https://github.com/cogno-us/cognous-open-control-stack/issues/282); ledger [Hub #273](https://github.com/cogno-us/cognous-open-control-stack/issues/273).

## Gap status

| Gap | Requirement | Status | What closes it |
|---|---|---|---|
| **H1** | OCS-12 / T-OCS-E: an independent consumer follows the published installation | **PENDING** — no independent consumer has been designated or has reported; builder-lineage runs (M1-4 PR #161; M1-5 fresh run) are not counted | one external consumer returns the filled template from [`INDEPENDENT_CONSUMER_HANDOFF.md`](INDEPENDENT_CONSUMER_HANDOFF.md); the Architect designates who |
| **H2** | OCS-11: "Pack absence disclosed" | **Recommend SATISFIED** (Architect ruling required) | Architect ruling on the interpretation below; no code change recommended |

Ten requirements (OCS-01–10), five scenarios and 14 invariants are not reopened.

## H1 — what is outstanding and what will be checked

**Single outstanding Architect dependency:** designate a real person or organization outside the builder lineage and send them the handoff (the handoff is self-contained: exact repository and SHA, prerequisites, commands, expected results for routine/high/refusal/uncertain-reconcile, return template, failure rules). The builders must not operate the run.

On receipt, the following will be checked and recorded (without altering any historical evidence):
1. **Independence and actual execution:** named identity; stated relationship to the builders; "no help during the run"; transcript with timestamps consistent with a real run on the consumer's host (uname/git/python versions); not produced by an agent in the builder lineage.
2. **Source identity (CA07):** `git rev-parse HEAD` equals `41f651d27e159f7b348e87f83475bf1bda7a6214`; `install-record.json` component heads equal the four pins; hash-lock digests equal the repository files.
3. **T-OCS-E expectations:** setup exit 0 and "already at pin" on repeat; demo five PASS lines; their own routine CLI call executed and revoked call held (`grant_revoked`) with zero rows; evidence index legible; cleanup plan exit 3 then `--yes` exit 0; no undocumented dependency or intervention (any is reported as a defect in OCS-12, not hidden).
4. **Other mandatory gaps exposed:** any failure, confusion about authorized/held, executed/uncertain, native effect/claim, producer-reported/independent, or `imported`/`import_failed`.
Outcome rule: complete, source-bound results meeting T-OCS-E ⇒ H1 SATISFIED and OCS-12 re-assessed PASS with the consumer's report cited next to (not instead of) the builder evidence; incomplete, unverifiable or adverse results ⇒ H1 FAILED/PENDING with the adverse evidence preserved and the smallest corrective action named. This is real consumer evidence, not institutional certification or independent qualification.

## H2 — interpretation decision packet

**Question.** Does the canonical contract require Evidence Pack absence to appear in machine-readable per-result limitations (reading B), or only require honest disclosure (reading A)?

**Exact governing text** (architecture OCS-M1-ARCH-001 v0.9; static plan #282):
- OCS-11 normative: "The application SHALL expose reason codes, native disposition, limitations, retry permission and traceable evidence references **without hiding a missing stage**."
- OCS-11 observable acceptance: "Refused, held, unknown and failed results are distinguishable; Verifier ABSTAIN never presented as PASS; **Pack absence disclosed**."
- §3: "a consumer SHALL NOT claim an unavailable downstream stage as run or trusted. A core developer transaction works without Verifier/Registry; their absence is **disclosed, not masked**."
- §4 step 7: "…no claim upgrades occur on missing stages." §6.2: "Verifier not selected or ABSTAIN | not run or abstain (actual native field) | No upgrade to verification PASS." §9: "Evidence packaging | Explicit actual Pack state **where selected**."
- Plan §3 OCS-11: "limitations, retry permission and missing-stage honesty; Verifier ABSTAIN ≠ PASS". Plan §4.5: "No nonexistent Pack/Verifier/Attestation/Registry stages reported as run." Plan §1/§5: Pack/Verifier/Attestation/Registry are **not mandatory** CORE-LOCAL completion conditions.

**Does any text prescribe an output-level field?** **No.** Every sentence requires *disclosure*, *honesty* or *not claiming* a stage; none names a result field, a limitations entry, or a format for Pack. The only field-level wording ("actual native field", §6.2) concerns a native Verifier status that does not exist in F1/F3, and §9's "where selected" makes an explicit Pack state conditional on Pack being selected (it is not). The word "limitations" in the OCS-11 normative sentence lists a field the application exposes; it does not say Pack absence must be placed in it. Independent read-only analysis of both documents reached the same conclusion and noted the sentence is "ambiguous" only in the sense that reading B is plausible but not stated.

**Existing disclosure locations (at `41f651d`):**
- `applications/refund_desk/README.md` *Limitations*: "No Pack, Verifier, Attestation or Registry. No independent qualification, certification or production claim."
- `orchestration/adapters/refund_disposition/README.md`: "Excluded: Pack, Verifier, Attestation, Registry, ODES, GAX, CDC, ISS."; "Pack is not used by F1"; "No Verifier, Pack, Attestation or Registry".
- `development/refund-desk-local/README.md` *Known limitations*: "No Evidence Pack, Verifier, Attestation, Registry, ODES/GAX, CDC/ISS, container or CI integration."
- `applications/refund_desk/SOURCES.json` `not_used`: manifest, evidence_pack, verifier, evidence_attestation, evidence_registry; F1 `source_pins.json` `not_used_by_f1`.
- Per-result output: `labels.not_verified`/`limitations` state "the Verifier, Attestation and Registry are not part of this interface" (Evidence Pack is **not named** there). Nothing in any result implies Pack or Verifier ran: the only stage represented is Replay (`evidence.replay_state`), and `evidence_basis` is `producer_reported`.

**Consumer visibility.** A developer installing through `development/refund-desk-local/` is directed to the installer README, whose limitations name Evidence Pack, and the evidence index legend states that every artifact is producer-reported. A developer consuming only JSON sees that verification, attestation and registry are outside the interface and sees no field suggesting Pack ran.

**Compatibility implications of changing F1 `NOT_VERIFIED`** (analysis of the tests and contracts at `41f651d`): the tuple feeds `labels.not_verified` and `limitations` of every routine-profile result. Tests assert the routine output is "byte-identical to the legacy list" (`test_m12_checks.py`, `test_m12_unit.py`, `_m12_support.py`, `test_m11_checks.py`); F1 oracles require historical suites to pass unchanged (`ORACLES_M1_1.md`); F3 contract amendments M2.2/M3.2 promise existing keys and values are preserved. Adding a string would therefore be a deliberate F1 contract change under CA21 (compatibility transition, test and documentation updates, F3 re-verification), not an editorial edit. Adding a new result key would additionally break exact key-set assertions.

**Reading A vs B.**
- A (existing explicit documentation satisfies "Pack absence disclosed"): supported by the text — it requires disclosure and forbids claiming/masking a stage, and does so without specifying location; Pack is optional and unselected; nothing is hidden or claimed.
- B (output-level field required): not supported by any quoted sentence; adopting it would be an interpretation that changes a frozen contract string.

**Recommended Architect ruling.** *H2 SATISFIED under reading A:* OCS-11's "Pack absence disclosed" is fulfilled by the explicit READMEs, `SOURCES.json` `not_used` and the per-result statement that Verifier/Attestation/Registry are outside the interface; the "Verifier ABSTAIN ≠ PASS" clause holds because no Verifier is present or reported. Do **not** change `NOT_VERIFIED` for symmetrical wording. *If the Architect nevertheless rules reading B,* authorize one small separate F1 compatibility sprint (add "Evidence Pack" to `NOT_VERIFIED`, update every byte-identical assertion and the F3 documentation, re-verify F1/F3, new exact-head packet); it is not started and is not recommended. Limitation to retain either way: the per-result text omits the word "Pack", disclosed here and in the original package.

## Recommendation and minimum remaining decision
- **H1: PENDING.** **H2: RECOMMEND SATISFIED** (ruling reserved). **M1: HOLD** until H1 evidence is returned and reconciled and the Architect rules on H2; then the revised recommendation is ACCEPT if H1 meets T-OCS-E and H2 is ruled satisfied.
- **Next Architect decision (one packet):** (1) designate the independent consumer and release `INDEPENDENT_CONSUMER_HANDOFF.md` to them; (2) rule on H2 — satisfied under reading A (recommended) or change required. The final M1 ACCEPT/HOLD decision remains reserved to the Chief Architect after H1 is reconciled.

## CI Scope Declaration and rollback
Hosted CI is CodeQL (JS/TS and Actions analysis) only; it does not execute any Python or script. This change adds two documentation files; no product, F1, F3, installer, native, workflow or lock file changes. Rollback: revert the PR that added this file (baseline `bbd127aff13ed844ad15780efdc34b65aa1c7c42`).
