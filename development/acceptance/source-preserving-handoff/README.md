# Source-preserving producer handoff (step 3.4 part B, producer side)

Candidate, non-authorizing, read-only. Authorized by the hub M0 decision record and specified by hub contract 1.4 (`docs/program-v0.2/s02/contracts/1.4-evidence-handoff.md`); sequencing in `s02/ownership-and-sequencing.md` (the source-preserving handoff precedes coordination, step 3.2). Release and production remain on HOLD. Any Qualification ingestion job is Qualification's own decision and is not part of this package.

`preserve.py` builds and checks a handoff record over the existing seed (`../o6-q5/candidate.json`, `../o6-q5/admission.py`) that carries the source **by digest only**. For each preserved file the record has the exact relative path, byte length, sha256 of the exact bytes and the git blob sha1 (`sha1(b"blob <len>\0" + bytes)`, computed locally; no git subprocess). It also carries the lock digest and component tuple, read by the 3.1 mapping (`read_lock` in `../lock-driven-handoff/handoff.py`, imported from this repository, not copied), and the 3.1 envelope conventions (`producer`, `hub`, `claim_scope`, `predecessor`, fixed `intent`, `effects`, `release_selection`, `operational_trust`, `qualification_reference`). The historical o6-q5 constants and candidate, and the 3.1 constants, are unchanged.

Canonical form: RFC 8785 subset, no floats; the digest is sha256 over the record without its `digest` member. The functions come from the 3.1 module (the same implementation the hub step 2.1 pattern describes); importing across repositories was not used.

## Guarantees and refusals (closed code set, `HandoffRefused.code`)

- Exact digest: every seed path needs a caller-supplied expected `sha256:` digest (the set of expected digests must equal the set of paths); a difference is `seed_digest_mismatch`, as is a lock that differs from `expected_lock_digest`.
- Read-only and race-aware: files are opened `O_RDONLY|O_NOFOLLOW`, every path component is `lstat`-checked, and each file is read twice; different bytes are `changed_between_reads`. A symlink anywhere is `symlink_refused`; an absolute path is `outside_root`; `..` is `path_traversal`; empty, `.`, backslash or NUL components are `path_invalid`; a missing file is `file_missing`; a directory or other non-regular file is `not_a_regular_file`; more than `max_bytes` (default 1 MiB, hard cap 16 MiB) is `oversize`.
- No rewrite: the API has no normalize, rewrite or re-serialize parameter and never opens a file for writing; the record holds no seed content, and a `content`-like or other unknown member is refused (`unknown_or_missing_member`). Tests assert the seed bytes and mtimes are unchanged and that no file was opened with a write flag.
- No decision: no verdict, pin, expectation, grant or selection member exists; such a member is `verdict_like_member`. `status` is always `HOLD`; fixed fields cannot change even with a valid digest (`fixed_field_changed`). Operational trust stays `not_established`.
- `check_record` validates a record offline; `recheck_sources` re-reads the files and the lock and refuses any difference.

Position on non-UTF-8: seed bytes are opaque and preserved as they are, never decoded or parsed; non-UTF-8 and CRLF seeds are accepted. The lock is parsed (strict UTF-8 JSON) through the 3.1 mapping and is refused when it is not.

Not independently qualified. `tests/integration/source_preserving_handoff/` holds developer tests only; independent cases belong to Qualification.
