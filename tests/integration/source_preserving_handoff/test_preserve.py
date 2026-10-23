"""Developer tests for the source-preserving producer handoff. Not independent acceptance cases."""
from __future__ import annotations
import ast
import builtins
import copy
import hashlib
import importlib.util
import json
import os
import signal
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
        def __init__(self, st):
            self._st = st
            self.st_size = 1

        def __getattr__(self, name):
            return getattr(self._st, name)

    monkeypatch.setattr(os, "fstat", lambda fd: FakeStat(real(fd)))
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
                      "normalized_or_reserialized": False, "symlinks_followed": False,
                      "root_ancestors_resolved_by_os": True}),
    ("preservation", {"mode": "bytes_by_digest_only", "reads_per_file": 2, "seed_files_modified": True,
                      "normalized_or_reserialized": False, "symlinks_followed": False,
                      "root_ancestors_resolved_by_os": True}),
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


def test_platform_capability_probe_is_true_on_this_interpreter():
    assert p._DIRFD_OK is True
    p._need_platform()  # must not refuse


def test_record_scopes_symlink_statement_to_below_the_root(hub):
    pres = p.build_record(**args(hub))["preservation"]
    assert pres["symlinks_followed"] is False and pres["root_ancestors_resolved_by_os"] is True


def test_root_ancestors_flag_cannot_change(hub):
    rec = p.build_record(**args(hub))
    rec["preservation"]["root_ancestors_resolved_by_os"] = False
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "fixed_field_changed"


def test_module_static_allow_list_of_imports_and_os_calls():
    """Static allow-list check of imports, names and `os` attributes. It is a tripwire, not proof of
    purity; the runtime no-write-flag test above (every os.open flag, every builtin open mode) backs it."""
    tree = ast.parse(SCRIPT.read_text())
    allowed_modules = {"__future__", "errno", "hashlib", "importlib", "os", "re", "stat", "pathlib"}
    allowed_from = {("__future__", "annotations"), ("pathlib", "Path")}
    allowed_os = {"O_RDONLY", "O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK", "O_CLOEXEC", "PathLike", "close",
                  "fspath", "fstat", "getcwd", "lstat", "open", "path", "read", "stat", "supports_dir_fd"}
    allowed_os_path = {"isabs", "join"}
    allowed_importlib = {"util"}
    allowed_importlib_util = {"spec_from_file_location", "module_from_spec"}
    banned_names = {"__import__", "ctypes", "getattr", "setattr", "hasattr", "delattr", "eval", "exec", "compile",
                    "open", "globals", "locals", "vars", "subprocess", "socket", "urllib", "shutil", "tempfile",
                    "O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND", "O_EXCL", "utime", "fork",
                    "touch", "write_bytes", "write_text", "unlink", "rename", "replace", "mkdir", "chmod"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert {a.name.split(".")[0] for a in node.names} <= allowed_modules, ast.dump(node)
            assert all(a.name in allowed_modules | {"importlib.util"} for a in node.names), ast.dump(node)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and all((node.module, a.name) in allowed_from for a in node.names), ast.dump(node)
        elif isinstance(node, ast.Name):
            assert node.id not in banned_names, node.id
        elif isinstance(node, ast.Attribute):
            owner = node.value.id if isinstance(node.value, ast.Name) else None
            assert node.attr not in banned_names or (owner, node.attr) in {("os", "open"), ("re", "compile")}, \
                node.attr
            base = node.value
            if isinstance(base, ast.Name) and base.id == "os":
                assert node.attr in allowed_os, f"os.{node.attr}"
            if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id == "os" \
                    and base.attr == "path":
                assert node.attr in allowed_os_path, f"os.path.{node.attr}"
            if isinstance(base, ast.Name) and base.id == "importlib":
                assert node.attr in allowed_importlib, node.attr
            if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) \
                    and base.value.id == "importlib" and base.attr == "util":
                assert node.attr in allowed_importlib_util, node.attr
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "os" \
                    and fn.attr == "open":
                # the flag argument must be one of the two module-level read-only constants
                assert len(node.args) >= 2 and isinstance(node.args[1], (ast.Name, ast.IfExp)), ast.dump(node)
                names = {n.id for n in ast.walk(node.args[1]) if isinstance(n, ast.Name)}
                assert names <= {"_DIR_FLAGS", "_FILE_FLAGS", "want_dir"}, names
    # the two flag constants themselves are read-only combinations
    assigns = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
               if isinstance(t, ast.Name) and t.id in ("_DIR_FLAGS", "_FILE_FLAGS")}
    assert set(assigns) == {"_DIR_FLAGS", "_FILE_FLAGS"}
    for value in assigns.values():
        attrs = {n.attr for n in ast.walk(value) if isinstance(n, ast.Attribute)}
        assert attrs <= {"O_RDONLY", "O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK", "O_CLOEXEC"}, attrs


# --- safe reader: races, special files, hardlinks, root --------------------------------------
class Timeout(Exception):
    pass


@pytest.fixture
def guard():
    def boom(*_):
        raise Timeout("read hung")
    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(5)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def swap_after_lstat(monkeypatch, name, action):
    """Run `action` once, right after the first lstat of entry `name` (the check-to-open window)."""
    real, done = os.lstat, []

    def wrapped(path, *a, **k):
        out = real(path, *a, **k)
        if path == name and k.get("dir_fd") is not None and not done:
            done.append(1)
            action()
        return out

    monkeypatch.setattr(os, "lstat", wrapped)
    return done


def test_intermediate_directory_swapped_for_symlink_is_refused(tmp_path, hub, monkeypatch):
    root = tmp_path / "r"
    (root / "d").mkdir(parents=True)
    (root / "d" / "f").write_bytes(b"x")
    other = tmp_path / "other"
    other.mkdir()
    (other / "f").write_bytes(b"x")

    def swap():
        os.rename(root / "d", root / "d_old")
        os.symlink(other, root / "d")

    done = swap_after_lstat(monkeypatch, "d", swap)
    refused("symlink_refused", **args(hub, root=root, seed_paths=["d/f"], expected_digests={"d/f": digest_of(b"x")}))
    assert done


def test_intermediate_directory_swapped_for_other_directory_is_refused(tmp_path, hub, monkeypatch):
    root = tmp_path / "r"
    (root / "d").mkdir(parents=True)
    (root / "d" / "f").write_bytes(b"x")

    def swap():
        os.rename(root / "d", root / "d_old")
        (root / "d").mkdir()
        (root / "d" / "f").write_bytes(b"x")

    done = swap_after_lstat(monkeypatch, "d", swap)
    refused("changed_between_reads", **args(hub, root=root, seed_paths=["d/f"],
                                            expected_digests={"d/f": digest_of(b"x")}))
    assert done


def test_file_swapped_for_symlink_after_lstat_is_refused(tmp_path, hub, monkeypatch):
    (tmp_path / "f").write_bytes(b"x")
    (tmp_path / "t").write_bytes(b"x")

    def swap():
        os.unlink(tmp_path / "f")
        os.symlink(tmp_path / "t", tmp_path / "f")

    swap_after_lstat(monkeypatch, "f", swap)
    refused("symlink_refused", **args(hub, root=tmp_path, seed_paths=["f"], expected_digests={"f": digest_of(b"x")}))


def test_file_swapped_for_fifo_after_lstat_does_not_hang(tmp_path, hub, monkeypatch, guard):
    (tmp_path / "f").write_bytes(b"x")

    def swap():
        os.unlink(tmp_path / "f")
        os.mkfifo(tmp_path / "f")

    done = swap_after_lstat(monkeypatch, "f", swap)
    refused("not_a_regular_file", **args(hub, root=tmp_path, seed_paths=["f"],
                                         expected_digests={"f": digest_of(b"x")}))
    assert done


def test_fifo_present_from_the_start_is_refused_without_opening(tmp_path, hub, guard):
    os.mkfifo(tmp_path / "f")
    refused("not_a_regular_file", **args(hub, root=tmp_path, seed_paths=["f"],
                                         expected_digests={"f": digest_of(b"x")}))


def test_hardlink_to_a_regular_file_is_accepted(tmp_path, hub):
    (tmp_path / "orig").write_bytes(b"same bytes")
    os.link(tmp_path / "orig", tmp_path / "hard")
    rec = p.build_record(**args(hub, root=tmp_path, seed_paths=["hard"],
                                expected_digests={"hard": digest_of(b"same bytes")}))
    assert rec["sources"][0]["bytes"] == 10 and rec["preservation"]["symlinks_followed"] is False


def test_symlinked_root_is_refused(tmp_path, hub):
    real = tmp_path / "real"
    real.mkdir()
    (real / "f").write_bytes(b"x")
    os.symlink(real, tmp_path / "rootlink")
    kw = dict(seed_paths=["f"], expected_digests={"f": digest_of(b"x")})
    refused("root_symlink_refused", **args(hub, root=tmp_path / "rootlink", **kw))
    refused("root_symlink_refused", **args(hub, root=str(tmp_path / "rootlink") + "/", **kw))
    os.symlink(hub, tmp_path / "locklink")
    refused("root_symlink_refused", **args(hub, root=real, lock_root=tmp_path / "locklink", **kw))
    rec = p.build_record(**args(hub, root=real, **kw))
    with pytest.raises(p.HandoffRefused) as ctx:
        p.recheck_sources(rec, root=tmp_path / "rootlink", lock_root=hub)
    assert ctx.value.code == "root_symlink_refused"


def test_relative_root_is_accepted(tmp_path, hub, monkeypatch):
    (tmp_path / "f").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)
    rec = p.build_record(**args(hub, root=".", seed_paths=["f"], expected_digests={"f": digest_of(b"x")}))
    assert rec["sources"][0]["path"] == "f"


# --- record checks: tuple and strict types ----------------------------------------------------
def test_tuple_tamper_with_stale_digest_is_refused(hub):
    rec = p.build_record(**args(hub))
    rec["tuple"]["bitrep"]["sha"] = D
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "tuple_digest_mismatch"


def test_consistent_tuple_forgery_passes_offline_but_not_recheck(hub):
    rec = p.build_record(**args(hub))
    rec["tuple"]["bitrep"]["sha"] = D
    rec["tuple_digest"] = p.h31.tuple_digest(rec["tuple"])
    redigest(rec)
    assert p.check_record(rec)["status"] == "HOLD"
    with pytest.raises(p.HandoffRefused) as ctx:
        p.recheck_sources(rec, root=ROOT, lock_root=hub)
    assert ctx.value.code == "tuple_differs_from_lock"


@pytest.mark.parametrize("mutate", [
    lambda t: t.clear(),
    lambda t: t["bitrep"].update(extra="x"),
    lambda t: t["bitrep"].pop("interfaces"),
    lambda t: t["bitrep"].update(sha="nothex"),
    lambda t: t["bitrep"].update(repository=""),
    lambda t: t["bitrep"].update(interfaces="Decision 1.0"),
    lambda t: t["bitrep"].update(interfaces=[1]),
    lambda t: t.update(bad="x"),
])
def test_tuple_shape_is_validated(hub, mutate):
    rec = p.build_record(**args(hub))
    mutate(rec["tuple"])
    rec["tuple_digest"] = p.h31.tuple_digest(rec["tuple"]) if rec["tuple"] and all(
        type(v) is dict for v in rec["tuple"].values()) else rec["tuple_digest"]
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "tuple_invalid"


def test_tuple_not_an_object_is_refused(hub):
    rec = p.build_record(**args(hub))
    rec["tuple"] = ["x"]
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "tuple_invalid"


@pytest.mark.parametrize("key,value", [
    ("preservation", {"mode": "bytes_by_digest_only", "reads_per_file": 2, "seed_files_modified": 0,
                      "normalized_or_reserialized": False, "symlinks_followed": False,
                      "root_ancestors_resolved_by_os": True}),
    ("preservation", {"mode": "bytes_by_digest_only", "reads_per_file": 2, "seed_files_modified": False,
                      "normalized_or_reserialized": 0, "symlinks_followed": False,
                      "root_ancestors_resolved_by_os": True}),
    ("preservation", {"mode": "bytes_by_digest_only", "reads_per_file": 2, "seed_files_modified": False,
                      "normalized_or_reserialized": False, "symlinks_followed": 0,
                      "root_ancestors_resolved_by_os": True}),
    ("preservation", {"mode": "bytes_by_digest_only", "reads_per_file": True, "seed_files_modified": False,
                      "normalized_or_reserialized": False, "symlinks_followed": False,
                      "root_ancestors_resolved_by_os": True}),
    ("qualification_reference", 0),
    ("qualification_reference", False),
])
def test_fixed_fields_are_type_exact(hub, key, value):
    rec = p.build_record(**args(hub))
    rec[key] = value
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "fixed_field_changed"


def test_float_in_fixed_field_is_refused_as_changed(hub):
    rec = p.build_record(**args(hub))
    rec["preservation"]["reads_per_file"] = 2.0  # cannot be digested; the fixed-field check comes first
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(rec)
    assert ctx.value.code == "fixed_field_changed"


def test_schema_version_false_is_refused(hub):
    rec = p.build_record(**args(hub))
    rec["schema_version"] = False
    with pytest.raises(p.HandoffRefused) as ctx:
        p.check_record(redigest(rec))
    assert ctx.value.code == "profile_mismatch"


# --- build-time inputs never raise TypeError -------------------------------------------------
@pytest.mark.parametrize("over,code", [
    ({"producer": None}, "producer_invalid"),
    ({"producer": "x"}, "producer_invalid"),
    ({"producer": {"component": ["x"], "revision": "f" * 40}}, "producer_invalid"),
    ({"seed_paths": [1, CANDIDATE]}, "seed_paths_invalid"),
    ({"seed_paths": [[CANDIDATE]]}, "seed_paths_invalid"),
    ({"seed_paths": [{"a": 1}]}, "seed_paths_invalid"),
    ({"seed_paths": [None]}, "seed_paths_invalid"),
    ({"claim_scope": {"claim": "c", "exclusions": "no verdict"}}, "claim_scope_invalid"),
    ({"claim_scope": {"claim": "c", "exclusions": [["x"]]}}, "claim_scope_invalid"),
    ({"claim_scope": None}, "claim_scope_invalid"),
    ({"claim_scope": "x"}, "claim_scope_invalid"),
    ({"claim_scope": {"claim": ["c"], "exclusions": ["x"]}}, "claim_scope_invalid"),
    ({"hub_sha": 5}, "hub_identity_invalid"),
    ({"hub_sha": None}, "hub_identity_invalid"),
    ({"hub_repository": None}, "hub_identity_invalid"),
    ({"predecessor": 5}, "predecessor_invalid"),
    ({"lock_path": None}, "path_invalid"),
    ({"expected_lock_digest": None}, "expected_digest_invalid"),
    ({"expected_digests": None}, "expected_digests_mismatch"),
    ({"root": None}, "root_invalid"),
    ({"lock_root": 5}, "root_invalid"),
])
def test_bad_build_inputs_are_refused_not_typeerror(hub, over, code):
    refused(code, **args(hub, **over))


def test_unhashable_expected_digest_value_is_refused(hub):
    refused("expected_digest_invalid", **args(hub, expected_digests={CANDIDATE: ["x"], ADMISSION: EXPECTED[ADMISSION]}))
