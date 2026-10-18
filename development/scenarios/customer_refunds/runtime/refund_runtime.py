"""Synthetic refund runtime qualification for O5-C-B.

This module is an orchestrator-side test adapter. It mirrors selected accepted
Execution Runtime contract boundaries but does not import the runtime, authenticate
a real Control Plane decision, call a payment processor, move funds, or observe
settlement.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXECUTION_RUNTIME_REVISION = "11de097c450d3ad4d89f9add41b00e38e7cc2c7c"
PROFILE = "urn:cognous:orchestrator:customer-refund-runtime-qualification:0.1.0"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def refund_attempt_key(*, tenant_id: str, request_id: str, order_ref: str, payment_ref: str) -> str:
    """Stable synthetic intent key scoped exactly to tenant/request/order/payment."""
    material = {
        "tenant_id": tenant_id,
        "request_id": request_id,
        "order_ref": order_ref,
        "payment_ref": payment_ref,
    }
    return "sha256:" + hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RefundIntent:
    tenant_id: str
    request_id: str
    order_ref: str
    payment_ref: str
    effect_id: str
    amount_minor: int
    currency: str = "USD"

    @property
    def attempt_key(self) -> str:
        return refund_attempt_key(
            tenant_id=self.tenant_id,
            request_id=self.request_id,
            order_ref=self.order_ref,
            payment_ref=self.payment_ref,
        )


def fixture_control_plane_permit(intent: RefundIntent, *, decision_id: str = "decision-fixture") -> dict[str, Any]:
    """Return a synthetic permit-shaped fixture.

    This helper does not authenticate a Control Plane or issue authority. Tests may
    use it only as a positive fixture for the adapter's fail-closed boundary.
    """
    return {
        "source": "synthetic_control_plane_fixture",
        "authenticated_control_plane_permit": True,
        "decision": "permit",
        "decision_id": decision_id,
        "effect_id": intent.effect_id,
        "tenant_id": intent.tenant_id,
        "request_id": intent.request_id,
        "order_ref": intent.order_ref,
        "payment_ref": intent.payment_ref,
        "amount_minor": intent.amount_minor,
        "currency": intent.currency,
        "authority_current": True,
    }


class SyntheticRefundRuntime:
    """Durable local intent ledger plus simulated effect boundary.

    Linearization uses one SQLite write transaction, consistent with the accepted
    same-host Execution Runtime profile. The resulting "effect" is only a retained
    simulated row; it is not a processor call or settlement observation.
    """

    def __init__(self, root: str | Path, database_name: str = "refund_runtime.sqlite3"):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / database_name
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS profile (
                    profile TEXT PRIMARY KEY,
                    runtime_revision TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cancellations (
                    attempt_key TEXT PRIMARY KEY,
                    reason TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS authority_withdrawals (
                    decision_id TEXT PRIMARY KEY,
                    reason TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS intents (
                    attempt_key TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    order_ref TEXT NOT NULL,
                    payment_ref TEXT NOT NULL,
                    effect_id TEXT NOT NULL UNIQUE,
                    decision_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('simulated_applied')),
                    operation_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY,
                    attempt_key TEXT NOT NULL,
                    effect_id TEXT NOT NULL,
                    decision_id TEXT,
                    outcome TEXT NOT NULL,
                    reason TEXT
                );
                """
            )
            row = conn.execute("SELECT profile,runtime_revision FROM profile").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO profile(profile,runtime_revision) VALUES(?,?)",
                    (PROFILE, EXECUTION_RUNTIME_REVISION),
                )
            elif row["profile"] != PROFILE or row["runtime_revision"] != EXECUTION_RUNTIME_REVISION:
                raise PermissionError("unsupported synthetic refund runtime profile")

    @staticmethod
    def _validate_intent(intent: RefundIntent) -> None:
        for name in ("tenant_id", "request_id", "order_ref", "payment_ref", "effect_id"):
            value = getattr(intent, name)
            if not isinstance(value, str) or not value:
                raise ValueError("invalid_" + name)
        if type(intent.amount_minor) is not int or intent.amount_minor <= 0:
            raise ValueError("invalid_amount_minor")
        if intent.currency != "USD":
            raise ValueError("unsupported_currency")

    @staticmethod
    def _permit_reason(intent: RefundIntent, permit: Any) -> tuple[str | None, str | None]:
        if not isinstance(permit, dict):
            return "missing_authenticated_control_plane_permit", None
        decision_id = permit.get("decision_id")
        if permit.get("authenticated_control_plane_permit") is not True:
            return "unauthenticated_control_plane_permit", decision_id
        if permit.get("decision") != "permit":
            return "control_plane_refused", decision_id
        if permit.get("authority_current") is not True:
            return "authority_not_current", decision_id
        expected = {
            "tenant_id": intent.tenant_id,
            "request_id": intent.request_id,
            "order_ref": intent.order_ref,
            "payment_ref": intent.payment_ref,
            "effect_id": intent.effect_id,
            "amount_minor": intent.amount_minor,
            "currency": intent.currency,
        }
        for field, value in expected.items():
            permitted = permit.get(field)
            if type(permitted) is not type(value) or permitted != value:
                return "permit_binding_mismatch_" + field, decision_id
        if not isinstance(decision_id, str) or not decision_id:
            return "missing_decision_id", None
        return None, decision_id

    @staticmethod
    def _operation_digest(intent: RefundIntent) -> str:
        operation = {
            "tenant_id": intent.tenant_id,
            "request_id": intent.request_id,
            "order_ref": intent.order_ref,
            "payment_ref": intent.payment_ref,
            "effect_id": intent.effect_id,
            "amount_minor": intent.amount_minor,
            "currency": intent.currency,
            "operation": "refund",
        }
        return "sha256:" + hashlib.sha256(_canonical(operation).encode("utf-8")).hexdigest()

    def cancel(self, intent: RefundIntent, reason: str = "cancelled") -> dict[str, Any]:
        self._validate_intent(intent)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT effect_id FROM intents WHERE attempt_key=?", (intent.attempt_key,)
            ).fetchone()
            if existing is not None:
                conn.execute("COMMIT")
                return {
                    "status": "post_commit_no_rollback",
                    "effect_id": existing["effect_id"],
                    "attempt_key": intent.attempt_key,
                }
            conn.execute(
                "INSERT OR IGNORE INTO cancellations(attempt_key,reason) VALUES(?,?)",
                (intent.attempt_key, reason),
            )
            conn.execute("COMMIT")
        return {"status": "cancelled_before_effect", "attempt_key": intent.attempt_key}

    def withdraw_authority(self, decision_id: str, reason: str = "withdrawn") -> dict[str, Any]:
        if not isinstance(decision_id, str) or not decision_id:
            raise ValueError("invalid_decision_id")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            applied = conn.execute(
                "SELECT effect_id FROM intents WHERE decision_id=?", (decision_id,)
            ).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO authority_withdrawals(decision_id,reason) VALUES(?,?)",
                (decision_id, reason),
            )
            conn.execute("COMMIT")
        return {
            "status": "withdrawn_after_effect_no_rollback" if applied else "withdrawn_before_effect",
            "effect_id": applied["effect_id"] if applied else None,
        }

    def execute(
        self,
        intent: RefundIntent,
        *,
        permit: Any = None,
        attempt_id: str,
    ) -> dict[str, Any]:
        self._validate_intent(intent)
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("invalid_attempt_id")

        permit_reason, decision_id = self._permit_reason(intent, permit)
        operation_digest = self._operation_digest(intent)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            duplicate = conn.execute(
                "SELECT * FROM intents WHERE attempt_key=?", (intent.attempt_key,)
            ).fetchone()
            if duplicate is not None:
                if permit_reason:
                    # An invalid permit never writes audit rows against the
                    # committed effect; it is refused on its own terms.
                    conn.execute("COMMIT")
                    return self._result(
                        status="refused",
                        reason=permit_reason,
                        attempted=False,
                        simulated_effect=False,
                        intent=intent,
                        attempt_id=attempt_id,
                        decision_id=decision_id,
                    )
                # Suppression is recorded against the persisted effect identity,
                # never a caller-substituted effect_id/decision_id.
                conn.execute(
                    """INSERT OR IGNORE INTO attempts
                    (attempt_id,attempt_key,effect_id,decision_id,outcome,reason)
                    VALUES(?,?,?,?,?,?)""",
                    (
                        attempt_id,
                        intent.attempt_key,
                        duplicate["effect_id"],
                        duplicate["decision_id"],
                        "suppressed",
                        "duplicate_intent",
                    ),
                )
                conn.execute("COMMIT")
                result = self._result(
                    status="refused",
                    reason="duplicate_intent",
                    attempted=False,
                    simulated_effect=False,
                    intent=intent,
                    attempt_id=attempt_id,
                    decision_id=duplicate["decision_id"],
                )
                result["effect_id"] = duplicate["effect_id"]
                return result

            if conn.execute(
                "SELECT 1 FROM cancellations WHERE attempt_key=?", (intent.attempt_key,)
            ).fetchone():
                permit_reason = permit_reason or "cancelled"

            if decision_id and conn.execute(
                "SELECT 1 FROM authority_withdrawals WHERE decision_id=?", (decision_id,)
            ).fetchone():
                permit_reason = permit_reason or "authority_withdrawn"

            # Refusals are durable attempts but never effect rows.
            if permit_reason:
                if conn.execute(
                    "SELECT 1 FROM attempts WHERE attempt_id=?", (attempt_id,)
                ).fetchone():
                    conn.execute("ROLLBACK")
                    raise PermissionError("attempt_identity_already_exists")
                conn.execute(
                    """INSERT INTO attempts
                    (attempt_id,attempt_key,effect_id,decision_id,outcome,reason)
                    VALUES(?,?,?,?,?,?)""",
                    (
                        attempt_id,
                        intent.attempt_key,
                        intent.effect_id,
                        decision_id,
                        "refused",
                        permit_reason,
                    ),
                )
                conn.execute("COMMIT")
                return self._result(
                    status="refused",
                    reason=permit_reason,
                    attempted=False,
                    simulated_effect=False,
                    intent=intent,
                    attempt_id=attempt_id,
                    decision_id=decision_id,
                )

            if conn.execute(
                "SELECT 1 FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone():
                conn.execute("ROLLBACK")
                raise PermissionError("attempt_identity_already_exists")

            # Synthetic linearization point: effect row and execution attempt commit
            # together. No external processor dispatch occurs.
            conn.execute(
                """INSERT INTO intents
                (attempt_key,tenant_id,request_id,order_ref,payment_ref,effect_id,
                 decision_id,state,operation_digest)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    intent.attempt_key,
                    intent.tenant_id,
                    intent.request_id,
                    intent.order_ref,
                    intent.payment_ref,
                    intent.effect_id,
                    decision_id,
                    "simulated_applied",
                    operation_digest,
                ),
            )
            conn.execute(
                """INSERT INTO attempts
                (attempt_id,attempt_key,effect_id,decision_id,outcome,reason)
                VALUES(?,?,?,?,?,NULL)""",
                (
                    attempt_id,
                    intent.attempt_key,
                    intent.effect_id,
                    decision_id,
                    "simulated_applied",
                ),
            )
            conn.execute("COMMIT")

        return self._result(
            status="simulated_applied",
            reason=None,
            attempted=True,
            simulated_effect=True,
            intent=intent,
            attempt_id=attempt_id,
            decision_id=decision_id,
        )

    def _result(
        self,
        *,
        status: str,
        reason: str | None,
        attempted: bool,
        simulated_effect: bool,
        intent: RefundIntent,
        attempt_id: str,
        decision_id: str | None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "reason": reason,
            "attempt_key": intent.attempt_key,
            "attempt_id": attempt_id,
            "effect_id": intent.effect_id,
            "decision_id": decision_id,
            "attempted": attempted,
            "simulated_effect": simulated_effect,
            "processor_call": False,
            "settlement": "not_observed",
            "runtime_revision": EXECUTION_RUNTIME_REVISION,
        }

    def state(self) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as conn:
            intents = [dict(row) for row in conn.execute("SELECT * FROM intents ORDER BY attempt_key")]
            attempts = [dict(row) for row in conn.execute("SELECT * FROM attempts ORDER BY attempt_id")]
            cancellations = [
                dict(row) for row in conn.execute("SELECT * FROM cancellations ORDER BY attempt_key")
            ]
            withdrawals = [
                dict(row)
                for row in conn.execute("SELECT * FROM authority_withdrawals ORDER BY decision_id")
            ]
        return {
            "intents": intents,
            "attempts": attempts,
            "cancellations": cancellations,
            "authority_withdrawals": withdrawals,
        }
