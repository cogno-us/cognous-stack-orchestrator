"""Lock-driven, read-only evidence handoff (step 3.1 / contract 1.4). Never authorizes anything.

The producer side of the independent evidence handoff. It reads component revisions from a hub
component-lock.json supplied to the run (bound by the lock's byte digest) instead of constants,
and builds or checks an immutable evidence envelope. It adds evidence only: it selects no pin,
writes no lock, writes no verdict or expectation, and has no promotion path. Qualification
decides by its own process whether to consume an envelope. The historical o6-q5 constants in
../o6-q5/ are history and are not changed.

Standard library only. Canonical JSON follows the hub step 1.3 profile (RFC 8785 subset, no
floats); this module carries a conforming implementation, not a second profile.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path

PROFILE = "cognous-lock-driven-evidence-handoff/0"
SCHEMA_VERSION = 0
CANONICAL_PROFILE = "rfc8785-jcs"
MAX_SAFE_INT = 2 ** 53 - 1
SHA = re.compile(r"^[a-f0-9]{40}$")
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
ENVELOPE_FIELDS = {
    "profile", "schema_version", "canonical_profile", "digest", "producer", "hub", "lock_digest",
    "tuple", "tuple_digest", "evidence", "claim_scope", "intent", "effects", "release_selection",
    "operational_trust", "predecessor", "qualification_reference",
}
EVIDENCE_FIELDS = {"kind", "producing_commit", "run_id", "result_digest", "tuple_digest", "artifact_refs"}
FIXED = {
    "intent": "read_only_candidate_evidence",
    "effects": "disabled",
    "release_selection": "unchanged",
    "operational_trust": {"state": "not_established", "independent_operator_evidence": None},
    "qualification_reference": None,
}


class HandoffRefused(ValueError):
    """Typed refusal; the code is from a closed set. A refusal changes nothing."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _refuse(code: str, detail: str = "") -> None:
    raise HandoffRefused(code, detail)


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


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def loads_strict(data: bytes):
    def pairs(items):
        if len({k for k, _ in items}) != len(items):
            raise ValueError("duplicate object key")
        return dict(items)

    def bad(_text_):
        raise ValueError("floats and non-finite numbers are not part of the profile")

    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_float=bad, parse_constant=bad)


def envelope_digest(envelope: dict) -> str:
    return _sha256(jcs_dumps({k: v for k, v in envelope.items() if k != "digest"}).encode("utf-8"))


# --- lock intake --------------------------------------------------------------------------
def read_lock(lock_bytes: bytes) -> tuple[str, dict]:
    """Return (lock byte digest, normalized tuple). Fails closed on an unknown key shape.

    The one documented key mapping (the same precedence the hub tools use): a component's
    revision is `sha` or `accepted_sha`; when both are present they must be equal, otherwise the
    entry is refused. An entry with `core_interop_sha` must have it equal to the revision. An
    entry with neither key, or a malformed revision, is an unknown shape. Nested history members
    such as `previous_acceptance` are not part of the tuple and are ignored. The lock is never
    edited.
    """
    try:
        lock = loads_strict(lock_bytes)
    except (ValueError, UnicodeDecodeError):
        _refuse("lock_not_strict_json")
    if type(lock) is not dict or not _text(lock.get("lock_version")) or type(lock.get("components")) is not dict \
            or not lock["components"]:
        _refuse("unknown_lock_shape", "lock_version and components required")
    tuple_: dict = {}
    for name, entry in lock["components"].items():
        if type(entry) is not dict or not _text(entry.get("repository")):
            _refuse("unknown_lock_shape", f"component {name}")
        present = [entry[k] for k in ("sha", "accepted_sha") if k in entry]
        if not present:
            _refuse("unknown_lock_shape", f"component {name} revision key")
        if any(type(v) is not str or not SHA.fullmatch(v) for v in present):
            _refuse("unknown_lock_shape", f"component {name} revision form")
        if len(set(present)) != 1:
            _refuse("lock_revision_conflict", name)
        revision = present[0]
        if "core_interop_sha" in entry and entry["core_interop_sha"] != revision:
            _refuse("lock_interop_drift", name)
        interfaces = entry.get("interfaces", [])
        if type(interfaces) is not list or any(not _text(i) for i in interfaces):
            _refuse("unknown_lock_shape", f"component {name} interfaces")
        tuple_[name] = {"repository": entry["repository"], "sha": revision, "interfaces": list(interfaces)}
    return _sha256(lock_bytes), tuple_


def tuple_digest(tuple_: dict) -> str:
    return _sha256(jcs_dumps(tuple_).encode("utf-8"))


# --- build and check ----------------------------------------------------------------------
def _check_evidence(entries, expected_tuple_digest: str) -> None:
    if type(entries) is not list or not entries:
        _refuse("evidence_missing")
    for item in entries:
        if type(item) is not dict or set(item) != EVIDENCE_FIELDS:
            _refuse("evidence_shape")
        if not _text(item["kind"]) or not _text(item["producing_commit"]) \
                or not SHA.fullmatch(item["producing_commit"]):
            _refuse("evidence_shape")
        if type(item["run_id"]) is not int or item["run_id"] < 1 or item["run_id"] > MAX_SAFE_INT:
            _refuse("evidence_shape")
        if type(item["result_digest"]) is not str or not DIGEST.fullmatch(item["result_digest"]):
            _refuse("evidence_shape")
        refs = item["artifact_refs"]
        if type(refs) is not list or any(not _text(r) for r in refs):
            _refuse("evidence_shape")
        if item["tuple_digest"] != expected_tuple_digest:
            _refuse("evidence_tuple_mismatch", item["kind"])


def _check_claim_scope(scope) -> None:
    if type(scope) is not dict or set(scope) != {"claim", "exclusions"} or not _text(scope["claim"]) \
            or type(scope["exclusions"]) is not list or not scope["exclusions"] \
            or any(not _text(e) for e in scope["exclusions"]):
        _refuse("claim_scope_invalid", "a narrow claim and explicit exclusions are required")


def build_envelope(*, lock_bytes: bytes, hub_repository: str, hub_sha: str, producer: dict,
                   evidence: list, claim_scope: dict, predecessor: str | None = None) -> dict:
    """Build an immutable envelope for exactly the tuple in the supplied lock."""
    lock_digest, tuple_ = read_lock(lock_bytes)
    t_digest = tuple_digest(tuple_)
    if not SHA.fullmatch(hub_sha or "") or not _text(hub_repository):
        _refuse("hub_identity_invalid")
    envelope = {
        "profile": PROFILE, "schema_version": SCHEMA_VERSION, "canonical_profile": CANONICAL_PROFILE,
        "digest": "sha256:" + "0" * 64, "producer": copy.deepcopy(producer),
        "hub": {"repository": hub_repository, "source_sha": hub_sha},
        "lock_digest": lock_digest, "tuple": tuple_, "tuple_digest": t_digest,
        "evidence": copy.deepcopy(evidence), "claim_scope": copy.deepcopy(claim_scope),
        "predecessor": predecessor, **copy.deepcopy(FIXED),
    }
    _check_producer(envelope["producer"])
    _check_evidence(envelope["evidence"], t_digest)
    _check_claim_scope(envelope["claim_scope"])
    _check_predecessor(predecessor)
    envelope["digest"] = envelope_digest(envelope)
    return envelope


def _check_producer(producer) -> None:
    if type(producer) is not dict or set(producer) != {"component", "revision"} \
            or not _text(producer["component"]) or type(producer["revision"]) is not str \
            or not SHA.fullmatch(producer["revision"]):
        _refuse("producer_invalid")


def _check_predecessor(value) -> None:
    if value is not None and (type(value) is not str or not DIGEST.fullmatch(value)):
        _refuse("predecessor_invalid")


def check_envelope(envelope: dict, *, lock_bytes: bytes, hub_head: str,
                   superseded: frozenset = frozenset()) -> dict:
    """Validate an envelope against the lock supplied to this run. Always ends in HOLD.

    Refuses any difference between the envelope and the supplied lock, so no historical pass
    transfers to a different tuple. Pure: reads its arguments, writes nothing.
    """
    if type(envelope) is not dict or set(envelope) != ENVELOPE_FIELDS:
        _refuse("unknown_or_missing_member")
    if envelope["profile"] != PROFILE or envelope["schema_version"] != SCHEMA_VERSION \
            or type(envelope["schema_version"]) is not int:
        _refuse("profile_mismatch")
    if envelope["canonical_profile"] != CANONICAL_PROFILE:
        _refuse("unknown_canonical_profile")
    for key, expected in FIXED.items():
        if type(envelope[key]) is not type(expected) or envelope[key] != expected:
            _refuse("fixed_field_changed", key)
    if type(envelope["digest"]) is not str or not DIGEST.fullmatch(envelope["digest"]):
        _refuse("digest_form")
    try:
        computed = envelope_digest(envelope)
    except ValueError:
        _refuse("not_canonicalizable")
    if envelope["digest"] != computed:
        _refuse("digest_mismatch")
    lock_digest, tuple_ = read_lock(lock_bytes)
    if envelope["lock_digest"] != lock_digest:
        _refuse("lock_digest_mismatch")
    if envelope["tuple"] != tuple_:
        _refuse("tuple_differs_from_lock")
    t_digest = tuple_digest(tuple_)
    if envelope["tuple_digest"] != t_digest:
        _refuse("tuple_digest_mismatch")
    hub = envelope["hub"]
    if type(hub) is not dict or set(hub) != {"repository", "source_sha"} or hub["source_sha"] != hub_head \
            or not _text(hub["repository"]):
        _refuse("hub_sha_mismatch")
    _check_producer(envelope["producer"])
    _check_evidence(envelope["evidence"], t_digest)
    _check_claim_scope(envelope["claim_scope"])
    _check_predecessor(envelope["predecessor"])
    if computed in superseded:
        _refuse("superseded")
    return {
        "status": "hold",
        "release_admission": "not_authorized",
        "selection": "unchanged",
        "effects": "disabled",
        "reason": "evidence_only_no_verdict",
        "envelope_digest": computed,
        "tuple_digest": t_digest,
        "lock_digest": lock_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check an evidence envelope against a supplied hub lock")
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--hub-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        head = subprocess.check_output(["git", "-C", str(args.hub_root), "rev-parse", "HEAD"], text=True,
                                       stderr=subprocess.STDOUT).strip()
        lock_bytes = (args.hub_root / "component-lock.json").read_bytes()
        envelope = loads_strict(args.envelope.read_bytes())
        result = check_envelope(envelope, lock_bytes=lock_bytes, hub_head=head)
    except (OSError, subprocess.CalledProcessError, ValueError, UnicodeDecodeError) as exc:
        print(json.dumps({"status": "hold", "release_admission": "not_authorized", "effects": "disabled",
                          "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
