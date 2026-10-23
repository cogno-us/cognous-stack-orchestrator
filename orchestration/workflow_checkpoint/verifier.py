"""Verifier-side check of a candidate history against independently retained checkpoints.

Read-only, non-authorizing, fail closed. Verdict words are only match / mismatch / unverifiable.
A match means the candidate agrees with what the custodian retained; it is not an authenticity,
completeness or tamper-evidence claim and says nothing about who wrote the history.
"""
import re
from dataclasses import dataclass, field

from . import custodian, record
from .refusal import (CheckpointRefusal, MATCH, MISMATCH, RESULT_CODES, UNVERIFIABLE, VERDICTS)


@dataclass(frozen=True)
class Candidate:
    """Head and count of the history under check. `chain_digests`, if given, is every event digest
    in order (length == head_count); it lets the verifier test each retained checkpoint, not just
    the latest."""
    workflow_id: str
    head_count: int
    head_digest: object
    store_profile: str = record.STORE_PROFILE
    chain_digests: object = None


@dataclass(frozen=True)
class Result:
    verdict: str
    code: str
    detail: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.verdict not in VERDICTS or self.code not in RESULT_CODES:
            raise ValueError('result outside the closed sets')


def _r(verdict, code, **detail):
    return Result(verdict, code, detail)


def _consistent(recs):
    prev = None
    for r in recs:
        if prev is not None:
            if r['predecessor'] != prev['digest'] or r['producer'] != prev['producer']:
                return False
            if r['head_count'] < prev['head_count']:
                return False
        else:
            if r['predecessor'] is not None:
                return False
        for q in recs:
            if q['head_count'] == r['head_count'] and q['head_digest'] != r['head_digest']:
                return False
        prev = r
    return True


def verify(custody_root, workflow_id, candidate):
    try:
        return _verify(custody_root, workflow_id, candidate)
    except Exception as exc:  # fail closed: nothing escapes as a pass or as an exception
        return _r(UNVERIFIABLE, 'input_invalid', error=exc.__class__.__name__)


def _verify(custody_root, workflow_id, c):
    try:
        record.check_workflow_id(workflow_id)
        if type(c) is not Candidate:
            raise CheckpointRefusal('schema_invalid')
        record.check_workflow_id(c.workflow_id)
        record.check_head(c.head_count, c.head_digest)
        if type(c.store_profile) is not str:
            raise CheckpointRefusal('schema_invalid')
        chain = c.chain_digests
        if chain is not None:
            if type(chain) not in (list, tuple) or len(chain) != c.head_count or \
                    any(type(d) is not str or not record.DIGEST_RE.match(d) for d in chain) or \
                    (chain and chain[-1] != c.head_digest):
                raise CheckpointRefusal('schema_invalid')
    except CheckpointRefusal:
        return _r(UNVERIFIABLE, 'input_invalid')
    if c.workflow_id != workflow_id:
        return _r(MISMATCH, 'workflow_mismatch')
    if c.store_profile != record.STORE_PROFILE:
        return _r(MISMATCH, 'profile_mismatch')
    try:
        recs = custodian.read_all(custody_root, workflow_id)
    except CheckpointRefusal as exc:
        code = {'sequence_gap': 'missing_checkpoint', 'duplicate_checkpoint': 'duplicate_checkpoint',
                'io_failure': 'custody_unavailable'}.get(exc.code)
        return _r(UNVERIFIABLE, code or 'checkpoint_corrupt')
    if not recs:
        return _r(UNVERIFIABLE, 'no_checkpoints')
    if not _consistent(recs):
        return _r(UNVERIFIABLE, 'retained_inconsistent')
    n, d = c.head_count, c.head_digest
    latest = recs[-1]
    if chain is not None:
        for r in recs:
            k = r['head_count']
            if k > n:
                continue
            if k == 0:
                continue
            if chain[k - 1] != r['head_digest']:
                return _r(MISMATCH, 'fork', checkpoint_sequence=r['checkpoint_sequence'])
    if n < latest['head_count']:
        for r in recs:
            if r['head_count'] == n:
                if r['head_digest'] == d:
                    return _r(MISMATCH, 'rollback', retained_count=latest['head_count'])
                return _r(MISMATCH, 'fork', checkpoint_sequence=r['checkpoint_sequence'])
        return _r(MISMATCH, 'truncation', retained_count=latest['head_count'])
    if n == latest['head_count']:
        if d != latest['head_digest']:
            return _r(MISMATCH, 'fork', checkpoint_sequence=latest['checkpoint_sequence'])
        return _r(MATCH, 'chain_matches_all' if chain is not None else 'head_matches_latest')
    # candidate is longer than the latest retained checkpoint
    if chain is None:
        return _r(UNVERIFIABLE, 'extension_unproven', retained_count=latest['head_count'])
    return _r(MATCH, 'chain_matches_all')
