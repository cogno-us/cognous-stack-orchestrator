"""O6-Q6 actual Runtime source resilience, adapter and mutation regression."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = Path(os.environ["COGNOUS_O6_Q6_RUNTIME_ROOT"]).resolve()
PIN = "1b0a9e32d010797711004ae612051a277b07912a"
assert subprocess.check_output(["git", "-C", str(RUNTIME), "rev-parse", "HEAD"], text=True).strip() == PIN
sys.path.insert(0, str(RUNTIME))
from engine.revocation_closeout import OrderingEvidence, RevocationCloseoutStore

spec = importlib.util.spec_from_file_location(
    "o6_q6_real_runtime_reconciliation", ROOT / "development/recovery/o6_q6/reconciliation.py"
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


def caps(**overrides):
    values = dict(adapter_id="adapter:synthetic", client_reference_searchable=True,
                  dedupe_by_effect_id=True, bounded_deadline=True,
                  observation_coverage=True, destination_watermark=True,
                  provider_acceptance_closure=True)
    values.update(overrides)
    return mod.AdapterCapabilities(**values)


def seeded(tmp_path, *, effect="effect:original", attempt="attempt:original",
           writer=True):
    store = RevocationCloseoutStore(
        tmp_path / "ledger", clock=lambda: NOW, closeout_writer_enabled=writer
    )
    store.record_item(
        effect_id=effect, attempt_id=attempt, decision_id="decision:original",
        grant_id="grant:alpha", grant_revision="v3", state="executing",
        ordering=OrderingEvidence(5, "test:committed-before-revocation"),
    )
    result = store.record_revocation(
        grant_id="grant:alpha", grant_revision="v3",
        revocation=OrderingEvidence(6, "test:revocation"),
        owner="synthetic:operator", deadline=NOW + timedelta(minutes=5),
        reconciliation_ref="synthetic:recovery",
    )
    assert result[0].status == "in_doubt"
    return store


def observation(*, state="unknown", effect="effect:original",
                attempt="attempt:original", **kw):
    values = dict(effect_id=effect, attempt_id=attempt,
                  adapter_id="adapter:synthetic", state=state,
                  observation_ref="observer:original-attempt:1",
                  ordering_ref="observer:watermark:7", order=7,
                  observed_at=NOW, client_reference=effect,
                  provider_acceptance_ref="provider:acceptance:ref" if state in ("applied", "partial") else None,
                  independent_observer_ref="observer:independent:ref",
                  watermark_ref="observer:watermark:ref")
    values.update(kw)
    return mod.Observation(**values)


def test_crash_restart_unknown_never_licenses_retry(tmp_path):
    store = seeded(tmp_path)
    # Simulated process crash after disposition, before observer response.
    del store
    restored = RevocationCloseoutStore(tmp_path / "ledger")
    coordinator = mod.RecoveryCoordinator(restored, caps())
    result = coordinator.reconcile(observation())
    assert not result.closed and not result.retry_eligible
    restarted = mod.RecoveryCoordinator(RevocationCloseoutStore(tmp_path / "ledger"), caps())
    assert restarted.reconcile(observation()) == result
    assert restarted.metrics(now=NOW)["original_attempts_unresolved"] == 1


@pytest.mark.parametrize("state", ["absent", "unknown"])
def test_absence_is_never_retry_permission(tmp_path, state):
    c = mod.RecoveryCoordinator(seeded(tmp_path), caps())
    result = c.reconcile(observation(state=state))
    assert not result.closed and not result.retry_eligible


@pytest.mark.parametrize("state", ["applied", "partial"])
def test_independently_referenced_outcome_closes_original_attempt_only(tmp_path, state):
    c = mod.RecoveryCoordinator(seeded(tmp_path), caps())
    result = c.reconcile(observation(state=state))
    assert result.closed and result.attempt_id == "attempt:original"
    assert result.effect_id == "effect:original" and not result.retry_eligible
    assert mod.RecoveryCoordinator(RevocationCloseoutStore(tmp_path / "ledger"), caps()).reconcile(
        observation(state=state)
    ) == result
    assert c.metrics(now=NOW)["original_attempts_closed"] == 1


@pytest.mark.parametrize("field", [
    "client_reference_searchable", "dedupe_by_effect_id", "bounded_deadline",
    "observation_coverage", "destination_watermark", "provider_acceptance_closure"
])
def test_missing_adapter_conformance_fails_closed(tmp_path, field):
    store = seeded(tmp_path)
    c = mod.RecoveryCoordinator(store, caps(**{field: False}))
    with pytest.raises(mod.RecoveryHold, match="adapter_capability_unqualified"):
        c.reconcile(observation(state="applied"))
    assert store.closeout("attempt:original") is None


@pytest.mark.parametrize("changes", [
    {"effect_id": "effect:other", "client_reference": "effect:other"},
    {"attempt_id": "attempt:other"},
    {"adapter_id": "adapter:other"},
    {"client_reference": "effect:other"},
    {"independent_observer_ref": None},
    {"watermark_ref": None},
    {"provider_acceptance_ref": None},
    {"observation_ref": ""},
])
def test_swapped_identity_or_missing_provenance_rejected(tmp_path, changes):
    store = seeded(tmp_path)
    c = mod.RecoveryCoordinator(store, caps())
    with pytest.raises(mod.RecoveryHold):
        c.reconcile(observation(state="applied", **changes))
    assert store.closeout("attempt:original") is None


def test_conflicting_observer_after_restart_cannot_overwrite(tmp_path):
    c = mod.RecoveryCoordinator(seeded(tmp_path), caps())
    first = c.reconcile(observation(state="unknown"))
    reopened = mod.RecoveryCoordinator(RevocationCloseoutStore(tmp_path / "ledger"), caps())
    with pytest.raises(mod.RecoveryHold, match="conflicting_original_attempt_observation"):
        reopened.reconcile(observation(state="applied", observation_ref="observer:late-conflict"))
    assert reopened.store.closeout("attempt:original") == first


def test_disabled_original_closeout_writer_is_detected(tmp_path):
    store = seeded(tmp_path, writer=False)
    c = mod.RecoveryCoordinator(store, caps())
    with pytest.raises(mod.RecoveryHold, match="closeout_persistence_unqualified"):
        c.reconcile(observation(state="applied"))
    assert store.closeout("attempt:original") is None


def test_concurrent_conflicting_observers_cannot_mutate_original_twice(tmp_path):
    store = seeded(tmp_path)
    observers = [observation(state="unknown", observation_ref="observer:a"),
                 observation(state="applied", observation_ref="observer:b")]
    def execute(item):
        c = mod.RecoveryCoordinator(RevocationCloseoutStore(tmp_path / "ledger"), caps())
        try:
            return ("ok", c.reconcile(item))
        except mod.RecoveryHold as exc:
            return ("hold", str(exc))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, observers))
    assert sum(kind == "ok" for kind, _ in results) == 1
    assert sum(kind == "hold" for kind, _ in results) == 1
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM original_attempt_closeouts_v1").fetchone()[0] == 1
        assert conn.execute("SELECT MAX(retry_eligible) FROM original_attempt_closeouts_v1").fetchone()[0] == 0


def test_overdue_metrics_are_restart_persistent_and_no_payload(tmp_path):
    store = seeded(tmp_path)
    c = mod.RecoveryCoordinator(store, caps())
    metrics = c.metrics(now=NOW + timedelta(minutes=12))
    assert metrics["retained_items"] == 1
    assert metrics["in_doubt_recorded"] == 1
    assert metrics["overdue_count"] == 1
    assert metrics["oldest_overdue_seconds"] == 420.0
    assert c.metrics(now=NOW + timedelta(minutes=12)) == metrics
    with sqlite3.connect(store.path) as conn:
        sql = " ".join(row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"))
    assert "raw_payload" not in sql
