"""The independent verifier (cognous-verify) and the ODES validators over the orchestrator's retained run records.

Report only. The verifier imports nothing from the stack; it is run here as a subprocess against records the orchestrator's own
harness (atomic-claim route) and the journal-mode adapter route produced from the orchestrator's inputs (the pinned Action Manifest
example and the tenant-bound proposal). A refusal of a real orchestrator record outside the named findings is a FINDING: these tests fail on it for the
default path and never loosen the verifier's verdict. For profile-on records they pin only the SHAPE of the current outcome.

What an accepted record proves: that its own fields are mutually consistent and recompute. It does not prove that the decision was
right, that the destination acted, or who produced the record (the verifier's own does_not_prove block says the same).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3
import subprocess
import sys

import pytest

from conftest import section

FIXED = "2026-10-18T12:00:00+00:00"
HANDOFF = ("applied", "held_no_grant", "lost_ack_then_reconcile", "duplicate_dispatch")
JOURNAL_DEFAULT = ("off/applied", "off/held")
JOURNAL_PROFILE_ON = ("identity/applied", "freshness/applied", "rule_revision/applied", "full/applied", "identity/held",
                      "freshness/held", "rule_revision/held", "full/held")
STRUCTURE_CODES = {"schema_violation", "undeclared_member", "unknown_enum_value", "invalid_extension_key", "unsupported_contract_version"}


def _load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def odes(overlay):
    root = pathlib.Path(overlay.paths["odes"]) / "contracts"
    return {name: _load_module("odes_" + name.replace("-", "_"), root / name / "validate.py")
            for name in ("verification-report", "control-plane-journal", "operation-identity")}


def ledger_projection(result_json: pathlib.Path, bundle_result: dict) -> dict:
    """Orchestrator-authored projection of the runtime route's SQLite effect rows into the verifier's ledger shape.

    The verifier's documented ledger is the control plane's local destination state; the orchestrator's accepted route writes a
    runtime SQLite destination instead, so this field-for-field projection is the orchestrator's own and is labelled as such.
    """
    effects, counts = {}, {}
    for row in bundle_result["effect_rows"]:
        effects[row["effect_id"]] = {"effect_id": row["effect_id"], "grant_id": row["grant_id"], "target": row["target"],
                                     "amount": row["amount"], "unit": row["unit"], "payload": json.loads(row["payload_json"]),
                                     "state": row["state"]}
        counts[row["grant_id"]] = counts.get(row["grant_id"], 0) + 1
    return {"effects": effects, "grant_effect_counts": counts}


def verify(overlay, bundle: pathlib.Path, *, ledger: pathlib.Path | None = None) -> tuple[int, dict, str]:
    report = bundle / ("report-ledger.json" if ledger else "report.json")
    verifier_src = pathlib.Path(overlay.paths["verifier"]) / "src"
    argv = [str(bundle / "run-record.json"), "--proposal", str(bundle / "proposal.json"), "--manifest", str(bundle / "manifest.json"),
            "--out", str(report), "--generated-at", FIXED, "--controller-revision", overlay.heads["control_plane"],
            "--source-revision", overlay.heads["verifier"]]
    if ledger:
        argv += ["--ledger", str(ledger)]
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from cognous_verify.cli import main; sys.exit(main(sys.argv[2:]))")
    proc = subprocess.run([sys.executable, "-I", "-c", code, str(verifier_src), *argv], capture_output=True, text=True, timeout=300,
                          env={"PATH": "", "HOME": ""})
    doc = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    return proc.returncode, doc, proc.stdout + proc.stderr


def tally(report: dict) -> dict:
    s = report["summary"]
    return {k: s[k] for k in ("checks", "confirmed", "could_not_check", "refuted")}


def assert_report_denominators(report: dict) -> None:
    s = report["summary"]
    assert s["checks"] == len(report["checks"]) == s["confirmed"] + s["could_not_check"] + s["refuted"]
    for check in report["checks"]:
        t = check.get("tally") or check.get("denominator") or {}
        if t and "n" in t:
            assert t.get("refuted", 0) + t.get("could_not_check", 0) <= t["n"]


def test_default_path_records_are_accepted_or_abstained_never_refuted(overlay, odes, candidate_handoff, candidate_journal):
    """The verifier's verdict on every default-path orchestrator record (4 handoff + 2 journal, with and without a ledger).

    Without a ledger the V4 checks are 'could not check' (exit 3, abstain). A refutation here would be a finding.
    The report must validate against the ODES verification-report contract validator (the ODES checkout, not the verifier's copy).
    """
    rows = []
    bundles = [candidate_handoff / sc for sc in HANDOFF] + [candidate_journal / sc for sc in JOURNAL_DEFAULT]
    for bundle in bundles:
        code, report, out = verify(overlay, bundle)
        assert code in (0, 3), f"{bundle.name}: cognous-verify exit {code} on a real orchestrator record (FINDING):\n{out}"
        assert odes["verification-report"].validate(report) == [], f"{bundle.name}: report does not validate against ODES"
        assert_report_denominators(report)
        assert report["summary"]["refuted"] == 0
        rows.append({"bundle": f"{bundle.parent.name}/{bundle.name}", "exit": code, **tally(report)})
    section("verifier_default_path_no_ledger", {"records": len(bundles), "rows": rows})


def _refusals(report: dict) -> dict[str, set[str]]:
    return {c["check_id"]: {f["code"] for f in c.get("findings", [])} for c in report["checks"] if c["verdict"] == "refuted"}


def _abstentions(report: dict) -> dict[str, str]:
    """check_id -> the verifier's own reason (extensions.x-reason) for every check that could not be made."""
    return {c["check_id"]: (c.get("extensions") or {}).get("x-reason", "") for c in report["checks"] if c["verdict"] == "could_not_check"}


# FINDING F-2 (narrowed, verifier main 5ed1ffb, PR #9). On the orchestrator's accepted route (Atomic claim) the Control Plane record
# carries no attempt row: the runtime keeps the attempt in its own SQLite destination. The verifier first accepted these records with
# a projected ledger (867402f), then refused them (from 2597196, "a ledger row needs an attempt"), and since 5ed1ffb abstains:
# `v4.ledger.rows-agree-with-attempts` is could_not_check with reason `attempt_rows_not_in_record`, 0 refutations. The route and the
# verifier's ledger model still do not meet; the verifier now says so instead of refusing. Expectations below are exact.
F2_ABSTAIN = {"v4.ledger.rows-agree-with-attempts": "attempt_rows_not_in_record"}


def test_runtime_route_records_with_an_orchestrator_projected_ledger(overlay, odes, candidate_handoff):
    """Handoff (atomic route) bundles with the orchestrator's SQLite-to-ledger projection (finding F-2, narrowed).

    4 records; the held record has no effect rows (an empty ledger). Exact expectations at verifier 5ed1ffb: the three records with an
    effect abstain on exactly `v4.ledger.rows-agree-with-attempts` (reason `attempt_rows_not_in_record`) with 0 refutations (exit 3);
    the held record is fully confirmed (exit 0, nothing abstained). Any refusal, and any other abstention or reason, fails: it is a new
    finding or a regression, never something to tolerate. The report must validate against ODES and its denominators must add up.
    """
    rows = []
    for sc in HANDOFF:
        bundle = candidate_handoff / sc
        ledger = bundle / "ledger-projection.json"
        ledger.write_text(json.dumps(ledger_projection(bundle / "result.json", json.loads((bundle / "result.json").read_text())),
                                     indent=1, sort_keys=True) + "\n", encoding="utf-8")
        code, report, out = verify(overlay, bundle, ledger=ledger)
        assert odes["verification-report"].validate(report) == []
        assert_report_denominators(report)
        refusals, abstentions = _refusals(report), _abstentions(report)
        assert refusals == {}, f"{sc}: refusal outside a named finding (F-2 is an abstention now)\n{out}"
        if sc == "held_no_grant":
            assert code == 0 and abstentions == {}, f"{sc}: held record (empty ledger) must be fully confirmed: exit {code} {abstentions}"
        else:
            assert code == 3 and abstentions == F2_ABSTAIN, f"{sc}: expected exactly {F2_ABSTAIN}, got exit {code} {abstentions}\n{out}"
        rows.append({"bundle": sc, "exit": code, "refused": {k: sorted(v) for k, v in refusals.items()}, "abstained": abstentions, **tally(report)})
    section("verifier_runtime_route_with_projected_ledger_F2", {"records": len(rows), "rows": rows,
                                                                "f2_abstained": sum(1 for r in rows if r["abstained"])})


def test_profile_on_records_report_only(overlay, odes, candidate_journal):
    """Profile-on records (opt-in profiles; 8 records): the report must validate; the outcome is recorded, not forced.

    Observed at the candidate revisions: the verifier refuses every one at v1.structure because its vendored journal contract does
    not declare the profile members (ODES stream J1, not merged at the time of writing), and the delegated V2 groups then report
    could-not-check. If the verifier later accepts these records, this test still passes and the report shows it. Any refusal code
    outside the structural set is a new finding and fails.
    """
    rows = []
    for name in JOURNAL_PROFILE_ON:
        bundle = candidate_journal / name
        code, report, out = verify(overlay, bundle)
        assert code in (0, 1, 3), f"{name}: unexpected exit {code} (crash or usage error)\n{out}"
        assert odes["verification-report"].validate(report) == []
        assert_report_denominators(report)
        codes = sorted({f["code"] for c in report["checks"] if c["verdict"] == "refuted" for f in c.get("findings", [])})
        refuted = [c["check_id"] for c in report["checks"] if c["verdict"] == "refuted"]
        assert set(codes) <= STRUCTURE_CODES, f"{name}: non-structural refusal codes {codes}"
        rows.append({"bundle": name, "exit": code, "refuted_checks": refuted, "refusal_codes": codes, **tally(report)})
    section("verifier_profile_on_records", {"records": len(rows), "rows": rows})


def test_odes_journal_contract_over_orchestrator_records(odes, candidate_handoff, candidate_journal):
    """ODES control-plane-journal validator: default records conform (6); profile-on raw records are refused (8), only structurally."""
    journal = odes["control-plane-journal"]

    def violations(path: pathlib.Path):
        rec = json.loads(path.read_text(encoding="utf-8"))
        doc = dict(rec, contract="control-plane-journal", contract_version="0.1.0-draft", producer="control-plane")
        return journal.validate(doc)

    default = [candidate_handoff / sc / "run-record.json" for sc in HANDOFF] + [candidate_journal / sc / "run-record.json" for sc in JOURNAL_DEFAULT]
    default_bad = {str(p.parent.name): [v.code for v in violations(p)] for p in default if violations(p)}
    assert default_bad == {}, f"default-path orchestrator records refused by the ODES journal contract (FINDING): {default_bad}"
    on = {name: sorted({v.code for v in violations(candidate_journal / name / "run-record.json")}) for name in JOURNAL_PROFILE_ON}
    for name, codes in on.items():
        assert set(codes) <= {"schema_violation", "undeclared_member"}, (name, codes)
    section("odes_journal_contract", {"default_records_conforming": len(default), "default_records_total": len(default),
                                      "profile_on_records": len(on), "profile_on_codes": on})


def test_odes_operation_identity_sidecar_over_the_identity_records(odes, candidate_journal):
    """Project the three operation-identity lists out of the raw record (they are members of it) and validate with the journal as context."""
    oi = odes["operation-identity"]
    rows = []

    def without_clock(rows_):
        # freshness/0.1 adds `evaluated_at` to identity rows; the freshness contract carries it in clock_rows, so a projection of the
        # identity contract drops it (the record itself is not altered)
        return [{k: v for k, v in r.items() if k != "evaluated_at"} for r in rows_]

    for name in ("identity/applied", "full/applied"):
        rec = json.loads((candidate_journal / name / "run-record.json").read_text(encoding="utf-8"))
        doc = {"contract": "operation-identity", "contract_version": "0.1.0-draft", "profile": "operation-identity/0.1",
               "producer": "control-plane", "run_id": rec["run_id"], "operations": without_clock(rec["operations"]),
               "operation_renewals": without_clock(rec.get("operation_renewals", [])), "attempt_joins": without_clock(rec["attempt_joins"])}
        found = oi.validate(doc, journal=rec)
        rows.append({"bundle": name, "violations": [f"{v.code} {v.path}" for v in found]})
    section("odes_operation_identity_sidecar", {"records": len(rows), "rows": rows})
    assert all(not r["violations"] for r in rows), rows


# FINDING F-1 (narrowed, verifier main 5ed1ffb, PR #9). The runtime's destination observation carries `operation_digest` inside
# `destination_state`; the verifier's ledger row shape is closed and has no such member. Projection A (ledger row omits the member):
# `v4.ledger.observations-agree` used to refuse (`observation_differs_from_ledger_row`); since 5ed1ffb it abstains with reason
# `destination_state_has_members_outside_ledger_row`, 0 refutations. Projection B (ledger row keeps the member) is still refused at
# `v1.structure.ledger` / `ledger_shape`, by design (the ledger row shape is closed).
F1_A_ABSTAIN = {"v4.ledger.observations-agree": "destination_state_has_members_outside_ledger_row"}
F1_B_REFUSAL = {"v1.structure.ledger": {"ledger_shape"}}


def test_adapter_route_records_with_projected_ledger_finding_f1(overlay, odes, candidate_journal, candidate_destinations):
    """Adapter-route default-path records (profile off) with the orchestrator's projected ledger, both projections (finding F-1, narrowed).

    Records: journal applied, journal held, lost-ack-then-land, renewal race (legacy: two effects for one operation). Variant A drops
    `operation_digest` from the ledger row, variant B keeps it. Exact expectations at verifier 5ed1ffb:
    - A, with an effect: exit 3, 0 refutations, abstains on exactly `v4.ledger.observations-agree`
      (`destination_state_has_members_outside_ledger_row`).
    - B, with an effect: exit 1, refused on exactly `v1.structure.ledger` / `ledger_shape` (by design).
    - the held record (empty ledger): exit 0, nothing abstained or refused, both variants.
    Any other refusal, abstention or reason fails. The report must validate and add up.
    """
    bundles = [candidate_journal / "off/applied", candidate_journal / "off/held",
               candidate_destinations / "lost_ack_then_land_identity_off", candidate_destinations / "renewal_race_identity_off"]
    rows = []
    for bundle in bundles:
        result = json.loads((bundle / "result.json").read_text())
        for variant in ("A_without_operation_digest", "B_with_operation_digest"):
            ledger = ledger_projection(bundle / "result.json", result)
            if variant.startswith("B"):
                for row, src in zip(ledger["effects"].values(), result["effect_rows"], strict=True):
                    row["operation_digest"] = src["operation_digest"]
            path = bundle / f"ledger-{variant}.json"
            path.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            code, report, out = verify(overlay, bundle, ledger=path)
            assert odes["verification-report"].validate(report) == [], f"{bundle.name}/{variant}: report does not validate"
            assert_report_denominators(report)
            refusals, abstentions = _refusals(report), _abstentions(report)
            where = f"{bundle.name}/{variant}"
            if not result["effect_rows"]:
                assert (code, refusals) == (0, {}) and abstentions == {}, f"{where}: empty ledger must be fully confirmed: {code} {refusals} {abstentions}\n{out}"
            elif variant.startswith("A"):
                assert code == 3 and refusals == {} and abstentions == F1_A_ABSTAIN, f"{where}: expected exactly {F1_A_ABSTAIN}: {code} {refusals} {abstentions}\n{out}"
            else:
                assert code == 1 and refusals == F1_B_REFUSAL, f"{where}: expected exactly {F1_B_REFUSAL}: {code} {refusals}\n{out}"
            rows.append({"bundle": f"{bundle.parent.name}/{bundle.name}", "variant": variant, "exit": code, "effects_in_ledger": len(result["effect_rows"]),
                         "refused": {k: sorted(v) for k, v in refusals.items()}, "abstained": abstentions, **tally(report)})
    section("verifier_adapter_route_projected_ledger_F1", {"records": len(bundles), "runs": len(rows), "rows": rows,
                                                           "f1_abstained_projection_a": sum(1 for r in rows if r["abstained"] and r["variant"].startswith("A")),
                                                           "f1_refused_projection_b": sum(1 for r in rows if r["refused"] and r["variant"].startswith("B"))})
