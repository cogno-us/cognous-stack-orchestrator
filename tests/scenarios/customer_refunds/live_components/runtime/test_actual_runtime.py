from __future__ import annotations

from dataclasses import replace
import multiprocessing as mp
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

EXPECTED_RUNTIME_SHA = "62a5cc156ecb439b4103b757fd265f276bb30374"
EXPECTED_CONTROL_SHA = "6093aca7b945698e89c0d8ac7c75306375e1a298"

RUNTIME_ROOT = Path(os.environ["COGNOUS_EXECUTION_RUNTIME_ROOT"]).resolve()
CONTROL_ROOT = Path(os.environ["COGNOUS_CONTROL_PLANE_ROOT"]).resolve()

sys.path.insert(0, str(CONTROL_ROOT / "src"))
sys.path.insert(0, str(RUNTIME_ROOT / "tests"))
sys.path.insert(0, str(RUNTIME_ROOT))

from engine.atomic_local_control_plane_executor import AtomicLocalControlPlaneExecutor
from engine.local_authority_effect import AtomicAuthorityEffectDestination
from engine.refund_intent import RefundIntentRegistry
from engine.safe_executor import snapshot_envelope

# The runtime's own test modules supply these helpers while they exist (the pinned default: unchanged). Runtime 2ee2e525 moved those
# tests to cognous-stack-qualification, so on a newer runtime checkout they are gone; then the copies vendored from the accepted pin
# (with provenance in each file header) are used instead. Only a missing test module triggers the fallback.
try:
    from test_local_authority_effect import APPROVAL, BASE, effect_rows, policy, setup_atomic
    from test_refund_intent import fixture as intent_fixture
    from test_w2_stop_recovery import _attempt_rows, _blocked_worker
except ModuleNotFoundError as exc:
    if exc.name not in {"test_local_authority_effect", "test_refund_intent", "test_w2_stop_recovery", "test_safe_executor"}:
        raise
    from vendored_runtime_helpers.local_authority_effect_helpers import APPROVAL, BASE, effect_rows, policy, setup_atomic
    from vendored_runtime_helpers.refund_intent_helpers import fixture as intent_fixture
    from vendored_runtime_helpers.w2_stop_recovery_helpers import _attempt_rows, _blocked_worker


def _head(path: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()


def test_exact_upstream_revisions_are_exercised():
    assert _head(RUNTIME_ROOT) == EXPECTED_RUNTIME_SHA
    assert _head(CONTROL_ROOT) == EXPECTED_CONTROL_SHA
    assert Path(AtomicAuthorityEffectDestination.__module__.replace(".", "/") + ".py").name == "local_authority_effect.py"
    assert Path(RefundIntentRegistry.__module__.replace(".", "/") + ".py").name == "refund_intent.py"


def test_revoked_grant_refuses_before_dispatch_and_records_no_effect(tmp_path):
    _, env, destination, claim = setup_atomic(tmp_path)
    destination.set_grant_status(claim.grant_id, status="revoked")

    result = AtomicLocalControlPlaneExecutor(
        workflow=object(), destination=destination, policy=policy(env.operation)
    ).execute(envelope=env, claim_id=claim.claim_id, attempt_id="refund-revoked-grant")

    assert result.status == "denied"
    assert result.attempted is False
    assert destination.claim_state(claim.claim_id) == "issued"
    assert effect_rows(destination) == []
    failure = destination.failure_history(env.effect_id)[0]
    assert failure["failure_class"] == "authority_hold"
    assert failure["reason_code"] == "current_authority_rejected"
    assert failure["attempt_id"] is None


def test_approval_withdrawal_refuses_before_dispatch_and_records_no_effect(tmp_path):
    _, env, destination, claim = setup_atomic(tmp_path)
    destination.set_approval_status(APPROVAL, status="revoked")

    result = AtomicLocalControlPlaneExecutor(
        workflow=object(), destination=destination, policy=policy(env.operation)
    ).execute(envelope=env, claim_id=claim.claim_id, attempt_id="refund-withdrawn-approval")

    assert result.status == "denied"
    assert result.attempted is False
    assert destination.claim_state(claim.claim_id) == "issued"
    assert effect_rows(destination) == []
    failure = destination.failure_history(env.effect_id)[0]
    assert failure["failure_class"] == "authority_hold"
    assert "approval state invalid" in (failure["detail"] or "")


def test_local_cancellation_before_commit_leaves_no_effect_and_no_retry_authorization(tmp_path):
    _, env, destination, claim = setup_atomic(tmp_path)
    ctx = mp.get_context("spawn")
    reached = ctx.Event()
    proc = ctx.Process(
        target=_blocked_worker,
        args=(str(tmp_path), env, claim.claim_id, "after_begin", reached),
    )
    proc.start()
    assert reached.wait(10)

    proc.terminate()
    proc.join(10)
    assert proc.exitcode is not None
    assert proc.is_alive() is False

    reopened = AtomicAuthorityEffectDestination(tmp_path, clock=lambda: BASE)
    before_effects = effect_rows(reopened)
    before_attempts = _attempt_rows(reopened)
    time.sleep(0.02)
    assert effect_rows(reopened) == before_effects == []
    assert _attempt_rows(reopened) == before_attempts == []
    assert reopened.claim_state(claim.claim_id) == "issued"

    reconciliation = reopened.reconcile_claim(claim.claim_id, snapshot_envelope(env))
    assert reconciliation["status"] == "hold"
    assert reconciliation["retry_eligible"] is False


def test_consumed_claim_suppresses_duplicate_execution_attempt(tmp_path):
    _, env, destination, claim = setup_atomic(tmp_path)
    executor = AtomicLocalControlPlaneExecutor(
        workflow=object(), destination=destination, policy=policy(env.operation)
    )
    first = executor.execute(
        envelope=env, claim_id=claim.claim_id, attempt_id="refund-first-attempt"
    )
    assert first.status == "executed"
    assert first.attempted is True
    assert first.acknowledged is True
    assert first.observed_state == "applied"

    before_effects = effect_rows(destination)
    before_attempts = _attempt_rows(destination)
    duplicate = executor.execute(
        envelope=env, claim_id=claim.claim_id, attempt_id="refund-duplicate-attempt"
    )
    assert duplicate.status == "denied"
    assert duplicate.attempted is False
    assert effect_rows(destination) == before_effects
    assert _attempt_rows(destination) == before_attempts

    reconciliation = destination.reconcile_claim(claim.claim_id, snapshot_envelope(env))
    assert reconciliation["status"] == "applied"
    assert reconciliation["retry_eligible"] is False


def test_lost_ack_recovery_suppresses_blind_retry(tmp_path):
    _, env, destination, claim = setup_atomic(tmp_path)
    executor = AtomicLocalControlPlaneExecutor(
        workflow=object(), destination=destination, policy=policy(env.operation)
    )
    first = executor.execute(
        envelope=env,
        claim_id=claim.claim_id,
        simulate="lost_ack",
        attempt_id="refund-lost-ack",
    )
    assert first.status == "unknown"
    assert first.attempted is True
    assert first.acknowledged is False
    assert first.observed_state == "applied"
    assert first.observation["retry_eligible"] is False

    before_effects = effect_rows(destination)
    before_attempts = _attempt_rows(destination)
    reopened = AtomicAuthorityEffectDestination(tmp_path, clock=lambda: BASE)
    recovery = reopened.reconcile_claim(claim.claim_id, snapshot_envelope(env))
    assert recovery["status"] == "applied"
    assert recovery["retry_eligible"] is False

    retried = AtomicLocalControlPlaneExecutor(
        workflow=object(), destination=reopened, policy=policy(env.operation)
    ).execute(
        envelope=env,
        claim_id=claim.claim_id,
        attempt_id="refund-blind-retry",
    )
    assert retried.status == "denied"
    assert retried.attempted is False
    assert effect_rows(reopened) == before_effects
    assert _attempt_rows(reopened) == before_attempts


def test_refund_intent_registry_keeps_original_owner_and_one_dispatch_claim(tmp_path):
    destination, registry, intent, snapshot = intent_fixture(tmp_path)
    registry.provision(intent, snapshot)
    original = registry.reserve(intent, snapshot)
    assert original.newly_reserved is True
    assert original.original_effect_id == snapshot.effect_id

    replacement = replace(snapshot, effect_id="replacement-effect")
    replay = registry.reserve(intent, replacement)
    assert replay.newly_reserved is False
    assert replay.original_effect_id == snapshot.effect_id
    with pytest.raises(PermissionError):
        registry.mark_dispatch_started(intent, replacement)

    assert registry.mark_dispatch_started(intent, snapshot) is True
    assert registry.mark_dispatch_started(intent, snapshot) is False
    evidence = registry.export_intent(intent)
    assert evidence["dispatch_started"] is True
    assert evidence["retry_eligible"] is False
    assert evidence["authority_established_by_registry"] is False
    assert destination.observe(snapshot.effect_id)["state"] == "absent"


def test_execution_ack_is_only_local_synthetic_effect_state_not_payment_settlement(tmp_path):
    _, env, destination, claim = setup_atomic(tmp_path)
    result = AtomicLocalControlPlaneExecutor(
        workflow=object(), destination=destination, policy=policy(env.operation)
    ).execute(envelope=env, claim_id=claim.claim_id, attempt_id="refund-local-effect")

    assert result.status == "executed"
    assert result.observation["destination_state"]["target"].startswith(
        "urn:cognous:synthetic-account:"
    )
    assert result.observation["destination_state"]["state"] == "applied"
    assert len(effect_rows(destination)) == 1
