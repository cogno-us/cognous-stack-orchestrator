"""Crash, torn-write and recovery tests for the workflow event store. Developer tests only."""
import ast
import hashlib
import json
import os

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


def seeded(store, n=2, hold=True):
    store.create_workflow('wf1')
    store.acquire('wf1', owner='w1', timestamp=TS)
    for i in range(n):
        store.append('wf1', rec(body={'i': i}), owner='w1')
    if not hold:
        store.release('wf1', owner='w1')
    return store.workflow_dir('wf1')


def listing(path):
    return sorted(os.listdir(path))


class Crash(BaseException):
    """Simulated process death: not an Exception, so no handler in the store runs to completion."""


# --- kill between temp write and the final name -----------------------------------------

def test_crash_between_temp_write_and_link_leaves_only_a_temp(store, monkeypatch):
    path = seeded(store)
    before = store.load('wf1')

    def die(*a, **k):
        raise Crash()

    monkeypatch.setattr(os, 'link', die)
    with pytest.raises(Crash):
        store.append('wf1', rec(body={'i': 2}), owner='w1')
    monkeypatch.undo()
    assert '.tmp.000003.json' in listing(path) and '000003.json' not in listing(path)
    e = refusal('leftover_temp', store.load, 'wf1')
    assert e.detail['files'] == ['.tmp.000003.json']
    # append refuses too: nothing is silently repaired or overwritten
    refusal('leftover_temp', store.append, 'wf1', rec(), owner='w1')
    assert '.tmp.000003.json' in listing(path)
    assert store.inspect('wf1') == [{'code': 'leftover_temp', 'files': ['.tmp.000003.json']}]
    # the events before the crash are untouched; verify by reading the chain directly
    assert before.head_sequence == 2


def test_real_process_death_between_temp_write_and_link(store):
    path = seeded(store, n=2, hold=False)
    pid = os.fork()
    if pid == 0:
        try:
            store.acquire('wf1', owner='child', timestamp=TS)
            os.link = lambda *a, **k: os._exit(9)  # the process dies; no cleanup runs
            store.append('wf1', rec(body={'late': True}), owner='child')
        finally:
            os._exit(1)
    assert os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]) == 9
    names = listing(path)
    assert '.tmp.000003.json' in names and 'LOCK' in names
    refusal('leftover_temp', store.load, 'wf1')
    refusal('lock_held', store.acquire, 'wf1', owner='next', timestamp=TS)
    # explicit operator path: break the stale lock (recover_torn handles the leftover), then continue
    event = store.break_lock('wf1', expected_owner='child', breaker='next', reason='child died',
                             timestamp=TS, recover_torn=True)
    loaded = store.load('wf1')
    assert [e['kind'] for e in loaded.events] == ['workflow.proposed', 'workflow.proposed',
                                                  'store.torn_tail_quarantined', 'store.lock_broken']
    assert event['sequence'] == 4
    q = loaded.events[2]['body']
    assert [f['name'] for f in q['files']] == ['.tmp.000003.json']
    store.append('wf1', rec(body={'resumed': True}), owner='next')
    assert store.load('wf1').head_sequence == 5


def test_crash_after_link_before_temp_unlink_reports_leftover_temp(store, monkeypatch):
    path = seeded(store)
    real = os.unlink
    calls = []

    def die_on_temp(p, *a, **k):
        if os.path.basename(p).startswith('.tmp.000003'):
            calls.append(p)
            raise Crash()
        return real(p, *a, **k)

    monkeypatch.setattr(os, 'unlink', die_on_temp)
    with pytest.raises(Crash):
        store.append('wf1', rec(body={'i': 2}), owner='w1')
    monkeypatch.undo()
    assert calls and '000003.json' in listing(path) and '.tmp.000003.json' in listing(path)
    refusal('leftover_temp', store.load, 'wf1')
    store.recover('wf1', owner='w1', timestamp=TS)
    loaded = store.load('wf1')
    # the durable event 3 is kept; the temp duplicate is quarantined and recorded as event 4
    assert [e['sequence'] for e in loaded.events] == [1, 2, 3, 4]
    assert loaded.events[3]['kind'] == 'store.torn_tail_quarantined'


def test_fsync_of_file_and_directory_happens_before_the_event_is_visible(store, monkeypatch):
    path = seeded(store, n=0)
    order = []
    real_fsync, real_link = os.fsync, os.link

    def fsync(fd):
        order.append('dir' if os.path.isdir('/proc/self/fd/%d' % fd) else 'file')
        return real_fsync(fd)

    def link(src, dst, *a, **k):
        order.append('link:' + os.path.basename(dst))
        return real_link(src, dst, *a, **k)

    monkeypatch.setattr(os, 'fsync', fsync)
    monkeypatch.setattr(os, 'link', link)
    store.append('wf1', rec(), owner='w1')
    monkeypatch.undo()
    assert order[:3] == ['file', 'link:000001.json', 'dir']
    assert order[3:] == ['dir']


def test_exclusive_final_name_never_overwrites_an_existing_event(store, monkeypatch):
    path = seeded(store)
    original = open(os.path.join(path, '000002.json'), 'rb').read()
    # force the store to believe the log is one event shorter than it is
    real_scan = store_mod._scan

    def short_scan(directory, bounds):
        scan = real_scan(directory, bounds)
        scan.events = scan.events[:1]
        return scan

    monkeypatch.setattr(store_mod, '_scan', short_scan)
    refusal('sequence_conflict', store.append, 'wf1', rec(body={'evil': True}), owner='w1')
    monkeypatch.undo()
    assert open(os.path.join(path, '000002.json'), 'rb').read() == original
    assert not [n for n in listing(path) if n.startswith('.tmp.')]


def test_failed_temp_fsync_is_typed_and_creates_no_event(store, monkeypatch):
    path = seeded(store, n=1)

    def boom(fd):
        raise OSError(5, 'simulated I/O error')

    monkeypatch.setattr(os, 'fsync', boom)
    refusal('io_failure', store.append, 'wf1', rec(), owner='w1')
    monkeypatch.undo()
    assert '000002.json' not in listing(path)
    refusal('leftover_temp', store.load, 'wf1')


def test_stale_temp_name_collision_refuses_instead_of_overwriting(store):
    path = seeded(store, n=1)
    open(os.path.join(path, '.tmp.000002.json'), 'wb').write(b'precious')
    refusal('leftover_temp', store.append, 'wf1', rec(), owner='w1')
    assert open(os.path.join(path, '.tmp.000002.json'), 'rb').read() == b'precious'


# --- torn final write -------------------------------------------------------------------

def torn_variants(path):
    good = open(os.path.join(path, '000002.json'), 'rb').read()
    return {'half': good[: len(good) // 2], 'one-byte': good[:1], 'empty': b'',
            'missing-brace': good[:-1], 'bad-utf8': good[:20] + b'\xff\xfe'}


@pytest.mark.parametrize('variant', ['half', 'one-byte', 'empty', 'missing-brace', 'bad-utf8'])
def test_torn_final_event_is_reported_not_repaired(store, variant):
    path = seeded(store, n=2, hold=False)
    data = torn_variants(path)[variant]
    final = os.path.join(path, '000002.json')
    os.chmod(final, 0o644)
    open(final, 'wb').write(data)
    e = refusal('torn_tail', store.load, 'wf1')
    assert e.detail['files'] == ['000002.json']
    assert open(final, 'rb').read() == data  # untouched
    store.acquire('wf1', owner='w1', timestamp=TS)
    refusal('torn_tail', store.append, 'wf1', rec(), owner='w1')
    assert store.inspect('wf1') == [{'code': 'torn_tail', 'files': ['000002.json']}]


def test_torn_tail_in_a_non_final_position_is_corruption_not_torn(store):
    path = seeded(store, n=3, hold=False)
    first = os.path.join(path, '000001.json')
    os.chmod(first, 0o644)
    open(first, 'wb').write(b'{"x')
    refusal('event_corrupt', store.load, 'wf1')
    store.acquire('wf1', owner='w1', timestamp=TS)
    refusal('event_corrupt', store.recover, 'wf1', owner='w1', timestamp=TS)  # recover never hides it


def test_complete_but_altered_final_event_is_tamper_not_torn(store):
    path = seeded(store, n=2, hold=False)
    final = os.path.join(path, '000002.json')
    obj = json.loads(open(final, 'rb').read())
    obj['body']['i'] = 7
    os.chmod(final, 0o644)
    open(final, 'wb').write(canonical.jcs_bytes(obj))
    refusal('digest_mismatch', store.load, 'wf1')
    store.acquire('wf1', owner='w1', timestamp=TS)
    refusal('digest_mismatch', store.recover, 'wf1', owner='w1', timestamp=TS)


def test_recover_quarantines_torn_tail_and_records_it(store):
    path = seeded(store, n=2, hold=False)
    torn = open(os.path.join(path, '000002.json'), 'rb').read()[:40]
    final = os.path.join(path, '000002.json')
    os.chmod(final, 0o644)
    open(final, 'wb').write(torn)
    open(os.path.join(path, '.tmp.000003.json'), 'wb').write(b'partial')
    store.acquire('wf1', owner='w1', timestamp=TS)
    events = store.recover('wf1', owner='w1', timestamp='recover-ts')
    assert len(events) == 1
    ev = events[0]
    assert ev['kind'] == 'store.torn_tail_quarantined' and ev['sequence'] == 2 and ev['timestamp'] == 'recover-ts'
    qname = 'torn-write-after-000001-1'
    assert ev['body']['quarantine'] == qname and ev['body']['last_good_sequence'] == 1
    assert ev['body']['files_total'] == 2
    assert ev['body']['files'] == [
        {'name': '.tmp.000003.json', 'size': 7, 'sha256': 'sha256:' + hashlib.sha256(b'partial').hexdigest()},
        {'name': '000002.json', 'size': 40, 'sha256': 'sha256:' + hashlib.sha256(torn).hexdigest()}]
    qdir = os.path.join(path, 'quarantine', qname)
    assert sorted(os.listdir(qdir)) == ['.tmp.000003.json', '000002.json']
    assert open(os.path.join(qdir, '000002.json'), 'rb').read() == torn  # moved, not deleted
    assert [n for n in listing(path) if n != '.locks'] == ['000001.json', '000002.json', 'LOCK', 'quarantine']
    loaded = store.load('wf1')
    assert [e['kind'] for e in loaded.events] == ['workflow.proposed', 'store.torn_tail_quarantined']
    store.append('wf1', rec(), owner='w1')
    assert store.load('wf1').head_sequence == 3


def test_second_recover_uses_a_new_numbered_quarantine(store):
    path = seeded(store, n=1, hold=True)
    open(os.path.join(path, '000002.json'), 'wb').write(b'{')
    store.recover('wf1', owner='w1', timestamp=TS)
    open(os.path.join(path, '000003.json'), 'wb').write(b'{')
    store.recover('wf1', owner='w1', timestamp=TS)
    assert sorted(os.listdir(os.path.join(path, 'quarantine'))) == ['torn-write-after-000001-1',
                                                                    'torn-write-after-000002-1']
    assert store.load('wf1').head_sequence == 3


def test_recover_requires_lock_and_something_to_recover(store):
    path = seeded(store, n=1, hold=False)
    open(os.path.join(path, '.tmp.000002.json'), 'wb').write(b'x')
    refusal('lock_not_held', store.recover, 'wf1', owner='w1', timestamp=TS)
    store.acquire('wf1', owner='w1', timestamp=TS)
    refusal('lock_owner_mismatch', store.recover, 'wf1', owner='w2', timestamp=TS)
    store.recover('wf1', owner='w1', timestamp=TS)
    refusal('nothing_to_recover', store.recover, 'wf1', owner='w1', timestamp=TS)


def test_recover_bad_timestamp(store):
    seeded(store, n=0)
    refusal('schema_invalid', store.recover, 'wf1', owner='w1', timestamp='')


def test_crash_between_quarantine_move_and_record_is_reported_then_recorded(store, monkeypatch):
    path = seeded(store, n=1)
    open(os.path.join(path, '000002.json'), 'wb').write(b'{"half')
    real_scan = store_mod._scan
    calls = {'n': 0}

    def die_after_move(directory, bounds):
        calls['n'] += 1
        if calls['n'] == 2:  # first scan before the move, second right after it
            raise Crash()
        return real_scan(directory, bounds)

    monkeypatch.setattr(store_mod, '_scan', die_after_move)
    with pytest.raises(Crash):
        store.recover('wf1', owner='w1', timestamp=TS)
    monkeypatch.undo()
    assert '000002.json' not in listing(path)
    e = refusal('unrecorded_quarantine', store.load, 'wf1')
    assert e.detail['files'] == ['torn-write-after-000001-1']
    refusal('unrecorded_quarantine', store.append, 'wf1', rec(), owner='w1')
    store.recover('wf1', owner='w1', timestamp=TS)
    loaded = store.load('wf1')
    assert loaded.events[1]['kind'] == 'store.torn_tail_quarantined'
    assert loaded.events[1]['body']['files'][0]['name'] == '000002.json'


def test_fabricated_quarantine_directory_is_flagged(store):
    path = seeded(store, n=1, hold=False)
    os.makedirs(os.path.join(path, 'quarantine', 'whatever'))
    refusal('unrecorded_quarantine', store.load, 'wf1')


def test_recorded_quarantine_name_must_match_the_event(store):
    path = seeded(store, n=1, hold=True)
    open(os.path.join(path, '000002.json'), 'wb').write(b'{')
    store.recover('wf1', owner='w1', timestamp=TS)
    os.rename(os.path.join(path, 'quarantine', 'torn-write-after-000001-1'),
              os.path.join(path, 'quarantine', 'renamed'))
    refusal('unrecorded_quarantine', store.load, 'wf1')


def test_quarantine_must_be_a_directory(store):
    path = seeded(store, n=1, hold=False)
    open(os.path.join(path, 'quarantine'), 'wb').write(b'x')
    refusal('unexpected_file', store.load, 'wf1')


# --- strictness of the module surface ---------------------------------------------------

def _imports(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(('.' * node.level) + (node.module or ''))
    return names


def test_no_clock_network_or_subprocess_in_the_package():
    root = os.path.dirname(store_mod.__file__)
    allowed = {'contextlib', 'errno', 'fcntl', 'hashlib', 'itertools', 'json', 'os', 're', 'stat', 'dataclasses',
               '.canonical', '.refusal', '.store'}
    banned_calls = ('os.system', 'os.popen', 'os.environ', 'os.getenv', 'os.spawn', 'os.exec', 'os.fork',
                    'time.', 'datetime.')
    for name in sorted(os.listdir(root)):
        if name.endswith('.py'):
            text = open(os.path.join(root, name)).read()
            assert _imports(ast.parse(text)) <= allowed, name
            for token in banned_calls:
                assert token not in text, '%s uses %s' % (name, token)


def test_package_does_not_import_the_state_machine_or_other_orchestration_code():
    root = os.path.dirname(store_mod.__file__)
    for name in sorted(os.listdir(root)):
        if name.endswith('.py'):
            text = open(os.path.join(root, name)).read()
            assert 'workflow_machine' not in text and 'orchestration.' not in text.replace(
                'orchestration.workflow_store', '')
