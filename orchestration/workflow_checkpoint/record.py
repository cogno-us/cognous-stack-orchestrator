"""Checkpoint record: build and strict validation. Non-authorizing. Names are PROVISIONAL."""
import re

from ..workflow_store.canonical import CANONICAL_PROFILE_NAME, object_digest
from .refusal import CheckpointRefusal

PROFILE = 'ocs-workflow-checkpoint/0'  # provisional; not frozen
SCHEMA_VERSION = 0
STORE_PROFILE = 'ocs-workflow-event/0'  # the event-store profile whose head this describes
STORE_SCHEMA_VERSION = 0

FIELDS = {'profile', 'schema_version', 'canonical_profile', 'workflow_id', 'store_profile',
          'store_schema_version', 'producer', 'checkpoint_sequence', 'head_count', 'head_digest',
          'predecessor', 'digest'}
WORKFLOW_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
PRODUCER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z')
DIGEST_RE = re.compile(r'^sha256:[0-9a-f]{64}\Z')
MAX_INT = 2 ** 53 - 1


def _is_int(v):
    return type(v) is int and 0 <= v <= MAX_INT


def check_workflow_id(wid):
    if type(wid) is not str or not WORKFLOW_ID_RE.match(wid):
        raise CheckpointRefusal('invalid_workflow_id', 'workflow id form')


def check_head(count, digest):
    """Head pair form: count 0 pairs with None; count > 0 pairs with a sha256 digest."""
    if not _is_int(count):
        raise CheckpointRefusal('schema_invalid', 'head_count must be a non-negative integer')
    if count == 0:
        if digest is not None:
            raise CheckpointRefusal('schema_invalid', 'empty head has no digest')
    elif type(digest) is not str or not DIGEST_RE.match(digest):
        raise CheckpointRefusal('schema_invalid', 'head_digest form')


def build(workflow_id, head_count, head_digest, producer, checkpoint_sequence, predecessor=None):
    check_workflow_id(workflow_id)
    check_head(head_count, head_digest)
    if type(producer) is not str or not PRODUCER_RE.match(producer):
        raise CheckpointRefusal('schema_invalid', 'producer form')
    if type(checkpoint_sequence) is not int or not 1 <= checkpoint_sequence <= MAX_INT:
        raise CheckpointRefusal('schema_invalid', 'checkpoint_sequence must be >= 1')
    if (checkpoint_sequence == 1) != (predecessor is None):
        raise CheckpointRefusal('schema_invalid', 'predecessor is None exactly for sequence 1')
    if predecessor is not None and (type(predecessor) is not str or not DIGEST_RE.match(predecessor)):
        raise CheckpointRefusal('schema_invalid', 'predecessor form')
    rec = {'profile': PROFILE, 'schema_version': SCHEMA_VERSION, 'canonical_profile': CANONICAL_PROFILE_NAME,
           'workflow_id': workflow_id, 'store_profile': STORE_PROFILE,
           'store_schema_version': STORE_SCHEMA_VERSION, 'producer': producer,
           'checkpoint_sequence': checkpoint_sequence, 'head_count': head_count,
           'head_digest': head_digest, 'predecessor': predecessor}
    rec['digest'] = object_digest(rec)
    return rec


def validate(rec):
    """Strict validation of a checkpoint record; raises CheckpointRefusal. Returns rec."""
    if type(rec) is not dict or set(rec) != FIELDS:
        raise CheckpointRefusal('schema_invalid', 'members')
    if rec['profile'] != PROFILE or rec['schema_version'] != SCHEMA_VERSION or \
            rec['canonical_profile'] != CANONICAL_PROFILE_NAME or \
            rec['store_profile'] != STORE_PROFILE or rec['store_schema_version'] != STORE_SCHEMA_VERSION:
        raise CheckpointRefusal('unsupported_profile', 'profile or schema identity')
    expect = build(rec['workflow_id'], rec['head_count'], rec['head_digest'], rec['producer'],
                   rec['checkpoint_sequence'], rec['predecessor'])
    if expect != rec:
        raise CheckpointRefusal('schema_invalid', 'digest does not match content')
    return rec
