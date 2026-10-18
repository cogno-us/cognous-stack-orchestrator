"""Duplicate, lost-acknowledgement and delayed-commit flows against the Runtime's opt-in destinations, with the orchestrator's inputs.

A runner, not a test (subprocess; candidate revisions only, because the destinations do not exist at the orchestrator's pins).
Inputs are the orchestrator's: the pinned Action Manifest example and the tenant-bound proposal. The route is Control Plane
BoundedAuthorizationWorkflow -> Runtime PinnedControlPlaneExecutor (not the orchestrator's atomic-claim route; see the gap report).

    COGNOUS_ACTION_MANIFEST_SRC=... COGNOUS_CONTROL_PLANE_SRC=... COGNOUS_EXECUTION_RUNTIME_ROOT=... \
        python tests/overlay/_destination_runner.py OUTDIR

Scenarios (each reports what happened; assertions are in test_overlay_destinations.py):
  lost_ack_then_land[identity=off|on]   delayed-commit destination loses the acknowledgement; absent is read; retry is refused;
                                        the late commit lands; one effect.
  renewal_race[identity=off|on]         r1 is inside the destination, the grant is renewed, r2 commits, r1 lands late.
  renewal_during_lost_ack[identity=..]  r1's commit is deferred (acknowledgement lost, unknown), the grant is renewed, r2 is attempted
                                        while r1 is outstanding, then r1 lands late (F-5 probe, adapter route).
  renewal_after_landing[identity=..]    r1 lands late, then the grant is renewed and a decision for the same operation is attempted.
  atomic_route_surface                  whether the orchestrator's accepted atomic route can carry an operation id at all.
"""
from __future__ import annotations

import inspect
import json
import os
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _journal_runner as J  # noqa: E402


def _attempts(flow) -> list[dict]:
    latest: dict[str, object] = {}
    for item in flow.f.records.load().attempts:
        latest[item.attempt_id] = item
    return [{"effect_id": a.effect_id, "status": a.status, "error": a.error} for a in latest.values()]


def lost_ack_then_land(work, identity: bool, out: pathlib.Path) -> dict:
    flow = J.Flow(work, "identity" if identity else "off", delayed=True)
    assert flow.d1.result == "authorized", flow.d1.reasons
    effect_id = flow.d1.effect_id
    flow.dest.defer_next_commit()
    first = flow.run()
    absent_ledger = flow.ledger()
    retry = flow.run()  # must not dispatch while the first commit is outstanding
    rec = flow.f.records.load()
    reconciliations = [{"result": x.result, "retry_eligible": x.retry_eligible} for x in rec.reconciliations if x.effect_id == effect_id]
    attempts_before_land = _attempts(flow)
    in_flight = len(flow.dest.in_flight)
    flow.dest.land()  # the provider processed the first commit late
    landed_ledger = [r["effect_id"] for r in flow.ledger()]
    again = flow.executor.reconcile(flow.envelope(flow.d1), now=flow.NOW)
    flow.keep(out, f"lost_ack_then_land_identity_{'on' if identity else 'off'}", {"decision": flow.d1.result})
    return {
        "first": J._res(first), "ledger_while_absent": [r["effect_id"] for r in absent_ledger], "retry": J._res(retry),
        "reconciliations": reconciliations, "attempts_before_land": attempts_before_land, "in_flight_before_land": in_flight,
        "ledger_after_land": landed_ledger, "effect_id": effect_id,
        "reconcile_after_land": {"result": again.result, "retry_eligible": again.retry_eligible},
        "safe_to_retry_rows": [x.result for x in flow.f.records.load().reconciliations if x.result == "safe_to_retry"],
    }


def renewal_race(work, identity: bool, out: pathlib.Path) -> dict:
    flow = J.Flow(work, "identity" if identity else "off", delayed=True, wide=True)
    assert flow.d1.result == "authorized", flow.d1.reasons
    box: dict = {}

    def renew_and_commit_r2():
        flow.publish_revision("2")
        if identity:
            flow.f.record_renewal(J.OPERATION, to_revision="2", written_by=flow.tba.ISSUER, now=flow.NOW)
        d2 = flow.f.decide(flow.p, now=flow.NOW)
        box["d2"] = d2
        box["r2"] = flow.run(d2) if d2.result == "authorized" else None

    flow.dest.pause_at("commit", renew_and_commit_r2)
    r1 = flow.run()
    d2, r2 = box["d2"], box["r2"]
    rec = flow.f.records.load()
    flow.keep(out, f"renewal_race_identity_{'on' if identity else 'off'}", {"decision": flow.d1.result})
    return {
        "d1_effect_id": flow.d1.effect_id, "d2_result": d2.result, "d2_reasons": list(d2.reasons), "d2_effect_id": d2.effect_id,
        "r1": J._res(r1), "r2": J._res(r2) if r2 else None, "ledger": [r["effect_id"] for r in flow.ledger()],
        "attempt_joins": len(getattr(rec, "attempt_joins", []) or []), "operations": len(getattr(rec, "operations", []) or []),
    }


def _renew(flow, identity: bool):
    flow.publish_revision("2")
    if identity:
        flow.f.record_renewal(J.OPERATION, to_revision="2", written_by=flow.tba.ISSUER, now=flow.NOW)
    return flow.f.decide(flow.p, now=flow.NOW)


def _land(flow) -> str | None:
    """Let the provider process the outstanding commit; return the refusal the destination raised, if any (recorded as data)."""
    try:
        flow.dest.land()
    except Exception as exc:  # the destination's own guard refusing a late commit is an outcome, not a runner failure
        return f"{type(exc).__name__}: {exc}"
    return None


def _joins(flow) -> dict:
    rec = flow.f.records.load()
    return {"operations": len(getattr(rec, "operations", []) or []), "attempt_joins": len(getattr(rec, "attempt_joins", []) or [])}


def renewal_during_lost_ack(work, identity: bool, out: pathlib.Path) -> dict:
    """F-5 probe on the adapter route: a renewal while the first commit is outstanding (delayed-commit destination)."""
    flow = J.Flow(work, "identity" if identity else "off", delayed=True, wide=True)
    assert flow.d1.result == "authorized", flow.d1.reasons
    flow.dest.defer_next_commit()
    r1 = flow.run()
    in_flight_after_r1 = len(flow.dest.in_flight)
    d2 = _renew(flow, identity)
    r2 = flow.run(d2) if d2.result == "authorized" else None
    in_flight_before_land = len(flow.dest.in_flight)
    ledger_before_land = [r["effect_id"] for r in flow.ledger()]
    land_refusal = _land(flow)
    ledger_after_land = [r["effect_id"] for r in flow.ledger()]
    flow.keep(out, f"renewal_during_lost_ack_identity_{'on' if identity else 'off'}", {"decision": flow.d1.result})
    return {"d1_effect_id": flow.d1.effect_id, "d2_result": d2.result, "d2_reasons": list(d2.reasons), "d2_effect_id": d2.effect_id,
            "r1": J._res(r1), "r2": J._res(r2) if r2 else None, "in_flight_after_r1": in_flight_after_r1,
            "in_flight_before_land": in_flight_before_land, "ledger_before_land": ledger_before_land,
            "land_refusal": land_refusal, "in_flight_after_land": len(flow.dest.in_flight),
            "ledger_after_land": ledger_after_land, **_joins(flow)}


def renewal_after_landing(work, identity: bool, out: pathlib.Path) -> dict:
    """F-5 probe on the adapter route: r1 lands late, then the grant is renewed and the same operation is decided again."""
    flow = J.Flow(work, "identity" if identity else "off", delayed=True, wide=True)
    assert flow.d1.result == "authorized", flow.d1.reasons
    flow.dest.defer_next_commit()
    r1 = flow.run()
    land_refusal = _land(flow)
    ledger_after_land = [r["effect_id"] for r in flow.ledger()]
    d2 = _renew(flow, identity)
    r2 = flow.run(d2) if d2.result == "authorized" else None
    flow.keep(out, f"renewal_after_landing_identity_{'on' if identity else 'off'}", {"decision": flow.d1.result})
    return {"d1_effect_id": flow.d1.effect_id, "d2_result": d2.result, "d2_reasons": list(d2.reasons), "d2_effect_id": d2.effect_id,
            "r1": J._res(r1), "r2": J._res(r2) if r2 else None, "land_refusal": land_refusal, "ledger_after_land": ledger_after_land,
            "ledger_final": [r["effect_id"] for r in flow.ledger()], **_joins(flow)}


def atomic_route_surface() -> dict:
    from engine.atomic_local_control_plane_executor import AtomicLocalControlPlaneExecutor
    from engine.local_authority_effect import AtomicAuthorityEffectDestination
    from engine.operation_identity_destination import OperationIdentityDestination
    from engine.safe_executor import DurableRefundDestination
    execute_params = list(inspect.signature(AtomicLocalControlPlaneExecutor.execute).parameters)
    atomic_params = list(inspect.signature(AtomicAuthorityEffectDestination.execute_claim_atomic).parameters)
    return {
        "atomic_executor_execute_params": execute_params,
        "atomic_destination_execute_claim_atomic_params": atomic_params,
        "atomic_destination_has_operation_identity_capability": hasattr(AtomicAuthorityEffectDestination, "operation_identity_capability"),
        "atomic_destination_subclasses_durable": issubclass(AtomicAuthorityEffectDestination, DurableRefundDestination),
        "atomic_destination_subclasses_operation_identity": issubclass(AtomicAuthorityEffectDestination, OperationIdentityDestination),
        "atomic_destination_has_delayed_commit_surface": hasattr(AtomicAuthorityEffectDestination, "defer_next_commit"),
        "atomic_executor_mentions_operation_id": "operation_id" in inspect.getsource(AtomicLocalControlPlaneExecutor),
        "atomic_destination_mentions_operation_id": "operation_id" in inspect.getsource(AtomicAuthorityEffectDestination),
    }


def main(out: pathlib.Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    J._deterministic_uuids()
    cp_src, rt_src = os.environ["COGNOUS_CONTROL_PLANE_SRC"], os.environ["COGNOUS_EXECUTION_RUNTIME_ROOT"]
    for p in (pathlib.Path(rt_src) / "tests", pathlib.Path(rt_src), pathlib.Path(cp_src) / "src", pathlib.Path(cp_src),
              pathlib.Path(os.environ["COGNOUS_ACTION_MANIFEST_SRC"]) / "src"):
        sys.path.insert(0, str(p))
    work = pathlib.Path(tempfile.mkdtemp(prefix="overlay-destinations-"))
    result = {"heads": {"control_plane": J._head(cp_src), "execution_runtime": J._head(rt_src)}}
    for identity in (False, True):
        tag = "on" if identity else "off"
        result[f"lost_ack_then_land[identity={tag}]"] = lost_ack_then_land(work / f"lost-{tag}", identity, out)
        result[f"renewal_race[identity={tag}]"] = renewal_race(work / f"race-{tag}", identity, out)
        result[f"renewal_during_lost_ack[identity={tag}]"] = renewal_during_lost_ack(work / f"rdla-{tag}", identity, out)
        result[f"renewal_after_landing[identity={tag}]"] = renewal_after_landing(work / f"ral-{tag}", identity, out)
    result["atomic_route_surface"] = atomic_route_surface()
    shutil.rmtree(work, ignore_errors=True)
    (out / "results.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: _destination_runner.py OUTDIR")
    main(pathlib.Path(sys.argv[1]))
