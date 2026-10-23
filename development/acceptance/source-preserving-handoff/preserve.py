"""Source-preserving producer handoff (step 3.4 part B / contract 1.4). Never authorizes anything.

Given explicit paths and expected digests, this producer emits a handoff record that carries the
seed files (for example ../o6-q5/candidate.json and admission.py) BY DIGEST ONLY: exact path, byte
length, sha256 of the exact bytes and git blob sha1. It never parses, normalizes, re-serializes or
writes a seed file; files are opened read-only without following symlinks and read twice, and any
difference between the reads, a digest that differs from the caller's expected digest, a symlink,
a path outside the root, an oversize file or an unknown member is a loud refusal.

The lock digest and component tuple come from the 3.1 module (`read_lock`, one documented key
mapping) imported from the sibling directory in this repository; nothing is copied. The record has
no verdict, pin or expectation member and always states HOLD. The historical o6-q5 constants and
candidate are not changed. Standard library only; no network and no subprocess (the git blob sha1
is computed from the bytes).
"""
from __future__ import annotations
import hashlib
import importlib.util
import os
import re
import stat
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "lock_driven_handoff_31", Path(__file__).resolve().parents[1] / "lock-driven-handoff" / "handoff.py")
assert _SPEC and _SPEC.loader
h31 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(h31)

HandoffRefused = h31.HandoffRefused
jcs_dumps = h31.jcs_dumps
loads_strict = h31.loads_strict
record_digest = h31.envelope_digest  # sha256 over the canonical record without its digest member

PROFILE = "cognous-source-preserving-handoff/0"
SCHEMA_VERSION = 0
CANONICAL_PROFILE = h31.CANONICAL_PROFILE
DEFAULT_MAX_BYTES = 1 << 20
HARD_MAX_BYTES = 16 << 20
MAX_FILES = 16
DIGEST = h31.DIGEST
SHA = h31.SHA
RECORD_FIELDS = {
    "profile", "schema_version", "canonical_profile", "digest", "status", "producer", "hub", "lock_digest",
    "tuple", "tuple_digest", "lock_file", "sources", "preservation", "claim_scope", "predecessor",
    "intent", "effects", "release_selection", "operational_trust", "qualification_reference",
}
FILE_FIELDS = {"path", "bytes", "sha256", "git_blob_sha1"}
FIXED = {
    "status": "HOLD",
    "intent": h31.FIXED["intent"],
    "effects": h31.FIXED["effects"],
    "release_selection": h31.FIXED["release_selection"],
    "operational_trust": h31.FIXED["operational_trust"],
    "qualification_reference": None,
    "preservation": {"mode": "bytes_by_digest_only", "reads_per_file": 2, "seed_files_modified": False,
                     "normalized_or_reserialized": False, "symlinks_followed": False},
}
# Names that would turn a record into a decision; refused with their own code (a subset of "unknown").
VERDICT_LIKE = re.compile(r"verdict|pin|expect|pass|fail|approv|grant|accept|decision|select|promot|"
                          r"authori[sz]|clear|certif|qualif(?!ication_reference)|override", re.I)


def _refuse(code: str, detail: str = "") -> None:
    raise HandoffRefused(code, detail)


def git_blob_sha1(data: bytes) -> str:
    """Git object id of a blob with exactly these bytes, computed locally (no git subprocess)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# --- safe, read-only reading --------------------------------------------------------------
def _split(rel) -> list[str]:
    if type(rel) is not str or not rel or "\0" in rel or "\\" in rel:
        _refuse("path_invalid", "relative POSIX text required")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        _refuse("outside_root", "absolute paths are not accepted")
    parts = rel.split("/")
    if any(p == ".." for p in parts):
        _refuse("path_traversal", rel)
    if any(p in ("", ".") for p in parts):
        _refuse("path_invalid", "empty or '.' component")
    return parts


def _read_once(root: str, parts: list[str], max_bytes: int) -> bytes:
    """One read-only pass: every component is checked with lstat (no symlink anywhere), the file
    is opened O_RDONLY|O_NOFOLLOW and must be a regular file within the size bound."""
    cur = root
    for index, part in enumerate(parts):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            _refuse("file_missing", "/".join(parts))
        except OSError as exc:
            _refuse("file_unreadable", f"{type(exc).__name__}")
        if stat.S_ISLNK(st.st_mode):
            _refuse("symlink_refused", "/".join(parts[: index + 1]))
        last = index == len(parts) - 1
        if last and not stat.S_ISREG(st.st_mode):
            _refuse("not_a_regular_file", "/".join(parts))
        if not last and not stat.S_ISDIR(st.st_mode):
            _refuse("path_invalid", "/".join(parts[: index + 1]))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(cur, flags)
    except OSError as exc:
        _refuse("file_unreadable", f"{type(exc).__name__}")
    try:
        if os.fstat(fd).st_size > max_bytes:
            _refuse("oversize", "/".join(parts))
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                _refuse("oversize", "/".join(parts))
            chunks.append(chunk)
    finally:
        os.close(fd)
    return b"".join(chunks)


def _root(root) -> str:
    if not isinstance(root, (str, os.PathLike)):
        _refuse("root_invalid")
    real = os.path.realpath(os.fspath(root))
    if not os.path.isdir(real):
        _refuse("root_invalid", "not a directory")
    return real


def _preserve(root: str, rel, expected, max_bytes: int) -> dict:
    parts = _split(rel)
    first = _read_once(root, parts, max_bytes)
    second = _read_once(root, parts, max_bytes)
    if first != second:
        _refuse("changed_between_reads", rel)
    digest = _sha256(first)
    if type(expected) is not str or not DIGEST.fullmatch(expected):
        _refuse("expected_digest_invalid", rel)
    if digest != expected:
        _refuse("seed_digest_mismatch", rel)
    return {"path": rel, "bytes": len(first), "sha256": digest, "git_blob_sha1": git_blob_sha1(first)}


def _bound(max_bytes) -> int:
    if type(max_bytes) is not int or not 1 <= max_bytes <= HARD_MAX_BYTES:
        _refuse("max_bytes_invalid")
    return max_bytes


# --- build --------------------------------------------------------------------------------
def build_record(*, root, seed_paths: list, expected_digests: dict, lock_root, lock_path: str,
                 expected_lock_digest: str, hub_repository: str, hub_sha: str, producer: dict,
                 claim_scope: dict, predecessor: str | None = None, max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    """Preserve exactly the listed seed files (relative to `root`) and the lock (relative to
    `lock_root`) by digest and return the digested HOLD record. Read-only; refusals change nothing.
    There is deliberately no parameter to rewrite, normalize or re-serialize anything."""
    max_bytes = _bound(max_bytes)
    if type(seed_paths) is not list or not seed_paths or len(seed_paths) > MAX_FILES:
        _refuse("seed_paths_invalid", f"1..{MAX_FILES} paths required")
    if len(set(seed_paths)) != len(seed_paths):
        _refuse("seed_paths_invalid", "duplicate path")
    if type(expected_digests) is not dict or set(expected_digests) != set(seed_paths):
        _refuse("expected_digests_mismatch", "an expected digest is required for exactly every seed path")
    if not SHA.fullmatch(hub_sha or "") or not h31._text(hub_repository):
        _refuse("hub_identity_invalid")
    real_root, real_lock_root = _root(root), _root(lock_root)
    sources = [_preserve(real_root, p, expected_digests[p], max_bytes) for p in sorted(seed_paths)]
    lock_file = _preserve(real_lock_root, lock_path, expected_lock_digest, max_bytes)
    lock_bytes = _read_once(real_lock_root, _split(lock_path), max_bytes)
    if _sha256(lock_bytes) != lock_file["sha256"]:
        _refuse("changed_between_reads", lock_path)
    lock_digest, tuple_ = h31.read_lock(lock_bytes)
    record = {
        "profile": PROFILE, "schema_version": SCHEMA_VERSION, "canonical_profile": CANONICAL_PROFILE,
        "digest": "sha256:" + "0" * 64, "producer": dict(producer), "hub": {"repository": hub_repository,
                                                                         "source_sha": hub_sha},
        "lock_digest": lock_digest, "tuple": tuple_, "tuple_digest": h31.tuple_digest(tuple_),
        "lock_file": lock_file, "sources": sources, "claim_scope": {
            "claim": claim_scope.get("claim") if type(claim_scope) is dict else None,
            "exclusions": list(claim_scope.get("exclusions", [])) if type(claim_scope) is dict else None},
        "predecessor": predecessor,
        **{k: (dict(v) if type(v) is dict else v) for k, v in FIXED.items()},
    }
    _check_shape(record)
    record["digest"] = record_digest(record)
    return record


# --- check --------------------------------------------------------------------------------
def _check_file_entry(entry) -> None:
    if type(entry) is not dict or set(entry) != FILE_FIELDS:
        _refuse("unknown_or_missing_member", "file entry")
    _split(entry["path"])
    if type(entry["bytes"]) is not int or not 0 <= entry["bytes"] <= HARD_MAX_BYTES:
        _refuse("file_entry_invalid", "bytes")
    if type(entry["sha256"]) is not str or not DIGEST.fullmatch(entry["sha256"]):
        _refuse("file_entry_invalid", "sha256")
    if type(entry["git_blob_sha1"]) is not str or not SHA.fullmatch(entry["git_blob_sha1"]):
        _refuse("file_entry_invalid", "git_blob_sha1")


def _check_shape(record) -> None:
    if type(record) is not dict:
        _refuse("unknown_or_missing_member", "record is not an object")
    extra = set(record) - RECORD_FIELDS
    for name in sorted(extra):
        if VERDICT_LIKE.search(name):
            _refuse("verdict_like_member", name)
    if extra or set(record) != RECORD_FIELDS:
        _refuse("unknown_or_missing_member", ",".join(sorted(set(record) ^ RECORD_FIELDS))[:80])
    if record["profile"] != PROFILE or record["schema_version"] != SCHEMA_VERSION \
            or type(record["schema_version"]) is not int:
        _refuse("profile_mismatch")
    if record["canonical_profile"] != CANONICAL_PROFILE:
        _refuse("unknown_canonical_profile")
    for key, expected in FIXED.items():
        if type(record[key]) is not type(expected) or record[key] != expected:
            _refuse("fixed_field_changed", key)
    if type(record["digest"]) is not str or not DIGEST.fullmatch(record["digest"]):
        _refuse("digest_form")
    h31._check_producer(record["producer"])
    h31._check_claim_scope(record["claim_scope"])
    h31._check_predecessor(record["predecessor"])
    hub = record["hub"]
    if type(hub) is not dict or set(hub) != {"repository", "source_sha"} or not h31._text(hub["repository"]) \
            or type(hub["source_sha"]) is not str or not SHA.fullmatch(hub["source_sha"]):
        _refuse("hub_identity_invalid")
    for key in ("lock_digest", "tuple_digest"):
        if type(record[key]) is not str or not DIGEST.fullmatch(record[key]):
            _refuse("digest_form", key)
    _check_file_entry(record["lock_file"])
    if record["lock_file"]["sha256"] != record["lock_digest"]:
        _refuse("lock_digest_mismatch")
    sources = record["sources"]
    if type(sources) is not list or not sources or len(sources) > MAX_FILES:
        _refuse("seed_paths_invalid")
    for entry in sources:
        _check_file_entry(entry)
    paths = [e["path"] for e in sources]
    if paths != sorted(set(paths)):
        _refuse("seed_paths_invalid", "sources must be sorted and unique")


def check_record(record: dict) -> dict:
    """Validate a record offline (shape, fixed fields, digest). Pure; always ends in HOLD."""
    _check_shape(record)
    try:
        computed = record_digest(record)
    except ValueError:
        _refuse("not_canonicalizable")
    if record["digest"] != computed:
        _refuse("digest_mismatch")
    return {"status": "HOLD", "release_admission": "not_authorized", "selection": "unchanged",
            "effects": "disabled", "reason": "evidence_only_no_verdict", "record_digest": computed}


def recheck_sources(record: dict, *, root, lock_root, max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    """check_record, then re-read every preserved file (read-only, twice) and require the same
    path, length, sha256 and blob sha1 as the record, and the lock's tuple unchanged."""
    result = check_record(record)
    max_bytes = _bound(max_bytes)
    real_root, real_lock_root = _root(root), _root(lock_root)
    for entry in record["sources"]:
        if _preserve(real_root, entry["path"], entry["sha256"], max_bytes) != entry:
            _refuse("source_differs_from_record", entry["path"])
    lock_entry = record["lock_file"]
    if _preserve(real_lock_root, lock_entry["path"], lock_entry["sha256"], max_bytes) != lock_entry:
        _refuse("source_differs_from_record", lock_entry["path"])
    lock_digest, tuple_ = h31.read_lock(_read_once(real_lock_root, _split(lock_entry["path"]), max_bytes))
    if lock_digest != record["lock_digest"] or tuple_ != record["tuple"] \
            or h31.tuple_digest(tuple_) != record["tuple_digest"]:
        _refuse("tuple_differs_from_lock")
    return result
