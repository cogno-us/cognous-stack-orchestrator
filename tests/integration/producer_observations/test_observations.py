"""Developer tests for immutable producer observations. Not independent acceptance cases."""
from __future__ import annotations
import importlib.util
import ast
import json
import os
import re
import threading
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "development/acceptance/producer-observations/observations.py"
spec = importlib.util.spec_from_file_location("producer_observations", SCRIPT)
assert spec and spec.loader
o = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o)

REV = "a" * 40
LOCK = "sha256:" + "b" * 64


def refused(code: str, fn, *args, **kwargs):
    with pytest.raises(o.ObservationRefused) as err:
        fn(*args, **kwargs)
    assert err.value.code == code
    return err.value


def make(seq=1, pred=None, kind="handoff_envelope_produced", **over):
    args = dict(kind=kind, subject="envelope:sha256-1", source_revisions=[REV],
                lock_digest=LOCK if kind in o.LOCK_BOUND_KINDS else None,
                observed_at="2026-10-23T12:00:00Z", sequence=seq, predecessor=pred)
    args.update(over)
    return o.build(**args)


def store(tmp_path, **kw):
    return o.ObservationStore(tmp_path / "obs", max_records=kw.get("n", 8), max_record_bytes=kw.get("b", 4096))


def fill(st, count=3):
    first = make()
    st.append(first)
    prev = first
    for i in range(2, count + 1):
        prev = make(seq=i, pred=prev["digest"], kind="ci_run_observed", subject=f"run:{i}")
        st.append(prev)
    return st


def reseal(obs):
    obs["digest"] = o.observation_digest(obs)
    obs["observation_id"] = o.observation_id_for(obs["digest"])
    return obs


# --- positive -----------------------------------------------------------------------------
def test_build_validate_digest_and_id():
    obs = make()
    assert o.validate(obs) == obs["digest"] == o.observation_digest(obs)
    assert obs["observation_id"] == "obs_" + obs["digest"][7:]
    assert obs["disposition"] == "hold"
    assert o.canonical_bytes(obs) == o.canonical_bytes(json.loads(json.dumps(obs)))
    assert o.canonical_bytes(make()) == o.canonical_bytes(make())  # no hidden clock or randomness


def test_append_load_and_verify_chain(tmp_path):
    st = fill(store(tmp_path), 3)
    digests = st.verify_chain()
    assert len(digests) == 3
    assert st.verify_chain(expected_head=digests[-1], expected_count=3) == digests
    all_ = st.load_all()
    assert [x["sequence"] for x in all_] == [1, 2, 3]
    assert st.load(all_[1]["observation_id"]) == all_[1]
    names = sorted(os.listdir(tmp_path / "obs"))
    assert names == ["000000000001.json", "000000000002.json", "000000000003.json"]
    for name in names:
        assert (tmp_path / "obs" / name).stat().st_mode & 0o777 == 0o444
    assert sorted(os.listdir(tmp_path)) == ["obs"]  # nothing created elsewhere


def test_verify_chain_is_read_only(tmp_path):
    st = fill(store(tmp_path), 2)
    before = {n: (tmp_path / "obs" / n).read_bytes() for n in os.listdir(tmp_path / "obs")}
    mtimes = {n: (tmp_path / "obs" / n).stat().st_mtime_ns for n in before}
    st.verify_chain()
    st.load_all()
    assert before == {n: (tmp_path / "obs" / n).read_bytes() for n in os.listdir(tmp_path / "obs")}
    assert mtimes == {n: (tmp_path / "obs" / n).stat().st_mtime_ns for n in before}


def test_missing_store_is_not_created_by_reads(tmp_path):
    st = store(tmp_path)
    refused("store_missing", st.verify_chain)
    refused("store_missing", st.load, "obs_" + "0" * 64)
    assert not (tmp_path / "obs").exists()


# --- validation refusals --------------------------------------------------------------------
def test_unknown_member():
    obs = make()
    obs["note"] = "x"
    refused("unknown_member", o.validate, obs)


@pytest.mark.parametrize("name", ["verdict", "pin", "expected_digest", "expectation", "grant", "authority",
                                  "authorized", "approved", "accepted", "pass", "status_pass", "decision",
                                  "selected_release", "Verdict"])
def test_forbidden_members(name):
    obs = make()
    obs[name] = "x"
    refused("forbidden_member", o.validate, obs)


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("subject"),
    lambda d: d.update(profile="other/0"),
    lambda d: d.update(schema_version=1),
    lambda d: d.update(schema_version=True),
    lambda d: d.update(canonical_profile="x"),
    lambda d: d.update(subject=" "),
    lambda d: d.update(subject="x" * 300),
    lambda d: d.update(subject="a\nb"),
    lambda d: d.update(source_revisions=[]),
    lambda d: d.update(source_revisions=["A" * 40]),
    lambda d: d.update(source_revisions=["a" * 39]),
    lambda d: d.update(source_revisions=["b" * 40, "a" * 40]),
    lambda d: d.update(source_revisions=["a" * 40, "a" * 40]),
    lambda d: d.update(lock_digest=None),
    lambda d: d.update(lock_digest="sha256:xyz"),
    lambda d: d.update(sequence=0),
    lambda d: d.update(sequence=True),
    lambda d: d.update(sequence=1.0),
    lambda d: d.update(digest="nope"),
])
def test_schema_invalid(mutate):
    obs = make()
    mutate(obs)
    refused("schema_invalid", o.validate, obs)
    refused("schema_invalid", o.validate, [obs])


def test_lock_digest_must_be_null_for_unbound_kind():
    obs = make(kind="ci_run_observed")
    obs["lock_digest"] = LOCK
    refused("schema_invalid", o.validate, obs)


def test_unknown_kind():
    refused("unknown_kind", make, kind="release_approved")


@pytest.mark.parametrize("stamp", ["2026-10-23 12:00:00Z", "2026-10-23T12:00:00+00:00", "2026-10-23T12:00:00",
                                   "2026-10-23T12:00:00.5Z", "2026-02-30T12:00:00Z", "2026-10-23T25:00:00Z", 5])
def test_timestamp_invalid(stamp):
    refused("timestamp_invalid", make, observed_at=stamp)


def test_digest_and_id_mismatch():
    obs = make()
    obs["subject"] = "other"
    refused("digest_mismatch", o.validate, obs)
    obs = make()
    obs["observation_id"] = "obs_" + "0" * 64
    refused("id_mismatch", o.validate, obs)


def test_fixed_disposition_cannot_change():
    obs = make()
    obs["disposition"] = "release"
    refused("fixed_field_changed", o.validate, reseal(obs))


def test_first_observation_with_predecessor_is_chain_break():
    refused("chain_break", make, seq=1, pred=LOCK)


def test_non_canonicalizable_is_refused():
    obs = make()
    obs["subject"] = "\ud800"
    refused("schema_invalid", o.validate, obs)


# --- append and chain -----------------------------------------------------------------------
def test_append_refuses_overwrite_and_chain_breaks(tmp_path):
    st = fill(store(tmp_path), 2)
    head = st.verify_chain()[-1]
    refused("chain_break", st.append, make(seq=3, pred=LOCK, kind="ci_run_observed"))  # wrong predecessor
    refused("chain_break", st.append, make(seq=4, pred=head, kind="ci_run_observed"))  # gap
    refused("chain_break", st.append, make(seq=2, pred=st.verify_chain()[0], kind="ci_run_observed",
                                           subject="fork"))  # fork at an occupied slot
    refused("chain_break", st.append, make())  # replay of the first record
    assert len(st.verify_chain()) == 2


def test_append_refuses_invalid_and_leaves_store_unchanged(tmp_path):
    st = fill(store(tmp_path), 1)
    bad = make(seq=2, pred=st.verify_chain()[0])
    bad["grant"] = 1
    refused("forbidden_member", st.append, bad)
    assert sorted(os.listdir(tmp_path / "obs")) == ["000000000001.json"]


def test_foreign_file_in_next_slot_fails_verification_before_append(tmp_path):
    st = fill(store(tmp_path), 1)
    path = tmp_path / "obs" / "000000000002.json"
    path.write_bytes(b"x")
    path.chmod(0o444)
    nxt = make(seq=2, pred=json.loads(
        (tmp_path / "obs/000000000001.json").read_text())["digest"], kind="ci_run_observed")
    refused("not_strict_json", st.append, nxt)


def test_concurrent_appends_to_the_same_slot_collide(tmp_path):
    st = store(tmp_path, n=8)
    st.append(make())
    pred = st.verify_chain()[0]
    rivals = [make(seq=2, pred=pred, kind="ci_run_observed", subject=f"run:{i}") for i in range(6)]
    barrier = threading.Barrier(len(rivals), timeout=30)
    results: list = []

    def run(obs):
        barrier.wait()
        try:
            st.append(obs)
            results.append("ok")
        except o.ObservationRefused as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=run, args=(r,), daemon=True) for r in rivals]
    [t.start() for t in threads]
    [t.join(timeout=30) for t in threads]
    assert not any(t.is_alive() for t in threads)
    assert len(results) == len(rivals)
    assert results.count("ok") == 1
    assert set(results) - {"ok"} <= {"store_conflict", "chain_break"}
    assert len(st.verify_chain()) == 2
    assert not [n for n in os.listdir(tmp_path / "obs") if n.startswith(".pending-")]


def test_slot_collision_without_precheck(tmp_path, monkeypatch):
    """Force the race window: the chain check passes, then another writer takes the slot."""
    st = store(tmp_path)
    st.append(make())
    pred = st.verify_chain()[0]
    rival = make(seq=2, pred=pred, kind="ci_run_observed", subject="rival")
    mine = make(seq=2, pred=pred, kind="ci_run_observed", subject="mine")
    real_link = os.link

    def racing_link(src, dst):
        st2_final = Path(dst)
        st2_final.write_bytes(o.canonical_bytes(rival))
        return real_link(src, dst)

    monkeypatch.setattr(o.os, "link", racing_link)
    refused("store_conflict", st.append, mine)
    monkeypatch.undo()
    assert not [n for n in os.listdir(tmp_path / "obs") if n.startswith(".pending-")]


# --- tamper, truncation, reorder, mode, bounds, ids ---------------------------------------------
def writable(path: Path, data: bytes):
    path.chmod(0o644)
    path.write_bytes(data)
    path.chmod(0o444)


def test_tamper_after_write_detected(tmp_path):
    st = fill(store(tmp_path), 3)
    p = tmp_path / "obs" / "000000000002.json"
    writable(p, p.read_bytes().replace(b"run:2", b"run:9"))
    refused("digest_mismatch", st.verify_chain)
    refused("digest_mismatch", st.load_all)
    refused("digest_mismatch", st.load, "obs_" + "0" * 64)


def test_tamper_with_resealed_record_breaks_chain(tmp_path):
    st = fill(store(tmp_path), 3)
    p = tmp_path / "obs" / "000000000002.json"
    obs = json.loads(p.read_text())
    obs["subject"] = "run:rewritten"
    writable(p, o.canonical_bytes(reseal(obs)))
    refused("chain_break", st.verify_chain)


def test_truncated_file_detected(tmp_path):
    st = fill(store(tmp_path), 2)
    p = tmp_path / "obs" / "000000000002.json"
    writable(p, p.read_bytes()[:-20])
    refused("not_strict_json", st.verify_chain)


def test_empty_file_detected(tmp_path):
    st = fill(store(tmp_path), 1)
    writable(tmp_path / "obs" / "000000000001.json", b"")
    refused("not_strict_json", st.verify_chain)


def test_duplicate_key_and_float_refused_on_load(tmp_path):
    st = fill(store(tmp_path), 1)
    p = tmp_path / "obs" / "000000000001.json"
    raw = p.read_text()
    writable(p, raw.replace('"kind":', '"kind":"x","kind":', 1).encode())
    refused("not_strict_json", st.verify_chain)
    writable(p, raw.replace('"sequence":1', '"sequence":1.0').encode())
    refused("not_strict_json", st.verify_chain)
    writable(p, raw.replace('"sequence":1', '"sequence":NaN').encode())
    refused("not_strict_json", st.verify_chain)
    writable(p, b"\xff\xfe")
    refused("not_strict_json", st.verify_chain)


def test_non_canonical_bytes_detected(tmp_path):
    st = fill(store(tmp_path), 1)
    p = tmp_path / "obs" / "000000000001.json"
    writable(p, json.dumps(json.loads(p.read_text()), indent=2).encode())
    refused("store_integrity", st.verify_chain)


def test_deletion_and_reordering_detected(tmp_path):
    st = fill(store(tmp_path), 4)
    d = tmp_path / "obs"
    head = st.verify_chain()[-1]
    # tail deletion is only visible against a held head or count
    (d / "000000000004.json").unlink()
    assert len(st.verify_chain()) == 3
    refused("chain_break", st.verify_chain, expected_head=head)
    refused("chain_break", st.verify_chain, expected_count=4)
    # middle deletion is visible on its own
    (d / "000000000002.json").unlink()
    refused("chain_break", st.verify_chain)


def test_reordered_files_detected(tmp_path):
    st = fill(store(tmp_path), 3)
    d = tmp_path / "obs"
    os.rename(d / "000000000002.json", d / "tmp.swap")
    os.rename(d / "000000000003.json", d / "000000000002.json")
    os.rename(d / "tmp.swap", d / "000000000003.json")
    refused("chain_break", st.verify_chain)


def test_writable_mode_detected_on_load(tmp_path):
    st = fill(store(tmp_path), 2)
    (tmp_path / "obs" / "000000000001.json").chmod(0o644)
    refused("store_mode_writable", st.verify_chain)
    refused("store_mode_writable", st.load_all)


def test_oversize_file_and_bounds(tmp_path):
    st = fill(store(tmp_path, b=4096), 1)
    small = o.ObservationStore(tmp_path / "obs", max_records=8, max_record_bytes=100)
    refused("store_bound_exceeded", small.verify_chain)
    tiny = o.ObservationStore(tmp_path / "other", max_records=8, max_record_bytes=100)
    refused("store_bound_exceeded", tiny.append, make())
    assert not (tmp_path / "other").exists()
    capped = o.ObservationStore(tmp_path / "cap", max_records=2, max_record_bytes=4096)
    fill(capped, 2)
    refused("store_bound_exceeded", capped.append, make(seq=3, pred=capped.verify_chain()[-1],
                                                        kind="ci_run_observed"))
    fewer = o.ObservationStore(tmp_path / "cap", max_records=1, max_record_bytes=4096)
    refused("store_bound_exceeded", fewer.verify_chain)
    with pytest.raises(ValueError):
        o.ObservationStore(tmp_path / "x", max_records=0, max_record_bytes=10)
    with pytest.raises(ValueError):
        o.ObservationStore(tmp_path / "x", max_records=1, max_record_bytes=True)


@pytest.mark.parametrize("bad", ["../escape", "obs_../../etc/passwd", "obs_" + "A" * 64, "obs_" + "a" * 63,
                                 "/etc/passwd", "obs_" + "a" * 64 + "/..", "", None, 7])
def test_path_traversal_ids_refused(tmp_path, bad):
    st = fill(store(tmp_path), 1)
    refused("unsafe_id", st.load, bad)


def test_unknown_missing_id_and_foreign_entries(tmp_path):
    st = fill(store(tmp_path), 1)
    refused("store_missing", st.load, "obs_" + "0" * 64)
    (tmp_path / "obs" / "notes.txt").write_text("x")
    refused("store_integrity", st.verify_chain)


def test_symlink_and_directory_entries_refused(tmp_path):
    st = fill(store(tmp_path), 1)
    d = tmp_path / "obs"
    real = tmp_path / "elsewhere.json"
    real.write_bytes((d / "000000000001.json").read_bytes())
    real.chmod(0o444)
    (d / "000000000001.json").unlink()
    os.symlink(real, d / "000000000001.json")
    refused("store_integrity", st.verify_chain)
    (d / "000000000001.json").unlink()
    os.mkdir(d / "000000000001.json")
    refused("store_integrity", st.verify_chain)


def test_stray_pending_file_is_not_a_record(tmp_path):
    st = fill(store(tmp_path), 1)
    (tmp_path / "obs" / ".pending-deadbeef").write_text("partial")
    assert len(st.verify_chain()) == 1


# --- review findings: held head, ascii-only, recursion, store directory, subject ------------------
def test_expected_head_and_count_detect_tail_replacement_and_alternative_chain(tmp_path):
    st = fill(store(tmp_path), 3)
    held = st.verify_chain()
    d = tmp_path / "obs"
    # replace the newest record by a different, valid one: undetectable without a held head
    (d / "000000000003.json").chmod(0o644)
    (d / "000000000003.json").unlink()
    st.append(make(seq=3, pred=held[1], kind="ci_run_observed", subject="run:replaced"))
    assert len(st.verify_chain()) == 3  # LIMIT: accepted on its own
    refused("chain_break", st.verify_chain, expected_head=held[-1])
    assert st.verify_chain(expected_count=3)  # count alone does not see a replacement
    # swap in a whole alternative valid chain
    alt = o.ObservationStore(tmp_path / "alt", max_records=8, max_record_bytes=4096)
    prev = make(subject="envelope:other")
    alt.append(prev)
    for i in (2, 3):
        prev = make(seq=i, pred=prev["digest"], kind="ci_run_observed", subject=f"alt:{i}")
        alt.append(prev)
    assert len(alt.verify_chain()) == 3  # LIMIT: valid on its own
    refused("chain_break", alt.verify_chain, expected_head=held[-1])
    # whole store removed, then a fresh chain
    refused("chain_break", alt.verify_chain, expected_count=4)


def test_append_checks_held_head_and_count(tmp_path):
    st = fill(store(tmp_path), 2)
    head = st.verify_chain()[-1]
    nxt = make(seq=3, pred=head, kind="ci_run_observed", subject="run:3")
    refused("chain_break", st.append, nxt, expected_head=LOCK)
    refused("chain_break", st.append, nxt, expected_count=5)
    assert len(st.verify_chain()) == 2
    st.append(nxt, expected_head=head, expected_count=2)
    assert len(st.verify_chain()) == 3


def test_tail_removal_and_whole_store_removal_documented_limits(tmp_path):
    st = fill(store(tmp_path), 3)
    d = tmp_path / "obs"
    (d / "000000000003.json").unlink()
    assert len(st.verify_chain()) == 2  # LIMIT: tail removal invisible without a held head/count
    for n in os.listdir(d):
        (d / n).unlink()
    assert st.verify_chain() == []  # LIMIT: an empty store is a valid empty chain
    refused("chain_break", st.verify_chain, expected_count=3)


def test_arabic_indic_digits_refused_in_file_name_and_timestamp(tmp_path):
    ar = "\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669\u0660\u0660\u0661"
    assert not o.FILE_NAME.fullmatch(ar + ".json")
    assert o.FILE_NAME.fullmatch("000000000001.json")
    st = fill(store(tmp_path), 1)
    (tmp_path / "obs" / (ar + ".json")).write_text("x")
    refused("store_integrity", st.verify_chain)
    refused("timestamp_invalid", make, observed_at="\u0662\u0660\u0662\u0666-10-23T12:00:00Z")
    refused("timestamp_invalid", make, observed_at="2026-10-23T12:00:00Z\n")


def test_deeply_nested_file_is_not_strict_json(tmp_path):
    st = fill(store(tmp_path, b=4096), 1)
    p = tmp_path / "obs" / "000000000001.json"
    writable(p, b"[" * 4000 + b"]" * 90)
    assert p.stat().st_size <= 4096
    refused("not_strict_json", st.verify_chain)


def test_recursion_error_maps_to_not_strict_json_version_independent(tmp_path, monkeypatch):
    st = fill(store(tmp_path), 1)

    def boom(data):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(o, "loads_strict", boom)
    refused("not_strict_json", st.verify_chain)


def test_refused_append_on_missing_dir_creates_nothing(tmp_path):
    st = store(tmp_path)
    first = make()
    refused("chain_break", st.append, first, expected_count=1)
    refused("chain_break", st.append, first, expected_head=LOCK)
    refused("unknown_member", st.append, {"x": 1})
    assert not (tmp_path / "obs").exists()
    st.append(first, expected_count=0)  # 0 asserts an empty (here: absent) store
    assert len(st.verify_chain()) == 1


def test_held_value_types_and_zero_semantics(tmp_path):
    st = fill(store(tmp_path), 1)
    for bad in (True, False, 1.0, "1", -1):
        with pytest.raises(ValueError):
            st.verify_chain(expected_count=bad)
    with pytest.raises(ValueError):
        st.verify_chain(expected_head=5)
    with pytest.raises(ValueError):
        st.append(make(seq=2, pred=st.verify_chain()[0], kind="ci_run_observed"), expected_count=True)
    refused("chain_break", st.verify_chain, expected_count=0)
    assert st.verify_chain(expected_head=None)  # None means unchecked
    empty = store(tmp_path / "e")
    (tmp_path / "e").mkdir()
    (tmp_path / "e" / "obs").mkdir()
    assert empty.verify_chain(expected_count=0) == []
    assert empty.verify_chain(expected_head=None) == []


def test_bom_trailing_bytes_are_refused(tmp_path):
    st = fill(store(tmp_path), 1)
    p = tmp_path / "obs" / "000000000001.json"
    raw = p.read_bytes()
    writable(p, b"\xef\xbb\xbf" + raw)
    refused("not_strict_json", st.verify_chain)
    writable(p, raw + b"\n")
    refused("store_integrity", st.verify_chain)  # valid JSON, but not the canonical bytes
    writable(p, raw + b"x")
    refused("not_strict_json", st.verify_chain)
    writable(p, raw)
    assert len(st.verify_chain()) == 1


def test_dangling_symlink_store_directory(tmp_path):
    os.symlink(tmp_path / "nowhere", tmp_path / "obs")
    st = store(tmp_path)
    refused("store_integrity", st.append, make())
    refused("store_integrity", st.verify_chain)
    assert not (tmp_path / "nowhere").exists()


def test_symlink_to_real_directory_is_refused(tmp_path):
    (tmp_path / "real").mkdir()
    os.symlink(tmp_path / "real", tmp_path / "obs")
    refused("store_integrity", store(tmp_path).append, make())
    assert os.listdir(tmp_path / "real") == []


def test_missing_parent_is_store_missing(tmp_path):
    st = o.ObservationStore(tmp_path / "no" / "obs", max_records=2, max_record_bytes=4096)
    refused("store_missing", st.append, make())


def test_link_unsupported_is_typed_refusal_and_leaves_nothing(tmp_path, monkeypatch):
    st = store(tmp_path)
    st.append(make())
    nxt = make(seq=2, pred=st.verify_chain()[0], kind="ci_run_observed", subject="x")

    def no_link(src, dst):
        raise PermissionError("hard links not supported")

    monkeypatch.setattr(o.os, "link", no_link)
    refused("store_integrity", st.append, nxt)
    monkeypatch.undo()
    assert sorted(os.listdir(tmp_path / "obs")) == ["000000000001.json"]


def test_directory_fsync_is_attempted_after_publish(tmp_path, monkeypatch):
    synced = []
    real = os.fsync
    monkeypatch.setattr(o.os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
    store(tmp_path).append(make())
    assert len(synced) == 2  # file, then directory


@pytest.mark.parametrize("subject", ["a\x7fb", "a\u202eb", "a\u200bb", "\ufeffa", "a\u2028b", "a\x85b",
                                     "e\u0301", "a\u2066b"])
def test_subject_rejects_invisible_and_non_nfc(subject):
    refused("schema_invalid", make, subject=subject)


def test_subject_nfc_text_is_accepted_and_opaque():
    assert make(subject="caf\u00e9:run/7")["subject"] == "caf\u00e9:run/7"


# --- boundaries -------------------------------------------------------------------------------
def _module_tree():
    return ast.parse(SCRIPT.read_text())


def test_module_imports_and_calls_are_offline_and_clockless():
    tree = _module_tree()
    allowed = {"__future__", "copy", "datetime", "hashlib", "json", "os", "re", "secrets", "unicodedata", "pathlib"}
    banned_calls = {"system", "popen", "Popen", "run", "call", "check_output", "now", "utcnow", "today",
                    "time", "monotonic", "urlopen", "socket", "connect", "eval", "exec", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert {a.name.split(".")[0] for a in node.names} <= allowed
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] in allowed
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            assert name not in banned_calls, name
    # the only datetime use is strptime parsing of the caller's text
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
             and isinstance(n.value, ast.Attribute) and n.value.attr == "datetime"}
    assert attrs <= {"strptime"}


def _refused_literals():
    out = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_refuse":
            assert isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
            out.add(node.args[0].value)
    return out


def test_refusal_codes_match_static_refuse_calls():
    assert all(re.fullmatch(r"[a-z_]+", c) for c in o.CODES)
    assert _refused_literals() == set(o.CODES)


def _t_schema_invalid(tp): o.validate([])
def _t_unknown_member(tp): d = make(); d["note"] = "x"; o.validate(d)
def _t_forbidden_member(tp): d = make(); d["verdict"] = "x"; o.validate(d)
def _t_unknown_kind(tp): make(kind="release_approved")
def _t_timestamp_invalid(tp): make(observed_at="nope")
def _t_digest_mismatch(tp): d = make(); d["subject"] = "other"; o.validate(d)
def _t_id_mismatch(tp): d = make(); d["observation_id"] = "obs_" + "0" * 64; o.validate(d)
def _t_fixed_field_changed(tp): d = make(); d["disposition"] = "x"; o.validate(reseal(d))
def _t_chain_break(tp): make(seq=1, pred=LOCK)
def _t_unsafe_id(tp): store(tp).load("../x")
def _t_store_conflict(tp):
    st = store(tp)
    st.append(make())
    mine = make(seq=2, pred=st.verify_chain()[0], kind="ci_run_observed")
    real = os.link
    def racing(src, dst):
        Path(dst).write_bytes(b"x")
        return real(src, dst)
    o.os.link = racing
    try:
        st.append(mine)
    finally:
        o.os.link = real
def _t_store_bound_exceeded(tp): o.ObservationStore(tp / "o", max_records=1, max_record_bytes=10).append(make())
def _t_store_integrity(tp): fill(store(tp), 1); (tp / "obs" / "notes.txt").write_text("x"); store(tp).verify_chain()
def _t_not_strict_json(tp): fill(store(tp), 1); writable(tp / "obs" / "000000000001.json", b""); store(tp).verify_chain()
def _t_store_mode_writable(tp): fill(store(tp), 1); (tp / "obs" / "000000000001.json").chmod(0o644); store(tp).verify_chain()
def _t_store_missing(tp): store(tp).verify_chain()


TRIGGERS = {
    "schema_invalid": _t_schema_invalid, "unknown_member": _t_unknown_member,
    "forbidden_member": _t_forbidden_member, "unknown_kind": _t_unknown_kind,
    "timestamp_invalid": _t_timestamp_invalid, "digest_mismatch": _t_digest_mismatch,
    "id_mismatch": _t_id_mismatch, "fixed_field_changed": _t_fixed_field_changed,
    "chain_break": _t_chain_break, "unsafe_id": _t_unsafe_id, "store_conflict": _t_store_conflict,
    "store_bound_exceeded": _t_store_bound_exceeded, "store_integrity": _t_store_integrity,
    "not_strict_json": _t_not_strict_json, "store_mode_writable": _t_store_mode_writable,
    "store_missing": _t_store_missing,
}


def test_trigger_table_covers_exactly_the_codes():
    assert set(TRIGGERS) == set(o.CODES)


@pytest.mark.parametrize("code", sorted(o.CODES))
def test_refusal_code_trigger(code, tmp_path):
    refused(code, TRIGGERS[code], tmp_path)
