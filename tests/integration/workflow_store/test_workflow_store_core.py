"""Developer tests for the durable workflow event store. Not independent acceptance cases."""
import hashlib
import json
import os
import stat
import threading

import pytest

from orchestration import workflow_store as ws
from orchestration.workflow_store import canonical

TS = '2026-01-01T00:00:00Z'  # opaque caller-supplied text; the store never parses it


def rec(kind='workflow.proposed', body=None, ts=TS):
    return {'kind': kind, 'timestamp': ts, 'body': {} if body is None else body}


@pytest.fixture
def store(tmp_path):
    root = tmp_path / 'store'
    root.mkdir()
    return ws.Store(root)


def make(store, wid='wf1', n=0, owner='w1'):
    path = store.create_workflow(wid)
    if n:
        store.acquire(wid, owner=owner, timestamp=TS)
        for i in range(n):
            store.append(wid, rec(body={'i': i}), owner=owner)
        store.release(wid, owner=owner)
    return path


def refusal(code, fn, *a, **kw):
    with pytest.raises(ws.StoreRefusal) as info:
        fn(*a, **kw)
    assert info.value.code == code, str(info.value)
    return info.value


def read(path):
    with open(path, 'rb') as f:
        return f.read()


# --- positive ---------------------------------------------------------------------------

def test_append_load_roundtrip_in_order(store):
    path = make(store, n=3)
    loaded = store.load('wf1')
    assert [e['sequence'] for e in loaded.events] == [1, 2, 3]
    assert loaded.events[0]['predecessor'] is None
    assert loaded.events[1]['predecessor'] == loaded.events[0]['digest']
    assert loaded.events[2]['predecessor'] == loaded.events[1]['digest']
    assert loaded.head_sequence == 3 and loaded.head_digest == loaded.events[2]['digest']
    assert sorted(os.listdir(path)) == ['000001.json', '000002.json', '000003.json']
    assert all(e['workflow_id'] == 'wf1' and e['profile'] == 'ocs-workflow-event/0' for e in loaded.events)


def test_empty_workflow_loads_empty(store):
    make(store)
    loaded = store.load('wf1')
    assert loaded.events == () and loaded.head_sequence == 0 and loaded.head_digest is None


def test_event_digest_is_over_canonical_bytes_without_digest(store):
    path = make(store, n=1)
    data = read(os.path.join(path, '000001.json'))
    obj = json.loads(data)
    body = {k: v for k, v in obj.items() if k != 'digest'}
    assert obj['digest'] == 'sha256:' + hashlib.sha256(canonical.jcs_bytes(body)).hexdigest()
    assert data == canonical.jcs_bytes(obj)


def test_restart_new_store_object_continues_chain(store, tmp_path):
    make(store, n=2)
    again = ws.Store(store.root)  # a restart: nothing is held in memory
    again.acquire('wf1', owner='w2', timestamp=TS)
    third = again.append('wf1', rec(body={'k': 'v'}), owner='w2')
    again.release('wf1', owner='w2')
    assert third['sequence'] == 3
    assert [e['sequence'] for e in again.load('wf1').events] == [1, 2, 3]


def test_returned_event_and_loaded_events_are_detached_copies(store):
    make(store, n=1)
    loaded = store.load('wf1')
    loaded.events[0]['body']['x'] = 1
    assert 'x' not in store.load('wf1').events[0]['body']
    body = {'a': [1, 2]}
    store.acquire('wf1', owner='w1', timestamp=TS)
    store.append('wf1', rec(body=body), owner='w1')
    body['a'].append(3)
    assert store.load('wf1').events[1]['body'] == {'a': [1, 2]}


def test_expected_head_accepts_matching_and_progress(store):
    make(store, n=2)
    head = store.load('wf1')
    store.acquire('wf1', owner='w1', timestamp=TS)
    store.append('wf1', rec(), owner='w1')
    store.release('wf1', owner='w1')
    assert store.load('wf1', expected_head=(head.head_sequence, head.head_digest)).head_sequence == 3


def test_opaque_timestamp_is_stored_verbatim_and_never_parsed(store):
    make(store)
    store.acquire('wf1', owner='w1', timestamp='not a date at all')
    store.append('wf1', rec(ts='tomorrow-ish'), owner='w1')
    assert store.load('wf1').events[0]['timestamp'] == 'tomorrow-ish'


def test_workflows_listing_and_independent_chains(store):
    make(store, 'a', 1)
    make(store, 'b', 2)
    assert store.workflows() == ['a', 'b']
    assert store.load('a').head_sequence == 1 and store.load('b').head_sequence == 2
    assert store.load('a').events[0]['digest'] != store.load('b').events[0]['digest']


# --- canonical JSON and strict loading --------------------------------------------------

def test_canonical_vectors():
    assert canonical.jcs_dumps({'b': 1, 'a': [True, None, 'x']}) == '{"a":[true,null,"x"],"b":1}'
    assert canonical.jcs_dumps('€\x01"\\\n') == '"€\\u0001\\"\\\\\\n"'
    # UTF-16 code unit order: U+10000 (surrogates D800..) sorts before U+FFFF
    assert canonical.jcs_dumps({'￿': 1, '\U00010000': 2}) == '{"\U00010000":2,"￿":1}'
    assert canonical.jcs_dumps(-0) == '0'
    for bad in (1.5, (1,), {1: 2}, 2 ** 53, '\ud800', {'a': float('nan')}):
        with pytest.raises(ValueError):
            canonical.jcs_dumps(bad)


def test_strict_loader_refuses_duplicates_floats_constants():
    assert canonical.loads_strict('{"a":1}') == {'a': 1}
    for bad in ('{"a":1,"a":2}', '{"a":1.0}', '{"a":1e3}', '{"a":NaN}', '[Infinity]'):
        with pytest.raises(ValueError):
            canonical.loads_strict(bad)
    with pytest.raises(json.JSONDecodeError):
        canonical.loads_strict('{"a":')


def test_append_refuses_floats_and_nonjson_values(store):
    make(store)
    store.acquire('wf1', owner='w1', timestamp=TS)
    for body in ({'x': 1.5}, {'x': (1, 2)}, {'x': {1: 2}}, {'x': 2 ** 60}, {'x': {2: 1}}, {'x': b'a'}, {'x': {1}}):
        refusal('schema_invalid', store.append, 'wf1', rec(body=body), owner='w1')
    deep = {}
    cur = deep
    for _ in range(40):
        cur['n'] = {}
        cur = cur['n']
    refusal('schema_invalid', store.append, 'wf1', rec(body=deep), owner='w1')
    assert store.load('wf1').events == ()


def _rewrite_final(path, name, obj=None, raw=None):
    target = os.path.join(path, name)
    os.chmod(path, 0o700)
    os.chmod(target, 0o644)
    data = raw if raw is not None else canonical.jcs_bytes(obj)
    with open(target, 'wb') as f:
        f.write(data)


def _resign(obj):
    obj['digest'] = canonical.object_digest(obj)
    return obj


def test_load_refuses_duplicate_key_and_float_in_stored_event(store):
    path = make(store, n=2)
    good = read(os.path.join(path, '000002.json')).decode()
    dup = good.replace('"kind":', '"kind":"x","kind":', 1)
    _rewrite_final(path, '000002.json', raw=dup.encode())
    refusal('noncanonical_event', store.load, 'wf1')
    flt = good.replace('"sequence":2', '"sequence":2.0')
    _rewrite_final(path, '000002.json', raw=flt.encode())
    refusal('noncanonical_event', store.load, 'wf1')


def test_load_refuses_noncanonical_but_valid_json(store):
    path = make(store, n=2)
    obj = json.loads(read(os.path.join(path, '000002.json')))
    _rewrite_final(path, '000002.json', raw=json.dumps(obj, indent=2).encode())
    refusal('noncanonical_event', store.load, 'wf1')


# --- tamper, reorder, gaps, truncation --------------------------------------------------

def test_tampered_body_detected_as_digest_mismatch(store):
    path = make(store, n=3)
    obj = json.loads(read(os.path.join(path, '000002.json')))
    obj['body']['i'] = 99
    _rewrite_final(path, '000002.json', obj)
    e = refusal('digest_mismatch', store.load, 'wf1')
    assert e.detail['sequence'] == 2


def test_resigned_tamper_breaks_the_successor_link(store):
    path = make(store, n=3)
    obj = json.loads(read(os.path.join(path, '000002.json')))
    obj['body']['i'] = 99
    _rewrite_final(path, '000002.json', _resign(obj))
    e = refusal('chain_broken', store.load, 'wf1')
    assert e.detail['sequence'] == 3


def test_tampered_first_event_resigned_breaks_event_two(store):
    path = make(store, n=2)
    obj = json.loads(read(os.path.join(path, '000001.json')))
    obj['kind'] = 'workflow.other'
    _rewrite_final(path, '000001.json', _resign(obj))
    refusal('chain_broken', store.load, 'wf1')


def test_reordered_files_detected(store):
    path = make(store, n=3)
    a, b = os.path.join(path, '000002.json'), os.path.join(path, '000003.json')
    da, db = read(a), read(b)
    os.chmod(a, 0o644)
    os.chmod(b, 0o644)
    open(a, 'wb').write(db)
    open(b, 'wb').write(da)
    refusal('sequence_mismatch', store.load, 'wf1')


def test_reordered_with_renumbering_detected_as_chain_broken(store):
    path = make(store, n=3)
    e2 = json.loads(read(os.path.join(path, '000002.json')))
    e3 = json.loads(read(os.path.join(path, '000003.json')))
    e2['sequence'], e3['sequence'] = 3, 2
    _rewrite_final(path, '000002.json', _resign(e3))
    _rewrite_final(path, '000003.json', _resign(e2))
    refusal('chain_broken', store.load, 'wf1')


def test_gap_in_sequence_detected(store):
    path = make(store, n=3)
    os.unlink(os.path.join(path, '000002.json'))
    refusal('sequence_gap', store.load, 'wf1')


def test_missing_first_event_is_a_gap(store):
    path = make(store, n=2)
    os.unlink(os.path.join(path, '000001.json'))
    refusal('sequence_gap', store.load, 'wf1')


def test_truncation_detected_against_caller_held_head(store):
    path = make(store, n=3)
    head = store.load('wf1')
    os.unlink(os.path.join(path, '000003.json'))
    assert store.load('wf1').head_sequence == 2  # not detectable without an anchor
    e = refusal('truncated', store.load, 'wf1', expected_head=(head.head_sequence, head.head_digest))
    assert e.detail == {'have': 2, 'expected': 3}


def test_head_digest_mismatch_detected(store):
    make(store, n=2)
    refusal('chain_broken', store.load, 'wf1', expected_head=(2, 'sha256:' + '0' * 64))


def test_bad_expected_head_form(store):
    make(store, n=1)
    refusal('schema_invalid', store.load, 'wf1', expected_head='x')
    refusal('schema_invalid', store.load, 'wf1', expected_head=(0, 'sha256:' + '0' * 64))


def test_corrupt_middle_event_is_not_treated_as_torn(store):
    path = make(store, n=3)
    _rewrite_final(path, '000002.json', raw=b'{"half":')
    e = refusal('event_corrupt', store.load, 'wf1')
    assert e.detail['sequence'] == 2


def test_event_from_another_workflow_refused(store):
    pa = make(store, 'a', 1)
    pb = make(store, 'b', 1)
    _rewrite_final(pb, '000001.json', raw=read(os.path.join(pa, '000001.json')))
    refusal('workflow_id_mismatch', store.load, 'b')


def test_unknown_file_and_symlink_refused(store, tmp_path):
    path = make(store, n=1)
    open(os.path.join(path, 'notes.txt'), 'w').write('x')
    refusal('unexpected_file', store.load, 'wf1')
    os.unlink(os.path.join(path, 'notes.txt'))
    outside = tmp_path / 'outside.json'
    outside.write_bytes(read(os.path.join(path, '000001.json')))
    os.unlink(os.path.join(path, '000001.json'))
    os.symlink(outside, os.path.join(path, '000001.json'))
    refusal('path_escape', store.load, 'wf1')


def test_symlinked_workflow_directory_refused(store, tmp_path):
    real = tmp_path / 'elsewhere'
    real.mkdir()
    os.symlink(real, os.path.join(store.root, 'wf9'))
    refusal('path_escape', ws.load, os.path.join(store.root, 'wf9'))
    refusal('path_escape', store.load, 'wf9')


def test_directory_in_place_of_event_file_refused(store):
    path = make(store, n=1)
    os.unlink(os.path.join(path, '000001.json'))
    os.mkdir(os.path.join(path, '000001.json'))
    refusal('unexpected_file', store.load, 'wf1')


def test_load_of_missing_workflow(store):
    refusal('workflow_not_found', store.load, 'nope')
    refusal('workflow_not_found', ws.load, os.path.join(store.root, 'nope'))


# --- workflow ids and path traversal ----------------------------------------------------

@pytest.mark.parametrize('bad', ['', '.', '..', '../x', 'a/b', '/abs', 'a\\b', '.hidden', 'a b', 'x' * 65,
                                 '-lead', '_lead', 'a\x00b', 'a.b', 'wf\n', 'ünï'])
def test_invalid_workflow_ids_refused_everywhere(store, bad):
    refusal('invalid_workflow_id', store.create_workflow, bad)
    refusal('invalid_workflow_id', store.workflow_dir, bad)
    refusal('invalid_workflow_id', store.load, bad)
    refusal('invalid_workflow_id', store.acquire, bad, owner='w1', timestamp=TS)
    refusal('invalid_workflow_id', store.append, bad, rec(), owner='w1')


def test_non_string_workflow_id_refused(store):
    refusal('invalid_workflow_id', store.create_workflow, None)
    refusal('invalid_workflow_id', store.create_workflow, 5)


def test_traversal_creates_nothing_outside_root(store, tmp_path):
    refusal('invalid_workflow_id', store.create_workflow, '../escape')
    assert sorted(os.listdir(tmp_path)) == ['store']
    assert store.workflows() == []


def test_module_load_refuses_directory_with_bad_name(tmp_path):
    d = tmp_path / '.bad'
    d.mkdir()
    refusal('invalid_workflow_id', ws.load, d)


def test_store_root_must_be_real_directory(tmp_path):
    refusal('io_failure', ws.Store, tmp_path / 'missing')
    f = tmp_path / 'file'
    f.write_text('x')
    refusal('path_escape', ws.Store, f)
    real = tmp_path / 'real'
    real.mkdir()
    os.symlink(real, tmp_path / 'link')
    refusal('path_escape', ws.Store, tmp_path / 'link')


def test_duplicate_workflow_refused(store):
    store.create_workflow('wf1')
    refusal('workflow_exists', store.create_workflow, 'wf1')


# --- permission bits --------------------------------------------------------------------

def test_permission_bits(store):
    path = make(store, n=1)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(os.path.join(path, '000001.json')).st_mode) == 0o444
    store.acquire('wf1', owner='w1', timestamp=TS)
    assert stat.S_IMODE(os.stat(os.path.join(path, 'LOCK')).st_mode) == 0o600
    store.release('wf1', owner='w1')


def test_recovery_directories_have_private_mode(store):
    path = make(store, n=1)
    os.chmod(path, 0o700)
    open(os.path.join(path, '000002.json'), 'wb').write(b'{"x')
    store.acquire('wf1', owner='w1', timestamp=TS)
    store.recover('wf1', owner='w1', timestamp=TS)
    q = os.path.join(path, 'quarantine')
    assert stat.S_IMODE(os.stat(q).st_mode) == 0o700
    sub = os.path.join(q, os.listdir(q)[0])
    assert stat.S_IMODE(os.stat(sub).st_mode) == 0o700


# --- bounds -----------------------------------------------------------------------------

def test_max_events_per_workflow(tmp_path):
    (tmp_path / 's').mkdir()
    s = ws.Store(tmp_path / 's', ws.Bounds(max_events=3, max_event_bytes=4096, max_workflows=2))
    s.create_workflow('a')
    s.acquire('a', owner='w1', timestamp=TS)
    for _ in range(3):
        s.append('a', rec(), owner='w1')
    refusal('workflow_full', s.append, 'a', rec(), owner='w1')
    assert s.load('a').head_sequence == 3


def test_load_refuses_more_events_than_bound(tmp_path, store):
    make(store, n=5)
    small = ws.Store(store.root, ws.Bounds(max_events=3))
    refusal('workflow_full', small.load, 'wf1')


def test_max_event_size(tmp_path):
    (tmp_path / 's').mkdir()
    s = ws.Store(tmp_path / 's', ws.Bounds(max_event_bytes=600))
    s.create_workflow('a')
    s.acquire('a', owner='w1', timestamp=TS)
    s.append('a', rec(body={'x': 'y' * 10}), owner='w1')
    e = refusal('event_too_large', s.append, 'a', rec(body={'x': 'y' * 600}), owner='w1')
    assert e.detail['size'] > 600
    assert s.load('a').head_sequence == 1
    assert sorted(os.listdir(s.workflow_dir('a'))) == ['000001.json', 'LOCK']  # nothing left behind


def test_oversized_file_on_load_refused(store):
    path = make(store, n=1)
    small = ws.Store(store.root, ws.Bounds(max_event_bytes=100))
    refusal('event_too_large', small.load, 'wf1')


def test_max_workflows_per_store(tmp_path):
    (tmp_path / 's').mkdir()
    s = ws.Store(tmp_path / 's', ws.Bounds(max_workflows=2))
    s.create_workflow('a')
    s.create_workflow('b')
    refusal('store_full', s.create_workflow, 'c')
    assert s.workflows() == ['a', 'b']


@pytest.mark.parametrize('kw', [{'max_events': 0}, {'max_events': ws.store.CEILING_EVENTS + 1},
                                {'max_event_bytes': -1}, {'max_event_bytes': ws.store.CEILING_EVENT_BYTES + 1},
                                {'max_workflows': 0}, {'max_workflows': True and 1.5}, {'max_events': '5'}])
def test_bounds_must_be_within_ceilings(kw):
    refusal('bounds_invalid', ws.Bounds, **kw)


def test_store_requires_bounds_object(tmp_path):
    refusal('bounds_invalid', ws.Store, tmp_path, {'max_events': 3})


# --- envelope refusals ------------------------------------------------------------------

@pytest.mark.parametrize('name', ['verdict', 'pin', 'grant', 'authority'])
def test_forbidden_members_refused_by_name(store, name):
    make(store)
    store.acquire('wf1', owner='w1', timestamp=TS)
    for record in ({**rec(), name: 'x'}, rec(body={name: 1}), rec(body={'a': {'b': [{name: True}]}}),
                   {**rec(), name: None}):
        e = refusal('forbidden_member', store.append, 'wf1', record, owner='w1')
        assert name in str(e)
    assert store.load('wf1').events == ()


def test_forbidden_name_is_exact_so_references_are_allowed(store):
    make(store)
    store.acquire('wf1', owner='w1', timestamp=TS)
    store.append('wf1', rec(body={'grant_id': 'g1', 'decision_id': 'd1', 'pin_ref': 'x'}), owner='w1')


def test_forbidden_member_in_stored_event_refused_on_load(store):
    path = make(store, n=1)
    obj = json.loads(read(os.path.join(path, '000001.json')))
    obj['body']['verdict'] = 'pass'
    _rewrite_final(path, '000001.json', _resign(obj))
    refusal('forbidden_member', store.load, 'wf1')


def test_envelope_must_have_exactly_kind_timestamp_body(store):
    make(store)
    store.acquire('wf1', owner='w1', timestamp=TS)
    for bad in ({'kind': 'a', 'timestamp': TS}, {**rec(), 'extra': 1}, [], 'x', None,
                {'kind': 'a', 'timestamp': TS, 'body': []}, {'kind': 'a', 'timestamp': TS, 'body': None}):
        refusal('schema_invalid', store.append, 'wf1', bad, owner='w1')


@pytest.mark.parametrize('kind', ['', 'Upper', '1x', 'a b', 'x' * 65, None, 5, 'a/b'])
def test_bad_kind_refused(store, kind):
    make(store)
    store.acquire('wf1', owner='w1', timestamp=TS)
    refusal('schema_invalid', store.append, 'wf1', rec(kind=kind), owner='w1')


@pytest.mark.parametrize('ts', ['', '   ', None, 5, 'x' * 65])
def test_bad_timestamp_refused(store, ts):
    make(store)
    store.acquire('wf1', owner='w1', timestamp=TS)
    refusal('schema_invalid', store.append, 'wf1', rec(ts=ts), owner='w1')


def test_reserved_kind_refused(store):
    make(store)
    store.acquire('wf1', owner='w1', timestamp=TS)
    refusal('reserved_kind', store.append, 'wf1', rec(kind='store.lock_broken'), owner='w1')
    refusal('reserved_kind', store.append, 'wf1', rec(kind='store.anything'), owner='w1')


@pytest.mark.parametrize('owner', ['', '../x', 'a b', None, 'x' * 129, '-a', 'a/b'])
def test_invalid_owner_token_refused(store, owner):
    make(store)
    refusal('invalid_owner', store.acquire, 'wf1', owner=owner, timestamp=TS)
    refusal('invalid_owner', store.append, 'wf1', rec(), owner=owner)
    refusal('invalid_owner', store.release, 'wf1', owner=owner)


def test_acquire_needs_timestamp(store):
    make(store)
    refusal('schema_invalid', store.acquire, 'wf1', owner='w1', timestamp='')


def test_refusal_codes_are_a_closed_set():
    with pytest.raises(ValueError):
        ws.StoreRefusal('not_a_code')
    assert 'verdict' not in ws.CODES


# --- locking ----------------------------------------------------------------------------

def test_append_requires_lock(store):
    make(store)
    refusal('lock_not_held', store.append, 'wf1', rec(), owner='w1')
    store.acquire('wf1', owner='w1', timestamp=TS)
    refusal('lock_owner_mismatch', store.append, 'wf1', rec(), owner='w2')


def test_second_acquire_refused_and_never_steals(store):
    make(store)
    store.acquire('wf1', owner='w1', timestamp=TS)
    e = refusal('lock_held', store.acquire, 'wf1', owner='w2', timestamp='later')
    assert e.detail['holder'] == {'owner': 'w1', 'timestamp': TS}
    refusal('lock_held', store.acquire, 'wf1', owner='w1', timestamp=TS)
    assert store.read_lock('wf1') == {'owner': 'w1', 'timestamp': TS}
    assert [n for n in os.listdir(store.workflow_dir('wf1')) if n.startswith('.tmp')] == []


def test_release_requires_holder(store):
    make(store)
    refusal('lock_not_held', store.release, 'wf1', owner='w1')
    store.acquire('wf1', owner='w1', timestamp=TS)
    refusal('lock_owner_mismatch', store.release, 'wf1', owner='w2')
    store.release('wf1', owner='w1')
    assert store.read_lock('wf1') is None
    store.acquire('wf1', owner='w2', timestamp=TS)


def test_lock_contention_threads_exactly_one_winner(store):
    make(store)
    barrier = threading.Barrier(8)
    results = []

    def worker(i):
        barrier.wait()
        try:
            store.acquire('wf1', owner='w%d' % i, timestamp=TS)
            results.append(('won', i))
        except ws.StoreRefusal as exc:
            results.append((exc.code, i))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    won = [i for r, i in results if r == 'won']
    assert len(won) == 1 and {r for r, _ in results if r != 'won'} == {'lock_held'}
    assert store.read_lock('wf1')['owner'] == 'w%d' % won[0]


def test_lock_contention_across_processes(store):
    make(store)
    path = store.workflow_dir('wf1')
    pids = []
    for i in range(4):
        pid = os.fork()
        if pid == 0:
            code = 3
            try:
                ws.acquire(path, owner='p%d' % i, timestamp=TS)
                code = 0
            except ws.StoreRefusal as exc:
                code = 1 if exc.code == 'lock_held' else 2
            os._exit(code)
        pids.append(pid)
    codes = [os.waitstatus_to_exitcode(os.waitpid(p, 0)[1]) for p in pids]
    assert sorted(codes) == [0, 1, 1, 1]


def test_corrupt_lock_file_is_reported_not_overwritten(store):
    path = make(store)
    open(os.path.join(path, 'LOCK'), 'wb').write(b'garbage')
    refusal('lock_corrupt', store.read_lock, 'wf1')
    refusal('lock_corrupt', store.append, 'wf1', rec(), owner='w1')
    refusal('lock_held', store.acquire, 'wf1', owner='w1', timestamp=TS)
    refusal('lock_corrupt', store.break_lock, 'wf1', expected_owner='w1', breaker='w2', reason='r', timestamp=TS)
    assert read(os.path.join(path, 'LOCK')) == b'garbage'


def test_stale_lock_is_never_stolen_implicitly(store):
    make(store, n=1)
    store.acquire('wf1', owner='dead', timestamp='old')
    # holder never releases (process died): every ordinary path keeps refusing
    refusal('lock_held', store.acquire, 'wf1', owner='w2', timestamp='new')
    refusal('lock_owner_mismatch', store.append, 'wf1', rec(), owner='w2')
    refusal('lock_owner_mismatch', store.release, 'wf1', owner='w2')
    refusal('lock_owner_mismatch', store.recover, 'wf1', owner='w2', timestamp=TS)
    assert store.read_lock('wf1')['owner'] == 'dead'
    assert store.load('wf1').head_sequence == 1


def test_break_lock_records_event_and_hands_over(store):
    make(store, n=1)
    store.acquire('wf1', owner='dead', timestamp='old')
    event = store.break_lock('wf1', expected_owner='dead', breaker='w2', reason='holder process gone',
                             timestamp='new')
    assert event['kind'] == 'store.lock_broken' and event['sequence'] == 2
    assert event['body'] == {'broken_owner': 'dead', 'broken_lock_timestamp': 'old', 'breaker': 'w2',
                             'reason': 'holder process gone'}
    assert store.read_lock('wf1') == {'owner': 'w2', 'timestamp': 'new'}
    store.append('wf1', rec(), owner='w2')
    refusal('lock_owner_mismatch', store.append, 'wf1', rec(), owner='dead')
    loaded = store.load('wf1')
    assert [e['kind'] for e in loaded.events] == ['workflow.proposed', 'store.lock_broken', 'workflow.proposed']
    assert [n for n in os.listdir(store.workflow_dir('wf1')) if n.startswith('.tmp')] == []


def test_break_lock_refusals(store):
    make(store, n=1)
    refusal('lock_not_held', store.break_lock, 'wf1', expected_owner='x', breaker='w2', reason='r', timestamp=TS)
    store.acquire('wf1', owner='dead', timestamp='old')
    refusal('lock_owner_mismatch', store.break_lock, 'wf1', expected_owner='other', breaker='w2', reason='r',
            timestamp=TS)
    refusal('schema_invalid', store.break_lock, 'wf1', expected_owner='dead', breaker='w2', reason='',
            timestamp=TS)
    refusal('invalid_owner', store.break_lock, 'wf1', expected_owner='dead', breaker='../x', reason='r',
            timestamp=TS)
    assert store.read_lock('wf1')['owner'] == 'dead' and store.load('wf1').head_sequence == 1


def test_break_lock_refused_when_log_has_torn_tail_unless_explicit(store):
    path = make(store, n=1)
    store.acquire('wf1', owner='dead', timestamp='old')
    open(os.path.join(path, '000002.json'), 'wb').write(b'{"profile":"ocs')
    refusal('torn_tail', store.break_lock, 'wf1', expected_owner='dead', breaker='w2', reason='r', timestamp=TS)
    assert store.read_lock('wf1')['owner'] == 'dead'  # nothing changed
    event = store.break_lock('wf1', expected_owner='dead', breaker='w2', reason='r', timestamp=TS,
                             recover_torn=True)
    kinds = [e['kind'] for e in store.load('wf1').events]
    assert kinds == ['workflow.proposed', 'store.torn_tail_quarantined', 'store.lock_broken']
    assert event['sequence'] == 3


def test_break_lock_with_no_room_refuses_before_changing_anything(tmp_path):
    (tmp_path / 's').mkdir()
    s = ws.Store(tmp_path / 's', ws.Bounds(max_events=2))
    s.create_workflow('a')
    s.acquire('a', owner='dead', timestamp='old')
    s.append('a', rec(), owner='dead')
    refusal('workflow_full', s.break_lock, 'a', expected_owner='dead', breaker='w2', reason='r', timestamp=TS)
    assert s.read_lock('a')['owner'] == 'dead'


def test_threads_appending_under_lock_keep_a_valid_chain(store):
    make(store)
    store.acquire('wf1', owner='w1', timestamp=TS)
    errors = []

    def worker(i):
        try:
            store.append('wf1', rec(body={'i': i}), owner='w1')
        except Exception as exc:  # the single owner token is shared; races must not corrupt
            errors.append(exc)

    # serialize via a Python lock: the file lock is per owner token, not per thread
    guard = threading.Lock()

    def guarded(i):
        with guard:
            worker(i)

    threads = [threading.Thread(target=guarded, args=(i,)) for i in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and store.load('wf1').head_sequence == 10
