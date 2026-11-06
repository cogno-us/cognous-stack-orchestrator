# Interface design: external digest/count checkpoint (Q6)

**Non-authorizing. Provisional. Not frozen.** Release and production remain on HOLD. Builds on [../EXTERNAL-CHECKPOINT-NOTE-Q10.md](../EXTERNAL-CHECKPOINT-NOTE-Q10.md). The claim stays **local chain consistency with limited truncation detection** until this interface is adopted by a custodian and independently qualified. No authenticity claim, no complete tamper-evidence claim.

## 1. Roles

- **Orchestrator (producer):** derives a checkpoint from a head the store reported (`head_sequence` as count, `head_digest`; empty workflow is count 0, digest `null`). Holds no anchor. An `outcome_ambiguous` append must be reloaded before checkpointing.
- **Custodian (proposed: Evidence Attestation, subject to its owner's acceptance):** independently retains checkpoints append-only, outside the store's directory and control. The code here is a synthetic local-file stand-in, not that component.
- **Verifier (Qualification-style):** read-only. Compares a candidate history's head digest and count (optionally the full ordered digest list) with the retained checkpoints. It is not the operational store and does not repair.

## 2. Checkpoint record (`ocs-workflow-checkpoint/0`, provisional)

Canonical JSON (same `rfc8785-jcs` subset as the store), members: `profile`, `schema_version`, `canonical_profile`, `workflow_id`, `store_profile` (`ocs-workflow-event/0`), `store_schema_version`, `producer`, `checkpoint_sequence` (1-based, per workflow), `head_count`, `head_digest`, `predecessor` (digest of the previous checkpoint, `null` at sequence 1), `digest` (sha256 over the record without `digest`). No verdict, pin, grant or authority member.

## 3. Custodian retention rules (refusal codes, closed)

`schema_invalid`, `invalid_workflow_id`, `unsupported_profile`, `workflow_mismatch`, `producer_mismatch` (producer fixed per series), `duplicate_checkpoint`, `sequence_gap`, `predecessor_mismatch`, `head_regression` (count decreased), `head_fork` (same count, different digest, anywhere in the series), `io_failure`, `custody_corrupt`. A refusal changes nothing. There is no delete, rewrite or truncate operation; files are created by exclusive link at mode 0444 from a randomly named temp file that is removed on failure; a stale temp of that exact pattern is ignored, any other stray entry fails closed. Reads refuse symlinks (O_NOFOLLOW, lstat).

## 4. Verifier result (closed)

Verdict words: `match`, `mismatch`, `unverifiable` only.

| Verdict | Codes | Condition |
|---|---|---|
| mismatch | `truncation` | candidate count below the latest retained count and no retained checkpoint at that count |
| mismatch | `rollback` | candidate equals an older retained checkpoint (count and digest) |
| mismatch | `fork` | digest differs from a retained digest at the same count, or (with `chain_digests`) at a retained count inside the chain |
| mismatch | `workflow_mismatch`, `profile_mismatch` | the candidate names another workflow than the one requested, or another store profile than the checkpoints describe |
| unverifiable | `missing_checkpoint` | gap in the retained sequence |
| unverifiable | `duplicate_checkpoint` | two retained records claim one sequence |
| unverifiable | `checkpoint_corrupt`, `retained_inconsistent` | unreadable, non-canonical, bad digest, unexpected file, symlinked record, workflow directory or custody root (a symlinked root is `custody_unavailable`); a retained record with an unsupported profile, or naming another workflow than its directory (a foreign file); or a retained set that regresses, forks or breaks its predecessor chain |
| unverifiable | `no_checkpoints`, `custody_unavailable`, `input_invalid` | nothing retained, custody unreadable, malformed candidate |
| unverifiable | `extension_unproven` | candidate longer than the latest checkpoint and no `chain_digests` given: the extra events are not covered |
| match | `head_matches_latest`, `chain_matches_all` | agreement with the latest checkpoint; or with every retained checkpoint through the supplied chain |

Fail closed: any internal error returns `unverifiable`/`input_invalid`, never a match. `match` means agreement with retained checkpoints only: not authorship, not truth of events, not effect, not completeness beyond the latest retained head.

## 5. Limits (stated plainly)

- A writer who can rewrite a whole log and the custody records, or who controls the custodian, defeats this. Custody must be outside the Orchestrator's and the store's write reach; this reference cannot enforce that.
- Events after the latest retained checkpoint are not covered; checkpoint frequency (after each acknowledged append, before archival, at each acceptance) bounds the window.
- Deletion of the newest custody files (tail loss at the custodian) is not detectable from custody alone; a verifier holding a later acknowledgment would see it. Custodian-side retention rules are an open item.
- Substituting a different internally valid chain is detected only when it disagrees with a retained count/digest.
- The synthetic custodian is single-host, local files, no access control beyond file modes.

## 6. Open items for the operator and architect

Custodian designation and acceptance by its owner; any locked Evidence Attestation change and F3 package; wire/profile freeze; transport; whether the workflow store should accept an expected count (a store code change, not authorized here); archival hand-off of the final head (Q9).
