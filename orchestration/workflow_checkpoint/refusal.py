"""Closed code sets of the checkpoint interface. Non-authorizing. Provisional, not frozen."""

# Producer / custodian refusals: a refusal changes nothing.
REFUSAL_CODES = frozenset({
    'schema_invalid', 'invalid_workflow_id', 'unsupported_profile', 'workflow_mismatch',
    'producer_mismatch', 'duplicate_checkpoint', 'sequence_gap', 'predecessor_mismatch',
    'head_regression', 'head_fork', 'io_failure', 'custody_corrupt',
})

# The only verdict words of the verifier.
MATCH, MISMATCH, UNVERIFIABLE = 'match', 'mismatch', 'unverifiable'
VERDICTS = frozenset({MATCH, MISMATCH, UNVERIFIABLE})

MISMATCH_CODES = frozenset({'truncation', 'rollback', 'fork', 'workflow_mismatch', 'profile_mismatch'})
UNVERIFIABLE_CODES = frozenset({
    'input_invalid', 'custody_unavailable', 'no_checkpoints', 'missing_checkpoint',
    'duplicate_checkpoint', 'checkpoint_corrupt', 'retained_inconsistent', 'extension_unproven',
})
MATCH_CODES = frozenset({'head_matches_latest', 'chain_matches_all'})
RESULT_CODES = MISMATCH_CODES | UNVERIFIABLE_CODES | MATCH_CODES


class CheckpointRefusal(Exception):
    def __init__(self, code, message='', detail=None):
        if code not in REFUSAL_CODES:
            raise ValueError('refusal code outside the closed set: %r' % (code,))
        super().__init__('%s: %s' % (code, message) if message else code)
        self.code = code
        self.detail = dict(detail or {})
