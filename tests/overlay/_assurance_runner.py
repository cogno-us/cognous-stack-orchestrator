"""Witness-digest/0.1 and holder-inventory/0.1 (opt-in Control Plane profiles) over records the orchestrator's flows produced.

A runner, not a test (subprocess). Two probes:
  witness     publish a head digest of a retained run record to a local-file witness, then verify the untouched record, an appended
              record, a record with a dropped row, and a record with a rewritten row (the same drop is accepted by the record store
              alone). Records come from bundle directories given on the command line.
  inventory   the journal-mode refund with a revocation-assurance-flagged action class: held (`holder_inventory_missing`) with no
              inventory, authorized and applied with an inventory enumerating a holder.

    python tests/overlay/_assurance_runner.py OUT.json BUNDLE_DIR [BUNDLE_DIR ...]   (environment as the other runners)

The local-file witness is a test aid: it gives visibility to whoever holds the digest, not tamper evidence against the witness
holder (the module says so in its own `scope`).
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _journal_runner as J  # noqa: E402


def witness_probe(bundle: pathlib.Path, work: pathlib.Path) -> dict:
    import agent_control_plane.witness as W
    doc = json.loads((bundle / "run-record.json").read_text(encoding="utf-8"))
    witness = W.LocalFileWitness(work / "witness.jsonl")
    W.publish_head(doc, witness)
    out: dict = {"covered_ledgers": sorted(W.head_digest(doc)), "rows_covered": {k: v["count"] for k, v in W.head_digest(doc).items()}}
    out["untouched"] = W.verify_against_witness(doc, witness).as_dict()["ok"]
    grown = copy.deepcopy(doc)
    ledger = next(name for name in ("attempts", "decisions") if grown.get(name))
    grown[ledger].append(copy.deepcopy(grown[ledger][-1]))
    v = W.verify_against_witness(grown, witness)
    out["appended"] = {"ok": v.ok, "unwitnessed_rows": v.unwitnessed_rows}
    dropped = copy.deepcopy(doc)
    dropped_ledger = next(name for name in ("attempts", "decisions") if dropped.get(name))
    dropped[dropped_ledger].pop()
    v = W.verify_against_witness(dropped, witness)
    out["dropped"] = {"ledger": dropped_ledger, "ok": v.ok, "reasons": v.reasons}
    rewritten = copy.deepcopy(doc)
    rewritten["decisions"][0]["reasons"] = ["status_unreadable"] if not rewritten["decisions"][0]["reasons"] else []
    v = W.verify_against_witness(rewritten, witness)
    out["rewritten"] = {"ok": v.ok, "reasons": v.reasons}
    out["scope_statement"] = W.verify_against_witness(doc, witness).scope
    return out


def inventory_probe(work: pathlib.Path) -> dict:
    from agent_control_plane.holder_inventory import AuthorityHolder, HolderInventory
    flow = J.Flow(work, "off")
    assert flow.d1.result == "authorized", flow.d1.reasons

    def configure(flag: bool, inventory):
        actions = {k: v.model_copy(update={"requires_revocation_assurance": flag}) for k, v in flow.cfg.actions.items()}
        cfg2 = flow.cfg.model_copy(update={"actions": actions, "holder_inventory": inventory})
        flow.tra.bind_approval(flow.r, cfg2)
        flow.f.runtime_authority_profile = cfg2.snapshot()

    inv = HolderInventory(inventory_id="inv-1", recorded_by="urn:cognous:principal:inventory-owner", recorded_at=flow.NOW.isoformat(),
                          holders=[AuthorityHolder(holder_id="h-routed", kind="routed", enforcement_point="control plane effect check")])
    configure(True, None)
    held = flow.f.decide(flow.p, now=flow.NOW)
    held_ledger = flow.ledger()
    configure(True, inv)
    allowed = flow.f.decide(flow.p, now=flow.NOW)
    result = flow.run(allowed) if allowed.result == "authorized" else None
    return {"flagged_without_inventory": {"result": held.result, "reasons": list(held.reasons), "ledger_rows": len(held_ledger)},
            "flagged_with_inventory": {"result": allowed.result, "reasons": list(allowed.reasons),
                                       "execute": J._res(result) if result else None, "ledger_rows": len(flow.ledger())},
            "effect_id_same_as_unflagged": allowed.effect_id == flow.d1.effect_id}


def main() -> None:
    J._deterministic_uuids()
    cp_src, rt_src = os.environ["COGNOUS_CONTROL_PLANE_SRC"], os.environ["COGNOUS_EXECUTION_RUNTIME_ROOT"]
    for p in (pathlib.Path(rt_src) / "tests", pathlib.Path(rt_src), pathlib.Path(cp_src) / "src", pathlib.Path(cp_src),
              pathlib.Path(os.environ["COGNOUS_ACTION_MANIFEST_SRC"]) / "src"):
        sys.path.insert(0, str(p))
    work = pathlib.Path(tempfile.mkdtemp(prefix="overlay-assurance-"))
    result: dict = {"witness": {}, "heads": {"control_plane": J._head(cp_src), "execution_runtime": J._head(rt_src)}}
    for raw in sys.argv[2:]:
        b = pathlib.Path(raw)
        wdir = work / f"w-{b.parent.name}-{b.name}"
        wdir.mkdir()
        result["witness"][f"{b.parent.name}/{b.name}"] = witness_probe(b, wdir)
    result["inventory"] = inventory_probe(work / "inv")
    pathlib.Path(sys.argv[1]).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("usage: _assurance_runner.py OUT.json BUNDLE_DIR [BUNDLE_DIR ...]")
    main()
