# Vendored helper code. NOT a runtime module and not evidence about the runtime.
# Source: cogno-us/cognous-execution-runtime @ da9f52900ee2596dab087ec6c249ba84915d2b13 (the orchestrator's accepted runtime pin), tests/test_refund_intent.py, lines 1-19 (imports, fixture).
# Source file sha256: 5b4388b3d3f04edfd2920474c7b986f47ace6e087ba30da710da407ab55557ce
# Why: runtime 2ee2e525 moved its tests to cognous-stack-qualification, so a newer runtime checkout no longer has this module and
# test_actual_runtime.py (suite O5-D-B) failed at collection (gap report F-6). test_actual_runtime.py imports the runtime's own copy
# when it exists (pinned default, unchanged) and falls back to this copy otherwise.
# Modifications: import of test_safe_executor rewritten to the vendored .safe_executor_helpers.
from dataclasses import replace
import multiprocessing
import os
import sqlite3

import pytest

from engine.refund_intent import IntentRefundDestination, RefundIntent, RefundIntentRegistry
from engine.safe_executor import DurableRefundDestination, snapshot_envelope
from .safe_executor_helpers import envelope, make_operation


def fixture(root):
    destination = DurableRefundDestination(root)
    registry = RefundIntentRegistry(destination)
    intent = RefundIntent('urn:cognous:institution:demo', 'customer-refunds', 'c1', 'r1')
    snapshot = snapshot_envelope(envelope(make_operation(
        payload={'customer_id': 'c1', 'refund_reason': 'duplicate'}, effective_max_effects=10)))
    return destination, registry, intent, snapshot
