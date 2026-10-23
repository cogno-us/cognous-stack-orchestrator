"""Developer tests for the synthetic checkpoint interface. Not independent acceptance cases."""
import os
import shutil

import pytest

from orchestration import workflow_checkpoint as wc
from orchestration import workflow_store as ws
from orchestration.workflow_checkpoint import refusal
from orchestration.workflow_store.canonical import jcs_bytes, loads_strict, object_digest

TS = '2026-01-01T00:00:00Z'


def dg(i):
    return 'sha256:%064x' % i


def chain(n):
    return [dg(i + 1) for i in range(n)]


@pytest.fixture
def cust(tmp_path):
    root = tmp_path / 'custody'
    root.mkdir()
    return wc.Custodian(root)


def put(cust, wid, counts, producer='orch-1'):
    prev = None
    for n in counts:
        cp = wc.checkpoint_from_head(wid, n, dg(n) if n else None, producer, prev)
        cust.retain(cp)
        prev = cp
    return prev


def v(cust, wid, n, digest=..., **kw):
    d = (dg(n) if n else None) if digest is ... else digest
    return wc.verify(cust.root, wid, wc.Candidate(kw.pop('cwid', wid), n, d, **kw))


def pair(r):
    return r.verdict, r.code


def test_match_latest(cust):
    put(cust, 'wf', [2, 5])
    assert pair(v(cust, 'wf', 5)) == ('match', 'head_matches_latest')


def test_match_with_full_chain_and_extension(cust):
    put(cust, 'wf', [2, 5])
    assert pair(v(cust, 'wf', 5, chain_digests=chain(5))) == ('match', 'chain_matches_all')
    assert pair(v(cust, 'wf', 7, chain_digests=chain(7))) == ('match', 'chain_matches_all')


def test_extension_without_chain_unverifiable(cust):
    put(cust, 'wf', [5])
    assert pair(v(cust, 'wf', 7)) == ('unverifiable', 'extension_unproven')


def test_truncation_and_rollback(cust):
    put(cust, 'wf', [2, 5])
    assert pair(v(cust, 'wf', 4)) == ('mismatch', 'truncation')
    assert pair(v(cust, 'wf', 2)) == ('mismatch', 'rollback')
    assert pair(v(cust, 'wf', 0)) == ('mismatch', 'truncation')


def test_fork_head_and_inner(cust):
    put(cust, 'wf', [2, 5])
    assert pair(v(cust, 'wf', 5, digest=dg(999))) == ('mismatch', 'fork')
    assert pair(v(cust, 'wf', 2, digest=dg(999))) == ('mismatch', 'fork')
    bad = chain(7)
    bad[1] = dg(555)  # diverges at event 2, head and count look plausible
    bad[-1] = dg(7)
    assert pair(v(cust, 'wf', 7, chain_digests=bad)) == ('mismatch', 'fork')


def test_workflow_and_profile_mismatch(cust):
    put(cust, 'wf', [3])
    assert pair(v(cust, 'wf', 3, cwid='other')) == ('mismatch', 'workflow_mismatch')
    assert pair(v(cust, 'wf', 3, store_profile='ocs-workflow-event/1')) == ('mismatch', 'profile_mismatch')


def test_foreign_record_in_directory_is_workflow_mismatch(cust):
    put(cust, 'a', [3])
    put(cust, 'b', [3])
    os.chmod(os.path.join(cust.root, 'a', '000001.json'), 0o644)
    os.replace(os.path.join(cust.root, 'b', '000001.json'), os.path.join(cust.root, 'a', '000001.json'))
    assert pair(v(cust, 'a', 3)) == ('mismatch', 'workflow_mismatch')


def test_no_checkpoints_and_unavailable(cust, tmp_path):
    assert pair(v(cust, 'wf', 1)) == ('unverifiable', 'no_checkpoints')
    r = wc.verify(tmp_path / 'absent', 'wf', wc.Candidate('wf', 1, dg(1)))
    assert r.verdict == 'unverifiable'


def test_missing_checkpoint(cust):
    put(cust, 'wf', [1, 2, 3])
    p = os.path.join(cust.root, 'wf', '000002.json')
    os.chmod(p, 0o644)
    os.unlink(p)
    assert pair(v(cust, 'wf', 3)) == ('unverifiable', 'missing_checkpoint')


def test_duplicate_checkpoint_on_disk(cust):
    put(cust, 'wf', [1, 2])
    d = os.path.join(cust.root, 'wf')
    shutil.copy(os.path.join(d, '000001.json'), os.path.join(d, '000003.json'))
    assert pair(v(cust, 'wf', 2)) == ('unverifiable', 'duplicate_checkpoint')


def test_corrupt_and_foreign_files(cust):
    put(cust, 'wf', [1, 2])
    d = os.path.join(cust.root, 'wf')
    p = os.path.join(d, '000002.json')
    os.chmod(p, 0o644)
    with open(p, 'ab') as fh:
        fh.write(b' ')
    assert pair(v(cust, 'wf', 2)) == ('unverifiable', 'checkpoint_corrupt')
    os.unlink(p)
    open(os.path.join(d, 'notes.txt'), 'w').close()
    assert v(cust, 'wf', 1).verdict == 'unverifiable'


def test_tampered_content_rejected(cust):
    put(cust, 'wf', [4])
    p = os.path.join(cust.root, 'wf', '000001.json')
    rec = loads_strict(open(p, 'rb').read())
    rec['head_count'] = 1
    os.chmod(p, 0o644)
    open(p, 'wb').write(jcs_bytes(rec))  # digest no longer matches
    assert pair(v(cust, 'wf', 1)) == ('unverifiable', 'checkpoint_corrupt')


def test_retained_inconsistent_resigned_set(cust):
    put(cust, 'wf', [2, 5])
    p = os.path.join(cust.root, 'wf', '000002.json')
    rec = loads_strict(open(p, 'rb').read())
    rec['head_count'], rec['head_digest'] = 1, dg(1)  # regress, re-digested
    rec['digest'] = object_digest(rec)
    os.chmod(p, 0o644)
    open(p, 'wb').write(jcs_bytes(rec))
    assert pair(v(cust, 'wf', 1)) == ('unverifiable', 'retained_inconsistent')


def test_invalid_inputs_fail_closed(cust):
    put(cust, 'wf', [2])
    for bad in (wc.Candidate('wf', -1, dg(1)), wc.Candidate('wf', 2, 'nope'), wc.Candidate('wf', 0, dg(1)),
                wc.Candidate('wf', 2, dg(2), chain_digests=chain(3)), wc.Candidate('wf', True, dg(1)),
                wc.Candidate('../x', 2, dg(2)), None, 'x'):
        r = wc.verify(cust.root, 'wf', bad)
        assert r.verdict == 'unverifiable', bad
    assert wc.verify(cust.root, '../x', wc.Candidate('wf', 2, dg(2))).verdict == 'unverifiable'


# custodian refusals
def refused(cust, cp):
    with pytest.raises(wc.CheckpointRefusal) as e:
        cust.retain(cp)
    return e.value.code


def test_custodian_refusals(cust):
    first = put(cust, 'wf', [3])
    assert refused(cust, first) == 'duplicate_checkpoint'
    b = lambda n, dgst, seq, pred, prod='orch-1': wc.build('wf', n, dgst, prod, seq, pred)
    assert refused(cust, b(4, dg(4), 3, first['digest'])) == 'sequence_gap'
    assert refused(cust, b(4, dg(4), 2, first['digest'], 'orch-2')) == 'producer_mismatch'
    assert refused(cust, b(4, dg(4), 2, dg(77))) == 'predecessor_mismatch'
    assert refused(cust, b(2, dg(2), 2, first['digest'])) == 'head_regression'
    assert refused(cust, b(3, dg(9), 2, first['digest'])) == 'head_fork'
    fresh = wc.build('new', 1, dg(1), 'p', 2, dg(5))
    assert refused(cust, fresh) == 'sequence_gap'
    assert refused(cust, {'x': 1}) == 'schema_invalid'
    assert refused(cust, dict(first, digest=dg(1))) == 'schema_invalid'
    assert refused(cust, dict(first, profile='ocs-workflow-checkpoint/1')) == 'unsupported_profile'
    with pytest.raises(wc.CheckpointRefusal) as e:
        wc.build('../x', 1, dg(1), 'p', 1)
    assert e.value.code == 'invalid_workflow_id'


def test_append_only_and_readonly(cust):
    put(cust, 'wf', [1])
    p = os.path.join(cust.root, 'wf', '000001.json')
    assert oct(os.stat(p).st_mode & 0o777) == '0o444'
    assert not [n for n in dir(cust) if n in ('delete', 'remove', 'truncate', 'overwrite', 'replace')]
    assert not os.path.exists(os.path.join(cust.root, 'wf', '.tmp.%d' % os.getpid()))


def test_failed_retain_changes_nothing(cust):
    first = put(cust, 'wf', [3])
    before = sorted(os.listdir(os.path.join(cust.root, 'wf')))
    refused(cust, wc.build('wf', 2, dg(2), 'orch-1', 2, first['digest']))
    assert sorted(os.listdir(os.path.join(cust.root, 'wf'))) == before


def test_closed_codes():
    assert refusal.MISMATCH_CODES.isdisjoint(refusal.UNVERIFIABLE_CODES)
    assert refusal.VERDICTS == {'match', 'mismatch', 'unverifiable'}
    with pytest.raises(ValueError):
        wc.CheckpointRefusal('verdict_pass')


def test_no_authority_or_verdict_words_in_records(cust):
    cp = put(cust, 'wf', [1])
    assert not {'verdict', 'pin', 'grant', 'authority'} & set(cp)


# integration with the real store (read-only use of its head; the store is not modified)
def make_store(tmp_path, n):
    root = tmp_path / 'store'
    root.mkdir()
    st = ws.Store(root)
    st.create_workflow('wf1')
    st.acquire('wf1', owner='w1', timestamp=TS)
    for i in range(n):
        st.append('wf1', {'kind': 'workflow.step', 'timestamp': TS, 'body': {'i': i}}, owner='w1')
    st.release('wf1', owner='w1')
    return st


def test_real_store_round_trip_and_truncation(tmp_path, cust):
    st = make_store(tmp_path, 5)
    loaded = st.load('wf1')
    cp = wc.checkpoint_from_loaded(loaded, 'orch-1')
    assert (cp['head_count'], cp['head_digest']) == (5, loaded.head_digest)
    cust.retain(cp)
    digests = [e['digest'] for e in loaded.events]
    cand = wc.Candidate('wf1', loaded.head_sequence, loaded.head_digest, chain_digests=digests)
    assert pair(wc.verify(cust.root, 'wf1', cand)) == ('match', 'chain_matches_all')
    # negative control: truncate the real log by deleting its last event file, reload, re-verify
    wdir = tmp_path / 'store' / 'wf1'
    last = sorted(n for n in os.listdir(wdir) if n.endswith('.json'))[-1]
    os.chmod(wdir / last, 0o644)
    os.unlink(wdir / last)
    short = st.load('wf1')
    assert short.head_sequence == 4
    r = wc.verify(cust.root, 'wf1', wc.Candidate('wf1', 4, short.head_digest))
    assert pair(r) == ('mismatch', 'truncation')


def test_empty_workflow_checkpoint(tmp_path, cust):
    root = tmp_path / 'store2'
    root.mkdir()
    st = ws.Store(root)
    st.create_workflow('e1')
    loaded = st.load('e1')
    cp = wc.checkpoint_from_loaded(loaded, 'orch-1')
    assert (cp['head_count'], cp['head_digest']) == (0, None)
    cust.retain(cp)
    assert pair(wc.verify(cust.root, 'e1', wc.Candidate('e1', 0, None))) == ('match', 'head_matches_latest')
    assert pair(wc.verify(cust.root, 'e1', wc.Candidate('e1', 1, dg(1)))) == ('unverifiable', 'extension_unproven')
