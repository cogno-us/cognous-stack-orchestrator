# Source-preserving producer handoff (step 3.4 part B, producer side)

Candidate, non-authorizing, read-only. Authorized by the hub M0 decision record and specified by hub contract 1.4 (`docs/program-v0.2/s02/contracts/1.4-evidence-handoff.md`); sequencing in `s02/ownership-and-sequencing.md` (the source-preserving handoff precedes coordination, step 3.2). Release and production remain on HOLD. Any Qualification ingestion job is Qualification's own decision and is not part of this package.

`preserve.py` builds and checks a handoff record over the existing seed (`../o6-q5/candidate.json`, `../o6-q5/admission.py`) that carries the source **by digest only**. For each preserved file the record has the exact relative path, byte length, sha256 of the exact bytes and the git blob sha1 (`sha1(b"blob <len>\0" + bytes)`, computed locally; no git subprocess). It also carries the lock digest and component tuple, read by the 3.1 mapping (`read_lock` in `../lock-driven-handoff/handoff.py`, imported from this repository, not copied), and the 3.1 envelope conventions (`producer`, `hub`, `claim_scope`, `predecessor`, fixed `intent`, `effects`, `release_selection`, `operational_trust`, `qualification_reference`). The historical o6-q5 constants and candidate, and the 3.1 constants, are unchanged.

Canonical form: RFC 8785 subset, no floats; the digest is sha256 over the record without its `digest` member. The functions are imported from the 3.1 module in this repository (`../lock-driven-handoff/handoff.py`); nothing is copied and nothing is imported across repositories. No claim is made that this is byte-for-byte the hub's step 2.1 implementation.

The record is a new profile (`cognous-source-preserving-handoff/0`). It deliberately deviates from the 1.4 envelope field table: it replaces the `evidence` list with `lock_file`, `sources`, `tuple` and `preservation` members. It is not a 1.4 envelope and must not be read as one.

## Guarantees and refusals (closed code set, `HandoffRefused.code`)

- Exact digest: every seed path needs a caller-supplied expected `sha256:` digest (the set of expected digests must equal the set of paths); a difference is `seed_digest_mismatch`, as is a lock that differs from `expected_lock_digest`.
- Read-only and race-aware: the root directory is opened first, then every component is `lstat`-checked and opened relative to its parent directory fd (directories `O_RDONLY|O_NOFOLLOW|O_DIRECTORY`, the file `O_RDONLY|O_NOFOLLOW|O_NONBLOCK`); the opened object must be a regular file (or directory) with the same device and inode as the `lstat`, otherwise the read is refused (`changed_between_reads`, `symlink_refused` or `not_a_regular_file`). A FIFO swapped in after the check cannot hang the read. Each file is read twice; different bytes are `changed_between_reads`. A symlink anywhere below the root is `symlink_refused`; an absolute path is `outside_root`; `..` is `path_traversal`; empty, `.`, backslash or NUL components are `path_invalid`; a missing file is `file_missing`; a root or lock root that is itself a symlink is `root_symlink_refused` (a non-directory or missing root is `root_invalid`); a directory or other non-regular file is `not_a_regular_file`; more than `max_bytes` (default 1 MiB, hard cap 16 MiB) is `oversize`.
- No rewrite: the API has no normalize, rewrite or re-serialize parameter and never opens a file for writing; the record holds no seed content, and a `content`-like or other unknown member is refused (`unknown_or_missing_member`). Tests assert the seed bytes and mtimes are unchanged and that no file was opened with a write flag.
- No decision: no verdict, pin, expectation, grant or selection member exists; such a member is `verdict_like_member`. `status` is always `HOLD`; fixed fields cannot change even with a valid digest (`fixed_field_changed`). Operational trust stays `not_established`.
- Strict record checks: fixed fields (including the nested `preservation` object) are compared type-exactly, so `0` is not `False`; the `tuple` must be `name -> {repository, sha, interfaces}` (`tuple_invalid`) and `tuple_digest` must equal the 3.1 `tuple_digest` of it (`tuple_digest_mismatch`). Build-time inputs of the wrong type (for example `producer=None`, non-text paths, a string `exclusions`) are refused with the closed codes above, never a `TypeError`.
- `check_record` validates a record offline; `recheck_sources` re-reads the files and the lock and refuses any difference.

## Stated limits

- Same-content replacement is not detectable: if a file is replaced by a different inode with identical bytes (or changed and restored, A-B-A, between or around the two reads), the record is the same; the digest and the dev/inode comparison within one pass are the only checks. A hardlink to a regular file is accepted.
- Case-insensitive file systems: a path spelled with different case may name the same file; the record keeps the caller's spelling and does not canonicalize it.
- Only the root's own final component is checked for being a symlink. Symlinks in the root's ancestors are resolved by the operating system and are not disclosed; `symlinks_followed: false` states that nothing below the root was followed.
- The tests pin the exact current o6-q5 bytes, so a legitimate edit to the seed turns CI red by design; update the pins only with the seed change in the same reviewed change.
- The reader needs `dir_fd`, `O_NOFOLLOW`, `O_DIRECTORY` and `O_NONBLOCK` (POSIX); otherwise it refuses (`file_unreadable`).

Position on non-UTF-8: seed bytes are opaque and preserved as they are, never decoded or parsed; non-UTF-8 and CRLF seeds are accepted. The lock is parsed (strict UTF-8 JSON) through the 3.1 mapping and is refused when it is not.

Not independently qualified. `tests/integration/source_preserving_handoff/` holds developer tests only; independent cases belong to Qualification.
