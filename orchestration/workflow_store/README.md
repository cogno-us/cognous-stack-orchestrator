# Durable single-host workflow event store (step 3.2, part B)

**Candidate, non-authorizing.** Release and production remain on HOLD. This package is a local history store. It is not a state machine, not an alternate Control Plane and not a verdict, pin, grant or authority source. Nothing here claims clearance, certification, qualification or production readiness; no independent review has taken place.

It persists opaque, schema-checked **event records** for a workflow and returns them in order. Interpreting them (states, transitions) is the job of the separate workflow machine; this package neither imports it nor depends on step 3.4 code. Standard library only: no clock, no network, no subprocess, no environment reads.

## Layout on disk

```
<store root>/<workflow id>/
  000001.json 000002.json ...   one event per file, canonical JSON, mode 0444
  LOCK                          single-writer lock, mode 0600 (present only while held)
  .locks/                       lock temporaries and the internal mutex file; never scanned as events
  quarantine/torn-write-after-<last good seq>-<n>/   only after an explicit recover
  .tmp.<seq>.json               an append's temporary file; a leftover is reported, never ignored
```

Directories are mode 0700. A workflow id matches `[A-Za-z0-9][A-Za-z0-9_-]{0,63}` (no dots, slashes or leading punctuation); an owner token matches `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`. Symbolic links and unknown entries are refused.

## Event record and envelope

The caller supplies exactly `kind` (`[a-z][a-z0-9_.-]{0,63}`, not starting with `store.`), `timestamp` (non-empty opaque text of at most 64 characters, never parsed or compared) and `body` (an object of strings, safe integers, booleans, null, lists and objects; no floats; nesting at most 16).

The store adds `profile` (`ocs-workflow-event/0`, a candidate wire name), `schema_version` (0), `canonical_profile` (`rfc8785-jcs`), `workflow_id`, `sequence`, `predecessor` (digest of the previous event, null for the first) and `digest` (`sha256:` over the canonical form of the event without its `digest` member). The file holds exactly the canonical bytes, so the digest is over the bytes on disk.

The member names `verdict`, `pin`, `grant` and `authority` are refused by name (`forbidden_member`) at the envelope and at every depth of a body, and again when an event is loaded. The match is exact, so a reference such as `grant_id` is allowed: the workflow may carry references to records other components own, never set them.

Canonical JSON and strict loading follow hub step 2.1 (`tools/registry_records.py`: `jcs_dumps`, `loads_strict`, `record_digest`). The Orchestrator may not import hub tools, so `canonical.py` restates that small subset; tests pin it to fixed vectors. Duplicate keys, floats and non-finite constants are refused.

## API (`orchestration.workflow_store`)

| Call | Purpose |
|---|---|
| `Store(root, Bounds(...))` | A directory of workflows with explicit bounds; `create_workflow`, `workflows`, `acquire`, `release`, `append`, `load`, `inspect`, `recover`, `break_lock`, `read_lock` |
| `acquire(dir, owner=, timestamp=)` / `release(dir, owner=)` | Single-writer lock; never waits and never steals |
| `append(dir, record, owner=)` | Appends one event under the caller's lock; revalidates the whole chain first |
| `load(dir, expected_head=None, ignore_in_flight=False)` | Re-validates the whole chain; returns `LoadedWorkflow(events, head_sequence, head_digest)`. `ignore_in_flight` is for a non-writer reader: while a LOCK exists, temporary files are treated as an append in progress and not reported |
| `inspect(dir)` | Lists torn-write conditions and `lock_break_incomplete` without raising for them |
| `recover(dir, owner=, timestamp=, expected_head=None, acknowledge_drop=False)` | Explicit quarantine of a torn tail, leftover temporary files or an unrecorded quarantine; records `store.torn_tail_quarantined`. Refuses with `complete_event_in_tail` if the torn tail begins with a complete valid event, unless `expected_head` or `acknowledge_drop=True` is given |
| `break_lock(dir, expected_owner=, breaker=, reason=, timestamp=, recover_torn=False, corrupt_lock_sha256=None, expected_head=None, acknowledge_drop=False)` | Explicit break of a lock the caller judges stale; records `store.lock_broken` and hands the lock to `breaker` |

## Crash safety

An append writes `.tmp.<seq>.json` exclusively, sets mode 0444, flushes and fsyncs it, creates the final name with an exclusive hard link (never a replacing rename), fsyncs the directory, unlinks the temporary file and fsyncs the directory again. A final-named file is therefore either absent or complete. A hard-link-capable local filesystem is required.

A failure before the link is `io_failure` and no event exists. A failure after the link (directory fsync, temporary unlink) is `outcome_ambiguous`: the event is visible and may be durable; reload before doing anything else (a leftover temporary file then needs `recover`).

## Restart: what `load` detects

| Condition | Code |
|---|---|
| Missing or extra sequence number | `sequence_gap` |
| Files swapped or renumbered | `sequence_mismatch`, `chain_broken` |
| Body or envelope edited | `digest_mismatch`; if re-signed, `chain_broken` at the next event |
| Non-canonical bytes, duplicate key, float, nesting beyond the interpreter limit | `noncanonical_event` (or `schema_invalid` for nesting over 16) |
| Unparsable non-final event | `event_corrupt` |
| Event copied from another workflow | `workflow_id_mismatch` |
| Log shorter than a caller-held head | `truncated`; different digest at that sequence: `chain_broken` |
| Incomplete final event file (including one over 1 MiB) | `torn_tail` |
| Leftover temporary file | `leftover_temp` |
| Quarantine directory no event records | `unrecorded_quarantine` |

Torn-write conditions are reported and never silently repaired; `append` refuses until an explicit `recover`.

## Recovery

`recover` takes size and sha256 of every file first (streamed, no size cap), moves them into `quarantine/torn-write-after-<last good seq>-<n>/` and appends `store.torn_tail_quarantined` (at most 32 files listed, plus `files_total`). Records written by `recover` and `break_lock` (`store.*` kinds) may use a reserve of 64 events beyond `max_events` and are not refused for event size, so a full workflow can be recovered; ordinary appends stay bounded, and growth is bounded at `max_events` + 64. The reserve is shared: repeated `break_lock` calls (one reserved slot each, even if the call also records several recovery events) or repeated recoveries can consume it, after which a further crash may be unrecoverable by this API (`workflow_full`) and needs out-of-band handling. A quarantine event is one slot per quarantine directory.

A torn tail can be a complete, valid, possibly acknowledged event followed by garbage. `recover` then refuses (`complete_event_in_tail`) unless the caller passes `expected_head` **equal to the log head** (sequence equal to the number of valid events and the digest of the last valid event, i.e. the last head the caller was given) or `acknowledge_drop=True`. A caller holding an older head cannot discard the event on that basis; a head beyond the log is `truncated`, whose message points at `acknowledge_drop` as the explicit override. The digest of the discarded event is recorded. In the other recovery cases `expected_head` is only checked for consistency with the chain.

## Locking

`LOCK` holds an owner token, a caller-supplied opaque timestamp and a random `lock_id`, created atomically (temporary file in `.locks/`, then exclusive link). The `lock_id` identifies one lock instance; the break event records the broken and the new id. Every lock-state change and every append runs under a short-lived `flock` on `.locks/mutex`, so check-then-act on `LOCK` is atomic among callers of this API (a crashed process releases it automatically, and it is unlocked explicitly before close so a forked child that inherited the descriptor does not keep it; it is not the writer lock and nobody waits on a writer). `flock` must work: it needs a local filesystem that supports it. FUSE, NFS and some overlay filesystems are unsupported; an `flock` failure (for example ENOLCK) is `io_failure`. A held lock is always `lock_held`.

The store has no clock and does not decide staleness. `break_lock` is a manual operator act: the caller names the owner token it observed (mismatch is refused, so of two racing breakers exactly one wins). The order is: checks, optional recovery, the `store.lock_broken` event, then an atomic replace of `LOCK`. A crash between the last two (or a failed replace) leaves the old lock with the event recorded; `inspect` reports `lock_break_incomplete` (the lock named by the event's `broken_lock_id`, or the corrupt bytes it names, is still in place; ids rather than timestamps are compared, so a re-acquire by the same owner with the same timestamp is not a false positive) and repeating `break_lock` completes it. In that window the old holder, if alive, can still append: it still holds `LOCK`. A corrupt `LOCK` (invalid bytes, a FIFO or other non-regular file, or a symbolic link, which is replaced and never followed) has no owner: call `break_lock(expected_owner=None, corrupt_lock_sha256=<sha256 of the bytes you inspected>)`; the `lock_corrupt` refusal carries that digest (for a non-regular LOCK, a digest of its file type or link target).

Owner tokens identify holders; they are forgeable by anyone who can read the directory and authenticate nothing. `break_lock` does not fence a holder that is still running outside this API: `sequence_conflict` and the exclusive link protect the data, not the intent. A live holder whose lock was broken has its next call refused with `lock_owner_mismatch`.

## Bounds and refusal codes

`Bounds(max_events, max_event_bytes, max_workflows)` (defaults 10000, 65536, 1000; hard ceilings 999999, 1 MiB, 100000). Over a bound is refused (`workflow_full`, `event_too_large`, `store_full`); an out-of-range bound is `bounds_invalid`. The event size bound is checked cheaply while walking the body, before canonicalization. Refusals are `StoreRefusal` with a `.code` from the closed set `CODES` (34 codes, in `refusal.py`).

A refusal changes nothing, with these stated exceptions: `outcome_ambiguous` (the event, lock change or quarantine may have happened: a post-link failure in `append`, a directory-fsync failure in `acquire`, `release` or `recover`), `lock_break_incomplete` (the break event is recorded, the lock is not handed over) and a failure part-way through `recover` or `break_lock`, which can leave a quarantine (reported by `load` as `unrecorded_quarantine` until `recover` records it) or recorded recovery events.

## Limits

- Truncation of the tail is detectable only against a head the caller retained from `append` or `load`; a log can also be rewritten wholesale by someone who can write the directory and recompute every digest. The chain gives tamper evidence, not tamper prevention or authenticity.
- Append cost is quadratic: every append re-reads and re-validates the whole chain (measured here on Python 3.13 with fsync: about 0.01 s per append around 100 events, 0.05 s around 300-500, 0.12 s averaged over events 600-1000; the reviewer measured about 0.19 s at 1000). No verified head is cached, because a cache could not detect an out-of-band edit. Practical bound: keep `max_events` in the low thousands per workflow.
- The forbidden-member check is by exact name (`verdict`, `pin`, `grant`, `authority`). Lookalikes (`Verdict`, `verdict_`, `v3rdict`, a nested `{"k": "verdict"}` value) pass. It is a guard against accidental authority members, not a defence against a hostile writer; the store holds history, and whoever interprets events must never treat them as authority.
- Case-insensitive or normalizing filesystems can alias workflow ids differing only by case; use a case-sensitive filesystem. Only the workflow directory itself is checked for being a symbolic link, not its parents or the store root's parents.
- Hard links are required (a filesystem without them yields `io_failure` on every append).
- A crash during `break_lock` or `recover` leaves the states described above; `inspect` and `load` report them.
- Lock temporaries and the mutex file in `.locks/` left by crashes are never cleaned up or touched by the store (names carry random bytes and are created exclusively, so they cannot collide). They are ignored by every scan.
- Standard-library surface: `os.urandom` (lock ids, temp-name suffixes), `fcntl.flock`; no clock, network, subprocess or environment access. A test checks this by AST names and attributes.
- States that need out-of-band, manual intervention: `LOCK` is a directory (`break_lock` refuses with `io_failure`; remove it by hand); a non-final event with nesting beyond the interpreter limit (`noncanonical_event`, recover refuses to hide corruption); an exhausted recovery reserve; a tampered or corrupt non-final event (`event_corrupt`, `digest_mismatch`, `chain_broken` and the rest of the chain-validation codes); unknown entries or symbolic links among the events (`unexpected_file`, `path_escape`). A final file of deeply nested or unclosed brackets is classified as a torn tail and is recoverable.
- `ignore_in_flight` readers cannot distinguish a writer's in-progress temporary file from a crashed writer's leftover while a LOCK exists. A strict reader (the default) may see a transient `leftover_temp` during an append.
- Single host, single directory tree. Not a database, not multi-host, no encryption, no retention policy.

Tests: `python -m pytest -q tests/integration/workflow_store`. The refusal-code check is static (package literals equal `CODES`, and a table names the negative test for each code).
