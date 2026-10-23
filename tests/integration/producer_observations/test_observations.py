"""Developer tests for immutable producer observations. Not independent acceptance cases."""
from __future__ import annotations
import importlib.util
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
SEEN: set = set()


def refused(code: str, fn, *args, **kwargs):
    with pytest.raises(o.ObservationRefused) as err:
        fn(*args, **kwargs)
    assert err.value.code == code
    SEEN.add(code)
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
    barrier = threading.Barrier(len(rivals))
    results: list = []

    def run(obs):
        barrier.wait()
        try:
            st.append(obs)
            results.append("ok")
        except o.ObservationRefused as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=run, args=(r,)) for r in rivals]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1
    assert set(results) - {"ok"} <= {"store_conflict", "chain_break"}
    assert len(st.verify_chain()) == 2
    assert not [n for n in os.listdir(tmp_path / "obs") if n.startswith(".pending-")]
    if "store_conflict" in results:
        SEEN.add("store_conflict")


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


# --- boundaries -------------------------------------------------------------------------------
def test_module_has_no_network_subprocess_or_clock():
    src = SCRIPT.read_text()
    for banned in ("import subprocess", "import socket", "urllib", "http.client", "requests", "datetime.now",
                   "utcnow", "time.time", "os.system", "import time"):
        assert banned not in src, banned


def test_refusal_codes_are_a_closed_set_and_all_exercised():
    assert all(re.fullmatch(r"[a-z_]+", c) for c in o.CODES)
    # runs after the other tests in file order; every declared code must have been triggered
    assert SEEN == set(o.CODES), sorted(set(o.CODES) - SEEN)
