"""Read-only O6 candidate admission. Never authorizes a release or effects."""
from __future__ import annotations
import argparse
import copy
import json
import re
import subprocess
from pathlib import Path

HUB_SHA = "2a23a2fbb3f5469872170c07a11b57656c6c3d2f"
SELECTED = {
    "moltbot_safe": "c3c3ee7188b9367cf70b08074b9c40a5c70c94ac",
    "gax_imx_transport": "a1cbc7b28f702283b0e4f3192bb43e4a9e618ebf",
    "bitrep": "5b5077dafde232a7801cb425c4efddcffb468723",
}
CANDIDATE = {
    "moltbot_safe": "1b0a9e32d010797711004ae612051a277b07912a",
    "gax_imx_transport": "814927dac65a2078d5efee6bbf07c46091844822",
    "bitrep": "5786b91696ffa276650c4f7b424c9662ebf96fac",
}
EVIDENCE = {
    "o6_q2": ("2a7def42914de12f04d34bec8ec00d0a304bdd2e", 38046644074),
    "o6_q3": ("7a892ad78d741a8b3746c3b71dd1531ea9a9bc1e", 38061972573),
    "o6_q4": ("eb866109a42739919b8d345d523a4bf6438a0ca1", 38062399523),
}
ISSUE = "https://github.com/cogno-us/cognous-stack-orchestrator/issues/30"
SHA = re.compile(r"^[a-f0-9]{40}$")


class CandidateInvalid(ValueError):
    pass


def _ensure(condition: bool, reason: str) -> None:
    if not condition:
        raise CandidateInvalid(reason)


def check(candidate: dict, hub_lock: dict, hub_head: str) -> dict:
    """Validate exact evidence and enforce permanent HOLD (no promotion API)."""
    _ensure(hub_head == HUB_SHA, "hub_sha_mismatch")
    _ensure(candidate.get("profile") == "cognous-o6-release-candidate-admission/1", "profile_mismatch")
    _ensure(candidate.get("hub_repository") == "cogno-us/cognous-open-control-stack", "hub_repository_mismatch")
    _ensure(candidate.get("hub_source_sha") == HUB_SHA, "hub_manifest_sha_mismatch")
    _ensure(hub_lock.get("lock_version") == "1.0", "hub_lock_version_mismatch")
    _ensure(hub_lock.get("qualification_status") == "accepted", "selected_release_unaccepted")
    components = hub_lock.get("components")
    _ensure(isinstance(components, dict), "hub_components_missing")
    _ensure(candidate.get("selected") == SELECTED, "selected_manifest_mismatch")
    _ensure(candidate.get("candidate") == CANDIDATE, "candidate_pin_mismatch")
    for key, expected in SELECTED.items():
        _ensure(SHA.fullmatch(expected) is not None, "invalid_sha")
        actual = components.get(key, {})
        _ensure(isinstance(actual, dict), "selected_component_missing")
        actual_sha = actual.get("accepted_sha") if key == "moltbot_safe" else actual.get("sha")
        _ensure(actual_sha == expected, f"hub_selected_pin_mismatch:{key}")
        if key == "moltbot_safe":
            _ensure(actual.get("core_interop_sha") == expected, "hub_core_interop_drift")
    for key in SELECTED:
        _ensure(CANDIDATE[key] != SELECTED[key], "candidate_not_distinct")
    evidence = candidate.get("engineering_evidence")
    _ensure(isinstance(evidence, dict) and set(evidence) == set(EVIDENCE), "evidence_set_mismatch")
    for label, (commit, run_id) in EVIDENCE.items():
        _ensure(evidence[label] == {"orchestrator_merge": commit, "run_id": run_id},
                f"evidence_mismatch:{label}")
    _ensure(candidate.get("intent") == "read_only_candidate_evidence", "unexpected_intent")
    _ensure(candidate.get("effects") == "disabled", "effects_must_remain_disabled")
    _ensure(candidate.get("release_selection") == "unchanged", "release_selection_must_remain_unchanged")
    trust = candidate.get("operational_trust")
    _ensure(isinstance(trust, dict), "operator_trust_missing")
    _ensure(trust.get("issue_url") == ISSUE, "operator_trust_reference_mismatch")
    _ensure(trust.get("state") == "not_established", "unsupported_operational_trust_claim")
    _ensure(trust.get("independent_operator_evidence") is None, "unverified_operator_evidence")
    return {
        "status": "hold",
        "release_admission": "not_authorized",
        "selection": "unchanged",
        "effects": "disabled",
        "reason": "operational_trust_not_established",
        "engineering_scope": "synthetic_exact_source_tests_only",
        "candidate_revisions": copy.deepcopy(CANDIDATE),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--hub-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        actual = subprocess.check_output(
            ["git", "-C", str(args.hub_root), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.STDOUT,
        ).strip()
        candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
        lock = json.loads((args.hub_root / "component-lock.json").read_text(encoding="utf-8"))
        result = check(candidate, lock, actual)
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "hold", "release_admission": "not_authorized",
                          "effects": "disabled", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
