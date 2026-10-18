"""Witness-digest/0.1 and holder-inventory/0.1 (opt-in) over the orchestrator's records and refund flow.

Synthetic; the local-file witness is a test aid. What it shows: after a head digest is held outside the record store, a dropped or
rewritten covered row is rejected, while appended rows are reported as unwitnessed (not as intact). It does NOT show tamper evidence
against the witness holder, and no real witness location exists (that is a publication step outside this repository).
"""
from __future__ import annotations

from conftest import section


def test_witness_rejects_dropped_and_rewritten_rows_and_does_not_vouch_for_appends(assurance):
    rows = {}
    for name, w in assurance["witness"].items():
        assert w["untouched"] is True
        assert w["appended"]["ok"] is True and sum(w["appended"]["unwitnessed_rows"].values()) == 1, "an append is unwitnessed, not intact"
        assert w["dropped"]["ok"] is False and w["dropped"]["reasons"] == ["witness_ledger_shrunk"], (name, w["dropped"])
        assert w["rewritten"]["ok"] is False and w["rewritten"]["reasons"] == ["witness_ledger_head_mismatch"], (name, w["rewritten"])
        assert "not tamper evidence against the witness holder" in w["scope_statement"]
        rows[name] = {"ledgers": w["covered_ledgers"], "rows_covered": w["rows_covered"]}
    assert set(assurance["witness"]) == {"candidate-handoff/applied", "off/applied", "full/applied"}
    section("witness_over_orchestrator_records", {"records": len(rows), "rows": rows})


def test_flagged_action_class_holds_without_a_holder_inventory(assurance):
    inv = assurance["inventory"]
    held = inv["flagged_without_inventory"]
    assert held["result"] == "hold" and "holder_inventory_missing" in held["reasons"] and held["ledger_rows"] == 0
    ok = inv["flagged_with_inventory"]
    assert ok["result"] == "authorized" and ok["execute"]["status"] == "executed" and ok["ledger_rows"] == 1
    section("holder_inventory_refund", inv)
