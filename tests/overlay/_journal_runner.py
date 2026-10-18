"""Run the Control Plane journal-mode refund through the Runtime's Control Plane adapter, with the opt-in profiles on or off.

A runner, not a test (executed as a subprocess, one revision pair per interpreter). It uses the same inputs as the
orchestrator's connected handoff: the pinned Action Manifest refund example projected through the actual manifest model, and the
tenant-bound proposal (bounded-authorization-effect/0.2). The Control Plane fixtures are the component's own test helpers
(tests.test_runtime_authority.setup_flow), as in the orchestrator's handoff harness and the verifier's capture tool.

    COGNOUS_ACTION_MANIFEST_SRC=... COGNOUS_CONTROL_PLANE_SRC=... COGNOUS_EXECUTION_RUNTIME_ROOT=... \
        python tests/overlay/_journal_runner.py OUTDIR [SET ...]

Route: Control Plane BoundedAuthorizationWorkflow -> Runtime PinnedControlPlaneExecutor -> SQLite destination. This is NOT the
route the orchestrator's accepted handoff uses (that is AtomicLocalControlPlaneExecutor + AtomicAuthorityEffectDestination);
see development/programme-2-gap-report.md.

Profile sets: off (journal mode, no opt-in profile), identity, freshness, rule_revision, full (all three). Synthetic only.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
SETS = ("off", "identity", "freshness", "rule_revision", "full")
OPERATION = "op-order-100/refund-1"
SIGNER, REQUESTER, POLICY_SIGNER = ("urn:cognous:principal:rule-signer", "urn:cognous:principal:requester",
                                    "urn:cognous:principal:policy-signer")


def _head(path: str) -> str:
    return subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True).strip()


def _dump(path: pathlib.Path, doc) -> None:
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _deterministic_uuids() -> None:
    counter = iter(range(1, 10**6))
    os.getpid = lambda: 4242  # type: ignore[assignment]  # the journal records the owner pid; fixed so records compare byte for byte
    uuid.uuid4 = lambda: uuid.UUID(int=next(counter))  # type: ignore[assignment]


class Flow:
    def __init__(self, work: pathlib.Path, profile_set: str, *, delayed: bool = False, wide: bool = False):
        import agent_control_plane.bounded as cp
        import tests.test_bounded_authorization as tba
        import tests.test_runtime_authority as tra
        from agent_action_manifest.models import AgentActionManifest
        from engine.control_plane_adapter import PinnedControlPlaneExecutor
        from engine.safe_executor import DurableRefundDestination, LocalExecutionPolicy

        self.cp, self.tba, self.tra = cp, tba, tra
        self.NOW = tba.NOW
        cp._now = lambda: self.NOW
        use_identity = profile_set in ("identity", "full")
        use_fresh = profile_set in ("freshness", "full")
        use_rules = profile_set in ("rule_revision", "full")

        # the actual pinned Action Manifest example, through the actual manifest model (as the orchestrator's harness does)
        manifest_path = pathlib.Path(os.environ["COGNOUS_ACTION_MANIFEST_SRC"]) / "examples" / "refund_integration_v1_1.manifest.json"
        model = AgentActionManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
        canonical = model.model_dump(mode="json", exclude_none=False)
        if wide:  # let the cumulative cap allow a second effect, so only operation identity can prevent it
            for action in canonical["actions"]:
                action["effect_limits"]["max_effects"] = 2
        self.manifest_doc = json.loads(json.dumps(canonical))
        tba.manifest = lambda: json.loads(json.dumps(canonical))
        tra.manifest = tba.manifest

        # the orchestrator's tenant-bound proposal (the setup_flow fixture, tenant-aware)
        tra.proposal = tba.tenant_proposal
        tra.resolver_for = lambda p: tba.tenant_resolver_for(p)
        self.p, self.r, self.f, self.cfg = tra.setup_flow(work / "cp")
        for status in self.r.evidence.values():  # the fixture's signed evidence statement carries tenant_id
            tra.sign_evidence(status, tenant_id=tba.TENANT)
        if wide:
            ctx = self.r.contexts[tba.PROFILE]
            ctx["requirement"]["permissions"][0]["max_effects"] = 2
            ctx["grant"]["permissions"][0]["max_effects"] = 2
        updates = {}
        if use_identity:
            from agent_control_plane.operation_identity import OperationIdentityProfile
            updates["operation_identity"] = OperationIdentityProfile(resolver_id="synthetic-resolver", resolver_version="1")
            self.r.contexts[tba.PROFILE]["runtime_authority"]["operation_id"] = OPERATION
        if use_fresh:
            from agent_control_plane.freshness import FreshnessProfile
            updates["freshness"] = FreshnessProfile()
        if updates:
            self.cfg = self.cfg.model_copy(update=updates)
        tra.bind_approval(self.r, self.cfg)
        self.f.runtime_authority_profile = self.cfg.snapshot()
        if use_rules:
            from agent_control_plane.bounded import commitment
            from agent_control_plane.rule_revision import RuleRevision, RuleRevisionProfile, append_rule_revision
            digest = commitment({"policy": "v1"})
            self.r.policies[tba.POLICY_REF].digest = digest
            self.f.rule_revision_profile = RuleRevisionProfile(signers=[SIGNER, POLICY_SIGNER])
            append_rule_revision(self.f.records, self.f.rule_revision_profile, RuleRevision(
                revision_id="adopt-1", rule_kind="policy", rule_ref=tba.POLICY_REF, from_digest=None, to_digest=digest,
                reviser=REQUESTER, signer=POLICY_SIGNER, authority_ref="synthetic-authority:1", reason="synthetic",
                recorded_at=self.NOW.isoformat()))
        root = work / "sqlite"
        if delayed:
            from engine.delayed_commit_destination import delayed as delayed_class
            self.dest = delayed_class(operation_identity=use_identity)(root)
        elif use_identity:
            from engine.operation_identity_destination import OperationIdentityDestination
            self.dest = OperationIdentityDestination(root)
        else:
            self.dest = DurableRefundDestination(root)
        policy = LocalExecutionPolicy(
            allowed_institutions=frozenset({tba.INSTITUTION}), allowed_authority_domains=frozenset({"customer-refunds"}),
            allowed_adapters=frozenset({self.p.adapter_id}), allowed_actions=frozenset({self.p.action_id}),
            allowed_target_prefixes=("urn:cognous:synthetic-account:",), allowed_units=frozenset({"USD"}),
            max_amount=1000, max_effects=2)
        self.executor = PinnedControlPlaneExecutor(workflow=self.f, destination=self.dest, policy=policy,
                                                   observation_clock=lambda: self.NOW)
        self.d1 = self.f.decide(self.p, now=self.NOW)

    def envelope(self, d):
        from engine.safe_executor import EXECUTION_ENVELOPE_VERSION, ExecutionEnvelope, ExecutionOperation
        p = self.p
        fields = {k: getattr(p, k) for k in ["actor", "principal", "manifest_id", "manifest_version", "manifest_digest", "action_id",
                                             "adapter_id", "target", "payload", "payload_commitment", "amount", "unit", "effects",
                                             "requirement_id"]}
        op = ExecutionOperation(**fields, institution_id=self.tba.INSTITUTION, authority_domain="customer-refunds",
                                proposal_commitment=self.cp.commitment(p.model_dump(mode="json")),
                                requested_permissions=tuple(p.requested_permissions), authority_context_id=p.authority_context_ref,
                                grant_id=d.binding.grant_id, grant_revision=d.binding.grant_revision,
                                effective_max_effects=d.binding.effective_max_effects, tenant_id=p.tenant_id)
        return ExecutionEnvelope(EXECUTION_ENVELOPE_VERSION, d.decision_id, d.effect_id, op)

    def run(self, d=None):
        d = d or self.d1
        return self.executor.execute(envelope=self.envelope(d), proposal=self.p, decision=d, now=self.NOW)

    def publish_revision(self, revision: str) -> None:
        """The authority side publishes a new revision of the same grant (a renewal candidate)."""
        ctx = self.r.contexts[self.tba.PROFILE]
        ctx["grant"]["revision"] = revision
        for status in self.r.statuses.values():
            status.revision = revision
        for approval in self.r.approvals.values():
            approval.grant_revision = revision
        self.tra.bind_approval(self.r, self.f.runtime_authority_profile or self.cfg)

    def ledger(self) -> list[dict]:
        uri = pathlib.Path(self.dest.path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM effects ORDER BY effect_id")]
        finally:
            conn.close()

    def keep(self, out: pathlib.Path, name: str, extra: dict) -> dict:
        d = out / name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        shutil.copyfile(self.f.records.path, d / "run-record.json")
        _dump(d / "proposal.json", self.p.model_dump(mode="json", exclude_none=False))
        _dump(d / "manifest.json", self.manifest_doc)
        rows = self.ledger()
        extra = dict(extra, ledger_effect_ids=[r["effect_id"] for r in rows], effect_rows=rows)
        _dump(d / "result.json", extra)
        return {"effects": len(extra["ledger_effect_ids"])}


def _res(r) -> dict:
    return {k: getattr(r, k, None) for k in ("status", "error", "attempted", "acknowledged", "observed_state")}


def run(out: pathlib.Path, sets: tuple[str, ...]) -> dict:
    _deterministic_uuids()
    cp_src, rt_src = os.environ["COGNOUS_CONTROL_PLANE_SRC"], os.environ["COGNOUS_EXECUTION_RUNTIME_ROOT"]
    for p in (pathlib.Path(rt_src) / "tests", pathlib.Path(rt_src), pathlib.Path(cp_src) / "src", pathlib.Path(cp_src),
              pathlib.Path(os.environ["COGNOUS_ACTION_MANIFEST_SRC"]) / "src"):
        sys.path.insert(0, str(p))
    out.mkdir(parents=True, exist_ok=True)
    heads = {"control_plane": _head(cp_src), "execution_runtime": _head(rt_src), "action_manifest": _head(os.environ["COGNOUS_ACTION_MANIFEST_SRC"])}
    _dump(out / "heads.json", heads)
    work = pathlib.Path(tempfile.mkdtemp(prefix="overlay-journal-"))
    summary: dict[str, dict] = {}
    for s in sets:
        # applied, then the same request again (the adapter reconciles; no second effect)
        f = Flow(work / s / "applied", s)
        assert f.d1.result == "authorized", f.d1.reasons
        first = f.run()
        again = f.run()
        summary[f"{s}/applied"] = f.keep(out, f"{s}/applied", {"decision": f.d1.result, "first": _res(first), "again": _res(again)})
        # held: the grant status becomes unreadable at decision time
        f2 = Flow(work / s / "held", s)
        f2.r.grant_status = lambda ref: None
        held = f2.f.decide(f2.p, now=f2.NOW)
        summary[f"{s}/held"] = f2.keep(out, f"{s}/held", {"decision": held.result, "reasons": list(held.reasons)})
    shutil.rmtree(work, ignore_errors=True)
    _dump(out / "summary.json", {"heads": heads, "scenarios": summary})
    return summary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: _journal_runner.py OUTDIR [SET ...]")
    chosen = tuple(sys.argv[2:]) or SETS
    bad = [s for s in chosen if s not in SETS]
    if bad:
        raise SystemExit(f"unknown profile set {bad}")
    print(json.dumps(run(pathlib.Path(sys.argv[1]), chosen), sort_keys=True))
