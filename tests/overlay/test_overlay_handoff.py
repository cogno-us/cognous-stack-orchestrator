"""Refund handoff on candidate component revisions, opt-in profiles on and off.

Synthetic only. These tests prove what they assert on the named candidate revisions and nothing about a deployment: no authority,
no effect, no release selection (README claims 1-4 unchanged; issue #30 HOLD unchanged). They never edit the orchestrator's pins.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from conftest import section

ROOT = pathlib.Path(__file__).resolve().parents[2]
HARNESS = ROOT / "development/scenarios/customer_refunds/connected/handoff/connected_handoff.py"
HANDOFF_SCENARIOS = ("applied", "held_no_grant", "lost_ack_then_reconcile", "duplicate_dispatch")
PROFILE_SETS = ("off", "identity", "freshness", "rule_revision", "full")
# top-level run-record members each opt-in profile adds (default records carry none of them)
EXPECTED_ADDED = {
    "off": set(),
    "identity": {"attempt_joins", "operations"},
    "freshness": set(),  # freshness adds members inside existing rows (clocks, nonce, deadline), not new top-level lists
    "rule_revision": {"rule_revisions"},
    "full": {"attempt_joins", "operations", "rule_revisions"},
}


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_orchestrator_pins_are_untouched_by_the_overlay():
    """The overlay substitutes pins only inside a subprocess copy of the harness source; the file on disk keeps the accepted pins."""
    text = HARNESS.read_text(encoding="utf-8")
    assert 'CONTROL_PLANE_PIN = "2bac7875391cad0a431fa0d75208b7ade39743e3"' in text
    assert 'EXECUTION_RUNTIME_BASE_PIN = "c4a05883266b815f39d97cbf2240406647985147"' in text
    assert 'ACTION_MANIFEST_PIN = "ff5490828b2bf7f6a976da209f3f533701855687"' in text


def test_candidate_heads_are_recorded(overlay, candidate_handoff):
    heads = load(candidate_handoff / "heads.json")
    assert heads["control_plane"] == overlay.heads["control_plane"] and heads["execution_runtime"] == overlay.heads["runtime"]
    assert all(re.fullmatch(r"[0-9a-f]{40}", v) for v in heads.values())
    section("candidate_heads", heads)


def test_default_handoff_scenarios_hold_on_candidate_sources(candidate_handoff):
    """The orchestrator's accepted route (Atomic claim) with its own harness, on candidate sources: same four outcomes."""
    applied = load(candidate_handoff / "applied/result.json")
    assert applied["decision"] == "authorized" and applied["execute"]["status"] == "executed"
    assert applied["claim_state"] == "consumed"
    assert len(applied["effect_rows"]) == 1 and len(applied["attempt_rows"]) == 1

    held = load(candidate_handoff / "held_no_grant/result.json")
    assert held["decision"] == "hold" and "issued_grant_missing" in held["reasons"]
    assert held["effect_rows"] == [] and held["attempt_rows"] == [] and held["observation"]["state"] == "absent"

    lost = load(candidate_handoff / "lost_ack_then_reconcile/result.json")
    assert lost["first"]["status"] == "unknown" and lost["first"]["acknowledged"] is False
    assert lost["recovery"]["status"] == "applied" and lost["recovery"]["retry_eligible"] is False
    assert lost["blind_retry"]["status"] == "denied" and lost["blind_retry"]["attempted"] is False
    assert len(lost["effect_rows"]) == 1 and len(lost["attempt_rows"]) == 1

    dup = load(candidate_handoff / "duplicate_dispatch/result.json")
    assert dup["first"]["status"] == "executed" and dup["second"]["status"] == "denied" and dup["second"]["attempted"] is False
    assert len(dup["effect_rows"]) == 1 and len(dup["attempt_rows"]) == 1
    section("handoff_default_path_on_candidate", {"scenarios": len(HANDOFF_SCENARIOS), "assertions_hold": True})


def test_default_path_is_byte_identical_to_the_programme_2_baseline(candidate_handoff, candidate_journal, baseline):
    """Profiles off: the candidate's records equal the programme-2 starting revisions' records byte for byte.

    The runners fix uuid4 and the process id (the only sources of difference), so no normalisation is applied to the files.
    Files compared: run record and result for each of the 4 handoff scenarios, and run record and result for the journal-mode
    route with every opt-in profile off, applied and held (4 files). 12 file pairs.
    """
    pairs = []
    for sc in HANDOFF_SCENARIOS:
        for name in ("run-record.json", "result.json"):
            pairs.append((baseline["handoff"] / sc / name, candidate_handoff / sc / name))
    for sc in ("applied", "held"):
        for name in ("run-record.json", "result.json"):
            pairs.append((baseline["journal"] / "off" / sc / name, candidate_journal / "off" / sc / name))
    assert len(pairs) == 12
    different = [str(b.relative_to(b.parents[2])) for b, c in pairs if b.read_bytes() != c.read_bytes()]
    section("default_path_byte_identity_vs_programme_2_baseline", {"file_pairs": len(pairs), "identical": len(pairs) - len(different),
                                                                  "different": different})
    assert different == [], f"default-path bytes changed on the candidate: {different}"


def test_atomic_default_path_with_the_key_off_is_byte_identical_between_runtime_d90a2cae_and_the_candidate(candidate_handoff, prior_runtime_handoff):
    """R2 (runtime fc034d14) added an opt-in operation key to the atomic route. With the key off (the default executor and the base
    `AtomicAuthorityEffectDestination`, which is what these four scenarios use), nothing may change: run record, result, and every row and
    the schema of the destination database are compared byte for byte between runtime d90a2cae (the revision before R2) and the candidate,
    same Control Plane, same inputs. The one masked value is the destination's wall-clock `failure_records_v1.created_at`.
    4 scenarios x 3 files = 12 pairs."""
    pairs = [(prior_runtime_handoff / sc / name, candidate_handoff / sc / name)
             for sc in HANDOFF_SCENARIOS for name in ("run-record.json", "result.json", "atomic-tables.json")]
    assert len(pairs) == 12
    different = [str(b.relative_to(b.parents[1])) for b, c in pairs if b.read_bytes() != c.read_bytes()]
    section("atomic_default_path_byte_identity_runtime_d90a2cae_vs_candidate", {"file_pairs": len(pairs), "identical": len(pairs) - len(different),
                                                                              "different": different})
    assert different == [], f"atomic default path (key off) changed between d90a2cae and the candidate: {different}"


def test_orchestrator_pins_versus_candidate_default_path_is_additive_only(candidate_handoff, pinned):
    """Report-only: what moving the orchestrator's control-plane and runtime pins would change on the DEFAULT path.

    Known and expected (control plane d489f85 and 2a17b2b, 2026-10-13 to 2026-10-15, before programme 2): the default run record gains
    `resolution_checks`, `input_time_floors`, and the (empty) lists `closeouts` and `refusals`. The runtime's denied-result
    `observation` changed from {} to null. Anything else is a finding.
    """
    changes: dict[str, dict] = {}
    for sc in HANDOFF_SCENARIOS:
        old, new = load(pinned / sc / "run-record.json"), load(candidate_handoff / sc / "run-record.json")
        removed, added = sorted(set(old) - set(new)), sorted(set(new) - set(old))
        shared_changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
        old_r, new_r = load(pinned / sc / "result.json"), load(candidate_handoff / sc / "result.json")
        result_changed = sorted(k for k in set(old_r) | set(new_r) if old_r.get(k) != new_r.get(k))
        changes[sc] = {"record_members_removed": removed, "record_members_added": added, "shared_members_changed": shared_changed,
                       "result_members_changed": result_changed}
        assert removed == [], f"{sc}: members vanished from the default record"
        assert set(added) <= {"resolution_checks", "input_time_floors", "closeouts", "refusals"}, f"{sc}: unexpected new default-path members {added}"
        for key in ("decisions", "attempts", "refusals"):
            assert [d.get("effect_id") for d in old.get(key, [])] == [d.get("effect_id") for d in new.get(key, [])], f"{sc}.{key} effect ids"
        assert old_r.get("decision") == new_r.get("decision")
    section("pin_move_default_path_delta", changes)


@pytest.mark.parametrize("profile_set", PROFILE_SETS)
def test_refund_journal_route_with_profile_set(candidate_journal, profile_set):
    """Applied and held, tenant-bound orchestrator inputs, profiles on and off. The legacy effect_id is unchanged by every profile."""
    off = load(candidate_journal / "off/applied/result.json")
    applied = load(candidate_journal / profile_set / "applied/result.json")
    assert applied["decision"] == "authorized"
    assert applied["first"]["status"] == "executed" and applied["again"]["status"] == "reconciled"
    assert len(applied["ledger_effect_ids"]) == 1
    assert applied["ledger_effect_ids"] == off["ledger_effect_ids"], "an opt-in profile changed the effect id"

    record = load(candidate_journal / profile_set / "applied/run-record.json")
    base = load(candidate_journal / "off/applied/run-record.json")
    assert set(record) - set(base) == EXPECTED_ADDED[profile_set]
    assert set(base) - set(record) == set()

    held = load(candidate_journal / profile_set / "held/result.json")
    assert held["decision"] == "hold" and held["ledger_effect_ids"] == []
    assert held["reasons"] == load(candidate_journal / "off/held/result.json")["reasons"]


def test_profile_off_record_carries_no_profile_member(candidate_journal):
    record = load(candidate_journal / "off/applied/run-record.json")
    assert not {"operations", "operation_renewals", "attempt_joins", "rule_revisions", "rule_revision_refusals", "age_extensions",
                "age_extension_refusals", "recovery_runs"} & set(record)
    section("profile_sets_run", {"sets": list(PROFILE_SETS), "scenarios_per_set": 2, "bundles": len(PROFILE_SETS) * 2})
