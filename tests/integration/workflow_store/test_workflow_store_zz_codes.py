"""Every refusal code of the closed set must have been raised by a negative test in this directory.

Order-dependent by design: it runs last (file name) and inspects what the other tests raised.
"""
from orchestration.workflow_store import CODES, refusal

SEEN_CODES = refusal.TEST_SEEN_CODES


def test_every_refusal_code_has_a_negative_test():
    assert sorted(CODES - SEEN_CODES) == []


def test_only_declared_codes_were_raised():
    assert SEEN_CODES <= CODES
