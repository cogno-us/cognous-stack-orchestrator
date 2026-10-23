# Amendment proposal Q9: store limits, cached verified head, qualification and archival

**PROPOSAL. Non-authorizing. NOT implemented.** Release and production remain on HOLD. This document changes no `.py` file, no workflow file and no behavior of `orchestration/workflow_store`; the store described in [README.md](README.md) is unchanged. Implementation of Q9 is not authorized in this round. Nothing here claims clearance, certification, qualification or production readiness, and no independent review has taken place.

Origin: architect decision Q9 (approve provisionally, with changes). Verified against the merged store at Orchestrator `72fb6ed` ([store.py](store.py), [refusal.py](refusal.py), [README.md](README.md)). Baseline: the existing `workflow_machine`, `workflow_store` and `producer_observations` suites pass (438 tests) on Python 3.11.17 and 3.13.16.

Companions: [../workflow_machine/AMENDMENT-PROPOSAL-Q1-coordination-states.md](../workflow_machine/AMENDMENT-PROPOSAL-Q1-coordination-states.md) and [../EXTERNAL-CHECKPOINT-NOTE-Q10.md](../EXTERNAL-CHECKPOINT-NOTE-Q10.md).

## 1. Limits are upper bounds, not safe defaults

`Bounds` today is `max_events=10000`, `max_event_bytes=65536`, `max_workflows=1000` with hard ceilings 999999, 1 MiB and 100000, plus `RECOVERY_RESERVE = 64` for `store.*` records (`store.py:50-80`). Per the architect:

- 1,000 workflows, 10,000 events per workflow, 64 KiB per event and the 64-event reserve are configurable **upper** bounds. Nothing in this repository demonstrates that any of them is a safe operating default, and the README must stop presenting the numbers as defaults once implemented (proposal: `DEFAULT_BOUNDS` becomes either removed or explicitly named `UPPER_BOUNDS_UNQUALIFIED`, and a constructor without explicit bounds is refused outside tests).
- Production-oriented defaults are set only after the qualification plan in section 7 has run. Until then the README's own advice stands: keep `max_events` in the low thousands.
- The 16-event machine bound and the durable `max_events` are separate (section 2).

Worst-case footprint implied by the upper bounds (arithmetic, not a measurement): 1000 workflows x 10000 events x 65536 bytes is about 655 GB of event bytes before block rounding, and about 10 million files (each event is one file, plus the 64 reserve records). `load` and `append` hold every event of a workflow in memory (`_Scan.events`, then a deep copy in `_loaded`), so one workflow at the upper bounds is about 655 MB resident per copy and roughly twice that during `load`. These figures are why the bounds are not defaults.

## 2. Keeping the 16-event machine bound separate from the durable limit

- `MAX_EVENTS_PER_WORKFLOW = 16` (`workflow_machine/vocabulary.py:53`) is the length of a coordination history. It counts machine events only.
- The store `max_events` bounds durable records of every kind in a workflow directory, including `store.lock_broken` and `store.torn_tail_quarantined`, and any non-machine kinds an adapter writes. `store.*` records may use the 64 reserve beyond `max_events`.
- Neither bound is derived from the other. The adapter checks at open that `store.max_events >= 16 + (non-machine records it expects)`, and a store refusal (`workflow_full`) is never mapped to a machine state or to a machine refusal. A workflow never "fails" or "completes" because the store is full; the store refuses, the coordinator reports the refusal, and an operator acts.
- Machine `seq` is renumbered by the adapter among machine events; store `sequence` counts every record. They are different numbers and must not be compared.

## 3. Measured cost of the current append (quadratic)

Mechanism, verified in the code: `append` (`store.py:744-758`) runs `_scan` on the whole directory for every call; `_scan` (`store.py:338-438`) reads each event file, strictly parses it, checks the stored event, re-canonicalizes it and compares bytes, recomputes the digest and checks sequence and predecessor. One append is therefore O(N) in events already present, and building N events is O(N squared).

Reused figures (per the README and reviewers, Python 3.13, fsync on): about 0.01 s per append around 100 events, 0.05 s around 300 to 500, 0.12 s averaged over events 600 to 1000, and the reviewer measured about 0.19 s at 1000.

Re-measurement for this document, read-only on a scratch copy of the merged `orchestration` package (the repository was not touched), Python 3.11.17, ext4, one workflow, 1000 sequential appends of a tiny body, run on a shared sandbox whose disk was nearly full and busy, so wall-clock append figures include noisy fsync and are indicative only:

| Events present | Full chain validation (`_scan`) alone | Directory listing plus `lstat` of every entry | Mean append wall time (last 10 appends) |
|---|---|---|---|
| 10 | 0.0019 s | 0.00005 s | 0.003 s |
| 100 | 0.012 s | 0.0003 s | 0.19 s (fsync noise) |
| 300 | 0.034 s | 0.0011 s | 0.12 s |
| 500 | 0.050 s | 0.0017 s | 0.12 s |
| 700 | 0.081 s | 0.0027 s | 0.09 s |
| 1000 | 0.098 s | 0.0037 s | 0.10 s |

Reading: the validation cost grows about linearly per call (roughly 0.1 ms per event on this host) while the listing and `lstat` pass costs about 3.7 ms at 1000 entries, around 3 percent of validation. Wall time per append is dominated by fsync and host noise at small N and by validation at large N, which is why the reused reviewer figures and these differ; the sum of 1000 appends took 135.6 s here, the mean over events 600 to 1000 was 0.11 s. Neither set of numbers is a qualification result. Extrapolating to 10000 events (not measured) would put validation alone near 1 s per append and the cumulative validation cost in the thousands of seconds; that extrapolation is the reason the upper bound cannot be a default.

## 4. Cached verified chain head: design

Principle: the event files are the authoritative custody; the chain is validated from them. A cache is only an optimization. **An unverified cache never replaces authoritative custody**, and a cache adds no tamper evidence: anyone able to edit an event can also edit a cache file, so the cache does not strengthen or replace the external anchor of Q10. The design must therefore prove it does not weaken the checks that remain, rather than claim a new property.

### 4.1 Recommended first step: a session head held in memory, bound to the lock

- Where it lives: in the memory of the process that holds the writer `LOCK`, created by `acquire` and discarded by `release`, `break_lock` or process exit. Nothing is persisted, so there is no stale on-disk cache to refuse and no new file name for `_scan` to learn.
- What is verified when it is created: `acquire` performs one full validation (the existing `_scan` plus `_raise_conditions`), then records `(workflow_id, lock_id, count, head_digest)`. Restart validation is therefore a full validation, once per lock acquisition, not per append.
- What each append verifies instead of a full scan (all while holding the mutex and the lock):
  1. the `LOCK` file still names the same `lock_id` and owner (existing `_require_holder`);
  2. the directory listing, with `lstat` of every entry, contains exactly the entries the session expects: event files `000001` to `count`, no extra event file, no temporary file, no symbolic link, no unknown entry (this keeps `unexpected_file`, `path_escape`, `sequence_gap`, `leftover_temp` detection on every append at about 3.7 ms per 1000 entries);
  3. the last event file (sequence `count`) is read, fully validated (strict parse, canonical bytes, digest) and its digest equals the cached head digest, so an out-of-band edit, replacement or removal of the tail is refused;
  4. only then the new event is built from the cached head and published with the existing exclusive hard link, with directory fsyncs as today;
  5. after a successful publish the cache advances to `(count + 1, new digest)`; after `outcome_ambiguous` or any failure the cache is dropped, so the next call does a full validation.
- What is not re-verified per append: events 1 to `count - 1`. An out-of-band edit of an old, non-tail event is detected at the next full validation, which is every `load`, `inspect`, `recover`, `break_lock`, archival and every lock acquisition. This is a deliberate, stated weakening of the append path only (today an append refuses on any corruption anywhere); the read path keeps full validation. A qualification test must pin exactly this boundary (section 6).
- Optional bounded re-check: a full validation every K appends (K configured) limits the window in which old-event corruption goes unnoticed by the writer. K is not set here.

### 4.2 Deferred second step: a persisted head file (only if restart cost is shown to matter)

Restart cost under the recommended step is one full validation per lock acquisition (about 0.1 s at 1000 events on this host). A persisted cache is worth its risk only if the load plan (section 7) shows that cost is unacceptable at the chosen `max_events`. If it is added:

- Where: `<workflow dir>/HEAD`, a new reserved name that `_scan` must classify (today an unknown name is `unexpected_file`), replaced atomically (temporary file, fsync, rename, directory fsync). It is cache, not custody, so replace-by-rename is acceptable here although event files never are.
- Content (canonical JSON, one object): profile `ocs-workflow-head-cache/0`, `workflow_id`, `count`, `head_digest`, `lock_id` of the writer that wrote it, and `verified_through` (the highest sequence a full validation covered). It holds no event content.
- Written only after the event is durable, so the event is authoritative: a crash between event publish and `HEAD` update leaves `HEAD` one behind the log.
- What is verified on open: the same checks as 4.1 steps 1 to 3 plus `HEAD` agreement: listing contiguous 1 to N; the tail event fully validated; `HEAD.count` and `HEAD.head_digest` equal to the log.
- Stale cache refusal and classification (each is a distinct typed outcome, tested):
  - `HEAD` behind the log by exactly the in-flight event (count N-1, digest equals event N-1's digest): benign crash window; the opener performs a full validation, then rewrites `HEAD`.
  - `HEAD` ahead of the log (count greater than the number of events): evidence that events were removed or never became durable; reported as `truncated` (local evidence only), never silently rewritten.
  - `HEAD` digest differs from the event at that sequence, malformed, wrong workflow id, unknown member, or non-canonical: `cache_corrupt`, ignored for trust, full validation forced, and the file is not repaired until the operator acts.
  - `HEAD` written by a lock instance that is not the current or a recorded predecessor: treated as stale, full validation forced.
  - Any of the above that a full validation shows to be consistent is still logged as an anomaly and never trusted on the next open until rewritten after a full validation.
- Out-of-band edit detection: a tail edit is caught by step 3; an old-event edit is caught by the next full validation and, if `verified_through` is below the head, by a rolling full validation that the opener must complete within a configured number of opens (never left to chance). A wholesale rewrite with all digests recomputed (including `HEAD`) is not detected by any local mechanism; only the external checkpoint of Q10 can detect it.

### 4.3 What a cache must never do

Never skip full validation on `load`, `inspect`, `recover`, `break_lock` or archival; never let a cache value stand in for an `expected_head` the caller holds; never be used by a second process without that process validating; never be consulted when `inspect` reports a torn-write condition; never widen what `append` accepts (a refusal that exists today for the tail or listing stays).

### 4.4 New refusal codes (store, closed set; each needs a named negative test)

`cache_stale` (session or persisted head disagrees with the directory in a way that is not a benign crash window; forces full validation and refuses the append), `cache_corrupt` (persisted head unreadable or inconsistent; step 4.2 only). Existing codes keep their meaning; `chain_broken`, `digest_mismatch`, `truncated` and `sequence_gap` are still raised by full validation.

## 5. Tests required before the cache may be used (all explicit; none exist)

Persistence and restart:

1. Session head advances exactly with appends; a second `acquire` after `release` or process restart starts from a full validation (assert by a validation counter or a patched `_scan` call count).
2. (If 4.2) `HEAD` round trip; `HEAD` canonical bytes pinned to fixed vectors; a restart with a correct `HEAD` still validates the tail and listing.

Tamper detection:

3. Edit the tail event body, with and without recomputing its digest: the next append is refused (`digest_mismatch`, `chain_broken`); the cache is dropped.
4. Edit an old event: append in the same session succeeds (the stated boundary), and the next `load`, `inspect` or `acquire` refuses; this test exists to pin the boundary so it cannot move silently.
5. Delete, replace or rename the tail file; add a stray event file, temporary file, symbolic link, unknown entry: the next append refuses with the existing codes.
6. Replace `LOCK` (another owner or lock id): the append is refused and the cache is dropped.
7. (If 4.2) `HEAD` forged to match a tail edit: detected when the tail event itself no longer validates; `HEAD` set ahead of the log: `truncated`; garbage, wrong workflow id and an old workflow's `HEAD` copied in: `cache_corrupt`, with full validation forced.
8. A test that no unverified value ever stands in for custody: with a deliberately wrong cache injected, every `load` still returns the validated log or a typed refusal.

Crash recovery (extend the existing crash tests in `tests/integration/workflow_store/test_workflow_store_crash.py`):

9. Kill (fault-inject) after the temporary write, after the link, after the first directory fsync, after the temporary unlink, and (4.2) between event publish and `HEAD` write: restart reaches either "event absent" or "event present", never a cache that disagrees silently; `outcome_ambiguous` drops the cache.
10. Torn tail, `recover` and `break_lock` flows invalidate the cache and the following operation starts with a full validation; the 64 reserve and `store.*` records behave as before.
11. Differential test: the same random operation sequences (appends, crashes, recoveries, edits) against the current no-cache store and the cached store must produce identical event logs and identical refusal codes except where section 4.1 states the boundary (old-event edit seen later). A fixed-seed fuzz plus a recorded seed list.

## 6. Archival and active-slot release

Goal (architect): the 64-slot limit must not become a permanent resource leak, and terminal workflows must release their active slots without ever archiving an unresolved effect as completed. Today nothing leaves `<store root>` (the store has "no retention policy"), `Store.workflows()` counts every directory, and the machine keeps terminal workflows in its fleet.

### 6.1 Archival definition

Archive = move a closed workflow's directory out of the live store root into an archive root, read-only, after recording what was archived. It is never deletion. Eligibility (all required, checked by the store or the adapter at archive time):

1. replayed status is terminal (`observed`, `reconciled`, and with the Q1 amendment `failed`, `cancelled`); never `dispatched`, `unresolved` or `suspended`; never a workflow with an open effect;
2. full chain validation succeeds and `inspect` reports nothing (no torn tail, leftover temporary file, unrecorded quarantine, incomplete lock break);
3. the lock is released (no `LOCK`), or is held by the archiving owner;
4. the head sequence and digest were handed to the external custodian (Q10), or the archive receipt records `external_checkpoint: not_retained` (and the Q10 limits statement applies to that workflow);
5. the archive root is on the same filesystem (so the move is an atomic rename, not a copy), outside the live store root, and not itself a symbolic link.

### 6.2 Procedure (crash-safe ordering)

1. Append a final `store.archive_intent` record (a new reserved kind; may use the reserve) naming the head sequence and digest, then fsync. This is the write-ahead for archival.
2. Atomic rename of the workflow directory into the archive root, fsync of both parents.
3. Write an archive receipt in the archive root (workflow id, terminal status, closure class from Q1, event count, head digest, archive time supplied by the caller, `external_checkpoint` status). The receipt is a convenience; the intent record inside the log is the evidence.
4. Only after step 3 does the caller invoke the machine's `release_terminal` (Q1 document, 8.3), which frees the fleet entry.

A crash after step 1 and before step 2 leaves a terminal workflow with an intent record: `inspect` reports `archive_incomplete` (new condition) and archival is repeatable. A crash after step 2 and before step 3 leaves a directory in the archive without a receipt: reported by an archive verifier, repairable by writing the receipt from the log. The live store never reads the archive for decisions.

### 6.3 Slot accounting

- The store workflow limit (1000) counts live directories only; the archive root is not scanned by `workflows()` and not counted against `max_workflows`.
- Machine execution slots and waiting records (Q1 document, section 8) are derived from replayed status; archival and `release_terminal` are the only things that reduce the fleet's closed set. Held, denied, suspended and unresolved workflows are never archived and never released; they remain waiting records until closed by an explicit event. This is the honest cost: a growing set of waiting records is visible in `waiting_records` and in the live store limit, not hidden by archival.
- Archived workflows stay verifiable: `load` on an archived directory with the same functions must pass unchanged, and the external checkpoint (if any) must still match. Reading an archive never reopens a workflow.

### 6.4 Retention

Retention periods and deletion are external custody decisions (open question 3). The store proposes no deletion API.

## 7. Load and resource-exhaustion qualification plan (required before any production-oriented default)

Run on the target filesystem class (local, hard-link and `flock` capable), at least 3.11 and 3.12 or 3.13, with the exact commit hash, hardware, filesystem and kernel recorded. Output is a table, not a pass/fail claim.

| Dimension | Cases | What is recorded or asserted |
|---|---|---|
| Events per workflow | 100, 500, 1000, 2000, 5000, 10000, and 10000 plus 64 reserve records | append latency distribution (p50, p95, p99, max), `load` latency, peak resident memory, total time to build; refusal at `workflow_full` exactly at the bound; `store.*` recovery still works at the full bound |
| Event size | 1 KiB, 16 KiB, 64 KiB, 64 KiB plus 1 byte, 1 MiB reserve record | `event_too_large` boundary; memory scaling of `load` (events times size); store records exempt from the size bound as documented |
| Workflow count | 100, 500, 1000, 1001 | `store_full` at the bound; `create_workflow` and `workflows()` latency (each lists the root); behavior with the archive root present |
| Concurrency | one writer and 1, 4, 16 readers; two writers racing on one workflow; many workflows each with its own writer | single-writer enforcement unchanged (`lock_held`, `sequence_conflict`); reader transient `leftover_temp` rate with and without `ignore_in_flight`; no lock starvation claims |
| Disk full | ENOSPC injected at temporary write, link, directory fsync, `HEAD` write, archive rename | typed `io_failure` or `outcome_ambiguous`; no partial final-named file; recovery after space returns |
| Inode exhaustion | fill the filesystem inode table; 1000 workflows near full | typed refusal, no corruption, recovery after cleanup |
| File descriptors | low `ulimit -n`; many concurrent readers | typed `io_failure`, no leaked descriptors or locks |
| Memory | cgroup limit below the computed footprint of `load` at the bound | explicit failure mode recorded (today an out-of-memory kill is possible); decision whether `load` needs a streaming or paging interface before large `max_events` |
| Archive | archive 1, 100, 1000 closed workflows; crash at every ordering step of 6.2 | live store count returns below the bound; archived workflows still validate; no unresolved effect archived (negative test over every non-terminal status) |
| Cache (if adopted) | all of section 5 under load; differential fuzz at scale | no divergence from the no-cache store beyond the stated boundary |
| Sustained soak | hours of mixed operations, with periodic kill -9 | no unexplained `unexpected_file`, no stuck lock, no growth beyond expected |

Exit criterion for setting a default is a reviewed table showing each dimension within an operator-chosen envelope; the qualification report, not this proposal, names the numbers. None of these results exists yet.

## 8. Migration and compatibility

- The on-disk event format, envelope (`ocs-workflow-event/0`), canonical form and digest are unchanged by sections 4 (session head) and 6; the session head needs no format change. A persisted `HEAD` file, `store.archive_intent` and the archive root are additions: old stores contain none of them and load unchanged; a store with a `HEAD` file or an intent record cannot be loaded by the current code (`unexpected_file` for `HEAD`; the intent record is a `store.*` kind the current code would accept as a reserved-kind event but its meaning would be ignored).
- Because the wire profile is provisional (`/0`) and the change adds a reserved file name and a reserved kind, it is recommended that the amendment declares its additions inside `/0` before first freeze, and that any later incompatible change uses a new identity per Q4. If the operator prefers, a `ocs-workflow-event/1` could be declared; the proposal does not require it.
- The retirement of `DEFAULT_BOUNDS` as a "default" is an API change for any caller relying on it; known callers are tests.

## 9. What this proposal does not do

It does not change `store.py`, set production defaults, introduce external custody, deletion, encryption or multi-host operation, make the store a state machine, or claim tamper-prevention. Chain consistency plus limited truncation detection against a caller-held head remains the only integrity property until the external anchor of Q10 exists.

## 10. Open questions

1. Is the in-memory session head (4.1) acceptable as the only first step, with the persisted file (4.2) deferred until a measured need?
2. The value of K (periodic full validation inside a session), if any.
3. Retention periods and deletion of archives; whether the archive root is custody the Orchestrator may hold or must be handed to the evidence custodian.
4. Whether `load` needs a paging or streaming interface before `max_events` is raised above the low thousands (memory footprint, section 1).
5. Whether the new reserved kind and file name stay inside `ocs-workflow-event/0` or justify `/1`.
