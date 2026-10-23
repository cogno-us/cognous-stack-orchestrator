"""External checkpoint interface, local synthetic reference (Q6). Non-authorizing; see README.md.

Wire and profile names (`ocs-workflow-checkpoint/0`) are PROVISIONAL and not frozen.
"""
from .custodian import Custodian, read_all
from .producer import checkpoint_from_head, checkpoint_from_loaded
from .record import PROFILE, build, validate
from .refusal import MISMATCH, REFUSAL_CODES, RESULT_CODES, UNVERIFIABLE, MATCH, CheckpointRefusal
from .verifier import Candidate, Result, verify

__all__ = ['Candidate', 'CheckpointRefusal', 'Custodian', 'MATCH', 'MISMATCH', 'PROFILE', 'REFUSAL_CODES',
           'RESULT_CODES', 'Result', 'UNVERIFIABLE', 'build', 'checkpoint_from_head',
           'checkpoint_from_loaded', 'read_all', 'validate', 'verify']
