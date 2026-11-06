"""Refund developer-only producer: strict-tenant CP decisions and LOCAL synthetic execute/reconcile.

Development-only, non-authorizing. Every input is synthetic: the evidence is signed with a TEST-ONLY Ed25519 key that
ships in the pinned Control Plane test tree. Only the authorized fixture invokes execute()/reconcile() against its own LocalRefundDestination scratch JSON. No payment or remote destination is permitted.
Copied and generalised from c2_producer.py (which stays unedited). Differences: the workflow's manifest is the caller-supplied, already
AM-validated manifest object (asserted equal to the CP-repo copy), and `scenario` selects `authorized` (exactly the C2 behaviour) or
`grant_revoked` (the SAME flow with ONLY the synthetic grant status object's `status` set to "revoked" before the final decide()).
Precondition (the adapter's job): the CP tree was measured against its pin and <cp_root>/src and <cp_root> are on sys.path.
"""
import contextlib
import copy
import hashlib
import os
import pathlib
import subprocess
import sys
import tempfile
from unittest import mock
from datetime import datetime, timezone
from typing import NamedTuple

CONFIG_ID = "REFUND-LOCAL-STRICT-TENANT-SYNTHETIC-ONLY"
SCENARIOS = ("authorized", "grant_revoked")
SCENARIO_MUTATION = {"authorized": None, "grant_revoked": "grant_status=revoked"}
NOW = datetime(2026, 10, 5, 19, 0, tzinfo=timezone.utc)
PROPOSAL_COMMITMENT = "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53"
# Unshipped CP test helpers: (module, file relative to the CP root, symbol, why). Blob-checked before use.
PRIVATE = (
    ("tests.test_bounded_authorization", "tests/test_bounded_authorization.py", "manifest, workflow, tenant_resolver_for, NOW, PROFILE, TENANT", "synthetic manifest/resolver builders"),
    ("tests.test_runtime_authority", "tests/test_runtime_authority.py", "sign_evidence, bind_approval, PUBLIC, MEMBERS", "test-only Ed25519 signing of synthetic evidence"),
    ("tests.test_runtime_authority", "tests/test_runtime_authority.py", "sign_evidence -> bounded._canonical_bytes", "unstable private canonicaliser reached inside sign_evidence"),
    ("tests.test_runtime_authority", "tests/test_runtime_authority.py", "bind_approval's synthetic grant statuses (r.statuses)", "grant_revoked sets status='revoked' on the first synthetic grant status object"),
)


class Produced(NamedTuple):
    decision: dict
    record_path: pathlib.Path
    destination_path: pathlib.Path
    provenance: dict
    local_effect: dict


class ProducerError(Exception):
    pass


def _git(root, *args):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1"}
    try:
        done = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *args], cwd=tempfile.gettempdir(), env=env,
                              capture_output=True, text=True, timeout=60, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProducerError("git failed: %s" % type(exc).__name__) from None
    return done.stdout.strip()


def _blob(cp_root, path):
    """Return the file's record after checking it byte-equals its blob at the CP HEAD (git hash-object vs HEAD:path)."""
    path = pathlib.Path(path).resolve()
    try:
        rel = path.relative_to(pathlib.Path(cp_root).resolve()).as_posix()
    except ValueError:
        raise ProducerError(f"{path} is outside the CP root")
    blob = _git(cp_root, "rev-parse", f"HEAD:{rel}")
    data = path.read_bytes()  # git blob id computed here: no clean filters, no git on the file
    if hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != blob:
        raise ProducerError(f"{rel} differs from its pinned blob")
    return {"file": rel, "git_blob_sha": blob, "sha256": hashlib.sha256(data).hexdigest()}


def produce(cp_root: pathlib.Path, workdir: pathlib.Path, proposal_obj: dict, manifest_obj: dict, scenario: str) -> Produced:
    if scenario not in SCENARIOS:  # refused before any Control Plane import or call
        raise ProducerError("unknown scenario %r" % (scenario,))
    if not isinstance(manifest_obj, dict):
        raise ProducerError("manifest_obj must be the parsed AM-validated manifest object")
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
    if manifest_obj != T.manifest():  # the supplied AM-validated bytes must equal the CP-repo copy
        raise ProducerError("supplied manifest differs from the pinned Control Plane test manifest")
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
            manifest=copy.deepcopy(manifest_obj), resolver=r, destination=LocalRefundDestination(root / "destination.json"),
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
    if scenario == "grant_revoked":  # the ONLY difference from the authorized flow: the synthetic grant status object
        statuses = list(r.statuses.values())
        if len(statuses) != 1 or not hasattr(statuses[0], "status"):
            raise ProducerError("expected exactly one synthetic grant status object")
        statuses[0].status = "revoked"
    run = workdir / "run"
    run.mkdir()
    f = flow(run, runtime_authority_profile=cfg)
    # Observed (not declared) native call trace: class-level wrappers record every call to decide/execute/reconcile
    # made on the final workflow instance, including any call a held scenario might wrongly make.
    trace = []

    def traced(name):
        orig = getattr(BoundedAuthorizationWorkflow, name)

        def wrapper(self, *a, **k):
            if self is f:
                trace.append(name)
            return orig(self, *a, **k)
        return wrapper

    local_effect = {"attempt": None, "observation": None, "reconciliation": None}
    with contextlib.ExitStack() as stack:
        for name in ("decide", "execute", "reconcile"):
            stack.enter_context(mock.patch.object(BoundedAuthorizationWorkflow, name, traced(name)))
        decision = f.decide(p, now=NOW)  # the only call that produces the decision
        if scenario == "authorized":
            # Test-only fixed virtual clock: LocalRefundDestination.observe() and the record stamps read
            # agent_control_plane.bounded._now, while the frozen October 2026 fixtures are judged at now=NOW.
            # Only that CP module clock is patched, only around local synthetic execute/reconcile; it is not a
            # claim about real-world freshness.
            with mock.patch.object(B, "_now", return_value=NOW):
                attempt, observation = f.execute(p, decision, adapter_id=p.adapter_id, now=NOW)
                reconciliation = f.reconcile(decision.effect_id, now=NOW)
            local_effect = {
                "attempt": attempt.model_dump(mode="json"),
                "observation": None if observation is None else observation.model_dump(mode="json"),
                "reconciliation": reconciliation.model_dump(mode="json"),
            }
        elif f.records.load().attempts:
            raise ProducerError("held synthetic refund produced an unauthorized attempt")
    expected_trace = ["decide", "execute", "reconcile"] if scenario == "authorized" else ["decide"]
    if trace != expected_trace:
        raise ProducerError("observed native call trace %r differs from %r" % (trace, expected_trace))
    provenance = {
        "config_id": CONFIG_ID, "scenario": scenario, "scenario_mutation": SCENARIO_MUTATION[scenario],
        "manifest_source": "supplied_validated_AM_bytes", "manifest_equals_cp_repo_copy": True, "clock_mode": ("decide_now_argument_plus_bounded_now_patch_around_execute_reconcile" if scenario == "authorized" else "decide_now_argument_only"),
        "clock_patch": ("bounded._now=NOW around execute/reconcile only" if scenario == "authorized" else "none"),
        "calls": list(trace), "decide_calls_on_final_workflow": 1,
        "virtual_clock_patch": "agent_control_plane.bounded._now set to frozen NOW only around local synthetic execute/reconcile",
        "catalogue_version": cfg.catalogue_version, "action_class_id": action.class_id, "producer_key_id": "synthetic-validator",
        "producer_public_key_hex": R.PUBLIC, "authority_profile": context["runtime_authority"]["profile"],
        "allow_synthetic_resolver": True, "tenant_binding_generation": B.TENANT_GENERATION_STRICT,
        "derived_authority_context_commitment": commitment(context), "required_inputs_digest": commitment(required),
        "c2_relation": "copied and generalised from c2_producer.py; the authorized scenario reproduces the C2 flow",
        "c1_configuration_contrast": "C1 ran the strict-tenant workflow with NO RuntimeAuthorityProfile (no runtime_authority context, "
                                     "no check_events journal); C2 adds the profile and signed synthetic evidence, decide() only",
        "other_symbols_used": ["agent_replay_bundle.ingress.check_depth", "agent_control_plane.strict_json.strict_loads",
                               "agent_replay_bundle.importers.CONTROL_PLANE_STRICT_TENANT_REVISION"],
        "private_api_dependencies": [{"module": m, "file": rel, "git_blob_sha": modules[m]["git_blob_sha"],
                                      "file_sha256": modules[m]["sha256"], "symbol": s, "why": w} for m, rel, s, w in PRIVATE],
        "tests_modules_checked": modules,
    }
    return Produced(decision.model_dump(mode="json"), run / "run.json", run / "destination.json", provenance, local_effect)
