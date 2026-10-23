"""Typed refusals of the workflow store. The code set is closed; a refusal changes nothing."""

CODES = frozenset({
    # input and identity
    'schema_invalid', 'forbidden_member', 'reserved_kind', 'invalid_workflow_id', 'invalid_owner',
    'bounds_invalid', 'path_escape', 'unexpected_file', 'io_failure',
    # existence and bounds
    'workflow_exists', 'workflow_not_found', 'store_full', 'workflow_full', 'event_too_large',
    # locking
    'lock_held', 'lock_not_held', 'lock_owner_mismatch', 'lock_corrupt',
    # chain validation on load
    'event_corrupt', 'noncanonical_event', 'digest_mismatch', 'workflow_id_mismatch',
    'sequence_mismatch', 'sequence_gap', 'chain_broken', 'truncated', 'sequence_conflict',
    # torn-write conditions (reported, never silently repaired)
    'torn_tail', 'leftover_temp', 'unrecorded_quarantine', 'nothing_to_recover',
})


class StoreRefusal(Exception):
    """A typed refusal with a code from CODES and an optional detail mapping."""

    def __init__(self, code, message='', detail=None):
        if code not in CODES:
            raise ValueError('refusal code outside the closed set: %r' % (code,))
        super().__init__('%s: %s' % (code, message) if message else code)
        self.code = code
        self.detail = dict(detail or {})
