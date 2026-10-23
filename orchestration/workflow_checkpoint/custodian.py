"""Synthetic custodian-side retention. Local files only. Non-authorizing.

Stand-in for the PROPOSED custodian (Evidence Attestation, subject to its owner's acceptance; no
change to Evidence Attestation is made or implied). Append-only by construction: there is no
delete, rewrite or truncate operation; a record is created with exclusive link and mode 0444.
Layout: <root>/<workflow_id>/<checkpoint_sequence:06d>.json (canonical JSON). Its custody root must
be outside the store it describes; this reference cannot enforce that for a real deployment.
"""
import os

from ..workflow_store.canonical import jcs_bytes, loads_strict
from . import record
from .refusal import CheckpointRefusal

FILE_MODE = 0o444
DIR_MODE = 0o700


def _wdir(root, wid):
    record.check_workflow_id(wid)
    return os.path.join(os.fspath(root), wid)


def _name(seq):
    return '%06d.json' % seq


def read_all(root, workflow_id):
    """All retained records in sequence order, strictly validated; raises CheckpointRefusal.

    Gaps, duplicates and foreign files are reported as custody_corrupt / duplicate_checkpoint.
    """
    d = _wdir(root, workflow_id)
    try:
        names = sorted(os.listdir(d))
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise CheckpointRefusal('io_failure', 'list: %s' % exc.__class__.__name__)
    recs, seen = [], set()
    for n in names:
        if len(n) != 11 or not n.endswith('.json') or not n[:6].isdigit():
            raise CheckpointRefusal('custody_corrupt', 'unexpected entry %r' % n)
        try:
            with open(os.path.join(d, n), 'rb') as fh:
                raw = fh.read()
            rec = loads_strict(raw)
        except (OSError, ValueError) as exc:
            raise CheckpointRefusal('custody_corrupt', 'unreadable %s' % n)
        record.validate(rec)
        if jcs_bytes(rec) != raw:
            raise CheckpointRefusal('custody_corrupt', 'noncanonical %s' % n)
        if rec['workflow_id'] != workflow_id:
            raise CheckpointRefusal('workflow_mismatch', n)
        if rec['checkpoint_sequence'] in seen:
            raise CheckpointRefusal('duplicate_checkpoint', n)
        seen.add(rec['checkpoint_sequence'])
        if rec['checkpoint_sequence'] != int(n[:6]):
            raise CheckpointRefusal('custody_corrupt', 'name/sequence disagree %s' % n)
        recs.append(rec)
    recs.sort(key=lambda r: r['checkpoint_sequence'])
    for i, r in enumerate(recs, 1):
        if r['checkpoint_sequence'] != i:
            raise CheckpointRefusal('sequence_gap', 'missing checkpoint %d' % i)
    return recs


class Custodian:
    def __init__(self, root):
        self.root = os.fspath(root)
        if not os.path.isdir(self.root):
            raise CheckpointRefusal('io_failure', 'custody root is not a directory')

    def retain(self, rec):
        """Append one checkpoint. Returns its digest as the acknowledgment. Never overwrites."""
        record.validate(rec)
        wid = rec['workflow_id']
        existing = read_all(self.root, wid)
        seq = rec['checkpoint_sequence']
        if existing:
            last = existing[-1]
            if seq <= last['checkpoint_sequence']:
                raise CheckpointRefusal('duplicate_checkpoint', 'sequence %d already retained' % seq)
            if seq != last['checkpoint_sequence'] + 1:
                raise CheckpointRefusal('sequence_gap', 'expected %d' % (last['checkpoint_sequence'] + 1))
            if rec['producer'] != last['producer']:
                raise CheckpointRefusal('producer_mismatch', 'producer differs from the retained series')
            if rec['predecessor'] != last['digest']:
                raise CheckpointRefusal('predecessor_mismatch', 'predecessor is not the retained head')
            if rec['head_count'] < last['head_count']:
                raise CheckpointRefusal('head_regression', 'head_count decreased')
            if rec['head_count'] == last['head_count'] and rec['head_digest'] != last['head_digest']:
                raise CheckpointRefusal('head_fork', 'same count, different digest')
        elif seq != 1:
            raise CheckpointRefusal('sequence_gap', 'first retained checkpoint must be sequence 1')
        # A head claimed earlier at the same count with another digest is a fork across the series.
        for r in existing:
            if r['head_count'] == rec['head_count'] and r['head_digest'] != rec['head_digest']:
                raise CheckpointRefusal('head_fork', 'same count, different digest')
        d = _wdir(self.root, wid)
        try:
            os.makedirs(d, mode=DIR_MODE, exist_ok=True)
            final = os.path.join(d, _name(seq))
            tmp = os.path.join(d, '.tmp.%d' % os.getpid())
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
            try:
                os.write(fd, jcs_bytes(rec))
                os.fsync(fd)
            finally:
                os.close(fd)
            try:
                os.link(tmp, final)  # fails if present: append-only
            except FileExistsError:
                raise CheckpointRefusal('duplicate_checkpoint', 'sequence %d already retained' % seq)
            finally:
                os.unlink(tmp)
        except OSError as exc:
            raise CheckpointRefusal('io_failure', exc.__class__.__name__)
        return rec['digest']

    def latest(self, workflow_id):
        recs = read_all(self.root, workflow_id)
        return recs[-1] if recs else None
