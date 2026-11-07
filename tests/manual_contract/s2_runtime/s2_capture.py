"""S2-REFUND-RT-01 capture (DEVELOPMENT ONLY, SYNTHETIC / NONPRODUCTION, UNQUALIFIED, NOT A TEST).

One strict-tenant (tenant-alpha) synthetic refund authorized by the pinned Control Plane, executed ONCE through the pinned Execution Runtime Route A
(PinnedControlPlaneExecutor.execute) into an isolated local SQLite destination, then the Runtime's own export_execution_artifacts output is persisted
UNMODIFIED. Control Plane run record and proposal are persisted beside it. Nothing here is hand-edited; no real payment, network or provider call.

Adapted from the pinned Evidence Pack developer tool tests/fixtures/cp2_generation/capture_strict_tenant_runtime.py (which omitted the operation tenant,
so the Runtime denied it) with ONE difference: ExecutionOperation carries tenant_id = proposal.tenant_id, the Runtime's native tenant field.

Usage (cwd = pristine CP checkout at 484fdbd2; PYTHONPATH=<cp>/src:<cp>:<runtime checkout at f7a55e2a>):
    python s2_capture.py <out-dir> <scenario>        scenario: valid | lost_ack
The Runtime repository_revision recorded in the export is CALLER-ASSERTED by this script (the Runtime does not authenticate it).
"""
import json
import sys
import tempfile
from pathlib import Path

import agent_control_plane.bounded as B
from agent_control_plane.bounded import BoundedAuthorizationWorkflow, BoundedRecordStore, ObservationPolicy, commitment
from agent_control_plane.runtime_authority import ActionClass, RuntimeAuthorityProfile
from tests import test_bounded_authorization as T
from tests import test_runtime_authority as R
from engine.effective_grant import DERIVATION, EffectiveGrantDestination
from engine.safe_executor import EXECUTION_ENVELOPE_VERSION, ExecutionEnvelope, ExecutionOperation, LocalExecutionPolicy
from engine.control_plane_adapter import PinnedControlPlaneExecutor
from engine.producer_contract import export_execution_artifacts

RUNTIME_REVISION = "f7a55e2a8494801e49193f9f46935f0a971c248d"
OUT = Path(sys.argv[1])
SCENARIO = sys.argv[2]
assert SCENARIO in ("valid", "lost_ack"), SCENARIO
B._now = lambda: T.NOW


def capture():
    work = Path(tempfile.mkdtemp(prefix=f"s2rt-{SCENARIO}-"))
    p = T.tenant_proposal()
    r = T.tenant_resolver_for(p)
    cl = ActionClass(class_id="synthetic-irreversible", irreversible=True, max_status_age_seconds=60, on_unreadable="refuse")
    cfg = RuntimeAuthorityProfile(catalogue_version="synthetic-catalogue/1", actions={p.action_id: cl}, producer_keys={"synthetic-validator": R.PUBLIC},
                                  allow_synthetic_resolver=True)
    generation = B.TENANT_GENERATION_STRICT
    base = T.workflow(work / "baseline", p, resolver=r, tenant_binding_generation=generation).decide(p, now=T.NOW)
    required = sorted([{"input_type": x.input_type, "input_id": x.input_id} for x in base.resolution_inputs], key=lambda x: (x["input_type"], x["input_id"]))
    context = r.contexts[T.PROFILE]
    criteria = {}
    for ob in context["requirement"]["evidence"]:
        if ob["required"] and ob["kind"] == "authorization":
            criteria[ob["obligation_id"]] = {"kind": "exact_members", "producer_id": "synthetic-validator", "subject_digest": commitment(R.MEMBERS),
                                             "minimum_count": 40, "members": R.MEMBERS}
            R.sign_evidence(r.evidence[ob["obligation_id"]], tenant_id=T.TENANT)
    context["runtime_authority"] = {"profile": "runtime-authority/0.1", "required_inputs": required, "required_inputs_digest": commitment(required),
                                    "evidence_criteria": criteria}
    grant = context["grant"]
    dest = EffectiveGrantDestination(work / "sqlite")
    digest = dest.set_effective_grant(principal=p.principal, grant_id=grant["grant_id"], revision=grant["revision"], permissions=p.requested_permissions)
    context["runtime_authority"].update(expected_effective_grant_digest=digest, effective_grant_derivation_version=DERIVATION)
    R.bind_approval(r, cfg)
    f = BoundedAuthorizationWorkflow(manifest=T.manifest(), resolver=r, destination=dest, records=BoundedRecordStore(work / "run.json", "run-1"),
                                     observation_policy=ObservationPolicy(max_age_seconds=300), allow_test_time=True, runtime_authority_profile=cfg,
                                     tenant_binding_generation=generation)
    d = f.decide(p, now=T.NOW)
    assert d.result == "authorized", d.reasons
    fields = {k: getattr(p, k) for k in ["actor", "principal", "manifest_id", "manifest_version", "manifest_digest", "action_id", "adapter_id",
                                         "target", "payload", "payload_commitment", "amount", "unit", "effects", "requirement_id"]}
    op = ExecutionOperation(**fields, institution_id=R.INSTITUTION, authority_domain="customer-refunds",
                            proposal_commitment=commitment(p.model_dump(mode="json")), requested_permissions=tuple(p.requested_permissions),
                            authority_context_id=p.authority_context_ref, grant_id=d.binding.grant_id, grant_revision=d.binding.grant_revision,
                            effective_max_effects=d.binding.effective_max_effects, tenant_id=p.tenant_id)     # the ONE difference from the Pack tool
    pol = LocalExecutionPolicy(allowed_institutions=frozenset({R.INSTITUTION}), allowed_authority_domains=frozenset({"customer-refunds"}),
                               allowed_adapters=frozenset({p.adapter_id}), allowed_actions=frozenset({p.action_id}),
                               allowed_target_prefixes=("urn:cognous:synthetic-account:",), allowed_units=frozenset({"USD"}), max_amount=1000, max_effects=1)
    ex = PinnedControlPlaneExecutor(workflow=f, destination=dest, policy=pol, observation_clock=lambda: T.NOW)
    env = ExecutionEnvelope(EXECUTION_ENVELOPE_VERSION, d.decision_id, d.effect_id, op)
    res = ex.execute(envelope=env, proposal=p, decision=d, now=T.NOW, simulate="lost_ack" if SCENARIO == "lost_ack" else None)
    export = export_execution_artifacts(env, res, dest, repository_revision=RUNTIME_REVISION)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, payload in (("control_plane_run.json", f.records.load().model_dump(mode="json")), ("proposal.json", p.model_dump(mode="json")),
                          ("runtime_export.json", export)):
        (OUT / name).write_text(json.dumps(payload, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (OUT / "capture_summary.json").write_text(json.dumps({"scenario": SCENARIO, "result_status": res.status, "error": res.error, "decision_result": d.result,
                                                          "effect_id": d.effect_id, "tenant_id": p.tenant_id}, indent=1, sort_keys=True) + "\n")
    print("RESULT", SCENARIO, res.status, res.error)


capture()
