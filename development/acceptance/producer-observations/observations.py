"""Immutable producer observations (step 3.4, part A). Never authorizes anything.

An append-only, content-addressed, hash-chained directory of observations the Orchestrator records
about what it handed off and observed. An observation is a fact with a source and a time; it is
not a verdict, pin, expectation, grant or authority, and every record carries the fixed
disposition "hold". Members that look like any of those are refused by name. There is no hidden
clock (observed_at is caller-supplied), no network, no subprocess, and no file is written outside
the one directory the caller names. Whether Qualification ingests observations is Qualification's
own decision; no ingestion job lives here.

Standard library only. Canonical JSON and the store pattern follow hub step 1.3 / 2.1
(RFC 8785 subset, no floats; exclusive create, read-only files, re-validation on load).
"""
from __future__ import annotations
import copy
import datetime
import hashlib
import json
import os
import re
import secrets
from pathlib import Path

PROFILE = "cognous-producer-observation/0"
SCHEMA_VERSION = 0
CANONICAL_PROFILE = "rfc8785-jcs"
MAX_SAFE_INT = 2 ** 53 - 1
SHA = re.compile(r"^[a-f0-9]{40}$")
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
OBS_ID = re.compile(r"^obs_[a-f0-9]{64}$")
PENDING_PREFIX = ".pending-"
FILE_NAME = re.compile(r"^(\d{12})\.json$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_SUBJECT = 256
MAX_REVISIONS = 64

FIELDS = {
    "profile", "schema_version", "canonical_profile", "digest", "observation_id", "kind", "subject",
    "source_revisions", "lock_digest", "observed_at", "sequence", "predecessor", "disposition",
}
# Closed set. Lock-bound kinds must carry the lock digest they were observed against; the rest must
# carry null (an observation is never bound to a lock it was not made against).
LOCK_BOUND_KINDS = frozenset({"handoff_envelope_produced", "handoff_envelope_checked"})
OTHER_KINDS = frozenset({"source_revision_observed", "ci_run_observed"})
KINDS = LOCK_BOUND_KINDS | OTHER_KINDS
FIXED_DISPOSITION = "hold"
# Member names refused as verdict/pin/expectation/grant/authority-like. Matched on lowercase
# substrings so renamed variants of the same idea are still refused, distinctly from plain unknowns.
FORBIDDEN_MARKERS = (
    "verdict", "pin", "expect", "grant", "authori", "approv", "accept", "pass", "fail", "decision",
    "certif", "qualif", "release", "promot", "select", "allow", "permission", "result", "clear",
)
CODES = frozenset({
    "schema_invalid", "unknown_member", "forbidden_member", "unknown_kind", "timestamp_invalid",
    "digest_mismatch", "id_mismatch", "fixed_field_changed", "chain_break", "unsafe_id",
    "store_conflict", "store_bound_exceeded", "store_integrity", "not_strict_json",
    "store_mode_writable", "store_missing",
})


class ObservationRefused(ValueError):
    """Typed refusal; the code is from a closed set. A refusal changes nothing."""

    def __init__(self, code: str, detail: str = "") -> None:
        assert code in CODES
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _refuse(code: str, detail: str = "") -> None:
    raise ObservationRefused(code, detail)


def _text(value) -> bool:
    return type(value) is str and bool(value.strip())


# --- canonical JSON -----------------------------------------------------------------------
_ESC = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _jstr(value: str) -> str:
    out = "".join(_ESC.get(c, "\\u%04x" % ord(c) if ord(c) < 0x20 else c) for c in value)
    text = '"' + out + '"'
    text.encode("utf-8")
    return text


def jcs_dumps(value) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) is int:
        if abs(value) > MAX_SAFE_INT:
            raise ValueError("integer outside the safe range")
        return str(value)
    if type(value) is str:
        return _jstr(value)
    if type(value) is list:
        return "[" + ",".join(jcs_dumps(v) for v in value) + "]"
    if type(value) is dict:
        if any(type(k) is not str for k in value):
            raise ValueError("object keys must be strings")
        keys = sorted(value, key=lambda k: k.encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(_jstr(k) + ":" + jcs_dumps(value[k]) for k in keys) + "}"
    raise ValueError("type not representable")


def loads_strict(data: bytes):
    """Parse JSON refusing duplicate keys, floats and non-finite constants."""
    def pairs(items):
        if len({k for k, _ in items}) != len(items):
            raise ValueError("duplicate object key")
        return dict(items)

    def bad(_):
        raise ValueError("floats and non-finite numbers are not part of the profile")

    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_float=bad, parse_constant=bad)


def canonical_bytes(observation: dict) -> bytes:
    """Canonical bytes of the whole observation (what is stored)."""
    try:
        return jcs_dumps(observation).encode("utf-8")
    except (ValueError, UnicodeEncodeError):
        _refuse("schema_invalid", "not canonicalizable")


def observation_digest(observation: dict) -> str:
    """sha256 over the canonical form without its digest member and the id derived from it."""
    body = {k: v for k, v in observation.items() if k not in ("digest", "observation_id")}
    try:
        return "sha256:" + hashlib.sha256(jcs_dumps(body).encode("utf-8")).hexdigest()
    except (ValueError, UnicodeEncodeError):
        _refuse("schema_invalid", "not canonicalizable")


def observation_id_for(digest: str) -> str:
    return "obs_" + digest.split(":", 1)[1]


# --- validation ---------------------------------------------------------------------------
def validate(observation) -> str:
    """Validate shape, fixed fields, id and digest. Returns the digest. Pure; changes nothing."""
    if type(observation) is not dict:
        _refuse("schema_invalid", "object required")
    extra = set(observation) - FIELDS
    for key in sorted(extra, key=str):
        if type(key) is str and any(m in key.lower() for m in FORBIDDEN_MARKERS):
            _refuse("forbidden_member", key[:40])
    if extra:
        _refuse("unknown_member", "unknown member")
    if set(observation) != FIELDS:
        _refuse("schema_invalid", "exact members required")
    if observation["profile"] != PROFILE or type(observation["schema_version"]) is not int \
            or observation["schema_version"] != SCHEMA_VERSION:
        _refuse("schema_invalid", "unsupported profile or schema version")
    if observation["canonical_profile"] != CANONICAL_PROFILE:
        _refuse("schema_invalid", "unknown canonical profile")
    if type(observation["disposition"]) is not str or observation["disposition"] != FIXED_DISPOSITION:
        _refuse("fixed_field_changed", "disposition")
    kind = observation["kind"]
    if type(kind) is not str or kind not in KINDS:
        _refuse("unknown_kind", str(kind)[:40])
    subject = observation["subject"]
    if not _text(subject) or len(subject) > MAX_SUBJECT or any(ord(c) < 0x20 for c in subject):
        _refuse("schema_invalid", "subject reference")
    revs = observation["source_revisions"]
    if type(revs) is not list or not revs or len(revs) > MAX_REVISIONS \
            or any(type(r) is not str or not SHA.fullmatch(r) for r in revs) or revs != sorted(set(revs)):
        _refuse("schema_invalid", "source_revisions must be sorted unique 40-hex revisions")
    lock = observation["lock_digest"]
    if kind in LOCK_BOUND_KINDS:
        if type(lock) is not str or not DIGEST.fullmatch(lock):
            _refuse("schema_invalid", "lock_digest required for this kind")
    elif lock is not None:
        _refuse("schema_invalid", "lock_digest must be null for this kind")
    _check_timestamp(observation["observed_at"])
    seq = observation["sequence"]
    if type(seq) is not int or not 1 <= seq <= 999_999_999_999:
        _refuse("schema_invalid", "sequence")
    pred = observation["predecessor"]
    if seq == 1:
        if pred is not None:
            _refuse("chain_break", "first observation has no predecessor")
    elif type(pred) is not str or not DIGEST.fullmatch(pred):
        _refuse("schema_invalid", "predecessor form")
    if type(observation["digest"]) is not str or not DIGEST.fullmatch(observation["digest"]):
        _refuse("schema_invalid", "digest form")
    computed = observation_digest(observation)
    if observation["digest"] != computed:
        _refuse("digest_mismatch")
    if observation["observation_id"] != observation_id_for(computed):
        _refuse("id_mismatch")
    return computed


def _check_timestamp(value) -> None:
    if type(value) is not str or not TIMESTAMP.fullmatch(value):
        _refuse("timestamp_invalid", "RFC 3339 UTC with Z, whole seconds")
    try:
        datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        _refuse("timestamp_invalid", "not a calendar time")


def build(*, kind: str, subject: str, source_revisions: list, lock_digest, observed_at: str,
          sequence: int, predecessor) -> dict:
    """Assemble and validate an observation; observed_at is supplied by the caller (no clock)."""
    obs = {
        "profile": PROFILE, "schema_version": SCHEMA_VERSION, "canonical_profile": CANONICAL_PROFILE,
        "digest": "sha256:" + "0" * 64, "observation_id": "obs_" + "0" * 64, "kind": kind,
        "subject": subject, "source_revisions": copy.deepcopy(source_revisions),
        "lock_digest": lock_digest, "observed_at": observed_at, "sequence": sequence,
        "predecessor": predecessor, "disposition": FIXED_DISPOSITION,
    }
    obs["digest"] = observation_digest(obs)
    obs["observation_id"] = observation_id_for(obs["digest"])
    validate(obs)
    return obs


# --- store --------------------------------------------------------------------------------
class ObservationStore:
    """Append-only directory: one read-only file per observation, named by sequence.

    The name is the sequence slot, so two writers racing for the same slot collide on exclusive
    create (store_conflict) instead of forking. Every read re-validates the whole chain. Deleting
    the newest records is only detectable against an externally held head (see verify_chain).
    """

    def __init__(self, directory, *, max_records: int, max_record_bytes: int) -> None:
        if type(max_records) is not int or max_records < 1 or type(max_record_bytes) is not int \
                or max_record_bytes < 1:
            raise ValueError("explicit positive bounds required")
        self.directory = Path(directory)
        self.max_records = max_records
        self.max_record_bytes = max_record_bytes

    # reading (never writes)
    def _entries(self) -> list:
        if not self.directory.is_dir() or self.directory.is_symlink():
            _refuse("store_missing")
        # in-flight temporary files of an appender (removed after publish) are not records
        names = sorted(n for n in os.listdir(self.directory) if not n.startswith(PENDING_PREFIX))
        for name in names:
            if not FILE_NAME.fullmatch(name):
                _refuse("store_integrity", "unexpected entry in store")
        return names

    def _read(self, name: str) -> dict:
        path = self.directory / name
        st = os.lstat(path)
        if not os.path.isfile(path) or os.path.islink(path):
            _refuse("store_integrity", "not a regular file")
        if st.st_size > self.max_record_bytes:
            _refuse("store_bound_exceeded", "oversized record")
        if st.st_mode & 0o222:
            _refuse("store_mode_writable", name)
        data = path.read_bytes()
        try:
            obs = loads_strict(data)
        except (ValueError, UnicodeDecodeError):
            _refuse("not_strict_json", name)
        validate(obs)
        if canonical_bytes(obs) != data:
            _refuse("store_integrity", "stored bytes are not canonical")
        if int(FILE_NAME.fullmatch(name).group(1)) != obs["sequence"]:
            _refuse("chain_break", "file name does not match sequence")
        return obs

    def verify_chain(self, *, expected_head: str | None = None, expected_count: int | None = None) -> list:
        """Read-only. Re-validate every record and the whole chain; return the digests in order.

        expected_head / expected_count are values the caller holds outside the store; they are
        the only way to notice removal of the newest records.
        """
        names = self._entries()
        if len(names) > self.max_records:
            _refuse("store_bound_exceeded", "record count")
        digests: list = []
        for index, name in enumerate(names, start=1):
            obs = self._read(name)
            if obs["sequence"] != index:
                _refuse("chain_break", f"gap or reorder at {index}")
            if obs["predecessor"] != (digests[-1] if digests else None):
                _refuse("chain_break", f"predecessor mismatch at {index}")
            digests.append(obs["digest"])
        if expected_count is not None and expected_count != len(digests):
            _refuse("chain_break", "record count differs from the held count")
        if expected_head is not None and expected_head != (digests[-1] if digests else None):
            _refuse("chain_break", "head differs from the held head")
        return digests

    def load(self, observation_id: str) -> dict:
        """Return one observation by id after re-validating the whole chain."""
        if type(observation_id) is not str or not OBS_ID.fullmatch(observation_id):
            _refuse("unsafe_id", "observation id form")
        self.verify_chain()
        for name in self._entries():
            obs = self._read(name)
            if obs["observation_id"] == observation_id:
                return obs
        _refuse("store_missing", "no such observation")

    def load_all(self) -> list:
        self.verify_chain()
        return [self._read(n) for n in self._entries()]

    # writing
    def append(self, observation: dict) -> str:
        """Validate, check the chain, then publish one new read-only file. Returns the id."""
        validate(observation)
        data = canonical_bytes(observation)
        if len(data) > self.max_record_bytes:
            _refuse("store_bound_exceeded", "record too large")
        if not self.directory.exists():
            os.mkdir(self.directory)  # only the named directory; parents must exist
        digests = self.verify_chain()
        if len(digests) >= self.max_records:
            _refuse("store_bound_exceeded", "record count bound reached")
        if observation["sequence"] != len(digests) + 1 \
                or observation["predecessor"] != (digests[-1] if digests else None):
            _refuse("chain_break", "does not extend the current head")
        final = self.directory / f"{observation['sequence']:012d}.json"
        temp = self.directory / f"{PENDING_PREFIX}{secrets.token_hex(8)}"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            try:
                os.link(temp, final)  # atomic and exclusive: never overwrites, never half-visible
            except FileExistsError:
                _refuse("store_conflict", "sequence slot already taken")
        finally:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass
        return observation["observation_id"]
