"""Archival tests for the workflow event store (step 3.2-A). Developer tests only.

Archival is a move of a closed workflow directory, never a deletion. These tests pin: what is refused, the
crash-safe ordering and its recoverable states, that an archived workflow still validates unchanged, and that
the live store's workflow count (the slot-like resource it owns) is released by archival."""
import os
import types

import pytest

from orchestration import workflow_store as ws
from orchestration.workflow_store import store as store_mod

TS = '2026-01-01T00:00:00Z'
TERMINAL = {'observed': 'completed', 'reconciled': 'completed', 'failed': 'failed', 'cancelled': 'cancelled'}


def rec(kind='workflow.event', body=None):
    return {'kind': kind, 'timestamp': TS, 'body': {} if body is None else body}


class Crash(BaseException):
    """Simulated process death: not an Exception, so no handler in the store runs to completion."""


def refusal(code, fn, *a, **kw):
    with pytest.raises(ws.StoreRefusal) as info:
        fn(*a, **kw)
    assert info.value.code == code, str(info.value)
    return info.value


@pytest.fixture
def store(tmp_path):
    (tmp_path / 'live').mkdir()
    (tmp_path / 'archive').mkdir()
    return ws.Store(tmp_path / 'live', archive_root=tmp_path / 'archive')


def seeded(store, wid='wf1', n=3, hold=True):
    store.create_workflow(wid)
    store.acquire(wid, owner='w1', timestamp=TS)
    for i in range(n):
        store.append(wid, rec(body={'i': i}), owner='w1')
    if not hold:
        store.release(wid, owner='w1')
    return store.workflow_dir(wid)


def head(store, wid='wf1'):
    loaded = store.load(wid)
    return loaded.head_sequence, loaded.head_digest


def do_archive(store, wid='wf1', status='cancelled', **kw):
    return store.archive(wid, owner='w1', timestamp=TS, closure_class=TERMINAL[status], terminal_status=status,
                         expected_head=kw.pop('expected_head', head(store, wid)), **kw)


def event_bytes(path):
    return {n: open(os.path.join(path, n), 'rb').read() for n in sorted(os.listdir(path)) if n.endswith('.json')}


# --- happy path: a move, not a deletion -----------------------------------------------------

def test_archive_moves_the_directory_keeps_every_event_byte_and_writes_a_receipt(store, tmp_path):
    path = seeded(store, n=3)
    before = event_bytes(path)
    pre_head = head(store)
    receipt = do_archive(store, status='observed')
    assert not os.path.lexists(path) and store.workflows() == []
    archived = str(tmp_path / 'archive' / 'wf1')
    after = event_bytes(archived)
    assert {k: v for k, v in after.items() if k in before} == before  # events 1..3 byte-identical
    assert sorted(after) == sorted(before) + ['000004.json']  # plus exactly the intent
    assert 'LOCK' not in os.listdir(archived)  # the caller's own lock is dropped
    loaded = ws.load(archived)
    assert [e['kind'] for e in loaded.events][-1] == 'store.archive_intent'
    body = loaded.events[-1]['body']
    assert body == {'head_sequence': 3, 'head_digest': pre_head[1], 'closure_class': 'completed',
                    'terminal_status': 'observed', 'external_checkpoint': {'status': 'not_retained'}}
    assert receipt['head_sequence'] == 3 and receipt['head_digest'] == pre_head[1]
    assert receipt['profile'] == 'ocs-workflow-archive-receipt/0' and receipt['event_count'] == 4
    # the pre-archive head still verifies against the archived log (truncation detection unchanged)
    assert ws.load(archived, expected_head=pre_head).head_sequence == 4
    info = store.verify_archive('wf1')
    assert info['receipt'] == 'agrees' and info['terminal_status'] == 'observed'
    assert ws.inspect(archived) == []  # a receipt beside the directory: nothing to report


def test_archival_releases_the_live_workflow_slot_it_is_not_a_leak(tmp_path):
    (tmp_path / 'live').mkdir()
    (tmp_path / 'archive').mkdir()
    s = ws.Store(tmp_path / 'live', ws.Bounds(max_workflows=2), archive_root=tmp_path / 'archive')
    for wid in ('a', 'b'):
        seeded(s, wid=wid, n=1)
    refusal('store_full', s.create_workflow, 'c')
    do_archive(s, 'a', status='failed')
    assert s.workflows() == ['b']
    s.create_workflow('c')
    assert s.workflows() == ['b', 'c']
    refusal('archive_exists', s.create_workflow, 'a')  # an id archived under this archive root is not reused


def test_external_checkpoint_is_recorded_as_declared_and_never_verified(store):
    seeded(store)
    r = do_archive(store, external_checkpoint_ref='custodian-ckpt-17')
    assert r['external_checkpoint'] == {'status': 'caller_declared', 'ref': 'custodian-ckpt-17'}
    seeded(store, wid='wf2')
    refusal('schema_invalid', store.archive, 'wf2', owner='w1', timestamp=TS, closure_class='cancelled',
            terminal_status='cancelled', expected_head=head(store, 'wf2'), external_checkpoint_ref=5)
    assert do_archive(store, 'wf2')['external_checkpoint'] == {'status': 'not_retained'}


# --- refusals (negative controls); a refusal records nothing ----------------------------------

@pytest.mark.parametrize('status', ['initial', 'proposed', 'awaiting_authority', 'authorized', 'dispatched',
                                    'unresolved', 'suspended', 'completed', 'open', '', 'Observed'])
def test_every_non_terminal_or_unknown_status_name_is_not_archivable(store, status):
    path = seeded(store)
    names = os.listdir(path)
    for closure in ('completed', 'failed', 'cancelled', 'open'):
        refusal('not_archivable', store.archive, 'wf1', owner='w1', timestamp=TS, closure_class=closure,
                terminal_status=status, expected_head=head(store))
    assert os.listdir(path) == names and store.load('wf1').head_sequence == 3  # nothing was recorded


def test_closure_class_must_match_the_terminal_status_and_be_text(store):
    seeded(store)
    for status, closure in (('observed', 'failed'), ('failed', 'completed'), ('cancelled', 'completed'),
                            ('reconciled', 'cancelled'), ('observed', None), (None, 'completed'), (3, 3)):
        refusal('not_archivable', store.archive, 'wf1', owner='w1', timestamp=TS, closure_class=closure,
                terminal_status=status, expected_head=head(store))


def test_head_must_be_the_log_head_so_a_stale_replay_cannot_archive(store):
    seeded(store)
    h = head(store)
    store.append('wf1', rec(body={'late': True}), owner='w1')  # an event after the state the caller replayed
    refusal('not_archivable', do_archive, store, expected_head=h)
    refusal('chain_broken', do_archive, store, expected_head=(3, 'sha256:' + '0' * 64))
    refusal('truncated', do_archive, store, expected_head=(9, h[1]))
    refusal('schema_invalid', do_archive, store, expected_head=[4, 'x'])
    refusal('schema_invalid', do_archive, store, expected_head=None)
    assert store.load('wf1').head_sequence == 4


def test_archive_needs_events_and_the_callers_own_lock(store):
    store.create_workflow('empty')
    store.acquire('empty', owner='w1', timestamp=TS)
    refusal('not_archivable', store.archive, 'empty', owner='w1', timestamp=TS, closure_class='cancelled',
            terminal_status='cancelled', expected_head=(1, 'sha256:' + '0' * 64))
    seeded(store, hold=False)
    refusal('lock_not_held', do_archive, store)
    store.acquire('wf1', owner='other', timestamp=TS)
    refusal('lock_owner_mismatch', do_archive, store)
    assert 'wf1' in store.workflows()


@pytest.mark.parametrize('damage,code', [('torn', 'torn_tail'), ('temp', 'leftover_temp'),
                                          ('quarantine', 'unrecorded_quarantine')])
def test_archive_refuses_an_unclean_workflow_and_records_no_intent(store, damage, code):
    path = seeded(store)
    h = head(store)
    if damage == 'torn':
        open(os.path.join(path, '000004.json'), 'wb').write(b'{"profile":')
    elif damage == 'temp':
        open(os.path.join(path, '.tmp.000004.json'), 'wb').write(b'x')
    else:
        os.mkdir(os.path.join(path, 'quarantine'))
        os.mkdir(os.path.join(path, 'quarantine', 'stray'))
    refusal(code, do_archive, store, expected_head=h)
    assert os.path.lexists(path) and 'wf1' in store.workflows()
    assert not os.path.lexists(os.path.join(path, '000005.json'))  # no intent event was written


def test_archive_root_must_be_a_separate_real_directory_on_the_same_filesystem(store, tmp_path, monkeypatch):
    path = seeded(store)
    h = head(store)
    live = str(tmp_path / 'live')
    bad = [live, os.path.join(live, 'inside'), str(tmp_path), str(tmp_path / 'missing')]
    os.mkdir(bad[1])
    link = tmp_path / 'link'
    os.symlink(str(tmp_path / 'archive'), link)
    bad.append(str(link))
    for root in bad:
        refusal('archive_root_invalid', ws.archive, path, root, owner='w1', timestamp=TS, closure_class='cancelled',
                terminal_status='cancelled', expected_head=h)
        refusal('archive_root_invalid', ws.Store, live, archive_root=root)
    refusal('archive_root_invalid', ws.archive, path, 5, owner='w1', timestamp=TS, closure_class='cancelled',
            terminal_status='cancelled', expected_head=h)
    # a different filesystem would make the rename a copy: refused before anything is written
    real = os.lstat

    def other_device(p, *a, **k):
        st = real(p, *a, **k)
        if os.path.abspath(os.fspath(p)) == str(tmp_path / 'archive'):
            return types.SimpleNamespace(st_mode=st.st_mode, st_dev=st.st_dev + 1)
        return st

    monkeypatch.setattr(os, 'lstat', other_device)
    refusal('archive_root_invalid', do_archive, store, expected_head=h)
    monkeypatch.undo()
    assert os.path.lexists(path) and store.load('wf1').head_sequence == 3  # no intent was written
    no_archive = ws.Store(tmp_path / 'live')
    refusal('archive_root_invalid', no_archive.archive, 'wf1', owner='w1', timestamp=TS, closure_class='cancelled',
            terminal_status='cancelled', expected_head=h)
    refusal('archive_root_invalid', no_archive.verify_archive, 'wf1')


def test_an_existing_archive_entry_blocks_the_move_before_the_intent(store, tmp_path):
    path = seeded(store)
    os.mkdir(tmp_path / 'archive' / 'wf1')
    refusal('archive_exists', do_archive, store)
    assert store.load('wf1').head_sequence == 3 and os.path.lexists(path)
    os.rmdir(tmp_path / 'archive' / 'wf1')
    open(tmp_path / 'archive' / 'wf1.receipt.json', 'wb').write(b'{}')
    refusal('archive_exists', do_archive, store)


def test_exhausted_recovery_reserve_makes_archival_refuse_rather_than_skip_the_intent(store, monkeypatch):
    monkeypatch.setattr(store_mod, 'RECOVERY_RESERVE', 0)
    small = ws.Store(store.root, ws.Bounds(max_events=3), archive_root=store.archive_root)
    path = seeded(small, n=3)
    refusal('workflow_full', do_archive, small)
    assert os.path.lexists(path) and small.load('wf1').head_sequence == 3


# --- the intent: the workflow accepts nothing after it ----------------------------------------

def test_crash_after_the_intent_and_before_the_move_is_reported_blocks_appends_and_is_repeatable(store, monkeypatch):
    path = seeded(store)
    h = head(store)

    def die(*a, **k):
        raise Crash()

    monkeypatch.setattr(os, 'rename', die)
    with pytest.raises(Crash):
        do_archive(store, status='cancelled', expected_head=h)
    monkeypatch.undo()
    assert os.path.lexists(path) and 'LOCK' in os.listdir(path)
    assert store.inspect('wf1') == [{'code': 'archive_incomplete', 'files': []}]
    refusal('archive_incomplete', store.append, 'wf1', rec(), owner='w1')  # no event after the intent
    assert store.load('wf1').head_sequence == 4  # still loads: the log is valid
    refusal('archive_incomplete', do_archive, store, status='failed', expected_head=h)  # different closure
    refusal('not_archivable', do_archive, store, status='cancelled', expected_head=(4, store.load('wf1').head_digest))
    receipt = do_archive(store, status='cancelled', expected_head=h)  # the same arguments finish it
    assert receipt['event_count'] == 4 and not os.path.lexists(path)
    assert store.verify_archive('wf1')['receipt'] == 'agrees'


def test_crash_after_the_move_before_the_receipt_is_finished_by_repeating_archive(store, tmp_path, monkeypatch):
    seeded(store)
    h = head(store)

    def die(*a, **k):
        raise Crash()

    monkeypatch.setattr(store_mod, '_write_receipt', die)
    with pytest.raises(Crash):
        do_archive(store, expected_head=h)
    monkeypatch.undo()
    archived = str(tmp_path / 'archive' / 'wf1')
    assert not os.path.lexists(store.workflow_dir('wf1')) and os.path.isdir(archived)
    assert store.verify_archive('wf1')['receipt'] == 'missing'  # reported, repairable from the log
    assert ws.load(archived, expected_head=h).head_sequence == 4
    refusal('workflow_not_found', store.archive, 'wf1', owner='w1', timestamp=TS, closure_class='cancelled',
            terminal_status='cancelled', expected_head=h)  # no live directory: use finish_archive
    receipt = store.finish_archive('wf1', owner='w1', timestamp=TS, closure_class='cancelled',
                                   terminal_status='cancelled', expected_head=h)
    assert receipt['head_sequence'] == 3 and store.verify_archive('wf1')['receipt'] == 'agrees'
    refusal('archive_exists', store.finish_archive, 'wf1', owner='w1', timestamp=TS, closure_class='cancelled',
            terminal_status='cancelled', expected_head=h)
    assert 'LOCK' not in os.listdir(archived)


def test_finishing_with_other_parameters_or_on_an_unarchived_directory_is_refused(store, tmp_path, monkeypatch):
    seeded(store)
    h = head(store)
    monkeypatch.setattr(store_mod, '_write_receipt', lambda *a, **k: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        do_archive(store, expected_head=h)
    monkeypatch.undo()
    kw = dict(owner='w1', timestamp=TS, expected_head=h)
    refusal('archive_incomplete', store.finish_archive, 'wf1', closure_class='failed', terminal_status='failed', **kw)
    refusal('not_archivable', store.finish_archive, 'wf1', closure_class='cancelled', terminal_status='cancelled',
            owner='w1', timestamp=TS, expected_head=(4, h[1]))
    os.mkdir(tmp_path / 'archive' / 'plain')  # a directory in the archive that never recorded an intent
    refusal('not_archivable', store.finish_archive, 'plain', closure_class='cancelled', terminal_status='cancelled',
            **kw)


def _crash_in_receipt_link(store, h, monkeypatch):
    real_link = os.link

    def die_on_receipt(src, dst, *a, **k):
        if str(dst).endswith('.receipt.json'):
            raise Crash()
        return real_link(src, dst, *a, **k)

    monkeypatch.setattr(os, 'link', die_on_receipt)
    with pytest.raises(Crash):
        do_archive(store, expected_head=h)
    monkeypatch.undo()


def test_our_own_stale_receipt_temporary_file_is_replaced_on_finish(store, tmp_path, monkeypatch):
    seeded(store)
    h = head(store)
    _crash_in_receipt_link(store, h, monkeypatch)
    tmp = tmp_path / 'archive' / '.tmp.wf1.receipt.json'
    assert tmp.exists() and store.verify_archive('wf1')['receipt'] == 'missing'
    kw = dict(owner='w1', timestamp=TS, closure_class='cancelled', terminal_status='cancelled', expected_head=h)
    assert store.finish_archive('wf1', **kw)['head_sequence'] == 3
    assert not tmp.exists() and store.verify_archive('wf1')['receipt'] == 'agrees'


def test_a_receipt_temporary_name_that_is_not_a_regular_file_is_reported_not_touched(store, tmp_path, monkeypatch):
    seeded(store)
    h = head(store)
    _crash_in_receipt_link(store, h, monkeypatch)
    tmp = tmp_path / 'archive' / '.tmp.wf1.receipt.json'
    tmp.unlink()
    tmp.mkdir()  # not ours: a directory under our temporary name
    kw = dict(owner='w1', timestamp=TS, closure_class='cancelled', terminal_status='cancelled', expected_head=h)
    refusal('leftover_temp', store.finish_archive, 'wf1', **kw)
    assert tmp.is_dir() and store.verify_archive('wf1')['receipt'] == 'missing'


def test_archive_root_symlinked_parent_cannot_land_inside_the_live_root(store, tmp_path):
    seeded(store)
    h = head(store)
    os.symlink(str(tmp_path / 'live'), str(tmp_path / 'alias'))
    inner = tmp_path / 'live' / 'inner'
    inner.mkdir()
    for root in (str(tmp_path / 'alias' / 'inner'), str(tmp_path / 'alias')):  # resolves into / onto the live root
        refusal('archive_root_invalid', ws.archive, store.workflow_dir('wf1'), root, owner='w1', timestamp=TS,
                closure_class='cancelled', terminal_status='cancelled', expected_head=h)
        refusal('archive_root_invalid', ws.Store, tmp_path / 'live', archive_root=root)
    assert store.load('wf1').head_sequence == 3  # nothing was written


def _crash_after_intent(store, h, monkeypatch):
    def die(*a, **k):
        raise Crash()

    monkeypatch.setattr(os, 'rename', die)
    with pytest.raises(Crash):
        do_archive(store, expected_head=h)
    monkeypatch.undo()


def test_a_second_intent_or_a_non_store_event_after_the_intent_is_not_archivable(store, monkeypatch):
    path = seeded(store)
    h = head(store)
    _crash_after_intent(store, h, monkeypatch)
    loaded = store.load('wf1')
    intent = loaded.events[-1]
    scan = store_mod._scan(path, ws.Bounds())
    with store_mod._mutex(path):  # forge, through the internal writer, what the public API never writes
        store_mod._append_locked(path, 'wf1', {'kind': 'workflow.late', 'timestamp': TS, 'body': {}}, ws.Bounds(),
                                 scan, reserved=False)
    refusal('not_archivable', do_archive, store, expected_head=h)
    # a second intent
    seeded(store, wid='wf2')
    h2 = head(store, 'wf2')
    _crash_after_intent_for(store, 'wf2', h2, monkeypatch)
    path2 = store.workflow_dir('wf2')
    scan = store_mod._scan(path2, ws.Bounds())
    with store_mod._mutex(path2):
        store_mod._append_locked(path2, 'wf2', {'kind': 'store.archive_intent', 'timestamp': TS,
                                                'body': dict(intent['body'])}, ws.Bounds(), scan, reserved=True)
    refusal('not_archivable', do_archive, store, 'wf2', expected_head=h2)
    refusal('archive_incomplete', ws.verify_archive, store.root, 'wf2')  # two intents: not a valid archive


def _crash_after_intent_for(store, wid, h, monkeypatch):
    monkeypatch.setattr(os, 'rename', lambda *a, **k: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        do_archive(store, wid, expected_head=h)
    monkeypatch.undo()


def test_a_malformed_intent_body_fails_closed_in_verify_archive(store, tmp_path, monkeypatch):
    for n, body in enumerate(({}, {'head_sequence': 3}, {'head_sequence': 'x', 'head_digest': 1,
                                                       'closure_class': 'completed', 'terminal_status': 'observed',
                                                       'external_checkpoint': {}},
                              {'head_sequence': 3, 'head_digest': 'sha256:' + '0' * 64, 'closure_class': 'completed',
                               'terminal_status': 'unresolved', 'external_checkpoint': {'status': 'not_retained'}},
                              {'head_sequence': 3, 'head_digest': 'sha256:' + '0' * 64, 'closure_class': 'completed',
                               'terminal_status': 'observed', 'external_checkpoint': 'none'})):
        wid = 'm%d' % n
        path = seeded(store, wid=wid)
        scan = store_mod._scan(path, ws.Bounds())
        with store_mod._mutex(path):
            store_mod._append_locked(path, wid, {'kind': 'store.archive_intent', 'timestamp': TS, 'body': body},
                                     ws.Bounds(), scan, reserved=True)
        os.rename(path, str(tmp_path / 'archive' / wid))
        refusal('archive_incomplete', store.verify_archive, wid)


def test_real_process_death_between_the_intent_and_the_move(store):
    path = seeded(store)
    h = head(store)
    pid = os.fork()
    if pid == 0:
        try:
            os.rename = lambda *a, **k: os._exit(9)
            do_archive(store, expected_head=h)
        finally:
            os._exit(1)
    assert os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]) == 9
    assert os.path.lexists(path) and store.inspect('wf1') == [{'code': 'archive_incomplete', 'files': []}]
    refusal('lock_held', store.acquire, 'wf1', owner='next', timestamp=TS)
    # the dead holder's lock is broken by an explicit operator act; the break event follows the intent
    store.break_lock('wf1', expected_owner='w1', breaker='next', reason='holder died', timestamp=TS)
    kinds = [e['kind'] for e in store.load('wf1').events]
    assert kinds[-2:] == ['store.archive_intent', 'store.lock_broken']
    receipt = store.archive('wf1', owner='next', timestamp=TS, closure_class='cancelled',
                            terminal_status='cancelled', expected_head=h)
    assert receipt['head_sequence'] == 3 and receipt['event_count'] == 5
    assert store.verify_archive('wf1')['receipt'] == 'agrees'


# --- the archive stays verifiable and read-only -----------------------------------------------

def test_archived_workflow_still_detects_tampering_and_accepts_no_events(store, tmp_path):
    seeded(store)
    do_archive(store)
    archived = str(tmp_path / 'archive' / 'wf1')
    refusal('lock_not_held', ws.append, archived, rec(), owner='w1')  # no lock in the archive
    ws.acquire(archived, owner='w1', timestamp=TS)  # even a lock taken by hand does not reopen it
    refusal('archive_incomplete', ws.append, archived, rec(), owner='w1')
    ws.release(archived, owner='w1')
    assert ws.inspect(archived) == []
    f = os.path.join(archived, '000002.json')
    os.chmod(f, 0o644)
    data = open(f, 'rb').read()
    open(f, 'wb').write(data.replace(b'"i":1', b'"i":7'))
    refusal('digest_mismatch', store.verify_archive, 'wf1')
    refusal('digest_mismatch', ws.load, archived)


def test_verify_archive_reports_a_missing_or_disagreeing_receipt_and_a_foreign_intent(store, tmp_path):
    seeded(store)
    do_archive(store)
    rpath = tmp_path / 'archive' / 'wf1.receipt.json'
    good = rpath.read_bytes()
    os.chmod(rpath, 0o644)
    rpath.write_bytes(good.replace(b'"cancelled"', b'"observed"', 1))
    assert store.verify_archive('wf1')['receipt'] == 'disagrees'
    rpath.write_bytes(b'not json')
    assert store.verify_archive('wf1')['receipt'] == 'disagrees'
    rpath.unlink()
    assert store.verify_archive('wf1')['receipt'] == 'missing'
    refusal('workflow_not_found', store.verify_archive, 'ghost')
    os.mkdir(tmp_path / 'archive' / 'plain')  # an archive directory with no intent is not an archive
    refusal('archive_incomplete', store.verify_archive, 'plain')


def test_archival_never_deletes_an_event_and_has_no_deletion_api():
    assert not [n for n in dir(ws) if 'delete' in n.lower() or 'remove' in n.lower() or 'purge' in n.lower()]
    assert not [n for n in dir(ws.Store) if 'delete' in n.lower() or 'remove' in n.lower() or 'purge' in n.lower()]
