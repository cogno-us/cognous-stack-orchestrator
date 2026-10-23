"""Developer tests for the source-preserving producer handoff. Not independent acceptance cases."""
from __future__ import annotations
import builtins
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "development/acceptance/source-preserving-handoff/preserve.py"
spec = importlib.util.spec_from_file_location("source_preserving_handoff", SCRIPT)
assert spec and spec.loader
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

CANDIDATE = "development/acceptance/o6-q5/candidate.json"
ADMISSION = "development/acceptance/o6-q5/admission.py"
# Exact seed bytes at Orchestrator 95a3b48 (git blob ids as in `git ls-tree`).
SEED = {
    CANDIDATE: {"bytes": 1298, "sha256": "sha256:01b9a1c6db038b6782eba038642a7bced2ebfa7abf887a136349ad1aef0b6ba6",
                "git_blob_sha1": "27381ad46876966af4e6b9ac6bb514ff588f952b"},
    ADMISSION: {"bytes": 5103, "sha256": "sha256:3804e22d55f7db0ce3b2a18dc766ce3074c3c57780710fdccc19df632a5a1b5b",
                "git_blob_sha1": "3ab582a9c29f8b055733ee701644504c3062eb8c"},
}
EXPECTED = {k: v["sha256"] for k, v in SEED.items()}
A, B, C, D = ("a" * 40, "b" * 40, "c" * 40, "d" * 40)
PRODUCER = {"component": "cognous-stack-orchestrator", "revision": "f" * 40}
SCOPE = {"claim": "source bytes of the o6-q5 seed by digest only", "exclusions": ["no verdict", "no pin selection"]}
HUB = "e" * 40


def lock_bytes() -> bytes:
    return json.dumps({"lock_version": "1.0", "components": {
        "control_plane": {"repository": "cogno-us/control-plane", "sha": A, "interfaces": ["Decision 1.0"]},
        "moltbot_safe": {"repository": "cogno-us/runtime", "accepted_sha": B, "core_interop_sha": B},
        "bitrep": {"repository": "cogno-us/bitrep", "sha": C},
    }}, indent=2).encode()


@pytest.fixture
def hub(tmp_path):
    d = tmp_path / "hub"
    d.mkdir()
    (d / "component-lock.json").write_bytes(lock_bytes())
    return d


def args(hub, **over):
    a = dict(root=ROOT, seed_paths=[ADMISSION, CANDIDATE], expected_digests=dict(EXPECTED), lock_root=hub,
             lock_path="component-lock.json",
             expected_lock_digest="sha256:" + hashlib.sha256(lock_bytes()).hexdigest(),
             hub_repository="cogno-us/cognous-open-control-stack", hub_sha=HUB, producer=PRODUCER,
             claim_scope=copy.deepcopy(SCOPE))
    a.update(over)
    return a


def refused(code, **kw):
    with pytest.raises(p.HandoffRefused) as ctx:
        p.build_record(**kw)
    assert ctx.value.code == code, ctx.value
    return ctx.value


def redigest(rec):
    rec["digest"] = p.record_digest(rec)
    return rec


def snapshot():
    return {k: ((ROOT / k).read_bytes(), (ROOT / k).stat().st_mtime_ns) for k in SEED}


# --- positive -----------------------------------------------------------------------------
def test_real_seed_is_preserved_by_digest_and_blob_id(hub):
    before = snapshot()
    rec = p.build_record(**args(hub))
    assert snapshot() == before
    assert [e["path"] for e in rec["sources"]] == sorted(SEED)
    for e in rec["sources"]:
        assert {k: e[k] for k in ("bytes", "sha256", "git_blob_sha1")} == SEED[e["path"]]
    assert rec["status"] == "HOLD" and rec["effects"] == "disabled" and rec["release_selection"] == "unchanged"
    assert rec["operational_trust"] == {"state": "not_established", "independent_operator_evidence": None}
    assert rec["qualification_reference"] is None
    assert rec["lock_file"]["sha256"] == rec["lock_digest"]
    assert rec["tuple"]["moltbot_safe"]["sha"] == B and rec["tuple"]["bitrep"]["interfaces"] == []
    out = p.check_record(rec)
    assert out["status"] == "HOLD" and out["release_admission"] == "not_authorized"
    assert out["record_digest"] == rec["digest"]
    assert p.recheck_sources(rec, root=ROOT, lock_root=hub)["status"] == "HOLD"


def test_record_is_canonical_and_deterministic(hub):
    r1, r2 = p.build_record(**args(hub)), p.build_record(**args(hub, seed_paths=[CANDIDATE, ADMISSION]))
    assert r1 == r2
    body = {k: v for k, v in r1.items() if k != "digest"}
    assert r1["digest"] == "sha256:" + hashlib.sha256(p.jcs_dumps(body).encode()).hexdigest()
    assert p.loads_strict(p.jcs_dumps(r1).encode()) == r1


def test_record_carries_no_seed_content(hub):
    text = p.jcs_dumps(p.build_record(**args(hub)))
    for needle in ("cognous-o6-release-candidate-admission/1", "2a23a2fbb3f5", "CandidateInvalid"):
        assert needle not in text


def test_git_blob_sha1_known_vectors():
    assert p.git_blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert p.git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_seed_never_opened_for_writing_and_no_other_io(hub, monkeypatch):
    flags, modes = [], []
    real_open, real_builtin = os.open, builtins.open

    def spy_os(path, fl, *a, **k):
        flags.append((str(path), fl))
        return real_open(path, fl, *a, **k)

    def spy_builtin(file, mode="r", *a, **k):
        modes.append(mode)
        return real_builtin(file, mode, *a, **k)

    monkeypatch.setattr(os, "open", spy_os)
    monkeypatch.setattr(builtins, "open", spy_builtin)
    rec = p.build_record(**args(hub))
    p.recheck_sources(rec, root=ROOT, lock_root=hub)
    assert flags and all(fl & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) == 0
                         for _, fl in flags)
    assert all(set(m) <= set("rb") for m in modes)
    seed_reads = [f for f, _ in flags if f.endswith(("candidate.json", "admission.py"))]
    assert len(seed_reads) == 8  # 2 files x (2 reads at build + 2 at recheck)


def test_no_rewrite_normalize_or_reserialize_parameter(hub):
    for kw in ("normalize", "rewrite", "reserialize", "write_back", "canonicalize_seed"):
        with pytest.raises(TypeError):
            p.build_record(**args(hub), **{kw: True})


def test_non_utf8_seed_bytes_are_preserved_opaquely(tmp_path, hub):
    data = b"\xff\xfe\x00not utf-8\x80\n"
    (tmp_path / "seed.bin").write_bytes(data)
    rec = p.build_record(**args(hub, root=tmp_path, seed_paths=["seed.bin"],
                                expected_digests={"seed.bin": "sha256:" + hashlib.sha256(data).hexdigest()}))
    assert rec["sources"][0]["bytes"] == len(data) and rec["sources"][0]["git_blob_sha1"] == p.git_blob_sha1(data)
    assert (tmp_path / "seed.bin").read_bytes() == data


def test_crlf_and_trailing_whitespace_are_not_normalized(tmp_path, hub):
    data = b'{"a": 1}\r\n  \r\n'
    (tmp_path / "s.json").write_bytes(data)
    rec = p.build_record(**args(hub, root=tmp_path, seed_paths=["s.json"],
                                expected_digests={"s.json": "sha256:" + hashlib.sha256(data).hexdigest()}))
    assert rec["sources"][0]["bytes"] == len(data)


# --- negatives: sources -------------------------------------------------------------------
def test_digest_mismatch_is_loud_and_names_the_path(hub):
    bad = dict(EXPECTED, **{CANDIDATE: "sha256:" + "0" * 64})
    err = refused("seed_digest_mismatch", **args(hub, expected_digests=bad))
    assert CANDIDATE in str(err)


def test_malformed_expected_digest(hub):
    refused("expected_digest_invalid", **args(hub, expected_digests=dict(EXPECTED, **{CANDIDATE: "abc"})))


def test_expected_digest_set_must_equal_seed_paths(hub):
    refused("expected_digests_mismatch", **args(hub, expected_digests={CANDIDATE: EXPECTED[CANDIDATE]}))
    refused("expected_digests_mismatch", **args(hub, expected_digests=dict(EXPECTED, extra="sha256:" + "1" * 64)))


def test_lock_digest_mismatch(hub):
    refused("seed_digest_mismatch", **args(hub, expected_lock_digest="sha256:" + "2" * 64))


def test_symlink_file_refused(tmp_path, hub):
    (tmp_path / "real.txt").write_bytes(b"x")
    os.symlink(tmp_path / "real.txt", tmp_path / "link.txt")
    d = "sha256:" + hashlib.sha256(b"x").hexdigest()
    refused("symlink_refused", **args(hub, root=tmp_path, seed_paths=["link.txt"], expected_digests={"link.txt": d}))


def test_symlinked_directory_component_refused(tmp_path, hub):
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "f").write_bytes(b"x")
    os.symlink(tmp_path / "real", tmp_path / "dirlink")
    d = "sha256:" + hashlib.sha256(b"x").hexdigest()
    refused("symlink_refused", **args(hub, root=tmp_path, seed_paths=["dirlink/f"],
                                      expected_digests={"dirlink/f": d}))


def test_symlink_to_outside_root_refused(tmp_path, hub):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    root = tmp_path / "repo"
    root.mkdir()
    os.symlink(outside, root / "x")
    refused("symlink_refused", **args(hub, root=root, seed_paths=["x"],
                                      expected_digests={"x": "sha256:" + hashlib.sha256(b"secret").hexdigest()}))


def test_absolute_path_is_outside_root(tmp_path, hub):
    f = tmp_path / "abs.txt"
    f.write_bytes(b"x")
    d = "sha256:" + hashlib.sha256(b"x").hexdigest()
    refused("outside_root", **args(hub, root=tmp_path, seed_paths=[str(f)], expected_digests={str(f): d}))


@pytest.mark.parametrize("rel", ["../x", "a/../../x", "development/../../x", ".."])
def test_path_traversal_refused(hub, rel):
    refused("path_traversal", **args(hub, seed_paths=[rel], expected_digests={rel: EXPECTED[CANDIDATE]}))


@pytest.mark.parametrize("rel", ["", "a//b", "./a", "a/./b", "a\\b", "a\0b", "a/"])
def test_malformed_paths_refused(hub, rel):
    refused("path_invalid", **args(hub, seed_paths=[rel], expected_digests={rel: EXPECTED[CANDIDATE]}))


def test_missing_file(hub):
    refused("file_missing", **args(hub, seed_paths=["nope.json"], expected_digests={"nope.json": EXPECTED[CANDIDATE]}))


def test_directory_instead_of_file(hub):
    refused("not_a_regular_file", **args(hub, seed_paths=["development"],
                                         expected_digests={"development": EXPECTED[CANDIDATE]}))


def test_file_used_as_directory(hub):
    rel = CANDIDATE + "/x"
    refused("path_invalid", **args(hub, seed_paths=[rel], expected_digests={rel: EXPECTED[CANDIDATE]}))


def test_oversize_refused_before_digest(hub):
    refused("oversize", **args(hub, max_bytes=SEED[CANDIDATE]["bytes"] - 1))


def test_oversize_when_file_grows_past_bound_after_stat(tmp_path, hub, monkeypatch):
    (tmp_path / "g").write_bytes(b"x" * 100)
    real = os.fstat

    class FakeStat:
        st_size = 1

    monkeypatch.setattr(os, "fstat", lambda fd: FakeStat())
    refused("oversize", **args(hub, root=tmp_path, seed_paths=["g"], max_bytes=10,
                               expected_digests={"g": "sha256:" + "0" * 64}))
    monkeypatch.setattr(os, "fstat", real)


@pytest.mark.parametrize("bound", [0, -1, p.HARD_MAX_BYTES + 1, "10", 1.5, True])
def test_bad_max_bytes(hub, bound):
    refused("max_bytes_invalid", **args(hub, max_bytes=bound))


def test_bytes_changed_between_two_reads(tmp_path, hub, monkeypatch):
    f = tmp_path / "s.txt"
    f.write_bytes(b"one")
    real = p._read_once
    calls = []

    def flaky(root, parts, max_bytes):
        data = real(root, parts, max_bytes)
        calls.append(1)
        return data if len(calls) == 1 else data + b"!"

    monkeypatch.setattr(p, "_read_once", flaky)
    refused("changed_between_reads", **args(hub, root=tmp_path, seed_paths=["s.txt"],
                                            expected_digests={"s.txt": "sha256:" + hashlib.sha256(b"one").hexdigest()}))


def test_file_really_modified_between_reads(tmp_path, hub, monkeypatch):
    f = tmp_path / "s.txt"
    f.write_bytes(b"one")
    real_os_read = os.read
    state = {"n": 0}

    def mutate_after_first_pass(fd, n):
        out = real_os_read(fd, n)
        if out == b"" :
            state["n"] += 1
            if state["n"] == 1:
                f.write_bytes(b"two")
        return out

    monkeypatch.setattr(os, "read", mutate_after_first_pass)
    refused("changed_between_reads", **args(hub, root=tmp_path, seed_paths=["s.txt"],
                                            expected_digests={"s.txt": "sha256:" + hashlib.sha256(b"one").hexdigest()}))


def test_duplicate_and_empty_and_excess_seed_paths(hub):
    refused("seed_paths_invalid", **args(hub, seed_paths=[CANDIDATE, CANDIDATE]))
    refused("seed_paths_invalid", **args(hub, seed_paths=[], expected_digests={}))
    many = [f"f{i}" for i in range(p.MAX_FILES + 1)]
    refused("seed_paths_invalid", **args(hub, seed_paths=many, expected_digests={m: EXPECTED[CANDIDATE] for m in many}))
    refused("seed_paths_invalid", **args(hub, seed_paths=(CANDIDATE,)))


def test_root_must_be_a_directory(tmp_path, hub):
    refused("root_invalid", **args(hub, root=tmp_path / "missing"))
    refused("root_invalid", **args(hub, lock_root=ROOT / CANDIDATE))


# --- negatives: lock and identity ---------------------------------------------------------
def test_unknown_lock_shape_is_refused_via_the_3_1_mapping(tmp_path):
    bad = json.dumps({"lock_version": "1.0", "components": {"x": {"repository": "r"}}}).encode()
    (tmp_path / "component-lock.json").write_bytes(bad)
    refused("unknown_lock_shape", **args(tmp_path, expected_lock_digest="sha256:" + hashlib.sha256(bad).hexdigest()))


def test_lock_revision_conflict_via_the_3_1_mapping(tmp_path):
    bad = json.dumps({"lock_version": "1.0", "components": {
        "x": {"repository": "r", "sha": A, "accepted_sha": B}}}).encode()
    (tmp_path / "component-lock.json").write_bytes(bad)
    refused("lock_revision_conflict", **args(tmp_path, expected_lock_digest="sha256:" + hashlib.sha256(bad).hexdigest()))


def test_lock_symlink_refused(tmp_path):
    (tmp_path / "real.json").write_bytes(lock_bytes())
    os.symlink(tmp_path / "real.json", tmp_path / "component-lock.json")
    refused("symlink_refused", **args(tmp_path))


def test_hub_identity_producer_and_scope_validated(hub):
    refused("hub_identity_invalid", **args(hub, hub_sha="short"))
    refused("producer_invalid", **args(hub, producer={"component": "x"}))
    refused("claim_scope_invalid", **args(hub, claim_scope={"claim": "c", "exclusions": []}))
    refused("claim_scope_invalid", **args(hub, claim_scope={"claim": "", "exclusions": ["x"]}))
    refused("predecessor_invalid", **args(hub, predecessor="nope"))


# --- negatives: record checks -------------------------------------------------------------
def test_unknown_member_refused_even_with_valid_digest(hub):
    rec = p.build_record(**args(hub))
    rec["note"] = "x"
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "unknown_or_missing_member"


@pytest.mark.parametrize("member", ["verdict", "pin", "expectation", "pass", "approved_pin", "selected_release",
                                    "decision", "promote", "qualification_result"])
def test_verdict_like_member_refused(hub, member):
    rec = p.build_record(**args(hub))
    rec[member] = "PASS"
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "verdict_like_member"


@pytest.mark.parametrize("member", ["normalized_content", "content", "seed_text", "reserialized", "rewritten_seed"])
def test_content_or_rewrite_members_refused(hub, member):
    rec = p.build_record(**args(hub))
    rec[member] = "{}"
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code in ("unknown_or_missing_member", "verdict_like_member")


def test_unknown_member_inside_file_entry_refused(hub):
    rec = p.build_record(**args(hub))
    rec["sources"][0]["content"] = "x"
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "unknown_or_missing_member"


def test_missing_member_refused(hub):
    rec = p.build_record(**args(hub))
    del rec["sources"]
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(rec)
    assert ctx.value.code == "unknown_or_missing_member"


@pytest.mark.parametrize("key,value", [
    ("status", "PASS"), ("status", "hold"), ("effects", "enabled"), ("release_selection", "advanced"),
    ("intent", "promote"), ("qualification_reference", "run-1"),
    ("operational_trust", {"state": "established", "independent_operator_evidence": None}),
    ("preservation", {"mode": "normalized", "reads_per_file": 2, "seed_files_modified": False,
                      "normalized_or_reserialized": False, "symlinks_followed": False}),
    ("preservation", {"mode": "bytes_by_digest_only", "reads_per_file": 2, "seed_files_modified": True,
                      "normalized_or_reserialized": False, "symlinks_followed": False}),
])
def test_fixed_fields_cannot_change_even_with_valid_digest(hub, key, value):
    rec = p.build_record(**args(hub))
    rec[key] = value
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "fixed_field_changed"


def test_digest_altered_after_issue(hub):
    rec = p.build_record(**args(hub))
    rec["sources"][0]["bytes"] += 1
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(rec)
    assert ctx.value.code == "digest_mismatch"


def test_lock_digest_must_equal_lock_file_digest(hub):
    rec = p.build_record(**args(hub))
    rec["lock_digest"] = "sha256:" + "9" * 64
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "lock_digest_mismatch"


def test_unsorted_or_duplicate_sources_refused(hub):
    rec = p.build_record(**args(hub))
    rec["sources"].reverse()
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "seed_paths_invalid"


def test_recheck_detects_a_changed_seed_and_a_changed_lock(tmp_path, hub):
    data = b"seed v1"
    (tmp_path / "s.txt").write_bytes(data)
    rec = p.build_record(**args(hub, root=tmp_path, seed_paths=["s.txt"],
                                expected_digests={"s.txt": "sha256:" + hashlib.sha256(data).hexdigest()}))
    (tmp_path / "s.txt").write_bytes(b"seed v2")
    with pytest.raises(p.HandoffRefused) as ctx:
        p.recheck_sources(rec, root=tmp_path, lock_root=hub)
    assert ctx.value.code == "seed_digest_mismatch"
    (tmp_path / "s.txt").write_bytes(data)
    (hub / "component-lock.json").write_bytes(lock_bytes() + b"\n")
    with pytest.raises(p.HandoffRefused) as ctx:
        p.recheck_sources(rec, root=tmp_path, lock_root=hub)
    assert ctx.value.code == "seed_digest_mismatch"


def test_failed_build_leaves_seed_untouched(hub):
    before = snapshot()
    refused("seed_digest_mismatch", **args(hub, expected_digests=dict(EXPECTED, **{ADMISSION: "sha256:" + "0" * 64})))
    assert snapshot() == before


def test_historical_o6_q5_constants_unchanged():
    text = (ROOT / ADMISSION).read_text()
    assert 'HUB_SHA = "2a23a2fbb3f5469872170c07a11b57656c6c3d2f"' in text
    assert p.h31.PROFILE == "cognous-lock-driven-evidence-handoff/0"


def test_module_uses_no_subprocess_network_or_write_modes():
    src = SCRIPT.read_text()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith(("#", '"""')))
    for banned in ("import subprocess", "import socket", "urllib", "O_WRONLY", "O_RDWR", "O_CREAT", "write_bytes",
                   "write_text", "shutil", "os.rename", "os.replace", "os.remove", "os.unlink"):
        assert banned not in code, banned
