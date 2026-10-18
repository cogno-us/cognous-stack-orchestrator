# Vendored helper code. NOT a runtime module and not evidence about the runtime.
# Source: cogno-us/cognous-execution-runtime @ da9f52900ee2596dab087ec6c249ba84915d2b13 (the orchestrator's accepted runtime pin), tests/test_safe_executor.py, lines 1-65 (imports, make_operation, envelope).
# Source file sha256: da265382b0983300ce8dd3343aba1c0a7fdb53b2ddd5b772c287a07f15719fbe
# Why: runtime 2ee2e525 moved its tests to cognous-stack-qualification, so a newer runtime checkout no longer has this module and
# test_actual_runtime.py (suite O5-D-B) failed at collection (gap report F-6). test_actual_runtime.py imports the runtime's own copy
# when it exists (pinned default, unchanged) and falls back to this copy otherwise.
# Modifications: none.
from __future__ import annotations

import copy
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from engine.control_plane_adapter import PinnedControlPlaneExecutor
from engine.producer_contract import export_execution_artifacts
from engine.safe_executor import (
    EXECUTION_ENVELOPE_VERSION,
    DurableRefundDestination,
    ExecutionEnvelope,
    ExecutionOperation,
    ExecutionResult,
    LocalDestinationExecutor,
    LocalExecutionPolicy,
    commitment,
    snapshot_envelope,
)


def make_operation(**overrides):
    payload = overrides.pop("payload", {"refund_reason": "synthetic-test"})
    base = dict(
        actor="urn:cognous:identity:agent-1",
        principal="urn:cognous:principal:service",
        institution_id="urn:cognous:institution:demo",
        authority_domain="customer-refunds",
        manifest_id="refund-integration-v1-1",
        manifest_version="1.1",
        manifest_digest="sha256:" + "a" * 64,
        proposal_commitment="sha256:" + "b" * 64,
        action_id="refund.issue",
        adapter_id="urn:cognous:adapter:synthetic-refund",
        target="urn:cognous:synthetic-account:customer-1",
        payload=payload,
        payload_commitment=commitment(payload),
        requested_permissions=("refund.issue",),
        amount=50.0,
        unit="USD",
        effects=1,
        authority_context_id="urn:cognous:authority-context:refund-demo",
        requirement_id="urn:cognous:requirement:refund-t1",
        grant_id="urn:cognous:grant:refund-1",
        grant_revision="1",
        effective_max_effects=1,
    )
    base.update(overrides)
    return ExecutionOperation(**base)


def envelope(op=None, decision_id="decision-1", effect_id="effect-1", attempt_id=None):
    return ExecutionEnvelope(
        EXECUTION_ENVELOPE_VERSION,
        decision_id,
        effect_id,
        op or make_operation(),
        attempt_id,
    )

