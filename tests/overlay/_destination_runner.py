"""Duplicate, lost-acknowledgement and delayed-commit flows against the Runtime's opt-in destinations, with the orchestrator's inputs.

A runner, not a test (subprocess; candidate revisions only, because the destinations do not exist at the orchestrator's pins).
Inputs are the orchestrator's: the pinned Action Manifest example and the tenant-bound proposal. The route is Control Plane
BoundedAuthorizationWorkflow -> Runtime PinnedControlPlaneExecutor, plus (atomic_renewal) the orchestrator's atomic-claim route; with the
Control Plane profile sets `identity` and `full` the atomic probes use the opt-in `AtomicLocalControlPlaneExecutor(operation_identity=True)`
and `OperationIdentityAtomicAuthorityEffectDestination` (runtime fc034d14); with `off` they use the default classes unchanged.

    COGNOUS_ACTION_MANIFEST_SRC=... COGNOUS_CONTROL_PLANE_SRC=... COGNOUS_EXECUTION_RUNTIME_ROOT=... \
        python tests/overlay/_destination_runner.py OUTDIR

Scenarios (each reports what happened; assertions are in test_overlay_destinations.py):
  lost_ack_then_land[identity=off|on]   delayed-commit destination loses the acknowledgement; absent is read; retry is refused;
                                        the late commit lands; one effect.
  renewal_race[identity=off|on]         r1 is inside the destination, the grant is renewed, r2 commits, r1 lands late.
  renewal_during_lost_ack[identity=..]  r1's commit is deferred (acknowledgement lost, unknown), the grant is renewed, r2 is attempted
                                        while r1 is outstanding, then r1 lands late (F-5 probe, adapter route).
  renewal_after_landing[identity=..]    r1 lands late, then the grant is renewed and a decision for the same operation is attempted.
  atomic_route_surface                  what the atomic route carries: the executor's `operation_identity` parameter (default off) and the
                                        destination's `operation_id` parameter (runtime fc034d14, R2); `execute` still takes none (derived).
  atomic_renewal[profile=..,cap=..,case=..]
                                        F-5 probe on the ATOMIC route (AtomicLocalControlPlaneExecutor + AtomicAuthorityEffectDestination,
                                        the route the orchestrator accepts). Control Plane profile sets off | identity | full, per-grant
                                        effect cap 1 (the shipped manifest) or 2 (a grant that legitimately allows two effects), and
                                        three cases: `outstanding` (claim 1 issued and not executed when the grant is renewed, then the
                                        stale claim is executed late), `lost_ack` (claim 1 committed, acknowledgement lost, blind retry,
                                        then renewal), `landed` (claim 1 applied, then renewal). The renewal re-approves under a new
                                        approval reference and moves the authority row to revision 2 through the destination's own
                                        `set_grant_status`. `landed_same_approval` renews without a new approval reference.
"""
from __future__ import annotations

import inspect
import json
import os
import pathlib
import shutil
import sqlite3
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


def _atomic_world(work, profile_set: str, cap: int):
    """The orchestrator's atomic route over the same inputs as the adapter-route probes (profile set and cap are the variables)."""
    from engine.atomic_local_control_plane_executor import AtomicLocalControlPlaneExecutor
    from engine.local_authority_effect import AtomicAuthorityEffectDestination
    flow = J.Flow(work, profile_set, wide=(cap == 2))
    assert flow.d1.result == "authorized", flow.d1.reasons
    if profile_set in ("identity", "full"):  # opt-in (runtime fc034d14): the operation id is derived from the persisted decision
        from engine.operation_identity_atomic_destination import OperationIdentityAtomicAuthorityEffectDestination
        dest = OperationIdentityAtomicAuthorityEffectDestination(work / "atomic", clock=lambda: flow.NOW)
        executor = AtomicLocalControlPlaneExecutor(workflow=flow.f, destination=dest, policy=flow.executor.policy, operation_identity=True)
    else:  # profile off: the default atomic route, unchanged
        dest = AtomicAuthorityEffectDestination(work / "atomic", clock=lambda: flow.NOW)
        executor = AtomicLocalControlPlaneExecutor(workflow=flow.f, destination=dest, policy=flow.executor.policy)
    return flow, dest, executor


def _atomic_ledger(dest) -> list[str]:
    with sqlite3.connect(dest.path) as conn:
        return [row[0] for row in conn.execute("SELECT effect_id FROM effects ORDER BY effect_id")]


def _atomic_renew(flow, dest, identity: bool, *, new_approval: bool):
    """The authority side renews the grant: new revision published, the authority row moved by the destination's own writer, and
    (new_approval) a fresh approval reference bound to revision 2. Returns the renewed decision."""
    flow.publish_revision("2")
    if new_approval:
        ctx = flow.r.contexts[flow.tba.PROFILE]
        grant = ctx["grant"]
        old = grant["approval_refs"][0]
        new = old.rsplit("-", 1)[0] + "-2"
        approval = flow.r.approvals[old].model_copy(deep=True)
        approval.approval_ref = new
        flow.r.approvals[new] = approval
        grant["approval_refs"] = [new]
        ra = ctx["runtime_authority"]
        for item in ra["required_inputs"]:
            if item["input_id"] == old:
                item["input_id"] = new
        ra["required_inputs"] = sorted(ra["required_inputs"], key=lambda x: (x["input_type"], x["input_id"]))
        ra["required_inputs_digest"] = flow.cp.commitment(ra["required_inputs"])
        flow.tra.bind_approval(flow.r, flow.f.runtime_authority_profile or flow.cfg)
    if identity:
        flow.f.record_renewal(J.OPERATION, to_revision="2", written_by=flow.tba.ISSUER, now=flow.NOW)
    dest.set_grant_status(flow.d1.binding.grant_id, status="active", revision="2")
    return flow.f.decide(flow.p, now=flow.NOW)


def _atomic_try(fn) -> dict:
    """Run a step; a raised refusal is an outcome (recorded as data), a returned result is summarised."""
    try:
        res = fn()
    except Exception as exc:
        return {"raised": f"{type(exc).__name__}: {exc}"}
    return {"raised": None, "status": getattr(res, "status", None), "error": getattr(res, "error", None),
            "acknowledged": getattr(res, "acknowledged", None), "observed_state": getattr(res, "observed_state", None)}


def atomic_renewal(work, profile_set: str, cap: int, case: str, out: pathlib.Path) -> dict:
    flow, dest, executor = _atomic_world(work, profile_set, cap)
    identity = profile_set in ("identity", "full")
    grant_id = flow.d1.binding.grant_id
    claim1 = executor.provision_claim(proposal=flow.p, decision=flow.d1, now=flow.NOW)
    env1 = flow.envelope(flow.d1)
    out_doc: dict = {"d1_effect_id": flow.d1.effect_id}
    if case == "lost_ack":
        out_doc["r1"] = _atomic_try(lambda: executor.execute(envelope=env1, claim_id=claim1.claim_id, simulate="lost_ack"))
        out_doc["retry1"] = _atomic_try(lambda: executor.execute(envelope=env1, claim_id=claim1.claim_id))
    elif case in ("landed", "landed_same_approval"):
        out_doc["r1"] = _atomic_try(lambda: executor.execute(envelope=env1, claim_id=claim1.claim_id))
    out_doc["ledger_before_renewal"] = _atomic_ledger(dest)
    d2 = _atomic_renew(flow, dest, identity, new_approval=(case != "landed_same_approval"))
    out_doc.update({"d2_result": d2.result, "d2_reasons": list(d2.reasons), "d2_effect_id": d2.effect_id})
    prov = {"raised": None}
    claim2 = None
    if d2.result == "authorized":
        try:
            claim2 = executor.provision_claim(proposal=flow.p, decision=d2, now=flow.NOW)
        except Exception as exc:
            prov = {"raised": f"{type(exc).__name__}: {exc}"}
    out_doc["provision2"] = prov
    if claim2 is not None:
        env2 = flow.envelope(d2)
        out_doc["r2"] = _atomic_try(lambda: executor.execute(envelope=env2, claim_id=claim2.claim_id))
    if case == "outstanding":
        out_doc["r1_late"] = _atomic_try(lambda: executor.execute(envelope=env1, claim_id=claim1.claim_id))
    out_doc.update({"ledger_final": _atomic_ledger(dest), "budget": dest.budget_state(f"grant:{grant_id}"),
                    "claim1_state": dest.claim_state(claim1.claim_id),
                    "claim2_state": dest.claim_state(claim2.claim_id) if claim2 is not None else None, **_joins(flow)})
    tag = f"atomic_renewal_{profile_set}_cap{cap}_{case}"
    flow.keep(out, tag, {"decision": flow.d1.result})
    return out_doc


def atomic_route_surface() -> dict:
    from engine.atomic_local_control_plane_executor import AtomicLocalControlPlaneExecutor
    from engine.local_authority_effect import AtomicAuthorityEffectDestination
    from engine.operation_identity_atomic_destination import OperationIdentityAtomicAuthorityEffectDestination
    from engine.operation_identity_destination import OperationIdentityDestination
    from engine.safe_executor import DurableRefundDestination
    execute_params = list(inspect.signature(AtomicLocalControlPlaneExecutor.execute).parameters)
    executor_init_params = list(inspect.signature(AtomicLocalControlPlaneExecutor.__init__).parameters)
    init_default = inspect.signature(AtomicLocalControlPlaneExecutor.__init__).parameters.get("operation_identity")
    atomic_params = list(inspect.signature(AtomicAuthorityEffectDestination.execute_claim_atomic).parameters)
    return {
        "atomic_executor_execute_params": execute_params,
        "atomic_executor_init_params": executor_init_params,
        "atomic_executor_operation_identity_default": None if init_default is None else init_default.default,
        "atomic_destination_execute_claim_atomic_params": atomic_params,
        "operation_identity_atomic_destination_subclasses_atomic": issubclass(OperationIdentityAtomicAuthorityEffectDestination, AtomicAuthorityEffectDestination),
        "operation_identity_atomic_destination_capability": getattr(OperationIdentityAtomicAuthorityEffectDestination, "operation_identity_capability", None),
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
    for profile_set in ("off", "identity", "full"):
        for cap in (1, 2):
            for case in ("outstanding", "lost_ack", "landed"):
                result[f"atomic_renewal[profile={profile_set},cap={cap},case={case}]"] = atomic_renewal(
                    work / f"atomic-{profile_set}-{cap}-{case}", profile_set, cap, case, out)
        result[f"atomic_renewal[profile={profile_set},cap=2,case=landed_same_approval]"] = atomic_renewal(
            work / f"atomic-{profile_set}-2-same", profile_set, 2, "landed_same_approval", out)
    shutil.rmtree(work, ignore_errors=True)
    (out / "results.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: _destination_runner.py OUTDIR")
    main(pathlib.Path(sys.argv[1]))
