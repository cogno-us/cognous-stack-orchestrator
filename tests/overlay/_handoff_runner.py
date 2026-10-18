"""Run the orchestrator's connected refund handoff against whichever component checkouts the environment names.

This is a runner, not a test. It is executed as a subprocess so that two component revisions (the orchestrator's pins and a
candidate) never share one interpreter. It loads the orchestrator's own harness source
(development/scenarios/customer_refunds/connected/handoff/connected_handoff.py) UNCHANGED except that the three pin constants are
replaced by the revisions actually checked out; the harness file on disk is never edited. Every other line of the harness runs,
including its source-interface imports.

    COGNOUS_ACTION_MANIFEST_SRC=... COGNOUS_CONTROL_PLANE_SRC=... COGNOUS_EXECUTION_RUNTIME_ROOT=... \
        python tests/overlay/_handoff_runner.py OUTDIR

Synthetic only. No network. Writes one directory per scenario (see SCENARIOS) plus heads.json.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "development/scenarios/customer_refunds/connected/handoff/connected_handoff.py"
SCENARIOS = ("applied", "held_no_grant", "lost_ack_then_reconcile", "duplicate_dispatch")


def head(path: str) -> str:
    return subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True).strip()


def load_harness():
    """Return (module namespace, heads). The pin constants are replaced by the actual heads; nothing else is altered."""
    heads = {
        "action_manifest": head(os.environ["COGNOUS_ACTION_MANIFEST_SRC"]),
        "control_plane": head(os.environ["COGNOUS_CONTROL_PLANE_SRC"]),
        "execution_runtime": head(os.environ["COGNOUS_EXECUTION_RUNTIME_ROOT"]),
    }
    source = HARNESS.read_text(encoding="utf-8")
    replacements = {
        r'^(ACTION_MANIFEST_PIN = )"[0-9a-f]{40}"': heads["action_manifest"],
        r'^(CONTROL_PLANE_PIN = )"[0-9a-f]{40}"': heads["control_plane"],
        r'^(EXECUTION_RUNTIME_BASE_PIN = )"[0-9a-f]{40}"': heads["execution_runtime"],
    }
    for pattern, value in replacements.items():
        source, n = re.subn(pattern, lambda m, v=value: f'{m.group(1)}"{v}"', source, count=1, flags=re.M)
        if n != 1:
            raise RuntimeError(f"harness pin constant not found for {pattern!r}; the harness changed shape")
    ns: dict = {"__name__": "overlay_connected_handoff", "__file__": str(HARNESS)}
    exec(compile(source, str(HARNESS), "exec"), ns)  # noqa: S102 - the orchestrator's own harness, pins substituted
    return ns, heads


def _dump(path: Path, doc) -> None:
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True, default=str) + "\n", encoding="utf-8")


# The only wall-clock column the destination writes: `failure_records_v1.created_at` (time.time() at the refusal; it differs between two
# runs of the same revision). Masked to the string "<wall-clock>" and nothing else is masked.
WALL_CLOCK_COLUMNS = {("failure_records_v1", "created_at")}


def _tables(destination) -> dict:
    """Every row of every table in the atomic destination's database (raw values, insertion order; wall-clock columns masked)."""
    import sqlite3
    with sqlite3.connect(destination.path) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        out: dict = {"_schema": [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name")]}
        for n in names:
            cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{n}")')]
            masked = [(n, c) in WALL_CLOCK_COLUMNS for c in cols]
            out[n] = [[("<wall-clock>" if m else v) for v, m in zip(r, masked)]
                      for r in conn.execute(f'SELECT * FROM "{n}" ORDER BY rowid')]  # noqa: S608 - names come from sqlite_master
        return out


def _result(res) -> dict:
    keys = ("status", "attempted", "acknowledged", "observed_state", "error", "decision_id", "effect_id", "attempt_id")
    out = {k: getattr(res, k, None) for k in keys}
    obs = getattr(res, "observation", None)
    out["observation"] = dict(obs) if isinstance(obs, dict) else obs
    return out


def run(out: Path) -> dict:
    counter = iter(range(1, 10**6))
    uuid.uuid4 = lambda: uuid.UUID(int=next(counter))  # type: ignore[assignment]  # deterministic ids: byte comparison
    os.getpid = lambda: 4242  # type: ignore[assignment]  # the journal records the owner pid
    ns, heads = load_harness()
    h = ns["h"]
    import agent_control_plane.bounded as bounded

    bounded._now = lambda: h.NOW  # the fixed synthetic clock the component's own suites use
    out.mkdir(parents=True, exist_ok=True)
    _dump(out / "heads.json", heads)
    work = Path(tempfile.mkdtemp(prefix="overlay-handoff-"))
    summary: dict[str, dict] = {}

    def keep(name: str, proposal, flow, destination, extra: dict) -> None:
        d = out / name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        shutil.copyfile(flow.records.path, d / "run-record.json")
        _dump(d / "proposal.json", proposal.model_dump(mode="json", exclude_none=False))
        _dump(d / "manifest.json", h.manifest())
        extra = dict(extra)
        extra["effect_rows"] = ns["effect_rows"](destination)
        extra["attempt_rows"] = ns["attempt_rows"](destination)
        _dump(d / "result.json", extra)
        _dump(d / "atomic-tables.json", _tables(destination))
        summary[name] = {"effects": len(extra["effect_rows"]), "attempts": len(extra["attempt_rows"])}

    # applied
    proposal, _, flow, dest = ns["tenant_case"](work / "applied")
    decision = ns["decide_with_trusted_owner"](flow, proposal)
    executor, claim, envelope = ns["provision_connected"](proposal, flow, dest, decision)
    res = executor.execute(envelope=envelope, claim_id=claim.claim_id)
    keep("applied", proposal, flow, dest, {"decision": decision.result, "reasons": list(decision.reasons), "execute": _result(res),
                                           "claim_state": dest.claim_state(claim.claim_id)})

    # held: no authenticated grant
    proposal, _, flow, dest = ns["tenant_case"](work / "held", with_grant=False)
    decision = ns["decide_with_trusted_owner"](flow, proposal)
    keep("held_no_grant", proposal, flow, dest, {"decision": decision.result, "reasons": list(decision.reasons),
                                                 "observation": dest.observe(decision.effect_id)})

    # lost acknowledgement then reconcile (original attempt, no retry)
    proposal, _, flow, dest = ns["tenant_case"](work / "lost")
    decision = ns["decide_with_trusted_owner"](flow, proposal)
    executor, claim, envelope = ns["provision_connected"](proposal, flow, dest, decision)
    first = executor.execute(envelope=envelope, claim_id=claim.claim_id, simulate="lost_ack", attempt_id="overlay-lost-ack")
    recovery = dest.reconcile_claim(claim.claim_id, ns["UP"]["snapshot_envelope"](envelope))
    retry = executor.execute(envelope=envelope, claim_id=claim.claim_id, attempt_id="overlay-blind-retry")
    keep("lost_ack_then_reconcile", proposal, flow, dest, {"decision": decision.result, "first": _result(first),
                                                           "recovery": recovery, "blind_retry": _result(retry)})

    # duplicate dispatch of the same claim
    proposal, _, flow, dest = ns["tenant_case"](work / "dup")
    decision = ns["decide_with_trusted_owner"](flow, proposal)
    executor, claim, envelope = ns["provision_connected"](proposal, flow, dest, decision)
    first = executor.execute(envelope=envelope, claim_id=claim.claim_id)
    second = executor.execute(envelope=envelope, claim_id=claim.claim_id)
    keep("duplicate_dispatch", proposal, flow, dest, {"decision": decision.result, "first": _result(first), "second": _result(second)})

    shutil.rmtree(work, ignore_errors=True)
    _dump(out / "summary.json", {"heads": heads, "scenarios": summary})
    return summary


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: _handoff_runner.py OUTDIR")
    print(json.dumps(run(Path(sys.argv[1])), sort_keys=True))
