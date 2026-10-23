# Durable single-host workflow event store (step 3.2, part B)

**Candidate, non-authorizing.** Release and production remain on HOLD. This package is a local history store. It is not a state machine, not an alternate Control Plane and not a verdict, pin, grant or authority source. Nothing here claims clearance, certification, qualification or production readiness; no independent review has taken place.

It persists opaque, schema-checked **event records** for a workflow and returns them in order. Interpreting them (states, transitions) is the job of the separate workflow machine; this package neither imports it nor depends on step 3.4 code. Standard library only: no clock, no network, no subprocess, no environment reads.

## Layout on disk

```
<store root>/<workflow id>/
  000001.json 000002.json ...   one event per file, canonical JSON, mode 0444
  LOCK                          single-writer lock, mode 0600 (present only while held)
  quarantine/torn-write-after-<last good seq>-<n>/   only after an explicit recover
  .tmp.*                        in-flight or leftover temporary files (reported, never ignored)
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
| `load(dir, expected_head=None)` | Re-validates the whole chain; returns `LoadedWorkflow(events, head_sequence, head_digest)` |
| `inspect(dir)` | Lists torn-write conditions without raising for them |
| `recover(dir, owner=, timestamp=)` | Explicit quarantine of a torn tail, leftover temporary files or an unrecorded quarantine; records `store.torn_tail_quarantined` |
| `break_lock(dir, expected_owner=, breaker=, reason=, timestamp=, recover_torn=False)` | Explicit break of a lock the caller judges stale; records `store.lock_broken` and hands the lock to `breaker` |

## Crash safety

An append writes `.tmp.<seq>.json` exclusively, flushes and fsyncs it, sets mode 0444, creates the final name with an exclusive hard link (never a replacing rename), fsyncs the directory, unlinks the temporary file and fsyncs the directory again. A final-named file is therefore either absent or complete. A hard-link-capable local filesystem is assumed.

## Restart: what `load` detects

| Condition | Code |
|---|---|
| Missing or extra sequence number | `sequence_gap` |
| Files swapped or renumbered | `sequence_mismatch`, `chain_broken` |
| Body or envelope edited | `digest_mismatch`; if re-signed, `chain_broken` at the next event |
| Non-canonical bytes, duplicate key, float | `noncanonical_event` |
| Unparsable non-final event | `event_corrupt` |
| Event copied from another workflow | `workflow_id_mismatch` |
| Log shorter than a caller-held head | `truncated`; different digest at that sequence: `chain_broken` |
| Incomplete final event file | `torn_tail` |
| Leftover temporary file | `leftover_temp` |
| Quarantine directory no event records | `unrecorded_quarantine` |

Torn-write conditions are reported and never silently repaired; `append` refuses until an explicit `recover`.

## Locking

`LOCK` holds an owner token and a caller-supplied opaque timestamp, created atomically (temporary file, then exclusive link). The store has no clock and does not decide staleness: a held lock is always `lock_held`. After judging a holder dead, a caller runs `break_lock` naming the owner token it observed; a mismatch is refused. The break appends a `store.lock_broken` event. If the log also has a torn tail, the break is refused unless `recover_torn=True`, which recovers (and records) first. Owner tokens identify holders; they are not credentials and authenticate nothing.

## Bounds and refusal codes

`Bounds(max_events, max_event_bytes, max_workflows)` (defaults 10000, 65536, 1000; hard ceilings 999999, 1 MiB, 100000). Over a bound is refused (`workflow_full`, `event_too_large`, `store_full`); an out-of-range bound is `bounds_invalid`. Refusals are `StoreRefusal` with a `.code` from the closed set `CODES` (31 codes, listed in `refusal.py`); a refusal changes nothing.

## Limits

- Truncation of the tail is detectable only against a head the caller retained from `append` or `load`; a log can also be rewritten wholesale by someone who can write the directory and recompute every digest. The chain gives tamper evidence, not tamper prevention or authenticity.
- A crash between `recover` moving files and recording the event is reported as `unrecorded_quarantine` and closed by running `recover` again.
- A crash during `break_lock` after the lock handover but before the event is appended leaves the breaker holding the lock without the event; the caller sees the error and can append a note.
- A concurrent reader can see a transient `leftover_temp` while a writer is mid-append; reload after the writer releases.
- Single host, single directory tree. Not a database, not multi-host, no encryption, no retention policy.

Tests: `python -m pytest -q tests/integration/workflow_store` (the final test file checks that every refusal code was raised, so run the whole directory).
