"""C2 synthetic producer: Control Plane strict-tenant + runtime-authority profile, decide() ONLY (DRAFT).

Development-only, non-authorizing. Every input is synthetic: the evidence is signed with a TEST-ONLY Ed25519 key that
ships in the pinned Control Plane test tree. This module never calls execute(), reconcile() or destination.apply().
Precondition (the adapter's job): the CP tree was measured against its pin and <cp_root>/src and <cp_root> are on sys.path.
"""
import hashlib
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import NamedTuple

CONFIG_ID = "C2-CP-RUNTIME-PROFILE-STRICT-TENANT-DECIDE-ONLY"
NOW = datetime(2026, 10, 5, 19, 0, tzinfo=timezone.utc)
PROPOSAL_COMMITMENT = "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53"
# Unshipped CP test helpers: (module, file relative to the CP root, symbol, why). Blob-checked before use.
PRIVATE = (
    ("tests.test_bounded_authorization", "tests/test_bounded_authorization.py", "manifest, workflow, tenant_resolver_for, NOW, PROFILE, TENANT", "synthetic manifest/resolver builders"),
    ("tests.test_runtime_authority", "tests/test_runtime_authority.py", "sign_evidence, bind_approval, PUBLIC, MEMBERS", "test-only Ed25519 signing of synthetic evidence"),
    ("tests.test_runtime_authority", "tests/test_runtime_authority.py", "sign_evidence -> bounded._canonical_bytes", "unstable private canonicaliser reached inside sign_evidence"),
)


class Produced(NamedTuple):
    decision: dict
    record_path: pathlib.Path
    destination_path: pathlib.Path
    provenance: dict


class ProducerError(Exception):
    pass


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def _blob(cp_root, path):
    """Return the file's record after checking it byte-equals its blob at the CP HEAD (git hash-object vs HEAD:path)."""
    path = pathlib.Path(path).resolve()
    try:
        rel = path.relative_to(pathlib.Path(cp_root).resolve()).as_posix()
    except ValueError:
        raise ProducerError(f"{path} is outside the CP root")
    blob = _git(cp_root, "rev-parse", f"HEAD:{rel}")
    if _git(cp_root, "hash-object", "--", str(path)) != blob:
        raise ProducerError(f"{rel} differs from its pinned blob")
    return {"file": rel, "git_blob_sha": blob, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def produce(cp_root: pathlib.Path, workdir: pathlib.Path, proposal_obj: dict) -> Produced:
    import agent_control_plane.bounded as B
    from agent_control_plane.bounded import (BoundedAuthorizationWorkflow, BoundedRecordStore, LocalRefundDestination,
                                             ObservationPolicy, TenantRuntimeProposal, commitment)
    from agent_control_plane.runtime_authority import ActionClass, RuntimeAuthorityProfile
    cp_root = pathlib.Path(cp_root)
    for rel in ("tests/__init__.py", *{p[1] for p in PRIVATE}):  # verify BEFORE the unshipped helpers are imported
        _blob(cp_root, cp_root / rel)
    from tests import test_bounded_authorization as T
    from tests import test_runtime_authority as R

    if T.NOW != NOW:
        raise ProducerError("pinned CP test NOW differs")
    modules = {n: _blob(cp_root, m.__file__) for n, m in sorted(sys.modules.items()) if n == "tests" or n.startswith("tests.")}
    workdir = pathlib.Path(workdir)
    p = TenantRuntimeProposal.model_validate(proposal_obj)
    if commitment(p.model_dump(mode="json")) != PROPOSAL_COMMITMENT:
        raise ProducerError("proposal commitment differs from the frozen value")
    r = T.tenant_resolver_for(p)
    action = ActionClass(class_id="synthetic-irreversible", irreversible=True, max_status_age_seconds=60, on_unreadable="refuse")
    cfg = RuntimeAuthorityProfile(catalogue_version="synthetic-catalogue/1", actions={p.action_id: action},
                                  producer_keys={"synthetic-validator": R.PUBLIC}, allow_synthetic_resolver=True)

    def flow(root, **extra):
        return BoundedAuthorizationWorkflow(
            manifest=T.manifest(), resolver=r, destination=LocalRefundDestination(root / "destination.json"),
            records=BoundedRecordStore(root / "run.json", "run-1"), observation_policy=ObservationPolicy(max_age_seconds=300),
            allow_test_time=True, tenant_binding_generation=B.TENANT_GENERATION_STRICT, **extra)

    # Baseline decide() in a scratch dir only learns required_inputs; its decision and records are discarded.
    scratch = workdir / "baseline"
    scratch.mkdir(parents=True)
    base = flow(scratch).decide(p, now=NOW)
    required = sorted(({"input_type": x.input_type, "input_id": x.input_id} for x in base.resolution_inputs),
                      key=lambda x: (x["input_type"], x["input_id"]))
    context = r.contexts[T.PROFILE]
    criteria = {}
    for ob in context["requirement"]["evidence"]:
        if ob["required"] and ob["kind"] == "authorization":
            criteria[ob["obligation_id"]] = {"kind": "exact_members", "producer_id": "synthetic-validator",
                                             "subject_digest": commitment(R.MEMBERS), "minimum_count": 40, "members": R.MEMBERS}
            R.sign_evidence(r.evidence[ob["obligation_id"]], tenant_id=T.TENANT)
    context["runtime_authority"] = {"profile": "runtime-authority/0.1", "required_inputs": required,
                                    "required_inputs_digest": commitment(required), "evidence_criteria": criteria}
    R.bind_approval(r, cfg)
    run = workdir / "run"
    run.mkdir()
    f = flow(run, runtime_authority_profile=cfg)
    decision = f.decide(p, now=NOW)  # the only call that produces the decision
    provenance = {
        "config_id": CONFIG_ID, "clock_mode": "decide_now_argument_only", "clock_patch": "none",
        "calls": ["decide"], "decide_calls_on_final_workflow": 1,
        "private_api_dependencies": [{"module": m, "file": rel, "git_blob_sha": modules[m]["git_blob_sha"],
                                      "file_sha256": modules[m]["sha256"], "symbol": s, "why": w} for m, rel, s, w in PRIVATE],
        "tests_modules_checked": modules,
    }
    return Produced(decision.model_dump(mode="json"), run / "run.json", run / "destination.json", provenance)
