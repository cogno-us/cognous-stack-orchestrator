import importlib.util
import pathlib
import sys
from copy import deepcopy
from types import SimpleNamespace
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[5]
DIR = ROOT / "development/scenarios/customer_refunds/connected/contracts"
sys.path.insert(0, str(DIR))
from reconciliation import reconcile_handoff, reconcile_replay_trace, compare_connected_boundaries
from trace_contract import ContractError

def decision(result="hold", reasons=("issued_grant_missing",), binding=None):
    return SimpleNamespace(result=result, reasons=reasons, binding=binding,
                           decision_id="d-1", effect_id="effect-1")

def handoff(**changes):
    args = dict(decision=decision(), observation={"effect_id": "effect-1", "state": "absent"},
                effect_rows=[], attempt_rows=[])
    args.update(changes)
    return reconcile_handoff(**args)

def event(i, kind, **extra):
    e = {"event_id": f"e-{i}", "kind": kind, "sequence": i,
         "tenant_id": "merchant", "request_id": "req", "correlation_id": "corr",
         "provenance": {"source_component": "synthetic-producer",
                        "source_revision": "fixture-not-upstream",
                        "source_record_id": f"source-{i}"}}
    e.update(extra)
    return e

def replay():
    return {"trace_id": "t", "tenant_id": "merchant", "request_id": "req",
            "correlation_id": "corr", "events": [
             event(0, "request"),
             event(1, "screening"),
             event(2, "decision", decision_id="d", authority_state="hold"),
             event(3, "approval_withdrawal", approval_id="a", authority_state="withdrawn"),
             event(4, "refusal", refusal_id="r", refusal_state="refused"),
             event(5, "runtime_attempt", effect_id="effect", attempt_id="attempt", execution_state="refused"),
             event(6, "transport_receipt", receipt_id="receipt", receipt_state="not_sent"),
             event(7, "effect_observation", observer_id="effect-observer", observed_effect="not_observed"),
             event(8, "settlement_observation", observer_id="settlement-observer",
                   settlement="not_observed", independent=True)]}

def test_real_hold_has_no_created_attempt():
    x = handoff()
    assert x["attempt_id"] is None and x["execution_state"] == "not_dispatched"
    assert x["merchant_authority"] == "not_established"

def test_hold_cannot_have_effect_rows():
    with pytest.raises(ContractError, match="effect_or_attempt_after_hold"):
        handoff(effect_rows=[{"effect_id": "effect-1"}])

def test_hold_cannot_generate_runtime_result():
    with pytest.raises(ContractError, match="runtime_result_without_authority"):
        handoff(runtime_result=SimpleNamespace(attempted=False))

def test_grant_and_authorization_distinct():
    with pytest.raises(ContractError, match="non_authorized_binding"):
        handoff(decision=decision(binding=object()))

def test_changed_policy_and_withdrawal_stay_denial_not_settlement():
    for msg in ("policy_stale_or_changed", "approval_not_active"):
        result=handoff(decision=decision(result="denied", reasons=(msg,)))
        assert result["settlement"] == "not_observed"

def test_connected_replay_fields_and_provenance():
    x=reconcile_replay_trace(replay())
    assert x["event_counts"]["runtime_attempt"] == 1
    assert x["source_provenance"] == "producer_reported_not_issuer_verified"
    assert x["institutional_grant"] == "not_established"

def test_missing_provenance():
    t=replay(); t["events"][6].pop("provenance")
    with pytest.raises(ContractError,match="missing_provenance"): reconcile_replay_trace(t)

@pytest.mark.parametrize("kind", ["tenant_id","request_id","correlation_id"])
def test_cross_tenant_and_correlation(kind):
    t=replay(); t["events"][6][kind]="swapped"
    with pytest.raises(ContractError,match=f"{kind}_mismatch"): reconcile_replay_trace(t)

def test_duplicate_intent_and_attempt_not_proof():
    t=replay(); t["events"].insert(6, event(6,"runtime_attempt",effect_id="effect",attempt_id="attempt",execution_state="refused"))
    for i,e in enumerate(t["events"]):
        e["sequence"]=i
        if i>=6: e["event_id"]=f"new-{i}"; e["provenance"]["source_record_id"]=f"new-source-{i}"
    with pytest.raises(ContractError,match="duplicate_or_missing_runtime_identity"):
        reconcile_replay_trace(t)

def test_unknown_effect_observation_remains_unverified():
    t=replay(); t["events"][7]["observed_effect"]="unknown"
    assert reconcile_replay_trace(t)["independent_effect_verification"] is False

@pytest.mark.parametrize("mutation", [
    lambda t: t["events"][8].update(settlement="settled"),
    lambda t: t["events"][6].update(settlement="completed"),
    lambda t: t["events"][8].update(independent=False),
])
def test_false_settlement_and_receipt_claims(mutation):
    t=replay(); mutation(t)
    with pytest.raises(ContractError): reconcile_replay_trace(t)

def test_issuer_verification_not_inferred_from_provenance():
    t=replay(); t["events"][0]["provenance"]["source_component"]="verified-issuer-claimed"
    assert reconcile_replay_trace(t)["source_provenance"] == "producer_reported_not_issuer_verified"

def test_no_fabricated_cross_pr_join():
    x=compare_connected_boundaries(handoff(),reconcile_replay_trace(replay()))
    assert x["compatible_semantics"] and not x["same_trajectory_proven"]
