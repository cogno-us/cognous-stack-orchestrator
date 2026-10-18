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


def acp(overlay, *argv: str) -> subprocess.CompletedProcess:
    cp = pathlib.Path(overlay.paths["control_plane"])
    code = "import sys; sys.path.insert(0, sys.argv[1]); from agent_control_plane.cli import main; sys.exit(main(sys.argv[2:]))"
    return subprocess.run([sys.executable, "-I", "-c", code, str(cp / "src"), *argv], capture_output=True, text=True, timeout=300,
                          env={"PATH": "", "HOME": ""})


def verify(overlay, bundle: pathlib.Path, *, ledger: pathlib.Path | None = None, witness: pathlib.Path | None = None,
           record: pathlib.Path | None = None, report_name: str | None = None) -> tuple[int, dict, str]:
    report = bundle / (report_name or ("report-ledger.json" if ledger else "report.json"))
    verifier_src = pathlib.Path(overlay.paths["verifier"]) / "src"
    argv = [str(record or bundle / "run-record.json"), "--proposal", str(bundle / "proposal.json"), "--manifest", str(bundle / "manifest.json"),
            "--out", str(report), "--generated-at", FIXED, "--controller-revision", overlay.heads["control_plane"],
            "--source-revision", overlay.heads["verifier"]]
    if ledger:
        argv += ["--ledger", str(ledger)]
    if witness:
        argv += ["--witness", str(witness)]
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


# FINDING F-1 (resolved for projection B, verifier main adb8927, PR #11; narrowed earlier by 5ed1ffb, PR #9). The runtime's destination
# observation carries `operation_digest` inside `destination_state`. Since adb8927 the verifier reads the ODES destination-ledger
# 0.1.0-draft contract: the ledger row accepts an optional `operation_digest` (sha256: + 64 hex) and `extensions`; an equal digest is
# confirmed, a differing one is refuted (`operation_digest_mismatch`). Projection B (ledger row keeps the member): accept.
# Projection A (ledger row omits it, the member only in the observation) still abstains on `v4.ledger.observations-agree` with reason
# `destination_state_has_members_outside_ledger_row`, 0 refutations.
F1_A_ABSTAIN = {"v4.ledger.observations-agree": "destination_state_has_members_outside_ledger_row"}


def _verdicts(report: dict) -> dict[str, str]:
    return {c["check_id"]: c["verdict"] for c in report["checks"]}


def test_adapter_route_records_with_projected_ledger_finding_f1(overlay, odes, candidate_journal, candidate_destinations):
    """Adapter-route default-path records (profile off) with the orchestrator's projected ledger, both projections (finding F-1).

    Records: journal applied, journal held, lost-ack-then-land, renewal race (legacy: two effects for one operation). Variant A drops
    `operation_digest` from the ledger row, variant B keeps it. Exact expectations at verifier adb8927:
    - A, with an effect: exit 3, 0 refutations, abstains on exactly `v4.ledger.observations-agree`
      (`destination_state_has_members_outside_ledger_row`).
    - B, with an effect: exit 0, overall accept, no refuted or could-not-check check, `v4.ledger.observations-agree` confirmed.
    - the held record (empty ledger): exit 0, nothing abstained or refused, both variants.
    Any other refusal, abstention or reason fails. The report must validate and add up. Tampering with the row's digest (variant C,
    not a producer shape) must be refuted with exactly `operation_digest_mismatch`.
    """
    bundles = [candidate_journal / "off/applied", candidate_journal / "off/held",
               candidate_destinations / "lost_ack_then_land_identity_off", candidate_destinations / "renewal_race_identity_off"]
    rows = []
    for bundle in bundles:
        result = json.loads((bundle / "result.json").read_text())
        for variant in ("A_without_operation_digest", "B_with_operation_digest", "C_tampered_operation_digest"):
            ledger = ledger_projection(bundle / "result.json", result)
            if variant[0] in "BC":
                for row, src in zip(ledger["effects"].values(), result["effect_rows"], strict=True):
                    row["operation_digest"] = src["operation_digest"]
            if variant[0] == "C":
                if not result["effect_rows"]:
                    continue
                first = next(iter(ledger["effects"].values()))
                first["operation_digest"] = "sha256:" + "0" * 64
            path = bundle / f"ledger-{variant}.json"
            path.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            code, report, out = verify(overlay, bundle, ledger=path)
            assert odes["verification-report"].validate(report) == [], f"{bundle.name}/{variant}: report does not validate"
            assert_report_denominators(report)
            refusals, abstentions = _refusals(report), _abstentions(report)
            overall = report["extensions"]["x-overall"]
            where = f"{bundle.name}/{variant}"
            if not result["effect_rows"]:
                assert (code, refusals) == (0, {}) and abstentions == {}, f"{where}: empty ledger must be fully confirmed: {code} {refusals} {abstentions}\n{out}"
            elif variant[0] == "A":
                assert code == 3 and refusals == {} and abstentions == F1_A_ABSTAIN, f"{where}: expected exactly {F1_A_ABSTAIN}: {code} {refusals} {abstentions}\n{out}"
            elif variant[0] == "B":
                assert (code, overall, refusals, abstentions) == (0, "accept", {}, {}), f"{where}: expected accept: {code} {overall} {refusals} {abstentions}\n{out}"
                assert _verdicts(report)["v4.ledger.observations-agree"] == "confirmed"
                assert report["summary"]["refuted"] == 0 and report["summary"]["could_not_check"] == 0
            else:
                assert code == 1 and set(refusals) and all(v == {"operation_digest_mismatch"} for v in refusals.values()), f"{where}: expected only operation_digest_mismatch: {code} {refusals}\n{out}"
            rows.append({"bundle": f"{bundle.parent.name}/{bundle.name}", "variant": variant, "exit": code, "overall": overall,
                         "effects_in_ledger": len(result["effect_rows"]), "refused": {k: sorted(v) for k, v in refusals.items()},
                         "abstained": abstentions, **tally(report)})
    section("verifier_adapter_route_projected_ledger_F1", {
        "records": len(bundles), "runs": len(rows), "rows": rows,
        "f1_abstained_projection_a": sum(1 for r in rows if r["abstained"] and r["variant"].startswith("A")),
        "f1_accepted_projection_b": sum(1 for r in rows if r["variant"].startswith("B") and r["overall"] == "accept" and r["effects_in_ledger"]),
        "f1_projection_b_with_effect": sum(1 for r in rows if r["variant"].startswith("B") and r["effects_in_ledger"]),
        "f1_tampered_digest_refused": sum(1 for r in rows if r["variant"].startswith("C") and r["refused"])})


# Tier V3 (verifier PR #10, 05afab84): `cognous-verify --witness` over the witness the Control Plane's own public command
# `acp witness publish` writes for each retained record. The verifier's tools/capture_witnessed_runs.py does the same for its own corpus.
WITNESS_BUNDLES = ([("handoff", sc) for sc in HANDOFF] + [("journal", sc) for sc in JOURNAL_DEFAULT]
                   + [("destinations", "lost_ack_then_land_identity_off"), ("destinations", "renewal_race_identity_off")])


def _bundle(kind: str, name: str, candidate_handoff, candidate_journal, candidate_destinations) -> pathlib.Path:
    return {"handoff": candidate_handoff, "journal": candidate_journal, "destinations": candidate_destinations}[kind] / name


V3_CHECK_IDS = {"v3.witness.records", "v3.witness.digest-recompute", "v3.witness.chain", "v3.witness.run-id",
                "v3.witness.ledger-heads", "v3.witness.coverage"}


def _v3(report: dict) -> list[dict]:
    """Tier V3 is reported as ordinary `v3.*` checks listed in scope.tiers_run (verifier #12); the old extensions["x-tier-v3"] block is gone."""
    assert "x-tier-v3" not in report.get("extensions", {}), "the old x-tier-v3 extension shape is not produced by this verifier"
    assert "V3" in report["scope"]["tiers_run"], report["scope"]
    return [c for c in report["checks"] if c["check_id"].startswith("v3.")]


def test_witness_tier_v3_over_acp_witness_publish_of_the_retained_records(overlay, odes, candidate_handoff, candidate_journal, candidate_destinations):
    """Clean records: every V3 check confirmed and nothing else changes. Tampered ledger row: a stable refusal code.

    For each retained default-path record, `acp witness publish` writes a local file witness (the record is not touched) and the
    verifier is run with `--witness`. Clean: every V3 check confirmed, 0 refuted; the only could-not-check checks are the V4 ledger ones (no ledger supplied).
    Tampered (the record's first `decisions` row has one value changed AFTER the witness was published, the witness is untouched):
    the V3 ledger-head comparison refuses with `witness_ledger_head_mismatch`. What a confirmed witness shows: that the records
    match a digest that was published; not that the publisher was independent, nor that it was published in time.
    """
    rows, clean_confirmed, clean_total, tamper_refused = [], 0, 0, 0
    for kind, name in WITNESS_BUNDLES:
        bundle = _bundle(kind, name, candidate_handoff, candidate_journal, candidate_destinations)
        wit_dir = overlay.out / "witness" / kind / name.replace("/", "_")
        wit_dir.mkdir(parents=True, exist_ok=True)
        witness = wit_dir / "witness.jsonl"
        witness.unlink(missing_ok=True)
        pub = acp(overlay, "witness", "publish", str(bundle / "run-record.json"), "--witness", str(witness))
        assert pub.returncode == 0, f"{kind}/{name}: acp witness publish failed:\n{pub.stdout}{pub.stderr}"
        code, report, out = verify(overlay, bundle, witness=witness, report_name="report-witness.json")
        assert odes["verification-report"].validate(report) == [], f"{kind}/{name}: report does not validate"
        assert_report_denominators(report)
        v3 = _v3(report)
        assert v3 and "V3" in report["scope"]["tiers_run"]  # tier V3 was requested and ran
        assert {c["check_id"] for c in v3} == V3_CHECK_IDS, [c["check_id"] for c in v3]
        assert all(c["verdict"] == "confirmed" for c in v3), f"{kind}/{name}: V3 not all confirmed: {[(c['check_id'], c['verdict']) for c in v3]}\n{out}"
        # No ledger is supplied here, so the V4 ledger checks stay could-not-check exactly as without --witness (exit 3, abstain);
        # tier V3 adds no abstention and no refusal.
        assert report["summary"]["refuted"] == 0 and code in (0, 3), out
        assert set(_abstentions(report)) <= {c["check_id"] for c in report["checks"] if c["check_id"].startswith("v4.ledger.")}, out
        clean_confirmed += sum(1 for c in v3 if c["verdict"] == "confirmed")
        clean_total += len(v3)

        record = json.loads((bundle / "run-record.json").read_text(encoding="utf-8"))
        ledger_name = next(k for k in ("decisions", "resolution_checks") if record.get(k))
        damaged = json.loads(json.dumps(record))
        row = damaged[ledger_name][0]
        key = next(k for k, v in row.items() if isinstance(v, str))
        row[key] = row[key] + "-tampered"
        bad_record = wit_dir / "run-record-tampered.json"
        bad_record.write_text(json.dumps(damaged, indent=1) + "\n", encoding="utf-8")
        bcode, breport, bout = verify(overlay, bundle, witness=witness, record=bad_record, report_name="report-witness-tampered.json")
        assert odes["verification-report"].validate(breport) == []
        assert_report_denominators(breport)
        v3_codes = {c["check_id"]: sorted({f["code"] for f in c.get("findings", [])}) for c in _v3(breport) if c["verdict"] == "refuted"}
        assert v3_codes, f"{kind}/{name}: tampering with {ledger_name}[0].{key} was not refuted by tier V3\n{bout}"
        assert {c for codes in v3_codes.values() for c in codes} == {"witness_ledger_head_mismatch"}, f"{kind}/{name}: {v3_codes}"
        assert bcode == 1
        tamper_refused += 1
        rows.append({"bundle": f"{kind}/{name}", "clean_exit": code, "v3_checks": len(v3), "v3_confirmed": sum(1 for c in v3 if c["verdict"] == "confirmed"),
                     "tampered_ledger": ledger_name, "tampered_exit": bcode, "tampered_v3_refusals": v3_codes,
                     "tampered_other_refusals": {k: sorted(v) for k, v in _refusals(breport).items() if k not in v3_codes}, **{f"clean_{k}": v for k, v in tally(report).items()}})
    section("verifier_witness_tier_v3", {"records": len(WITNESS_BUNDLES), "clean_records_all_confirmed": len(WITNESS_BUNDLES),
                                         "v3_checks_clean_total": clean_total, "v3_checks_clean_confirmed": clean_confirmed,
                                         "tampered_records": len(WITNESS_BUNDLES), "tampered_refused_witness_ledger_head_mismatch": tamper_refused, "rows": rows})
