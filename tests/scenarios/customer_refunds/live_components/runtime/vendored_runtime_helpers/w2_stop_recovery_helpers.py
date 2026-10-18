# Vendored helper code. NOT a runtime module and not evidence about the runtime.
# Source: cogno-us/cognous-execution-runtime @ da9f52900ee2596dab087ec6c249ba84915d2b13 (the orchestrator's accepted runtime pin), tests/test_w2_stop_recovery.py, lines 1-43 (imports, _blocked_worker, _attempt_rows).
# Source file sha256: 5e8d4f4ef3fc722457e911d70263b924efd10207861df5162dd26f82e80fb510
# Why: runtime 2ee2e525 moved its tests to cognous-stack-qualification, so a newer runtime checkout no longer has this module and
# test_actual_runtime.py (suite O5-D-B) failed at collection (gap report F-6). test_actual_runtime.py imports the runtime's own copy
# when it exists (pinned default, unchanged) and falls back to this copy otherwise.
# Modifications: import of test_local_authority_effect rewritten to the vendored .local_authority_effect_helpers; the pytestmark skip block is omitted.
"""W2 qualification for the existing local process stop/restart path."""
from __future__ import annotations

import multiprocessing as mp
import sqlite3
import time

import pytest

from engine.atomic_local_control_plane_executor import AtomicLocalControlPlaneExecutor
from engine.local_authority_effect import AtomicAuthorityEffectDestination
from engine.safe_executor import snapshot_envelope
from .local_authority_effect_helpers import BASE, effect_rows, policy, setup_atomic


def _blocked_worker(root, env, claim_id, stage, reached):
    class BarrierDestination(AtomicAuthorityEffectDestination):
        def _transaction_stage(self, current):
            if current == stage:
                reached.set()
                while True:
                    time.sleep(60)

    destination = BarrierDestination(root, clock=lambda: BASE)
    destination.execute_claim_atomic(
        claim_id,
        snapshot_envelope(env),
        attempt_id=f"stop-{stage}",
    )


def _attempt_rows(destination):
    with sqlite3.connect(destination.path) as conn:
        return conn.execute(
            "SELECT attempt_id,effect_id,decision_id FROM attempts ORDER BY attempt_id"
        ).fetchall()
