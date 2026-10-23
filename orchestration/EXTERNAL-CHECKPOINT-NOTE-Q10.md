# Note Q10: external digest and count checkpoint (Orchestrator side)

**NOTE. Non-authorizing. Documentation only. NOT implemented.** Release and production remain on HOLD. No `.py` file or workflow changes. Nothing here claims clearance, certification, qualification, authenticity or production readiness.

Origin: architect decision Q10. The tamper-evidence anchor is **external to the store**. The Orchestrator must not be the sole custodian of the anchor used to verify its own event history. An independently retained digest and count checkpoint is owned by the designated evidence or attestation custodian. Qualification verifies the checkpoint independently during acceptance but does not become the operational evidence store. Until an external anchor exists, the accurate statement is: **local chain consistency with limited truncation detection**. Do not claim complete tamper-evidence or authenticity.

Verified against Orchestrator `72fb6ed`: [workflow_store/store.py](workflow_store/store.py), [workflow_store/README.md](workflow_store/README.md), [../development/acceptance/producer-observations/observations.py](../development/acceptance/producer-observations/observations.py) and its [README](../development/acceptance/producer-observations/README.md).

## 1. What the Orchestrator already exposes

| Store | Head sequence and digest come from | Held value accepted back as | Result when it disagrees |
|---|---|---|---|
| Workflow event store (`orchestration/workflow_store`) | `append(...)` returns the stored event (its `sequence` and `digest`); `load(...)` returns `LoadedWorkflow(events, head_sequence, head_digest)`; `head_digest` is `None` for an empty workflow | `expected_head=(sequence, digest)` on `load` and on `recover` / `break_lock` (`_check_head`, `store.py:441-456`) | log shorter than the held sequence: `truncated`; a different digest at that sequence: `chain_broken`. A log longer than the held head is accepted (the held head is a prefix check, not a count assertion) |
| Producer observation store (`development/acceptance/producer-observations`) | `verify_chain()` returns the list of digests in order, so head digest is the last entry and count is its length; `append` returns the `observation_id`, which is `obs_` plus the digest hex | `expected_head=<digest string>` and `expected_count=<non-negative int>` on `verify_chain` and `append` (`_check_held`) | count differs or head differs: `chain_break`. `expected_head=None` means unchecked; `expected_count=0` asserts an empty store |

So both stores already return a (head sequence or count, head digest) pair and accept it back. No new Orchestrator code is needed to let a custodian retain one; what is missing is an owner and a procedure outside the Orchestrator.

## 2. What an external custodian can retain

Per workflow (workflow store): `workflow_id`, head `sequence`, head `digest` (`sha256:` plus 64 hex), and the time the custodian received it. Per observation store: record count and head digest. The custodian stores these in its own custody, with its own access control and its own retention, and returns them to the Orchestrator caller (or an acceptance verifier) to pass as `expected_head` / `expected_count`.

Hand-off timing recommended for design (not implemented): after each acknowledged `append` the caller may send the returned head to the custodian; at minimum before archival (see [workflow_store/AMENDMENT-PROPOSAL-Q9-store-limits-and-archival.md](workflow_store/AMENDMENT-PROPOSAL-Q9-store-limits-and-archival.md), section 6) and at each acceptance. An `outcome_ambiguous` append must be reloaded first so the checkpoint is of what is actually durable.

An acceptance verifier (Qualification) takes the custodian's checkpoint, loads the store read-only and passes the checkpoint to `load` or `verify_chain`. It checks; it does not store the operational evidence and does not repair.

## 3. What the Orchestrator must NOT claim

- That the store is tamper-evident in general. What exists is local chain consistency plus truncation detection **only against a head the caller retained outside the store**.
- That a stored log is authentic. A party who can write the directory can rewrite a whole log, recomputing every digest (the workflow store README and the observation README both say so). A matching checkpoint shows the log is the one the custodian saw at that head; it does not show who wrote it or that the events are true.
- That any checkpoint held by the Orchestrator itself (a `HEAD` cache file, a session head, a receipt in an archive, a value kept beside the store) is an anchor. Those are caches or conveniences; an unverified cache never replaces authoritative custody (Q9), and a value an attacker with directory access can edit is not external.
- That the head covers events not yet reached: a held head `N` says nothing about events after `N`, and the workflow store accepts a longer log. Complete-count assertion for the workflow store needs the held head to be the latest one; the observation store can assert a count.
- That removal of the whole store followed by a fresh valid chain, or substitution of a different internally valid chain, is detected unless the caller passes a held head or count (the observation README states both).
- That a checkpoint shows an effect happened, failed, was reversed or was verified. It is a digest and a count of an event history.
- That Qualification, the Hub or the Orchestrator has taken custody. The custodian is the designated evidence or attestation owner; the designation is outside this document and is not made here.

Until an external anchor is in place the Orchestrator reports only: local chain consistency with limited truncation detection (against a head a caller chose to retain).

## 4. Open items (owner decisions, not made here)

1. Which component is the designated custodian and what its retention and access rules are.
2. The checkpoint record format and transport (this note proposes none; a digest and count pair is sufficient for what the stores can verify).
3. Whether the workflow store should also accept an expected count (the observation store does; the workflow store checks a sequence-and-digest pair only). Any such change is a code change and is not authorized in this round.
4. How archival (Q9) hands the final head to the custodian before a workflow leaves the live store.
