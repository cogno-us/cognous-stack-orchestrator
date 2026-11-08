"""`dispose_refund` / `reconcile_refund` (DEVELOPMENT ONLY / SYNTHETIC / NONPRODUCTION / NON-AUTHORIZING).

Composition of the pinned native interfaces demonstrated by G3 (tests/manual_contract/g3_refund/g3_capture.py), exposed as a library call:

    IG root-lineage resolver -> Control Plane decide()  [the only authority]
      -> only when `authorized`: Runtime PinnedControlPlaneExecutor.execute (one attempt, one local SQLite destination, never retried)
      -> Replay import of the Control Plane record and the Runtime export.

The adapter evaluates no policy and invents no authority. Control Plane holds stay holds; native `unknown` stays `unknown`; no
acknowledgment and no evidence is ever reported as absence of effect. Not thread-safe: native modules and the Control Plane clock are
process-global, so calls are serialized by a lock and run one at a time.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import threading
from datetime import timezone
from pathlib import Path
from typing import Any
from unittest import mock

from . import profiles, workspace
from .contract import (CONTRACT_VERSION, NOT_VERIFIED, CleanupReport, DispositionRequest, DispositionResult, EvidenceReferences, FileReference, Labels,
                       NativeFacts, ProfileIdentity, Refusal, request_problems)
from .stack import PINS, NativeStack, StackError, load_stack

_LOCK = threading.Lock()
ACCOUNT_PREFIX = profiles.ACCOUNT_PREFIX
RUNTIME_REVISION = PINS["components"]["runtime"]  # caller-asserted in the Runtime export, exactly as in G3
CP_REVISION = PINS["components"]["control_plane"]
_STACK_STEP = "operator_inspection_no_retry_established"


@dataclasses.dataclass(frozen=True)
class _TestInjection:
    """PRIVATE, test-only. Not part of the request contract, not exported, not reachable through `dispose_refund(request)`.
    `wrap_destination` maps the pinned destination class to a test subclass; `simulate` is passed to the native Runtime `simulate` argument."""

    wrap_destination: Any
    simulate: str


class _Probe:
    """Counts calls at the adapter's single Runtime call site. Independent counters belong to the tests, not to this."""

    def __init__(self) -> None:
        self.executions = 0
        self.native: NativeFacts | None = None  # kept so a handler after dispatch still reports what the native path established
        self.source: tuple = ()
        self.profile: ProfileIdentity | None = None  # set once the approved-profile pre-flight passed
        self.labels: Labels | None = None


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n").encode("utf-8")


def _persist(state_dir: Path, subdir: str, kind: str, obj: Any, detail: dict | None = None) -> FileReference:
    """Write content-addressed JSON under the caller-owned state directory (never overwrites a differing file)."""
    data = _json_bytes(obj)
    digest = _sha(data)
    target_dir = state_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{kind}-{digest[7:23]}.json"
    if path.exists() and path.read_bytes() != data:
        raise FileExistsError(f"content-addressed evidence file differs from expected bytes: {path}")
    if not path.exists():
        tmp = path.with_name(path.name + f".tmp{os.getpid()}")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    return FileReference(kind=kind, path=str(path), sha256=digest, detail=detail or {})


def _cp_snapshot(state_dir: Path, corr: str, records: Any) -> FileReference:
    """Content-addressed point-in-time copy of the Control Plane run record, so the reference stays resolvable and its hash stays valid
    while the append-only per-correlation record keeps growing."""
    return _persist(state_dir, f"evidence/{corr}", "cp_run_record", records.load().model_dump(mode="json"), {"run_id": corr, "snapshot": True})


def _file_ref(kind: str, path: Path, detail: dict | None = None) -> FileReference:
    return FileReference(kind=kind, path=str(path), sha256=_sha(path.read_bytes()), detail=detail or {})


def map_runtime(status: str | None, observed_state: str | None, acknowledged: bool | None, newly_executed: bool | None) -> str:
    """Native Runtime status -> disposition. Anything not positively established as an applied effect stays `unknown` (fail closed)."""
    if status == "executed":
        return "executed" if (observed_state == "applied" and acknowledged and newly_executed) else "unknown"
    if status in ("reconciled", "observed"):
        return "executed" if observed_state == "applied" else "unknown"
    if status == "failed":
        return "failed"
    if status == "denied":
        return "denied"
    return "unknown"  # unknown, partial and any unmapped native status


_NEXT = {"executed": "none", "held": "resolve_authority_hold", "denied": "correct_request_or_runtime_policy", "refused": "correct_request",
         "unknown": "reconcile_read_only", "failed": _STACK_STEP}


def _result(request: Any, disposition: str, *, native: NativeFacts | None = None, probe: _Probe | None = None, evidence: EvidenceReferences | None = None,
            refusal: Refusal | None = None, error: str | None = None, mode: str = "dispose", next_step: str | None = None) -> DispositionResult:
    n = probe.executions if probe else 0
    corr = getattr(request, "correlation_id", None)
    prop = getattr(request, "proposal", None)
    return DispositionResult(
        contract_version=CONTRACT_VERSION, disposition=disposition, correlation_id=corr if isinstance(corr, str) else None,
        tenant_id=getattr(prop, "tenant_id", None) if isinstance(getattr(prop, "tenant_id", None), str) else None,
        native=native or NativeFacts(), runtime_invoked=n > 0, runtime_invocations=n, evidence=evidence or EvidenceReferences(), refusal=refusal,
        error=error, next_step=next_step or _NEXT[disposition], effect_absence_established=False,
        cleanup=CleanupReport(ok=True, scratch_path=None), mode=mode, profile=probe.profile if probe else None,
        labels=probe.labels if (probe and probe.labels is not None) else Labels())


def _refused(request: Any, code: str, reason: str, source: str = "adapter", *, mode: str = "dispose", next_step: str | None = None,
             probe: _Probe | None = None) -> DispositionResult:
    return _result(request, "refused", refusal=Refusal(code, reason, source), mode=mode, next_step=next_step, probe=probe)


def _build_proposal(S: NativeStack, request: DispositionRequest, manifest: dict, profile: profiles.ApprovedProfile, derived: profiles.Derived):
    B = S.B
    pr, facts = request.proposal, request.authority.facts
    payload = {"customer_id": pr.customer_id, "refund_reason": pr.refund_reason}
    if "case_reference" in derived.payload_required + derived.payload_optional and pr.case_reference is not None:
        payload["case_reference"] = pr.case_reference
    base = B.RuntimeProposal(
        manifest_id=manifest["manifest_id"], manifest_version=manifest["manifest_version"], manifest_digest=B.commitment(manifest),
        actor=pr.actor, principal=pr.principal, action_id=profile.action_id, adapter_id=derived.adapter_id, target=ACCOUNT_PREFIX + pr.customer_id,
        payload=payload, payload_commitment=B.commitment(payload), requested_permissions=list(derived.permissions), amount=float(pr.amount), unit=pr.unit,
        effects=1, authority_context_ref=facts["context_ref"], requirement_id=derived.requirement_id, correlation_id=request.correlation_id,
        run_id=request.correlation_id, evidence_refs=[])
    return manifest, B.TenantRuntimeProposal(**base.model_dump(mode="json", exclude_none=False), tenant_id=pr.tenant_id)


def _operation(S: NativeStack, p, binding, derived: profiles.Derived):
    """Runtime operation + policy, both derived from the native manifest action; the policy can only narrow what the manifest allows."""
    se = S.engine_safe_executor
    fields = {k: getattr(p, k) for k in ["actor", "principal", "manifest_id", "manifest_version", "manifest_digest", "action_id", "adapter_id", "target",
                                          "payload", "payload_commitment", "amount", "unit", "effects", "requirement_id"]}
    op = se.ExecutionOperation(**fields, institution_id=derived.institution_id, authority_domain=derived.authority_domain,
                               proposal_commitment=S.B.commitment(p.model_dump(mode="json")), requested_permissions=tuple(p.requested_permissions),
                               authority_context_id=p.authority_context_ref, grant_id=binding.grant_id, grant_revision=binding.grant_revision,
                               effective_max_effects=binding.effective_max_effects, tenant_id=p.tenant_id)
    pol = se.LocalExecutionPolicy(allowed_institutions=frozenset({derived.institution_id}), allowed_authority_domains=frozenset({derived.authority_domain}),
                                  allowed_adapters=frozenset({derived.adapter_id}), allowed_actions=frozenset({p.action_id}),
                                  allowed_target_prefixes=(derived.allowed_target,), allowed_units=frozenset({derived.unit}),
                                  max_amount=derived.max_amount, max_effects=derived.max_effects, target_match="exact")
    return op, pol


def dispose_refund(request: DispositionRequest) -> DispositionResult:
    """Dispose one synthetic refund proposal through the native IG/CP/Runtime/Replay path. Returns a structured result; it does not raise
    for refusals, holds, denials, failures or uncertain outcomes. `retry_permission` is always `not_established`."""
    return _dispose_refund(request, None)


def _dispose_refund(request: DispositionRequest, injection: _TestInjection | None) -> DispositionResult:
    if injection is not None and injection.simulate != "lost_ack":  # the only native simulate value the frozen C oracle uses
        return _refused(request, "test_injection_unsupported", "only simulate='lost_ack' is supported by the private test hook")
    if isinstance(request, DispositionRequest) and not profiles.is_supported(request.profile):
        return _refused(request, "profile_unsupported", "profile is not in the closed approved registry")
    problems = request_problems(request)
    if problems:
        return _refused(request, "request_invalid", ";".join(problems))
    scratch: Path | None = None
    result: DispositionResult | None = None
    probe = _Probe()
    with _LOCK:
        try:
            scratch = workspace.allocate()
            result = _dispose(request, scratch, probe, injection)
        except Exception as exc:  # noqa: BLE001 - unexpected adapter error
            if probe.executions > 0:  # the Runtime was entered: the effect may exist, so never `failed` and never "not invoked"
                result = _result(request, "unknown", native=probe.native, probe=probe, evidence=EvidenceReferences(source=probe.source),
                                 error=f"adapter_error_after_dispatch_outcome_unknown: {exc!r}")
            else:
                result = _result(request, "failed", probe=probe, error=f"adapter_error_no_dispatch_occurred: {exc!r}", next_step=_STACK_STEP)
        finally:
            cleanup = workspace.dispose(scratch)
    return dataclasses.replace(result, cleanup=cleanup)


def _dispose(request: DispositionRequest, scratch: Path, probe: _Probe, injection: _TestInjection | None) -> DispositionResult:
    try:
        S = load_stack(request.environment.stack_root)
    except StackError as exc:
        return _refused(request, "stack_" + exc.code, exc.detail, next_step=_STACK_STEP)
    B, RA = S.B, S.RA
    pid = profiles.effective_profile_id(request.profile)
    profile = profiles.REGISTRY[pid]
    try:  # approved-profile pre-flight: exact source identity + native validation + derivation; no Control Plane decision, Runtime call or write yet
        manifest, derived = profiles.load_and_check(S, profile)
    except profiles.ProfileRefusal as exc:
        return _refused(request, exc.code, exc.reason)
    shape = profiles.payload_problems(profile, derived, request.proposal.case_reference)
    if shape:
        return _refused(request, "request_invalid", ";".join(shape))
    probe.profile = profiles.identity(profile, derived)
    probe.labels = Labels(not_verified=NOT_VERIFIED + profiles.DISCLOSURES.get(pid, ()))
    AT = request.evaluation_time.astimezone(timezone.utc)
    state = request.environment.state_dir
    state.mkdir(parents=True, exist_ok=True)
    with mock.patch.object(B, "_now", lambda: AT):  # CP's own tests pin the synthetic clock the same way
        manifest, p = _build_proposal(S, request, manifest, profile, derived)
        auth = request.authority
        facts, bundle = copy.deepcopy(auth.facts), copy.deepcopy(auth.lineage_bundle)
        facts["approval"]["proposal_commitment"] = B.commitment(p.model_dump(mode="json", exclude_none=False))
        resolver = S.resolver_module.IGRootResolver(B, bundle, auth.authority_id, facts, AT, lineage=S.resolver_module.load_lineage_harness())
        cl = RA.ActionClass(class_id="synthetic-irreversible", irreversible=True, max_status_age_seconds=60, on_unreadable="refuse")
        cfg = RA.RuntimeAuthorityProfile(catalogue_version="synthetic-catalogue/1", actions={p.action_id: cl}, producer_keys={}, allow_synthetic_resolver=True)
        # `decide()` only reads the destination's declared capability, so a hold never creates or touches the SQLite file.
        capability_only = type("CapabilityOnlyDestination", (), {"runtime_authority_capability": S.engine_effective_grant.CAPABILITY})()
        records = B.BoundedRecordStore(state / "cp" / f"{request.correlation_id}.json", request.correlation_id)

        def flow(store, destination, profile):
            kw = {"runtime_authority_profile": profile} if profile else {}
            return B.BoundedAuthorizationWorkflow(manifest=manifest, resolver=resolver, destination=destination, records=store,
                                                  observation_policy=B.ObservationPolicy(max_age_seconds=300), allow_test_time=True,
                                                  tenant_binding_generation=B.TENANT_GENERATION_STRICT, **kw)

        # CP-native two-pass preparation (same as G2/G3): enumerate the inputs the gate reads, then bind them.
        base = flow(B.BoundedRecordStore(scratch / "baseline-run.json", "baseline"), B.LocalRefundDestination(scratch / "baseline-destination.json"), None).decide(p, now=AT)
        required = sorted([{"input_type": x.input_type, "input_id": x.input_id} for x in base.resolution_inputs], key=lambda x: (x["input_type"], x["input_id"]))
        revision = resolver.grant_status(auth.authority_id).revision
        expected = S.engine_effective_grant.effective_grant_digest(principal=p.principal, grant_id=auth.authority_id, revision=revision,
                                                                   permissions=list(p.requested_permissions), status="active")
        resolver.facts["runtime_authority"] = {"profile": "runtime-authority/0.1", "required_inputs": required, "required_inputs_digest": B.commitment(required),
                                               "evidence_criteria": {}, "expected_effective_grant_digest": expected,
                                               "effective_grant_derivation_version": S.engine_effective_grant.DERIVATION}
        resolver.facts["approval"]["runtime_authority_commitment"] = RA.approval_commitment(cfg, resolver.authority_context(facts["context_ref"]))
        wf = flow(records, capability_only, cfg)
        d = wf.decide(p, now=AT)
        source = (_cp_snapshot(state, request.correlation_id, records),)
        native = NativeFacts(cp_result=d.result, cp_reasons=tuple(d.reasons), decision_id=d.decision_id, effect_id=d.effect_id)
        if d.result != "authorized":
            # Runtime is NOT RUN, no grant mirror is written, no Replay is produced.
            return _result(request, "held", native=native, probe=probe, evidence=EvidenceReferences(source=source, replay_state="not_run",
                           replay_note="Control Plane did not authorize; Runtime and Replay were not run"),
                           refusal=Refusal("control_plane_hold", ",".join(d.reasons) or "hold", "control_plane"))
        latest: dict[str, str] = {}
        for a in records.load().attempts:  # attempts are append-only status events; the last event per attempt id is its current status
            if a.effect_id == d.effect_id:
                latest[a.attempt_id] = a.status
        prior = [i for i, st in latest.items() if st in ("attempted", "unknown", "partial")]
        if prior:  # native rule: absence never grants a retry. An earlier uncertain dispatch of this exact effect must be reconciled, not re-run.
            return _result(request, "refused", native=native, probe=probe, evidence=EvidenceReferences(source=source, replay_note="Runtime not run"),
                           refusal=Refusal("prior_uncertain_dispatch", "an earlier attempt for this effect is unknown/partial/unresolved; reconcile first", "adapter"),
                           next_step="reconcile_read_only")
        dest_cls = S.engine_effective_grant.EffectiveGrantDestination
        if injection is not None:
            dest_cls = injection.wrap_destination(dest_cls)
        dest = dest_cls(state / "sqlite")
        # Authorized: the trusted host mirrors the authorized grant into the destination (as G3 did), then the Runtime executes ONCE.
        mirrored = dest.set_effective_grant(principal=p.principal, grant_id=d.binding.grant_id, revision=d.binding.grant_revision,
                                            permissions=list(p.requested_permissions))
        if mirrored != expected:
            return _result(request, "failed", native=native, probe=probe, evidence=EvidenceReferences(source=source),
                           error="effective_grant_digest_mismatch_before_dispatch", next_step=_STACK_STEP)
        probe.native, probe.source = native, source
        op, pol = _operation(S, p, d.binding, derived)
        se, ad, pc = S.engine_safe_executor, S.engine_adapter, S.engine_producer
        ex = ad.PinnedControlPlaneExecutor(workflow=wf, destination=dest, policy=pol, observation_clock=lambda: AT)
        env = se.ExecutionEnvelope(se.EXECUTION_ENVELOPE_VERSION, d.decision_id, d.effect_id, op)
        simulate = injection.simulate if injection is not None else None
        probe.executions += 1  # counted before the call: if the call raises, dispatch may have happened
        try:
            res = ex.execute(envelope=env, proposal=p, decision=d, now=AT, simulate=simulate)  # exactly one attempt; never retried
        except Exception as exc:  # noqa: BLE001 - the Runtime may have committed: report uncertainty, never failure
            return _result(request, "unknown", native=native, probe=probe, evidence=EvidenceReferences(source=source),
                           error=f"runtime_raised_after_dispatch_outcome_unknown: {exc!r}")
        if hasattr(dest, "heal"):
            dest.heal()  # the simulated outage ends; the recorded native result stays `unknown`
        native = dataclasses.replace(native, runtime_status=res.status, runtime_error=res.error, acknowledged=res.acknowledged,
                                     newly_executed=res.newly_executed, observed_state=res.observed_state)
        probe.native = native
        disposition = map_runtime(res.status, res.observed_state, res.acknowledged, res.newly_executed)
        try:
            source = (_cp_snapshot(state, request.correlation_id, records),)  # after execute: includes attempt/reconciliation records
            evidence = _evidence(S, request, p, wf, env, res, dest, source)
        except Exception as exc:  # noqa: BLE001 - the effect disposition stands; only the evidence reference is lost
            evidence = EvidenceReferences(source=source, replay_state="not_run", replay_note=f"evidence_persistence_failed (source reference, if any, is the pre-execute CP snapshot): {exc!r}")
        refusal = None
        if disposition in ("denied", "failed", "unknown") and res.error:
            refusal = Refusal("runtime_" + res.status, res.error, "runtime")
        return _result(request, disposition, native=native, probe=probe, evidence=evidence, refusal=refusal)


def _evidence(S: NativeStack, request: DispositionRequest, p, wf, env, res, dest, source) -> EvidenceReferences:
    """Persist the Runtime export and import Replay. A Replay problem never changes the effect disposition; it is reported as evidence state."""
    state = request.environment.state_dir
    corr = request.correlation_id
    try:
        export = S.engine_producer.export_execution_artifacts(env, res, dest, repository_revision=RUNTIME_REVISION)
        export_ref = _persist(state, f"evidence/{corr}", "runtime_export", export, {"effect_id": res.effect_id, "caller_asserted_repository_revision": RUNTIME_REVISION})
    except Exception as exc:  # noqa: BLE001
        return EvidenceReferences(source=source, replay_state="not_run", replay_note=f"runtime_export_failed: {exc!r}")
    try:
        cp_run = wf.records.load().model_dump(mode="json")
        bundle = S.replay_importers.import_bounded_workflow(copy.deepcopy(cp_run), proposal=p.model_dump(mode="json"), moltbot_export=copy.deepcopy(export),
                                                            control_plane_revision=CP_REVISION).model_dump(mode="json")
        ref = _persist(state, f"evidence/{corr}", "replay_bundle", bundle, {"bundle_id": str(bundle.get("bundle_id")), "status": str(bundle.get("status")),
                                                                              "replay_revision": PINS["components"]["replay"], "control_plane_revision": CP_REVISION})
        return EvidenceReferences(source=source + (export_ref,), replay=ref, replay_state="imported")
    except Exception as exc:  # noqa: BLE001
        return EvidenceReferences(source=source + (export_ref,), replay_state="import_failed", replay_note=f"replay_import_failed: {exc!r}")


def reconcile_refund(request: DispositionRequest) -> DispositionResult:
    """Effect-free reconciliation of a previously dispatched proposal (no dispatch, no authority, no effect or attempt row written; the native
    constructors still run idempotent schema-ensure statements on an existing database). Reads the retained Control Plane decision and observes the bound
    destination state through the Runtime's `observe_historical` (read-only; no authority is renewed, nothing is dispatched).
    `applied` -> `executed` (native status `observed`, newly_executed false). `absent`, `partial`, `unknown` or an unreadable destination
    -> `unknown`: absence right after an ambiguous dispatch never establishes that the effect will not appear."""
    if isinstance(request, DispositionRequest) and not profiles.is_supported(request.profile):
        return _refused(request, "profile_unsupported", "profile is not in the closed approved registry", mode="reconcile")
    problems = request_problems(request)
    if problems:
        return _refused(request, "request_invalid", ";".join(problems), mode="reconcile")
    scratch: Path | None = None
    probe = _Probe()  # shared with _reconcile so every post-pre-flight result (including handled errors) keeps the validated profile identity and labels
    with _LOCK:
        try:
            scratch = workspace.allocate()
            result = _reconcile(request, probe)
        except Exception as exc:  # noqa: BLE001
            result = _result(request, "unknown", probe=probe, error=f"reconcile_error_outcome_still_unknown: {exc!r}", mode="reconcile")
        finally:
            cleanup = workspace.dispose(scratch)
    return dataclasses.replace(result, cleanup=cleanup)


def _reconcile(request: DispositionRequest, probe: _Probe) -> DispositionResult:
    try:
        S = load_stack(request.environment.stack_root)
    except StackError as exc:
        return _refused(request, "stack_" + exc.code, exc.detail, mode="reconcile", next_step=_STACK_STEP)
    B = S.B
    pid = profiles.effective_profile_id(request.profile)
    profile = profiles.REGISTRY[pid]
    try:
        manifest, derived = profiles.load_and_check(S, profile)
    except profiles.ProfileRefusal as exc:
        return _refused(request, exc.code, exc.reason, mode="reconcile")
    shape = profiles.payload_problems(profile, derived, request.proposal.case_reference)
    if shape:
        return _refused(request, "request_invalid", ";".join(shape), mode="reconcile")
    probe.profile = profiles.identity(profile, derived)
    probe.labels = Labels(not_verified=NOT_VERIFIED + profiles.DISCLOSURES.get(pid, ()))
    state = request.environment.state_dir
    cp_path = state / "cp" / f"{request.correlation_id}.json"
    if not cp_path.is_file():
        return _refused(request, "no_prior_dispatch_record", "no retained Control Plane run record for this correlation id", mode="reconcile", probe=probe)
    if not (state / "sqlite" / "refunds.sqlite3").is_file():
        return _refused(request, "no_prior_destination", "no destination database exists for this state_dir; reconciliation will not create one", mode="reconcile", probe=probe)
    AT = request.evaluation_time.astimezone(timezone.utc)
    with mock.patch.object(B, "_now", lambda: AT):
        _, p = _build_proposal(S, request, manifest, profile, derived)
        store = B.BoundedRecordStore(cp_path, request.correlation_id)
        commit = B.commitment(p.model_dump(mode="json", exclude_none=False))
        matches = [x for x in store.load().decisions if x.result == "authorized" and x.binding is not None and x.binding.proposal_commitment == commit]
        if not matches:
            return _refused(request, "no_authorized_decision_for_proposal", "the retained record holds no authorized decision for this exact proposal", mode="reconcile", probe=probe)
        d = matches[-1]
        op, pol = _operation(S, p, d.binding, derived)
        se = S.engine_safe_executor
        env = se.ExecutionEnvelope(se.EXECUTION_ENVELOPE_VERSION, d.decision_id, d.effect_id, op)
        native = NativeFacts(cp_result=d.result, cp_reasons=tuple(d.reasons), decision_id=d.decision_id, effect_id=d.effect_id)
        source = (_file_ref("cp_run_record", cp_path, {"run_id": request.correlation_id}),)
        try:
            dest = S.engine_effective_grant.EffectiveGrantDestination(state / "sqlite")
            res = se.LocalDestinationExecutor(dest, pol).observe_historical(env)
        except Exception as exc:  # noqa: BLE001 - an unreadable destination establishes nothing
            return _result(request, "unknown", native=native, probe=probe, evidence=EvidenceReferences(source=source), mode="reconcile",
                           refusal=Refusal("observation_unavailable", repr(exc), "runtime"), error="destination_unreadable_outcome_still_unknown")
    native = dataclasses.replace(native, runtime_status=res.status, runtime_error=res.error, acknowledged=res.acknowledged,
                                 newly_executed=res.newly_executed, observed_state=res.observed_state)
    return _result(request, map_runtime(res.status, res.observed_state, res.acknowledged, res.newly_executed), native=native, probe=probe,
                   evidence=EvidenceReferences(source=source, replay_state="not_run", replay_note="reconciliation is a read-only observation; no new Replay import"),
                   mode="reconcile")
