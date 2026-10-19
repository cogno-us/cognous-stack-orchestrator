"""O6-Q6 bounded reconciliation over the accepted Runtime closeout implementation.

Evidence intake only. Never issues authority, dispatches an effect, or permits retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from engine.revocation_closeout import OrderingEvidence, RevocationCloseoutStore

State = Literal["applied", "partial", "absent", "unknown"]


class RecoveryHold(RuntimeError):
    """An unverifiable or unsafe observation must never be promoted."""


@dataclass(frozen=True)
class AdapterCapabilities:
    adapter_id: str
    client_reference_searchable: bool
    dedupe_by_effect_id: bool
    bounded_deadline: bool
    observation_coverage: bool
    destination_watermark: bool
    provider_acceptance_closure: bool

    def conformant(self) -> bool:
        return bool(self.adapter_id and all((
            self.client_reference_searchable, self.dedupe_by_effect_id,
            self.bounded_deadline, self.observation_coverage,
            self.destination_watermark, self.provider_acceptance_closure,
        )))


@dataclass(frozen=True)
class Observation:
    effect_id: str
    attempt_id: str
    adapter_id: str
    state: State
    observation_ref: str
    ordering_ref: str
    order: int
    observed_at: datetime
    client_reference: str
    provider_acceptance_ref: str | None
    independent_observer_ref: str | None
    watermark_ref: str | None


class RecoveryCoordinator:
    """Compose actual Runtime evidence; reject unverifiable observations.

    Adapter conformance is a local declaration, not independently established
    provider capability. An independently sourced observer reference is still
    caller-provided and not cryptographically authenticated here.
    """

    def __init__(self, store: RevocationCloseoutStore, adapter: AdapterCapabilities):
        self.store = store
        self.adapter = adapter

    def reconcile(self, observation: Observation):
        if not self.adapter.conformant():
            raise RecoveryHold("adapter_capability_unqualified")
        if observation.adapter_id != self.adapter.adapter_id:
            raise RecoveryHold("adapter_identity_mismatch")
        if observation.state not in ("applied", "partial", "absent", "unknown"):
            raise RecoveryHold("observation_state_invalid")
        if not isinstance(observation.observed_at, datetime) or observation.observed_at.tzinfo is None:
            raise RecoveryHold("observation_time_unqualified")
        if observation.order < 0 or not observation.ordering_ref:
            raise RecoveryHold("observation_order_unqualified")
        if not observation.client_reference or not observation.observation_ref:
            raise RecoveryHold("observation_provenance_missing")
        if not observation.watermark_ref or not observation.independent_observer_ref:
            raise RecoveryHold("independent_observation_unqualified")
        if observation.state in ("applied", "partial") and not observation.provider_acceptance_ref:
            raise RecoveryHold("provider_acceptance_unqualified")

        # Bind to the specific original retained attempt before any closeout.
        # The Runtime store owns authoritative persisted effect/attempt records.
        import sqlite3
        with sqlite3.connect(self.store.path) as conn:
            row = conn.execute(
                "SELECT effect_id FROM runtime_items_v1 WHERE attempt_id=?",
                (observation.attempt_id,),
            ).fetchone()
        if row is None or row[0] != observation.effect_id:
            raise RecoveryHold("original_attempt_identity_mismatch")
        if observation.client_reference != observation.effect_id:
            raise RecoveryHold("client_reference_not_bound_to_effect")

        prior = self.store.closeout(observation.attempt_id)
        if prior is not None:
            if prior.effect_id != observation.effect_id or prior.observation_ref != observation.observation_ref:
                raise RecoveryHold("conflicting_original_attempt_observation")
            # Durable idempotent read. Any prior row remains retry-ineligible.
            if prior.retry_eligible:
                raise RecoveryHold("invalid_persisted_retry_claim")
            if prior.observation_state != observation.state:
                raise RecoveryHold("conflicting_observation_state")
            return prior

        try:
            result = self.store.close_original_attempt(
                attempt_id=observation.attempt_id,
                observation_state=observation.state,
                observation=OrderingEvidence(observation.order, observation.ordering_ref),
                observation_ref=observation.observation_ref,
            )
        except (ValueError, LookupError, RuntimeError, sqlite3.IntegrityError) as exc:
            raise RecoveryHold("closeout_persistence_unqualified") from exc
        if result.retry_eligible:
            raise RecoveryHold("closeout_must_never_authorize_retry")
        return result

    def metrics(self, *, now: datetime) -> dict[str, int | float | None]:
        import sqlite3
        report = self.store.overdue_report(now=now)
        with sqlite3.connect(self.store.path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM runtime_items_v1").fetchone()[0]
            refused = conn.execute(
                "SELECT COUNT(*) FROM revocation_dispositions_v1 WHERE status='refused_before_execution'"
            ).fetchone()[0]
            doubtful = conn.execute(
                "SELECT COUNT(*) FROM revocation_dispositions_v1 WHERE status='in_doubt'"
            ).fetchone()[0]
            closed = conn.execute(
                "SELECT COUNT(*) FROM original_attempt_closeouts_v1 WHERE closed=1"
            ).fetchone()[0]
            unresolved = conn.execute(
                "SELECT COUNT(*) FROM original_attempt_closeouts_v1 WHERE closed=0"
            ).fetchone()[0]
        return {
            "retained_items": total, "refused_before_execution": refused,
            "in_doubt_recorded": doubtful, "original_attempts_closed": closed,
            "original_attempts_unresolved": unresolved,
            "overdue_count": report["count"],
            "oldest_overdue_seconds": report["oldest_age_seconds"],
        }
