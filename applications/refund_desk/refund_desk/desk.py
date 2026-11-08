"""Refund Desk application logic. Builds the documented F1 request, calls F1, and presents the result truthfully.
It does not authorize, execute or reconstruct anything itself. DEVELOPMENT ONLY / SYNTHETIC / NONPRODUCTION / NON-AUTHORIZING."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestration.adapters.refund_disposition import (AuthorityFacts, DispositionRequest, RefundProposal,
                                                       SyntheticEnvironment, dispose_refund, reconcile_refund)

APP_CONTRACT = "refund-desk/0.1.0-dev"
AUTHORITY_ID = "urn:cognous:authority:harborview-refund-desk-1"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_EXECUTED_STATUSES = ("executed", "reconciled", "observed")

_OUTCOMES = {"executed": "executed", "held": "held", "refused": "refused", "denied": "denied",
             "unknown": "uncertain", "failed": "failed"}

_APP_NOTES = (
    "Application note: everything here is synthetic and nonproduction; the destination is a local SQLite file only.",
    "Application note: the evaluation time is a fixed synthetic clock read from the facts fixture, not the wall clock.",
    "Application note: the action manifest is bound by F1 (one allowed synthetic customer, maximum 100.00 USD); "
    "the application cannot widen it.",
)

_REASON_TEXT = {
    "grant_revoked": "the authority that would permit this refund has been revoked",
}


@dataclass(frozen=True)
class RefundCase:
    case_id: str
    tenant_id: str
    customer_account: str
    amount: float
    reason: str
    currency: str = "USD"
    authority: str = "valid"  # valid | revoked


@dataclass(frozen=True)
class DeskConfig:
    stack_root: Path
    state_dir: Path


@dataclass
class DeskResult:
    case_id: str
    outcome: str
    message: str
    f1_contract_version: str = ""
    control_plane: dict = field(default_factory=lambda: {"result": None, "reasons": []})
    native: dict = field(default_factory=dict)
    execution_claim: dict = field(default_factory=lambda: {"supported": False, "basis": "no native execution evidence"})
    effect: dict = field(default_factory=lambda: {"effect_id": None})
    evidence: dict = field(default_factory=lambda: {"replay_state": "not_run", "replay": None, "source": []})
    refusal: dict | None = None
    permitted_next_actions: list = field(default_factory=list)
    retry_permission: str = "not_established"
    effect_absence_established: bool = False
    labels: dict = field(default_factory=dict)
    limitations: list = field(default_factory=list)
    cleanup: dict = field(default_factory=lambda: {"ok": True, "errors": []})

    def to_dict(self) -> dict:
        return {
            "app_contract": APP_CONTRACT,
            "f1_contract_version": self.f1_contract_version,
            "case_id": self.case_id,
            "outcome": self.outcome,
            "message": self.message,
            "control_plane": self.control_plane,
            "native": self.native,
            "execution_claim": self.execution_claim,
            "effect": self.effect,
            "evidence": self.evidence,
            "refusal": self.refusal,
            "permitted_next_actions": list(self.permitted_next_actions),
            "retry_permission": self.retry_permission,
            "effect_absence_established": self.effect_absence_established,
            "labels": self.labels,
            "limitations": list(self.limitations),
            "cleanup": self.cleanup,
        }


def failed_result(case_id: str, text: str) -> DeskResult:
    """Shape for a usage or unexpected error. It never claims an execution."""
    return DeskResult(
        case_id=case_id, outcome="failed",
        message="The refund desk could not complete this request: " + text,
        native={"disposition": None, "runtime_status": None, "runtime_invoked": None, "runtime_invocations": None,
                "acknowledged": None, "newly_executed": None, "observed_state": None, "error": text},
        refusal={"code": "desk_error", "reasons": [text], "explanation": text},
        labels={"synthetic_authority": True, "authenticated": False, "evidence_basis": "producer_reported",
                "nonproduction": True, "non_authorizing": True, "retry_permission": "not_established",
                "not_verified": []},
        limitations=list(_APP_NOTES))


def uncertain_result(case_id: str, text: str) -> DeskResult:
    """Fail-closed shape used when the F1 call was entered but its result could not be obtained or presented."""
    res = failed_result(case_id, text)
    res.outcome = "uncertain"
    res.message = ("The outcome is UNKNOWN because the application could not present the F1 result (%s). "
                   "No retry was made, the absence of an effect is not established, and only reconciliation is permitted."
                   % text)
    res.refusal = None
    res.permitted_next_actions = ["reconcile"]
    return res


def _load(name: str) -> dict:
    with open(_FIXTURES / name, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_request(case: RefundCase, config: DeskConfig) -> DispositionRequest:
    if case.authority not in ("valid", "revoked"):
        raise ValueError("authority must be 'valid' or 'revoked'")
    facts = _load("authority_facts.json")
    observed_at = datetime.fromisoformat(facts["evaluation"]["observed_at"])
    if observed_at.tzinfo is None:
        raise ValueError("facts fixture evaluation.observed_at must be timezone-aware")
    lineage = _load("authority_valid.json" if case.authority == "valid" else "authority_revoked.json")
    return DispositionRequest(
        proposal=RefundProposal(tenant_id=case.tenant_id, customer_id=case.customer_account,
                                refund_reason=case.reason, amount=case.amount, unit=case.currency),
        authority=AuthorityFacts(authority_id=AUTHORITY_ID, lineage_bundle=lineage, facts=facts),
        correlation_id=case.case_id,
        evaluation_time=observed_at,
        environment=SyntheticEnvironment(stack_root=Path(config.stack_root), state_dir=Path(config.state_dir)))


def _call_and_present(fn: Any, request: DispositionRequest, case_id: str) -> DeskResult:
    # Request building happens before this point; once F1 is entered, any failure is reported as uncertain, never failed.
    try:
        f1_result = fn(request)
    except Exception as exc:
        return uncertain_result(case_id, "%s: %s" % (type(exc).__name__, exc))
    try:
        return present(f1_result, case_id)
    except Exception as exc:
        return uncertain_result(case_id, "%s: %s" % (type(exc).__name__, exc))


def process_refund(case: RefundCase, config: DeskConfig) -> DeskResult:
    return _call_and_present(dispose_refund, _build_request(case, config), case.case_id)


def reconcile_case(case: RefundCase, config: DeskConfig) -> DeskResult:
    return _call_and_present(reconcile_refund, _build_request(case, config), case.case_id)


def _val(x: Any) -> Any:
    return getattr(x, "value", x)


def _resolvable(path: str | None, sha: str | None) -> bool:
    if not path or not sha:
        return False
    try:
        p = Path(path)
        if not p.is_file():
            return False
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return False
    expected = sha[len("sha256:"):] if sha.startswith("sha256:") else sha
    return digest == expected


def _file_ref(ref: Any, with_status: bool) -> dict:
    out = {"kind": ref.kind, "path": ref.path, "sha256": ref.sha256, "resolvable": _resolvable(ref.path, ref.sha256)}
    if with_status:
        detail = getattr(ref, "detail", None) or {}
        out = {"path": ref.path, "sha256": ref.sha256, "status": detail.get("status"), "resolvable": out["resolvable"]}
    return out


def _explain(reasons: list, fallback: str) -> str:
    if not reasons:
        return fallback
    parts = [_REASON_TEXT.get(r, "reason recorded as '%s'" % r) for r in reasons]
    return "; ".join(parts)


def present(f1_result: Any, case_id: str) -> DeskResult:
    disposition = str(_val(f1_result.disposition))
    native = f1_result.native
    refusal = f1_result.refusal
    refusal_code = refusal.code if refusal is not None else None
    outcome = _OUTCOMES.get(disposition, "failed")
    # F1 refuses an unresolved repeat; the business meaning is that the earlier outcome is still uncertain.
    if refusal_code == "prior_uncertain_dispatch":
        outcome = "uncertain"
    cp_reasons = [str(r) for r in (native.cp_reasons or ())]

    supported = (disposition == "executed" and native.observed_state == "applied"
                 and native.runtime_status in _EXECUTED_STATUSES)
    if supported:
        claim = {"supported": True, "basis": "native runtime_status=%s with observed_state=applied (producer-reported)"
                 % native.runtime_status}
    else:
        claim = {"supported": False, "basis": "no supported native execution evidence (F1 disposition=%s)" % disposition}

    if outcome == "executed" and supported:
        message = ("The refund effect was observed as applied in the synthetic local SQLite; this is producer-reported, "
                   "not independently verified.")
        if native.acknowledged is False:
            message += " No acknowledgment was received."
    elif outcome == "executed":
        message = ("F1 reported executed, but the application cannot support an execution claim from the native "
                   "observations.")
    elif outcome == "uncertain":
        message = ("The outcome is UNKNOWN. No retry was made, and the absence of an effect is not established. "
                   "Only reconciliation is permitted.")
    elif outcome in ("held", "refused", "denied"):
        if outcome == "held":
            why = _explain(cp_reasons, "the authority decision did not authorize it")
        elif outcome == "refused":
            why = (refusal.reason if refusal is not None else None) or "the request was refused"
        else:
            why = "the runtime policy denied it"
        message = ("This request was not dispatched (%s). This result says nothing about any earlier attempt for this case."
                   % why)
    else:
        message = ("The refund could not be completed: %s. Nothing is reported as applied."
                   % (f1_result.error or native.runtime_error or "an error was reported"))

    refusal_dict = None
    if refusal is not None or outcome in ("held", "refused", "denied"):
        code = refusal_code or "control_plane_hold"
        reasons = cp_reasons if (code == "control_plane_hold" and cp_reasons) else [
            (refusal.reason if refusal is not None else code)]
        explanation = (_explain(cp_reasons, refusal.reason if refusal is not None else code)
                       if code == "control_plane_hold" else (refusal.reason if refusal is not None else code))
        refusal_dict = {"code": code, "reasons": reasons, "explanation": explanation}

    ev = f1_result.evidence
    replay = _file_ref(ev.replay, True) if ev.replay is not None else None
    labels = dataclasses.asdict(f1_result.labels)
    not_verified = [str(s) for s in labels.get("not_verified", ())]
    labels["not_verified"] = not_verified

    return DeskResult(
        case_id=case_id, outcome=outcome, message=message, f1_contract_version=f1_result.contract_version,
        control_plane={"result": native.cp_result, "reasons": cp_reasons},
        native={"disposition": disposition, "runtime_status": native.runtime_status,
                "runtime_invoked": f1_result.runtime_invoked, "runtime_invocations": f1_result.runtime_invocations,
                "acknowledged": native.acknowledged, "newly_executed": native.newly_executed,
                "observed_state": native.observed_state,
                "error": f1_result.error or native.runtime_error},
        execution_claim=claim,
        effect={"effect_id": native.effect_id},
        evidence={"replay_state": ev.replay_state, "replay": replay,
                  "source": [_file_ref(s, False) for s in ev.source]},
        refusal=refusal_dict,
        permitted_next_actions=["reconcile"] if outcome == "uncertain" else [],
        retry_permission="not_established",
        effect_absence_established=False,
        labels=labels,
        limitations=not_verified + list(_APP_NOTES),
        cleanup={"ok": bool(f1_result.cleanup.ok), "errors": [str(e) for e in f1_result.cleanup.errors]})
