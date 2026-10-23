"""Tests for the review findings: lock temporaries, deep JSON, dead states, ambiguity, lock races. Developer tests."""
import hashlib
import json
import os
import threading

import pytest

from orchestration import workflow_store as ws
from orchestration.workflow_store import canonical, store as store_mod

TS = '2026-01-01T00:00:00Z'


def rec(kind='workflow.proposed', body=None):
    return {'kind': kind, 'timestamp': TS, 'body': {} if body is None else body}


@pytest.fixture
def store(tmp_path):
    root = tmp_path / 'store'
    root.mkdir()
    return ws.Store(root)


def refusal(code, fn, *a, **kw):
    with pytest.raises(ws.StoreRefusal) as info:
        fn(*a, **kw)
    assert info.value.code == code, str(info.value)
    return info.value


def seeded(store, n=2, hold=True, wid='wf1', owner='w1'):
    store.create_workflow(wid)
    store.acquire(wid, owner=owner, timestamp=TS)
    for i in range(n):
        store.append(wid, rec(body={'i': i}), owner=owner)
    if not hold:
        store.release(wid, owner=owner)
    return store.workflow_dir(wid)


def names(path):
    return sorted(n for n in os.listdir(path) if n != '.locks')


class Crash(BaseException):
    pass


def force_write(path, data):
    if os.path.exists(path):
        os.chmod(path, 0o644)
    with open(path, 'wb') as f:
        f.write(data)


# --- 1. lock temporaries and concurrent readers -----------------------------------------

def test_contenders_never_poison_the_holder(store):
    path = seeded(store, n=0)
    stop = threading.Event()
    seen = []

    def contender(i):
        while not stop.is_set():
            try:
                store.acquire('wf1', owner='c%d' % i, timestamp=TS)
                seen.append('won')  # must never happen while w1 holds the lock
            except ws.StoreRefusal as exc:
                seen.append(exc.code)

    threads = [threading.Thread(target=contender, args=(i,)) for i in range(4)]
    [t.start() for t in threads]
    try:
        for i in range(60):
            store.append('wf1', rec(body={'i': i}), owner='w1')
    finally:
        stop.set()
        [t.join() for t in threads]
    assert set(seen) == {'lock_held'}
    assert store.load('wf1').head_sequence == 60
    assert store.read_lock('wf1')['owner'] == 'w1'
    assert not [n for n in os.listdir(os.path.join(path, '.locks')) if n != 'mutex']


def test_lock_directory_content_is_never_a_leftover_and_never_quarantined(store):
    path = seeded(store, n=1)
    force_write(os.path.join(path, '.locks', 'orphan.1.1'), b'x')
    assert store.load('wf1').head_sequence == 1
    assert store.inspect('wf1') == []
    force_write(os.path.join(path, '000002.json'), b'{"torn')
    store.recover('wf1', owner='w1', timestamp=TS)
    assert os.path.exists(os.path.join(path, '.locks', 'orphan.1.1'))
    assert os.listdir(os.path.join(path, 'quarantine', 'torn-write-after-000001-1')) == ['000002.json']


def test_recover_does_not_touch_a_live_contenders_staged_lock(store):
    path = seeded(store, n=1)
    staged = os.path.join(path, '.locks', 'contender.99.0')
    force_write(staged, b'staged lock bytes')
    force_write(os.path.join(path, '.tmp.000002.json'), b'leftover')
    store.recover('wf1', owner='w1', timestamp=TS)
    assert open(staged, 'rb').read() == b'staged lock bytes'


def test_reader_ignore_in_flight_sees_no_transient_temp(store):
    path = seeded(store, n=1)
    force_write(os.path.join(path, '.tmp.000002.json'), b'in flight')
    refusal('leftover_temp', store.load, 'wf1')  # strict default still reports it
    assert store.load('wf1', ignore_in_flight=True).head_sequence == 1  # lock is held
    store.release('wf1', owner='w1')
    refusal('leftover_temp', store.load, 'wf1', ignore_in_flight=True)  # no writer: not in flight


def test_concurrent_reader_during_appends_gets_no_errors(store):
    seeded(store, n=0)
    done = threading.Event()
    errors, loads = [], [0]

    def reader():
        while not done.is_set():
            try:
                store.load('wf1', ignore_in_flight=True)
                loads[0] += 1
            except Exception as exc:  # noqa: BLE001 - any error is a failure here
                errors.append(repr(exc))

    t = threading.Thread(target=reader)
    t.start()
    try:
        for i in range(80):
            store.append('wf1', rec(body={'i': i}), owner='w1')
    finally:
        done.set()
        t.join()
    assert not errors and loads[0] > 0


def test_entries_vanishing_after_listdir_are_tolerated(store, monkeypatch):
    path = seeded(store, n=1)
    real = os.listdir

    def with_ghosts(p):
        out = real(p)
        if os.path.abspath(p) == os.path.abspath(path):
            out = out + ['.tmp.000002.json', 'LOCK']
            out = [n for n in out if n != 'LOCK'] + ['LOCK']
        return out

    # the ghost temp never exists (finished between listdir and lstat); LOCK genuinely exists
    monkeypatch.setattr(os, 'listdir', with_ghosts)
    assert store.load('wf1').head_sequence == 1
    os.unlink(os.path.join(path, 'LOCK'))  # now LOCK is a ghost too (released between listdir and lstat)
    assert store.load('wf1').head_sequence == 1


# --- 2. deep JSON -----------------------------------------------------------------------

def test_recursion_error_from_the_decoder_is_a_typed_refusal(store, monkeypatch):
    path = seeded(store, n=2, hold=False)

    class Boom:
        def raw_decode(self, *a, **k):
            raise RecursionError()

    monkeypatch.setattr(canonical, '_decoder', lambda: Boom())
    with pytest.raises(ValueError):
        canonical.loads_strict('[1]')
    with pytest.raises(ValueError):
        canonical.raw_decode_strict('[1]')
    refusal('noncanonical_event', store.load, 'wf1')  # non-final and final positions alike
    monkeypatch.undo()
    assert store.load('wf1').head_sequence == 2


@pytest.mark.parametrize('payload', [b'[' * 5000 + b']' * 5000, b'{"a":' * 5000 + b'1' + b'}' * 5000,
                                     b'[' * 100000])
@pytest.mark.parametrize('position', [1, 3])
def test_real_deep_file_is_refused_not_a_crash(store, payload, position):
    path = seeded(store, n=3, hold=False)
    force_write(os.path.join(path, '%06d.json' % position), payload)
    with pytest.raises(ws.StoreRefusal) as info:
        store.load('wf1')
    # unbalanced input is a torn tail at the end; everything else is a typed profile refusal
    assert info.value.code in {'noncanonical_event', 'schema_invalid', 'event_corrupt', 'torn_tail',
                               'event_too_large'}


def test_deep_python_values_are_refused_without_recursion_error(store):
    seeded(store, n=0)
    deep = []
    cur = deep
    for _ in range(5000):
        nxt = []
        cur.append(nxt)
        cur = nxt
    with pytest.raises(ValueError):
        canonical.jcs_dumps(deep)
    refusal('schema_invalid', store.append, 'wf1', rec(body={'x': deep}), owner='w1')


# --- 3a. full workflow plus crash after the final link ----------------------------------

def test_full_workflow_crash_after_last_link_can_still_be_recovered(tmp_path):
    (tmp_path / 's').mkdir()
    s = ws.Store(tmp_path / 's', ws.Bounds(max_events=3))
    path = seeded(s, n=2, wid='a')
    real = os.unlink

    def die(p, *a, **k):
        if os.path.basename(p).startswith('.tmp.000003'):
            raise Crash()
        return real(p, *a, **k)

    os.unlink = die
    try:
        with pytest.raises(Crash):
            s.append('a', rec(), owner='w1')
    finally:
        os.unlink = real
    assert '000003.json' in os.listdir(path) and '.tmp.000003.json' in os.listdir(path)
    refusal('leftover_temp', s.load, 'a')
    events = s.recover('a', owner='w1', timestamp=TS)  # event 4 is beyond max_events: the reserve
    assert events[0]['sequence'] == 4
    assert s.load('a').head_sequence == 4
    refusal('workflow_full', s.append, 'a', rec(), owner='w1')  # ordinary appends stay bounded


def test_recovery_reserve_is_itself_bounded(tmp_path, monkeypatch):
    (tmp_path / 's').mkdir()
    s = ws.Store(tmp_path / 's', ws.Bounds(max_events=1))
    path = seeded(s, n=1, wid='a')
    monkeypatch.setattr(store_mod, 'RECOVERY_RESERVE', 1)
    force_write(os.path.join(path, '.tmp.000002.json'), b'x')
    s.recover('a', owner='w1', timestamp=TS)
    force_write(os.path.join(path, '.tmp.000003.json'), b'x')
    refusal('workflow_full', s.recover, 'a', owner='w1', timestamp=TS)


# --- 3b. oversized junk -----------------------------------------------------------------

def test_huge_junk_temp_is_quarantined_with_exact_facts(store):
    path = seeded(store, n=1)
    junk = b'j' * (store_mod.CEILING_EVENT_BYTES + 12345)
    force_write(os.path.join(path, '.tmp.000002.json'), junk)
    (ev,) = store.recover('wf1', owner='w1', timestamp=TS)
    assert ev['body']['files'] == [{'name': '.tmp.000002.json', 'size': len(junk),
                                    'sha256': 'sha256:' + hashlib.sha256(junk).hexdigest()}]
    assert store.load('wf1').head_sequence == 2


def test_huge_torn_final_file_is_a_torn_tail_not_a_size_refusal(store):
    path = seeded(store, n=1)
    force_write(os.path.join(path, '000002.json'), b'{' + b'j' * (store_mod.CEILING_EVENT_BYTES + 5))
    refusal('torn_tail', store.load, 'wf1')
    store.recover('wf1', owner='w1', timestamp=TS)
    assert store.load('wf1').head_sequence == 2


def test_many_quarantined_files_keep_the_record_small(store):
    path = seeded(store, n=1)
    for i in range(40):
        force_write(os.path.join(path, '.tmp.junk%02d' % i), b'x' * i)
    (ev,) = store.recover('wf1', owner='w1', timestamp=TS)
    assert ev['body']['files_total'] == 40 and len(ev['body']['files']) == store_mod.MAX_FACTS


def test_recovery_record_ignores_the_per_event_size_bound(tmp_path):
    (tmp_path / 's').mkdir()
    s = ws.Store(tmp_path / 's', ws.Bounds(max_event_bytes=300))
    path = seeded(s, n=1, wid='a')
    for i in range(10):
        force_write(os.path.join(path, '.tmp.junk%02d' % i), b'x')
    (ev,) = s.recover('a', owner='w1', timestamp=TS)
    assert len(canonical.jcs_bytes(ev)) > 300
    assert s.load('a').head_sequence == 2  # and it loads under the same bound


# --- 3c. corrupt LOCK -------------------------------------------------------------------

@pytest.mark.parametrize('content', [b'garbage', b'', b'{"profile":"x"}', b'x' * 10000])
def test_corrupt_lock_has_an_explicit_documented_recovery_path(store, content):
    path = seeded(store, n=1, hold=False)
    force_write(os.path.join(path, 'LOCK'), content)
    sha = 'sha256:' + hashlib.sha256(content).hexdigest()
    e = refusal('lock_corrupt', store.read_lock, 'wf1')
    assert e.detail['sha256'] == sha
    refusal('lock_held', store.acquire, 'wf1', owner='w2', timestamp=TS)
    refusal('lock_corrupt', store.append, 'wf1', rec(), owner='w2')
    refusal('lock_corrupt', store.break_lock, 'wf1', breaker='w2', reason='r', timestamp=TS)
    refusal('lock_corrupt', store.break_lock, 'wf1', expected_owner='w1', breaker='w2', reason='r',
            timestamp=TS, corrupt_lock_sha256=sha)
    refusal('lock_owner_mismatch', store.break_lock, 'wf1', breaker='w2', reason='r', timestamp=TS,
            corrupt_lock_sha256='sha256:' + '0' * 64)
    assert open(os.path.join(path, 'LOCK'), 'rb').read() == content  # nothing changed so far
    ev = store.break_lock('wf1', breaker='w2', reason='corrupt lock inspected', timestamp=TS,
                          corrupt_lock_sha256=sha)
    assert ev['body']['broken_owner'] is None and ev['body']['corrupt_lock_sha256'] == sha
    store.append('wf1', rec(), owner='w2')
    assert [e['kind'] for e in store.load('wf1').events] == ['workflow.proposed', 'store.lock_broken',
                                                             'workflow.proposed']


def test_valid_lock_refuses_the_corrupt_acknowledgement(store):
    seeded(store, n=0)
    refusal('schema_invalid', store.break_lock, 'wf1', breaker='w2', reason='r', timestamp=TS,
            corrupt_lock_sha256='sha256:' + '0' * 64)
    refusal('schema_invalid', store.break_lock, 'wf1', breaker='w2', reason='r', timestamp=TS)


def test_fifo_in_place_of_lock_or_event_does_not_block(store):
    path = seeded(store, n=1, hold=False)
    os.mkfifo(os.path.join(path, 'LOCK'))
    refusal('lock_held', store.acquire, 'wf1', owner='w2', timestamp=TS)
    refusal('lock_corrupt', store.read_lock, 'wf1')
    os.unlink(os.path.join(path, 'LOCK'))
    os.unlink(os.path.join(path, '000001.json'))
    os.mkfifo(os.path.join(path, '000001.json'))
    refusal('unexpected_file', store.load, 'wf1')


# --- 4. ambiguous outcomes --------------------------------------------------------------

def test_directory_fsync_failure_after_link_is_ambiguous_not_raw(store, monkeypatch):
    path = seeded(store, n=1)
    real = os.fsync
    calls = {'n': 0}

    def flaky(fd):
        calls['n'] += 1
        if calls['n'] == 2:  # 1: temp file, 2: the directory right after the link
            raise OSError(5, 'simulated')
        return real(fd)

    monkeypatch.setattr(os, 'fsync', flaky)
    e = refusal('outcome_ambiguous', store.append, 'wf1', rec(), owner='w1')
    assert e.detail == {'sequence': 2} and 'reload' in str(e)
    monkeypatch.undo()
    assert '000002.json' in os.listdir(path)  # the event does exist
    refusal('leftover_temp', store.load, 'wf1')
    store.recover('wf1', owner='w1', timestamp=TS)
    assert [e['kind'] for e in store.load('wf1').events][:2] == ['workflow.proposed', 'workflow.proposed']


def test_temp_unlink_failure_after_link_is_ambiguous(store, monkeypatch):
    seeded(store, n=1)
    real = os.unlink

    def flaky(p, *a, **k):
        if os.path.basename(p).startswith('.tmp.000002'):
            raise OSError(5, 'simulated')
        return real(p, *a, **k)

    monkeypatch.setattr(os, 'unlink', flaky)
    refusal('outcome_ambiguous', store.append, 'wf1', rec(), owner='w1')


def test_link_failure_before_the_event_exists_is_io_failure(store, monkeypatch):
    path = seeded(store, n=1)

    def nolink(*a, **k):
        raise OSError(1, 'links unsupported')

    monkeypatch.setattr(os, 'link', nolink)
    refusal('io_failure', store.append, 'wf1', rec(), owner='w1')
    monkeypatch.undo()
    assert '000002.json' not in os.listdir(path)


# --- 5. lock races ----------------------------------------------------------------------

def test_two_racing_breakers_exactly_one_wins_and_never_destroys_the_others_lock(store):
    seeded(store, n=1, hold=False)
    store.acquire('wf1', owner='dead', timestamp='old')
    barrier = threading.Barrier(2)
    results = {}

    def breaker(name):
        barrier.wait()
        try:
            store.break_lock('wf1', expected_owner='dead', breaker=name, reason='stale', timestamp=TS)
            results[name] = 'won'
        except ws.StoreRefusal as exc:
            results[name] = exc.code
        except BaseException as exc:  # noqa: BLE001
            results[name] = 'RAW ' + repr(exc)

    threads = [threading.Thread(target=breaker, args=(n,)) for n in ('b1', 'b2')]
    [t.start() for t in threads]
    [t.join() for t in threads]
    winner = [n for n, r in results.items() if r == 'won']
    assert len(winner) == 1, results
    loser = 'b1' if winner[0] == 'b2' else 'b2'
    assert results[loser] == 'lock_owner_mismatch'
    assert store.read_lock('wf1')['owner'] == winner[0]
    kinds = [e['kind'] for e in store.load('wf1').events]
    assert kinds.count('store.lock_broken') == 1


def test_racing_breakers_across_processes(store):
    seeded(store, n=0, hold=False)
    store.acquire('wf1', owner='dead', timestamp='old')
    path = store.workflow_dir('wf1')
    pids = []
    for name in ('p1', 'p2', 'p3'):
        pid = os.fork()
        if pid == 0:
            code = 9
            try:
                ws.break_lock(path, expected_owner='dead', breaker=name, reason='stale', timestamp=TS)
                code = 0
            except ws.StoreRefusal as exc:
                code = 1 if exc.code == 'lock_owner_mismatch' else 2
            except BaseException:  # noqa: BLE001
                code = 3
            os._exit(code)
        pids.append(pid)
    codes = sorted(os.waitstatus_to_exitcode(os.waitpid(p, 0)[1]) for p in pids)
    assert codes == [0, 1, 1]


def test_release_by_a_displaced_holder_never_removes_the_new_lock(store):
    seeded(store, n=0)  # w1 holds
    store.break_lock('wf1', expected_owner='w1', breaker='w2', reason='stale', timestamp='t2')
    refusal('lock_owner_mismatch', store.release, 'wf1', owner='w1')
    refusal('lock_owner_mismatch', store.append, 'wf1', rec(), owner='w1')
    assert store.read_lock('wf1') == {'owner': 'w2', 'timestamp': 't2'}


def test_release_racing_acquire_keeps_one_consistent_lock(store):
    seeded(store, n=0, hold=False)
    errors, held = [], []
    stop = threading.Event()

    def cycle(owner):
        for _ in range(40):
            try:
                store.acquire('wf1', owner=owner, timestamp=TS)
            except ws.StoreRefusal as exc:
                if exc.code != 'lock_held':
                    errors.append(exc.code)
                continue
            try:
                held.append(owner)
                assert store.read_lock('wf1')['owner'] == owner  # nobody swapped it under us
                store.release('wf1', owner=owner)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

    threads = [threading.Thread(target=cycle, args=('o%d' % i,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and held and store.read_lock('wf1') is None


def test_crash_between_break_event_and_lock_handover_is_detectable(store, monkeypatch):
    path = seeded(store, n=1)

    def die(*a, **k):
        raise Crash()

    monkeypatch.setattr(os, 'replace', die)
    with pytest.raises(Crash):
        store.break_lock('wf1', expected_owner='w1', breaker='w2', reason='stale', timestamp='t2')
    monkeypatch.undo()
    assert store.read_lock('wf1')['owner'] == 'w1'  # old lock still in place
    assert store.load('wf1').events[-1]['kind'] == 'store.lock_broken'
    assert store.inspect('wf1') == [{'code': 'lock_break_incomplete', 'files': []}]
    store.break_lock('wf1', expected_owner='w1', breaker='w2', reason='again', timestamp='t3')
    assert store.read_lock('wf1')['owner'] == 'w2' and store.inspect('wf1') == []
    assert os.listdir(os.path.join(path, '.locks')) == ['mutex']


def test_replace_failure_is_a_typed_incomplete_break(store, monkeypatch):
    seeded(store, n=0)

    def nope(*a, **k):
        raise OSError(1, 'denied')

    monkeypatch.setattr(os, 'replace', nope)
    e = refusal('lock_break_incomplete', store.break_lock, 'wf1', expected_owner='w1', breaker='w2',
                reason='r', timestamp=TS)
    assert e.detail == {'sequence': 1}
    monkeypatch.undo()
    assert store.inspect('wf1') == [{'code': 'lock_break_incomplete', 'files': []}]


def test_failed_break_leaves_the_lock_and_no_staged_file(store, monkeypatch):
    path = seeded(store, n=0)

    def boom(*a, **k):
        raise ws.StoreRefusal('io_failure', 'simulated')

    monkeypatch.setattr(store_mod, '_append_locked', boom)
    refusal('io_failure', store.break_lock, 'wf1', expected_owner='w1', breaker='w2', reason='r', timestamp=TS)
    monkeypatch.undo()
    assert store.read_lock('wf1')['owner'] == 'w1'
    assert os.listdir(os.path.join(path, '.locks')) == ['mutex']


# --- 6. recover must not drop a complete event ------------------------------------------

def tail_with_complete_event(store):
    path = seeded(store, n=1, hold=False)
    head1 = store.load('wf1').head_digest
    store.acquire('wf1', owner='w1', timestamp=TS)
    ev = store.append('wf1', rec(body={'acked': True}), owner='w1')
    final = os.path.join(path, '000002.json')
    good = open(final, 'rb').read()
    force_write(final, good + b'\x00GARBAGE')
    return path, head1, ev


def test_recover_refuses_when_the_tail_holds_a_complete_valid_event(store):
    path, head1, ev = tail_with_complete_event(store)
    refusal('torn_tail', store.load, 'wf1')
    e = refusal('complete_event_in_tail', store.recover, 'wf1', owner='w1', timestamp=TS)
    assert e.detail == {'digest': ev['digest']}
    assert '000002.json' in os.listdir(path) and not os.path.exists(os.path.join(path, 'quarantine'))
    refusal('complete_event_in_tail', store.break_lock, 'wf1', expected_owner='w1', breaker='w2', reason='r',
            timestamp=TS, recover_torn=True)
    assert store.read_lock('wf1')['owner'] == 'w1'


def test_recover_with_expected_head_that_excludes_the_tail_event_is_allowed_and_recorded(store):
    path, head1, ev = tail_with_complete_event(store)
    (rec_ev,) = store.recover('wf1', owner='w1', timestamp=TS, expected_head=(1, head1))
    assert rec_ev['body']['complete_event_discarded'] == ev['digest']
    assert store.load('wf1').events[1]['kind'] == 'store.torn_tail_quarantined'


def test_recover_expected_head_must_be_consistent(store):
    path, head1, ev = tail_with_complete_event(store)
    refusal('chain_broken', store.recover, 'wf1', owner='w1', timestamp=TS, expected_head=(1, 'sha256:' + '1' * 64))
    refusal('truncated', store.recover, 'wf1', owner='w1', timestamp=TS, expected_head=(2, ev['digest']))
    assert '000002.json' in os.listdir(path)


def test_recover_with_explicit_acknowledgement(store):
    path, head1, ev = tail_with_complete_event(store)
    store.recover('wf1', owner='w1', timestamp=TS, acknowledge_drop=True)
    assert store.load('wf1').head_sequence == 2


def test_plain_torn_tail_still_recovers_without_a_head(store):
    path = seeded(store, n=1)
    force_write(os.path.join(path, '000002.json'), b'{"profile":"ocs-workflow-ev')
    store.recover('wf1', owner='w1', timestamp=TS)
    assert store.load('wf1').head_sequence == 2


# --- 8. nits ----------------------------------------------------------------------------

def test_unhashable_quarantine_member_does_not_crash_scan(store):
    path = seeded(store, n=0, hold=False)
    obj = {'profile': store_mod.PROFILE, 'schema_version': 0, 'canonical_profile': 'rfc8785-jcs',
           'workflow_id': 'wf1', 'sequence': 1, 'predecessor': None, 'kind': 'store.torn_tail_quarantined',
           'timestamp': TS, 'body': {'quarantine': [1, 2]}}
    obj['digest'] = canonical.object_digest(obj)
    force_write(os.path.join(path, '000001.json'), canonical.jcs_bytes(obj))
    assert store.load('wf1').head_sequence == 1  # no TypeError; the list names no directory


def test_mode_is_set_before_the_data_is_flushed(store, monkeypatch):
    seeded(store, n=0)
    order = []
    real_fchmod, real_fsync = os.fchmod, os.fsync
    monkeypatch.setattr(os, 'fchmod', lambda fd, m: (order.append('fchmod'), real_fchmod(fd, m))[1])

    def fsync(fd):
        if not os.path.isdir('/proc/self/fd/%d' % fd):
            order.append('fsync-file')
        return real_fsync(fd)

    monkeypatch.setattr(os, 'fsync', fsync)
    store.append('wf1', rec(), owner='w1')
    assert order == ['fchmod', 'fsync-file']


def test_oversized_record_is_refused_before_canonicalization(store, monkeypatch):
    seeded(store, n=0)

    def never(*a, **k):
        raise AssertionError('canonicalized before the size check')

    monkeypatch.setattr(store_mod, 'jcs_bytes', never)
    body = {'k%d' % i: 'v' * 1000 for i in range(100)}  # ~100 KB > 64 KiB default bound
    refusal('event_too_large', store.append, 'wf1', rec(body=body), owner='w1')
    refusal('event_too_large', store.append, 'wf1', rec(body={'big': ['x' * 70000]}), owner='w1')


# === second re-review: exact head, fork-safe mutex, typed fsync/flock failures, break ids ============

import errno  # noqa: E402
import fcntl  # noqa: E402


def dir_fsync_fails(monkeypatch, after=0):
    real = os.fsync
    state = {'dir_calls': 0}

    def fsync(fd):
        if os.path.isdir('/proc/self/fd/%d' % fd):
            state['dir_calls'] += 1
            if state['dir_calls'] > after:
                raise OSError(5, 'simulated directory fsync failure')
        return real(fd)

    monkeypatch.setattr(os, 'fsync', fsync)


def chain_with_complete_tail(store, acked=3):
    """acked events, then a complete valid next event followed by garbage in its file."""
    path = seeded(store, n=acked, hold=False)
    heads = [(e['sequence'], e['digest']) for e in store.load('wf1').events]
    store.acquire('wf1', owner='w1', timestamp=TS)
    ev = store.append('wf1', rec(body={'tail': True}), owner='w1')
    final = os.path.join(path, '%06d.json' % ev['sequence'])
    force_write(final, open(final, 'rb').read() + b'#junk')
    return path, heads, ev


# --- 1 ---

def test_expected_head_must_equal_the_log_head_to_discard_a_complete_event(store):
    path, heads, ev = chain_with_complete_tail(store, acked=3)
    # a caller who saw event 3 (the log head) may discard the unacknowledged tail event 4
    # a caller whose head is OLDER than the log head must not
    e = refusal('complete_event_in_tail', store.recover, 'wf1', owner='w1', timestamp=TS, expected_head=heads[1])
    assert 'behind the log head' in str(e) and 'acknowledge_drop' in str(e)
    refusal('complete_event_in_tail', store.break_lock, 'wf1', expected_owner='w1', breaker='w2', reason='r',
            timestamp=TS, recover_torn=True, expected_head=heads[0])
    assert os.path.exists(os.path.join(path, '000004.json')) and store.read_lock('wf1')['owner'] == 'w1'
    store.recover('wf1', owner='w1', timestamp=TS, expected_head=heads[2])
    assert store.load('wf1').events[3]['body']['complete_event_discarded'] == ev['digest']


def test_expected_head_beyond_the_log_points_at_acknowledge_drop(store):
    path, heads, ev = chain_with_complete_tail(store, acked=2)
    e = refusal('truncated', store.recover, 'wf1', owner='w1', timestamp=TS, expected_head=(3, ev['digest']))
    assert 'acknowledge_drop' in str(e)


# --- 2 ---

def test_mutex_is_released_even_while_a_forked_child_holds_the_descriptor(store):
    path = seeded(store, n=0, hold=False)
    r, w = os.pipe()
    with store_mod._mutex(path):
        pid = os.fork()
        if pid == 0:
            os.read(r, 1)  # the child lives on, still holding any inherited descriptor
            os._exit(0)
    try:
        fd = os.open(os.path.join(path, '.locks', 'mutex'), os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises BlockingIOError if the mutex leaked
        finally:
            os.close(fd)
        store.acquire('wf1', owner='w1', timestamp=TS)  # and the API itself is not wedged
    finally:
        os.write(w, b'x')
        os.waitpid(pid, 0)


# --- 3 ---

def test_flock_failure_is_a_typed_io_failure(store, monkeypatch):
    seeded(store, n=0, hold=False)

    def enolck(fd, op):
        raise OSError(errno.ENOLCK, 'No locks available')

    monkeypatch.setattr(fcntl, 'flock', enolck)
    e = refusal('io_failure', store.acquire, 'wf1', owner='w1', timestamp=TS)
    assert 'flock' in str(e)
    refusal('io_failure', store.append, 'wf1', rec(), owner='w1')
    monkeypatch.undo()
    store.acquire('wf1', owner='w1', timestamp=TS)


# --- 4 ---

def test_corrupt_lock_break_with_failed_replace_is_reported_incomplete(store, monkeypatch):
    path = seeded(store, n=1, hold=False)
    content = b'garbage'
    force_write(os.path.join(path, 'LOCK'), content)
    sha = 'sha256:' + hashlib.sha256(content).hexdigest()

    def nope(*a, **k):
        raise OSError(1, 'denied')

    monkeypatch.setattr(os, 'replace', nope)
    refusal('lock_break_incomplete', store.break_lock, 'wf1', breaker='w2', reason='r', timestamp=TS,
            corrupt_lock_sha256=sha)
    monkeypatch.undo()
    assert store.inspect('wf1') == [{'code': 'lock_break_incomplete', 'files': []}]
    store.break_lock('wf1', breaker='w2', reason='again', timestamp=TS, corrupt_lock_sha256=sha)
    assert store.inspect('wf1') == []


def test_no_false_positive_when_the_original_owner_reacquires_with_an_identical_timestamp(store):
    seeded(store, n=0, hold=False)
    store.acquire('wf1', owner='old', timestamp='T')
    store.break_lock('wf1', expected_owner='old', breaker='new', reason='stale', timestamp='T2')
    store.release('wf1', owner='new')
    store.acquire('wf1', owner='old', timestamp='T')  # same owner token and timestamp as the broken lock
    assert store.load('wf1').events[-1]['kind'] == 'store.lock_broken'
    assert store.inspect('wf1') == []


def test_old_holder_can_still_append_during_the_incomplete_window(store, monkeypatch):
    seeded(store, n=1)

    def die(*a, **k):
        raise Crash()

    monkeypatch.setattr(os, 'replace', die)
    with pytest.raises(Crash):
        store.break_lock('wf1', expected_owner='w1', breaker='w2', reason='stale', timestamp='t2')
    monkeypatch.undo()
    assert store.inspect('wf1') == [{'code': 'lock_break_incomplete', 'files': []}]
    store.append('wf1', rec(body={'late': 1}), owner='w1')  # documented: the old holder still holds LOCK
    assert store.inspect('wf1') == []  # the break event is no longer the latest


# --- 5 ---

def test_acquire_directory_fsync_failure_is_typed(store, monkeypatch):
    path = seeded(store, n=0, hold=False)
    dir_fsync_fails(monkeypatch)
    e = refusal('outcome_ambiguous', store.acquire, 'wf1', owner='w1', timestamp=TS)
    assert 'read_lock' in str(e)
    monkeypatch.undo()
    assert store.read_lock('wf1')['owner'] == 'w1'  # the change did happen


def test_release_directory_fsync_failure_is_typed(store, monkeypatch):
    seeded(store, n=0)
    dir_fsync_fails(monkeypatch)
    refusal('outcome_ambiguous', store.release, 'wf1', owner='w1')
    monkeypatch.undo()
    assert store.read_lock('wf1') is None


def test_recover_directory_fsync_failure_is_typed_and_resumable(store, monkeypatch):
    path = seeded(store, n=1)
    force_write(os.path.join(path, '.tmp.000002.json'), b'x')
    dir_fsync_fails(monkeypatch)
    e = refusal('outcome_ambiguous', store.recover, 'wf1', owner='w1', timestamp=TS)
    assert 'inspect' in str(e)
    monkeypatch.undo()
    refusal('unrecorded_quarantine', store.load, 'wf1')
    store.recover('wf1', owner='w1', timestamp=TS)
    assert store.load('wf1').head_sequence == 2


def test_recover_fact_failure_moves_nothing(store, monkeypatch):
    path = seeded(store, n=1)
    force_write(os.path.join(path, '.tmp.000002.json'), b'x')

    def boom(*a, **k):
        raise OSError(5, 'read error')

    monkeypatch.setattr(store_mod, '_stream_facts', boom)
    refusal('io_failure', store.recover, 'wf1', owner='w1', timestamp=TS)
    monkeypatch.undo()
    assert '.tmp.000002.json' in os.listdir(path) and not os.path.exists(os.path.join(path, 'quarantine'))


# --- 6 ---

def test_fifo_lock_is_a_breakable_corrupt_lock(store):
    path = seeded(store, n=1, hold=False)
    os.mkfifo(os.path.join(path, 'LOCK'))
    e = refusal('lock_corrupt', store.read_lock, 'wf1')
    sha = e.detail['sha256']
    assert sha == 'sha256:' + hashlib.sha256(('nonregular:%o' % 0o010000).encode()).hexdigest()
    store.break_lock('wf1', breaker='w2', reason='fifo', timestamp=TS, corrupt_lock_sha256=sha)
    assert store.read_lock('wf1')['owner'] == 'w2'
    store.append('wf1', rec(), owner='w2')


def test_symlink_lock_is_a_breakable_corrupt_lock_and_the_target_is_untouched(store, tmp_path):
    path = seeded(store, n=0, hold=False)
    target = tmp_path / 'target.txt'
    target.write_text('keep')
    os.symlink(target, os.path.join(path, 'LOCK'))
    e = refusal('lock_corrupt', store.read_lock, 'wf1')
    store.break_lock('wf1', breaker='w2', reason='symlink', timestamp=TS, corrupt_lock_sha256=e.detail['sha256'])
    assert target.read_text() == 'keep' and store.read_lock('wf1')['owner'] == 'w2'


def test_directory_lock_needs_manual_removal(store):
    path = seeded(store, n=0, hold=False)
    os.mkdir(os.path.join(path, 'LOCK'))
    e = refusal('lock_corrupt', store.read_lock, 'wf1')
    refusal('io_failure', store.break_lock, 'wf1', breaker='w2', reason='dir', timestamp=TS,
            corrupt_lock_sha256=e.detail['sha256'])
    refusal('lock_held', store.acquire, 'wf1', owner='w2', timestamp=TS)


def test_junk_final_file_of_deep_unclosed_brackets_is_a_recoverable_torn_tail(store, monkeypatch):
    path = seeded(store, n=1)
    force_write(os.path.join(path, '000002.json'), b'[' * 100000)
    refusal('torn_tail', store.load, 'wf1')
    store.recover('wf1', owner='w1', timestamp=TS)
    assert store.load('wf1').head_sequence == 2
    # the same through an interpreter that raises RecursionError, and a deep NON-final file stays corruption
    class Boom:
        def raw_decode(self, *a, **k):
            raise RecursionError()

    path2 = seeded(store, n=3, wid='wf2')
    monkeypatch.setattr(canonical, '_decoder', lambda: Boom())
    refusal('noncanonical_event', store.load, 'wf2')  # first event "nests too deeply": non-final
    monkeypatch.undo()
    assert store.load('wf2').head_sequence == 3


# --- 8 ---

def test_lock_temp_names_are_collision_proof_after_pid_reuse(store, monkeypatch):
    path = seeded(store, n=0, hold=False)
    real = os.urandom
    seq = iter([b'\x01' * 6, b'\x01' * 6, b'\x02' * 6, real(16)])

    def fixed(n):
        return next(seq) if n == 6 else real(n)

    # a crashed process left a temp whose name the next attempt would pick first
    os.makedirs(os.path.join(path, '.locks'), exist_ok=True)
    force_write(os.path.join(path, '.locks', 'w1.%s.0' % ('01' * 6)), b'stale from a dead pid')
    monkeypatch.setattr(os, 'urandom', fixed)
    monkeypatch.setattr(store_mod, '_COUNTER', iter([0, 0, 1, 2, 3]))
    store.acquire('wf1', owner='w1', timestamp=TS)  # retries past the existing name instead of failing
    monkeypatch.undo()
    assert store.read_lock('wf1')['owner'] == 'w1'
    leftovers = sorted(n for n in os.listdir(os.path.join(path, '.locks')) if n != 'mutex')
    assert leftovers == ['w1.%s.0' % ('01' * 6)]  # crash leftovers in .locks are never cleaned or touched


# === third review ===

def test_directory_fsync_failure_after_the_lock_handover_is_ambiguous_not_incomplete(store, monkeypatch):
    seeded(store, n=1)
    # the break appends its event first (two directory fsyncs), then replaces LOCK, then fsyncs the directory
    dir_fsync_fails(monkeypatch, after=2)
    e = refusal('outcome_ambiguous', store.break_lock, 'wf1', expected_owner='w1', breaker='w2', reason='stale',
                timestamp='t2')
    assert 'WAS handed over' in str(e) and e.detail == {'sequence': 2}
    monkeypatch.undo()
    assert store.read_lock('wf1')['owner'] == 'w2'
    assert store.inspect('wf1') == [] and store.load('wf1').events[-1]['kind'] == 'store.lock_broken'


def test_old_format_lock_without_lock_id_is_a_corrupt_lock(store):
    path = seeded(store, n=1, hold=False)
    old = canonical.jcs_bytes({'profile': 'ocs-workflow-lock/0', 'owner': 'w1', 'timestamp': TS})
    force_write(os.path.join(path, 'LOCK'), old)
    sha = 'sha256:' + hashlib.sha256(old).hexdigest()
    refusal('lock_corrupt', store.read_lock, 'wf1')
    refusal('lock_corrupt', store.append, 'wf1', rec(), owner='w1')
    refusal('lock_corrupt', store.release, 'wf1', owner='w1')
    refusal('lock_held', store.acquire, 'wf1', owner='w2', timestamp=TS)
    refusal('lock_corrupt', store.break_lock, 'wf1', expected_owner='w1', breaker='w2', reason='r', timestamp=TS)
    store.break_lock('wf1', breaker='w2', reason='old format', timestamp=TS, corrupt_lock_sha256=sha)
    assert store.read_lock('wf1')['owner'] == 'w2'
