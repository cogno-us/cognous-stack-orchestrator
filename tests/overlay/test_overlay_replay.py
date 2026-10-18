"""Replay and the Evidence Pack importer over the overlay's records (report only; Replay and pack are not pinned by this overlay).

Replay chooses its profile from a Control Plane revision LABEL supplied by the caller. The nearest label for the candidate Control
Plane used to be Replay's newest listed generation (P4, 26a7e659). Replay c8e665bd lists the candidate's own revision (6093aca7), so
the candidate label is accepted for journal-mode records and refused with a typed profile error for the orchestrator's atomic-route
records ('resolution journal missing'). All statements here are about these synthetic records on the named revisions.
"""
from __future__ import annotations

from conftest import section

P4 = "26a7e659"
CANDIDATE_LABEL_PREFIX = "candidate:"


def test_replay_and_pack_accept_the_default_journal_record_under_the_p4_label(replay_probe):
    r = replay_probe["off/applied"]
    assert P4 in r["accepted_under"]
    assert r["evidence_pack"] == {"outcome": "accepted", "freshness_block": False}, "default path: no freshness block (byte-identical when absent)"
    assert not r["retained"]["rule_revisions_rows"] and not r["retained"]["attempt_joins_rows"]


ATOMIC_ROUTE_RECORDS = ("candidate-handoff/applied", "candidate-handoff/held_no_grant")
JOURNAL_MODE_RECORDS = ("off/applied", "identity/applied", "freshness/applied", "rule_revision/applied", "full/applied")


def test_replay_candidate_revision_label_outcomes_are_exact(replay_probe):
    """Replay c8e665bd lists the programme-2 Control Plane revision, so its label is no longer refused as unsupported. Replaces the
    earlier assertion that every record was refused with 'unsupported Control Plane revision' (the stale P4 behaviour). The outcome
    is asserted exactly for EVERY record, in both directions:
      * the atomic-route records (no resolution journal) are refused with exactly
        'ImportContractError: typed refusal profile: resolution journal missing' and are not accepted under the candidate label;
      * every journal-mode record is accepted under the candidate label, and appears in accepted_under for it;
      * no record has any other outcome, and the 'unsupported Control Plane revision' refusal appears nowhere.
    (Replay's label is a claim by the caller, not derived from the record.)"""
    assert set(replay_probe) == set(ATOMIC_ROUTE_RECORDS) | set(JOURNAL_MODE_RECORDS), sorted(replay_probe)
    for name, r in replay_probe.items():
        label = next(k for k in r["replay_by_label"] if k.startswith(CANDIDATE_LABEL_PREFIX))
        outcome = r["replay_by_label"][label]
        assert "unsupported Control Plane revision" not in outcome, (name, outcome)
        if name in ATOMIC_ROUTE_RECORDS:
            assert outcome == "ImportContractError: typed refusal profile: resolution journal missing", (name, outcome)
            assert label not in r["accepted_under"], name
        else:
            assert outcome == "accepted", (name, outcome)
            assert label in r["accepted_under"], name


def test_orchestrator_atomic_route_records_are_not_p4_records(replay_probe):
    """The orchestrator's accepted route writes a default-path record without the resolution journal; Replay's journal-mode profiles
    refuse it ('resolution journal missing'); only the pre-journal labels accept it."""
    for name in ("candidate-handoff/applied", "candidate-handoff/held_no_grant"):
        r = replay_probe[name]
        assert P4 not in r["accepted_under"]
        assert "resolution journal missing" in r["replay_by_label"][P4]


def test_profile_on_records_replay_outcome_table(replay_probe):
    """Report-only: what Replay (P4 label) and the pack do with each profile's record. Every outcome must be either accepted or a typed
    ImportContractError; anything else (a crash, another exception type) fails as a new finding."""
    rows = {}
    for name in ("identity/applied", "freshness/applied", "rule_revision/applied", "full/applied"):
        r = replay_probe[name]
        p4 = r["replay_by_label"][P4]
        assert p4 == "accepted" or p4.startswith("ImportContractError: "), (name, p4)
        pack = r.get("evidence_pack", {}).get("outcome")
        assert pack in (None, "accepted") or pack.startswith("ImportContractError: "), (name, pack)
        rows[name] = {"replay_p4": p4, "retained": r.get("retained"), "replay_findings_under_p4": r.get("replay_findings_under_p4"),
                      "evidence_pack": r.get("evidence_pack")}
    section("replay_and_pack_profile_on", rows)
    section("replay_and_pack_default", {k: {"accepted_under_n_labels": len(v["accepted_under"]), "p4": v["replay_by_label"][P4],
                                            "evidence_pack": v.get("evidence_pack")} for k, v in replay_probe.items()
                                        if k in ("off/applied", "candidate-handoff/applied", "candidate-handoff/held_no_grant")})
