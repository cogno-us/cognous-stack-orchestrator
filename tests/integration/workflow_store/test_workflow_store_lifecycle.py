"""Machine plus store lifecycle tests (step 3.2-A): restart recovery, cancellation, suspension, slot release.

The package under test does not join the two (the adapter is step 3.4); this file contains a minimal
test-only adapter to exercise them together. Coordination only: nothing here reads or settles an effect.
Developer tests, not independent acceptance."""
import os

import pytest

from orchestration import workflow_machine as wm
from orchestration import workflow_store as ws

TS = '2026-01-01T00:00:00Z'
REFS = {'propose': 'proposal_ref', 'record_authorized': 'decision_ref', 'dispatch': 'dispatch_ref',
        'record_observation': 'observation_ref', 'reconcile': 'observation_ref',
        'reconcile_inconclusive': 'observation_ref', 'suspend': 'suspension_ref', 'resume': 'resume_ref',
        'cancel': 'cancellation_ref', 'fail': 'failure_ref'}


class Adapter:
    """Minimal write-ahead adapter: validate against the replayed machine, persist, only then act."""

    def __init__(self, store, owner='orch'):
        self.store, self.owner = store, owner

    def replay(self, wid):
        events = [e for e in self.store.load(wid).events if not e['kind'].startswith('store.')]
        return wm.replay([dict(e['body'], seq=i + 1) for i, e in enumerate(events)]) if events \
            else wm.initial_state()

    def submit(self, wid, etype, fleet=None):
        state = self.replay(wid)
        event = {'type': etype, 'workflow_id': wid, 'seq': state.event_count + 1, 'at': TS}
        if etype in REFS:
            event[REFS[etype]] = '%s-%d' % (etype, state.event_count + 1)
        wm.apply_event(state, event)  # refuse before anything is written
        self.store.append(wid, {'kind': 'workflow.' + etype, 'timestamp': TS, 'body': {
            k: v for k, v in event.items() if k != 'seq'}}, owner=self.owner)
        return event

    def start(self, wid):
        self.store.create_workflow(wid)
        self.store.acquire(wid, owner=self.owner, timestamp=TS)
        self.submit(wid, 'propose')

    def fleet(self):
        return wm.replay_fleet(
            [dict(e['body'], seq=i + 1) for wid in self.store.workflows()
             for i, e in enumerate(x for x in self.store.load(wid).events if not x['kind'].startswith('store.'))])

    def archive(self, wid, fleet):
        """Archive, then release: the machine decides what is archivable; the store records it."""
        st = self.replay(wid)
        status = st.status
        if status in wm.vocabulary.OPEN_EFFECT_STATUSES or status not in wm.TERMINAL_STATUSES:
            # the machine-side refusal comes first, with its own code
            wm.release_terminal(fleet, wid)
        head = self.store.load(wid)
        self.store.archive(wid, owner=self.owner, timestamp=TS, closure_class=wm.describe(st)['closure_class'],
                           terminal_status=status, expected_head=(head.head_sequence, head.head_digest))
        return wm.release_terminal(fleet, wid)


@pytest.fixture
def adapter(tmp_path):
    (tmp_path / 'live').mkdir()
    (tmp_path / 'archive').mkdir()
    return Adapter(ws.Store(tmp_path / 'live', archive_root=tmp_path / 'archive'))


def advance(a, wid, *types):
    for t in types:
        a.submit(wid, t)


def test_cancelled_workflow_is_archived_as_cancelled_and_releases_its_places(adapter, tmp_path):
    a = adapter
    a.start('w1')
    advance(a, 'w1', 'request_authority', 'cancel')  # held awaiting authority, then cancelled
    fleet = a.fleet()
    assert fleet.slot_counts() == {'execution': 0, 'waiting': 0, 'closed': 1}
    fleet, receipt = a.archive('w1', fleet)
    assert receipt['closure_class'] == 'cancelled' and receipt['terminal_status'] == 'cancelled'
    assert fleet.states == {} and a.store.workflows() == []
    info = a.store.verify_archive('w1')
    assert info['closure_class'] == 'cancelled' and info['receipt'] == 'agrees'
    # coordination only: nothing says an effect failed, was reversed or verified
    d = wm.describe(wm.replay([dict(e['body'], seq=i + 1) for i, e in enumerate(
        x for x in ws.load(str(tmp_path / 'archive' / 'w1')).events if not x['kind'].startswith('store.'))]))
    assert d['effect_outcome'] == 'none' and d['refs_content_checked'] is False


def test_unresolved_effect_is_never_released_or_archived_and_stays_recoverable(adapter):
    a = adapter
    a.start('w1')
    advance(a, 'w1', 'request_authority', 'record_authorized', 'dispatch', 'record_outcome_unknown')
    fleet = a.fleet()
    assert wm.describe(a.replay('w1'))['closure_class'] == 'open'
    with pytest.raises(wm.Refusal) as ei:
        a.archive('w1', fleet)
    assert ei.value.code == 'open_effect_refused'
    # even if the adapter is bypassed and the store is asked directly, no completed/failed/cancelled label fits
    head = a.store.load('w1')
    for status in ('unresolved', 'dispatched', 'proposed'):
        with pytest.raises(ws.StoreRefusal) as si:
            a.store.archive('w1', owner='orch', timestamp=TS, closure_class='completed', terminal_status=status,
                            expected_head=(head.head_sequence, head.head_digest))
        assert si.value.code == 'not_archivable'
    for etype in ('cancel', 'fail', 'suspend'):
        with pytest.raises(wm.Refusal) as ei:
            a.submit('w1', etype)
        assert ei.value.code == 'open_effect_refused'
    assert a.store.workflows() == ['w1'] and a.store.load('w1').head_sequence == head.head_sequence
    # only an explicit reconcile moves it on; then it can be archived as completed
    advance(a, 'w1', 'reconcile')
    fleet, receipt = a.archive('w1', a.fleet())
    assert receipt['closure_class'] == 'completed' and receipt['terminal_status'] == 'reconciled'


def test_restart_after_a_crash_between_dispatch_and_outcome(adapter, tmp_path):
    """dispatch was persisted (write-ahead), then the process died. The restart replays `dispatched`, records
    crash_recovered, and from then on only reconciliation is legal. Nothing is closed, retried or archived."""
    a = adapter
    a.start('w1')
    advance(a, 'w1', 'request_authority', 'record_authorized', 'dispatch')
    pid = os.fork()
    if pid == 0:
        os._exit(9)  # simulated death with the lock still held
    os.waitpid(pid, 0)
    # a restarted process: new adapter object, lock taken over explicitly by break_lock (operator act)
    restarted = Adapter(a.store, owner='orch2')
    a.store.break_lock('w1', expected_owner='orch', breaker='orch2', reason='restart', timestamp=TS)
    fleet = restarted.fleet()
    assert wm.restart_recovery_needed(fleet) == ('w1',)
    assert fleet.slot_counts() == {'execution': 1, 'waiting': 0, 'closed': 0}
    with pytest.raises(wm.Refusal) as ei:
        restarted.submit('w1', 'dispatch')
    assert ei.value.code == 'blind_retry_refused'
    restarted.submit('w1', 'crash_recovered')
    fleet = restarted.fleet()
    assert wm.restart_recovery_needed(fleet) == () and fleet.states['w1'].status == 'unresolved'
    assert fleet.slot_counts() == {'execution': 0, 'waiting': 1, 'closed': 0}
    with pytest.raises(wm.Refusal):
        restarted.archive('w1', fleet)
    # a second restart finds the same state: nothing was lost, nothing duplicated
    assert Adapter(a.store, owner='orch2').fleet().states['w1'] == fleet.states['w1']


def test_held_workflows_survive_restart_without_consuming_execution_slots(adapter, monkeypatch):
    monkeypatch.setattr(wm.machine, 'MAX_ACTIVE_EXECUTION_SLOTS', 1)
    a = adapter
    for wid in ('held1', 'held2', 'run1', 'run2'):
        a.start(wid)
        advance(a, wid, 'request_authority')  # a Control Plane hold or deny leaves it here
    advance(a, 'run1', 'record_authorized')
    fleet = Adapter(a.store, owner='orch2').fleet()  # restart: rebuild from the durable log alone
    assert fleet.slot_counts() == {'execution': 1, 'waiting': 3, 'closed': 0}
    with pytest.raises(wm.Refusal) as ei:  # the single execution slot is full, held records did not take it
        wm.apply_fleet(fleet, {'type': 'record_authorized', 'workflow_id': 'run2', 'seq': 3, 'at': TS,
                               'decision_ref': 'd'})
    assert ei.value.code == 'bound_execution_slots_exceeded'
    assert fleet.states['run2'].status == 'awaiting_authority'
    advance(a, 'run1', 'cancel')  # frees the slot; the held record still exists and is now admitted
    fleet = a.fleet()
    assert fleet.slot_counts() == {'execution': 0, 'waiting': 3, 'closed': 1}
    advance(a, 'run2', 'record_authorized')
    assert a.fleet().states['run2'].status == 'authorized'
    assert sorted(a.store.workflows()) == ['held1', 'held2', 'run1', 'run2']  # held ones are still durable


def test_suspended_workflow_is_durable_not_terminated_and_resumes_only_through_new_authority(adapter):
    a = adapter
    a.start('w1')
    advance(a, 'w1', 'request_authority', 'record_authorized', 'suspend')
    fleet = Adapter(a.store, owner='orch2').fleet()
    assert fleet.states['w1'].status == 'suspended' and fleet.slot_counts()['waiting'] == 1
    with pytest.raises(wm.Refusal) as ei:
        wm.release_terminal(fleet, 'w1')
    assert ei.value.code == 'not_releasable'
    with pytest.raises(ws.StoreRefusal) as si:
        head = a.store.load('w1')
        a.store.archive('w1', owner='orch', timestamp=TS, closure_class='cancelled', terminal_status='suspended',
                        expected_head=(head.head_sequence, head.head_digest))
    assert si.value.code == 'not_archivable'
    with pytest.raises(wm.Refusal) as ei:
        a.submit('w1', 'dispatch')
    assert ei.value.code == 'authority_required'
    advance(a, 'w1', 'resume', 'request_authority', 'record_authorized', 'dispatch')
    assert a.replay('w1').status == 'dispatched'


def test_many_terminal_workflows_do_not_leak_slots_or_live_directories(adapter, monkeypatch):
    monkeypatch.setattr(wm.machine, 'MAX_ACTIVE_EXECUTION_SLOTS', 2)
    monkeypatch.setattr(wm.machine, 'MAX_WAITING_RECORDS', 2)
    a = adapter
    fleet = wm.Fleet({})
    for round_ in range(5):  # far more workflows over time than either bound
        for i in range(2):
            wid = 'w%d-%d' % (round_, i)
            a.start(wid)
            advance(a, wid, 'request_authority', 'record_authorized', 'dispatch', 'record_observation')
        fleet = a.fleet()
        assert fleet.slot_counts() == {'execution': 0, 'waiting': 0, 'closed': 2}
        for i in range(2):
            fleet, _ = a.archive('w%d-%d' % (round_, i), fleet)
        assert a.store.workflows() == [] and fleet.states == {}
    assert len(os.listdir(a.store.archive_root)) == 20  # 10 directories and 10 receipts, nothing deleted
    for round_ in range(5):
        for i in range(2):
            assert a.store.verify_archive('w%d-%d' % (round_, i))['receipt'] == 'agrees'
