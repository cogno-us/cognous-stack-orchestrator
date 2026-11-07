"""G3-REFUND capture (DEVELOPMENT ONLY, SYNTHETIC / NONPRODUCTION, UNQUALIFIED, NOT A TEST).

Modelled on the frozen s2_runtime/s2_capture.py, with ONE substitution: the Control Plane test resolver is replaced by the merged G2
Institutional Governance root-lineage adapter (IGRootResolver, authenticated=False). Control Plane `decide()` is the only authority.
Only when the CP decision is `authorized` does the pinned Runtime execute ONCE into a unique, isolated, local SQLite file
(a REAL local INSERT; producer-reported, not independently observed). A `hold` stops here: the Runtime is NOT RUN.

Usage (cwd = pinned CP checkout; PYTHONPATH = <cp>/src:<cp>:<runtime>; env G3_STACK_ROOT):
    python g3_capture.py <out-dir> <scenario>      scenario: valid | revoked
The Runtime repository_revision recorded in the export is CALLER-ASSERTED by this script.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ["G3_STACK_ROOT"])
sys.path.insert(0, str(ROOT / "institutional_governance" / "process" / "implementation" / "g2-cp-resolver-dev"))
import g2_driver as D  # noqa: E402  (merged G2 driver: fixtures, proposal builder, pins)
from ig_root_resolver import IGRootResolver, load_lineage_harness, load_pinned_control_plane  # noqa: E402

B, RA = load_pinned_control_plane(ROOT / "control_plane")  # verifies the CP pin and clean tree before use
from engine.effective_grant import DERIVATION, EffectiveGrantDestination  # noqa: E402
from engine.safe_executor import EXECUTION_ENVELOPE_VERSION, ExecutionEnvelope, ExecutionOperation, LocalExecutionPolicy  # noqa: E402
from engine.control_plane_adapter import PinnedControlPlaneExecutor  # noqa: E402
from engine.producer_contract import export_execution_artifacts  # noqa: E402

RUNTIME_REVISION = "f7a55e2a8494801e49193f9f46935f0a971c248d"
OUT = Path(sys.argv[1])
SCENARIO = sys.argv[2]
assert SCENARIO in ("valid", "revoked"), SCENARIO
BUNDLE = {"valid": "root_lineage.json", "revoked": "root_lineage_revoked.json"}[SCENARIO]
AT = D.AT
B._now = lambda: AT


def effects_rows(db: Path):
    if not db.exists():
        return []
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT effect_id, state, target, amount, unit FROM effects")]


def capture():
    work = Path(tempfile.mkdtemp(prefix=f"g3-{SCENARIO}-"))
    manifest = json.loads((ROOT / "control_plane" / "tests" / "fixtures" / "refund_integration_v1_1.manifest.json").read_text(encoding="utf-8"))
    facts = D.load_json("synthetic_facts.json")
    bundle = D.load_json(BUNDLE)
    p = D.build_proposal(B, manifest, facts["tenant_id"], facts["context_ref"])
    facts["approval"]["proposal_commitment"] = B.commitment(p.model_dump(mode="json", exclude_none=False))
    r = IGRootResolver(B, bundle, D.AUTHORITY_ID, facts, AT, lineage=load_lineage_harness())
    cl = RA.ActionClass(class_id="synthetic-irreversible", irreversible=True, max_status_age_seconds=60, on_unreadable="refuse")
    cfg = RA.RuntimeAuthorityProfile(catalogue_version="synthetic-catalogue/1", actions={p.action_id: cl}, producer_keys={}, allow_synthetic_resolver=True)
    generation = B.TENANT_GENERATION_STRICT
    dest = EffectiveGrantDestination(work / "sqlite")
    db = work / "sqlite" / "refunds.sqlite3"

    def flow(tag, profile, destination):
        kw = {"runtime_authority_profile": profile} if profile else {}
        return B.BoundedAuthorizationWorkflow(
            manifest=manifest, resolver=r, destination=destination, records=B.BoundedRecordStore(work / f"{tag}-run.json", "run-1"),
            observation_policy=B.ObservationPolicy(max_age_seconds=300), allow_test_time=True, tenant_binding_generation=generation, **kw)

    base = flow("baseline", None, B.LocalRefundDestination(work / "baseline-destination.json")).decide(p, now=AT)
    required = sorted([{"input_type": x.input_type, "input_id": x.input_id} for x in base.resolution_inputs], key=lambda x: (x["input_type"], x["input_id"]))
    revision = r.grant_status(D.AUTHORITY_ID).revision
    digest = dest.set_effective_grant(principal=p.principal, grant_id=D.AUTHORITY_ID, revision=revision, permissions=p.requested_permissions)
    r.facts["runtime_authority"] = {"profile": "runtime-authority/0.1", "required_inputs": required, "required_inputs_digest": B.commitment(required),
                                    "evidence_criteria": {}, "expected_effective_grant_digest": digest, "effective_grant_derivation_version": DERIVATION}
    r.facts["approval"]["runtime_authority_commitment"] = RA.approval_commitment(cfg, r.authority_context(facts["context_ref"]))
    f = flow("g3", cfg, dest)
    d = f.decide(p, now=AT)
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"scenario": SCENARIO, "label": D.LABEL, "decision_result": d.result, "reasons": list(d.reasons), "resolver_authenticated": r.authenticated,
               "authority_id": D.AUTHORITY_ID, "grant_revision": revision, "tenant_id": p.tenant_id, "runtime_run": False,
               "field_provenance": r.field_provenance(), "baseline_reasons": list(base.reasons)}
    (OUT / "proposal.json").write_text(json.dumps(p.model_dump(mode="json"), indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if d.result != "authorized":
        summary["effect_rows"] = effects_rows(db)
        (OUT / "control_plane_run.json").write_text(json.dumps(f.records.load().model_dump(mode="json"), indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
        (OUT / "capture_summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
        print("RESULT", SCENARIO, "HOLD", d.reasons)
        return
    fields = {k: getattr(p, k) for k in ["actor", "principal", "manifest_id", "manifest_version", "manifest_digest", "action_id", "adapter_id",
                                         "target", "payload", "payload_commitment", "amount", "unit", "effects", "requirement_id"]}
    institution = bundle["origins"][0]["institution_id"]
    domain = bundle["origins"][0]["authority_domain"]
    op = ExecutionOperation(**fields, institution_id=institution, authority_domain=domain, proposal_commitment=B.commitment(p.model_dump(mode="json")),
                            requested_permissions=tuple(p.requested_permissions), authority_context_id=p.authority_context_ref, grant_id=d.binding.grant_id,
                            grant_revision=d.binding.grant_revision, effective_max_effects=d.binding.effective_max_effects, tenant_id=p.tenant_id)
    pol = LocalExecutionPolicy(allowed_institutions=frozenset({institution}), allowed_authority_domains=frozenset({domain}), allowed_adapters=frozenset({p.adapter_id}),
                               allowed_actions=frozenset({p.action_id}), allowed_target_prefixes=("urn:cognous:synthetic-account:",), allowed_units=frozenset({"USD"}),
                               max_amount=1000, max_effects=1)
    ex = PinnedControlPlaneExecutor(workflow=f, destination=dest, policy=pol, observation_clock=lambda: AT)
    env = ExecutionEnvelope(EXECUTION_ENVELOPE_VERSION, d.decision_id, d.effect_id, op)
    res = ex.execute(envelope=env, proposal=p, decision=d, now=AT, simulate=None)  # exactly one attempt; never retried
    export = export_execution_artifacts(env, res, dest, repository_revision=RUNTIME_REVISION)
    summary.update(runtime_run=True, runtime_status=res.status, runtime_error=res.error, effect_id=d.effect_id, newly_executed=getattr(res, "newly_executed", None),
                   effect_rows=effects_rows(db), sqlite_path_kind="unique temp file, removed after capture")
    for name, payload in (("control_plane_run.json", f.records.load().model_dump(mode="json")), ("runtime_export.json", export)):
        (OUT / name).write_text(json.dumps(payload, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (OUT / "capture_summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print("RESULT", SCENARIO, res.status, res.error)


try:
    capture()
finally:
    for leftover in Path(tempfile.gettempdir()).glob(f"g3-{SCENARIO}-*"):  # dispose of the isolated SQLite after the evidence is captured
        shutil.rmtree(leftover, ignore_errors=True)
