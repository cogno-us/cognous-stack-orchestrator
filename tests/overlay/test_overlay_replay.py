"""Replay and the Evidence Pack importer over the overlay's records (report only; Replay and pack are not pinned by this overlay).

Replay chooses its profile from a Control Plane revision LABEL supplied by the caller. The nearest label for the candidate Control
Plane is Replay's newest listed generation (P4, 26a7e659); under the candidate's own revision Replay refuses everything
('unsupported Control Plane revision'). All statements here are about these synthetic records on the named revisions.
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


def test_replay_refuses_the_candidate_revision_label(replay_probe):
    """Replay's supported set does not list any programme-2 Control Plane revision: labelled with the candidate's own revision every
    record is refused. (Replay's label is a claim by the caller, not derived from the record.)"""
    for name, r in replay_probe.items():
        label = next(k for k in r["replay_by_label"] if k.startswith(CANDIDATE_LABEL_PREFIX))
        assert r["replay_by_label"][label] == "ImportContractError: unsupported Control Plane revision", name


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
