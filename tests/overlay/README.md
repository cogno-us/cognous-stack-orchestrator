# Candidate component overlay (opt-in, report only)

Synthetic integration scenarios that run the orchestrator's own inputs against **candidate** component revisions (Control Plane
main, Runtime main, the independent verifier, ODES, Replay, Evidence Pack) without touching what the default CI pins. Nothing here
runs on a pull request or push. It is started by hand through the
[workflow](../../.github/workflows/overlay-candidate-components.yml) (`workflow_dispatch`, inputs default to `main`) or locally.

**Claim boundary.** This is engineering evidence about synthetic records on named revisions. It selects no release (README claim 1),
grants nothing, authorizes no effect, and does not establish operational deployment assurance (claim 4; issue
[#30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30) stays **HOLD**). A passing run is not a qualification, and a
refusal by the verifier is a finding to report, never something the overlay loosens. Findings are collected in the
[gap report](../../development/programme-2-gap-report.md).

## What it does and does not change

- The orchestrator's pins (`.github/workflows/o*.yml`, the `*_PIN` constants in the harness) are not edited. The runners load the
  harness **source** in a subprocess and replace its three pin constants by the revisions actually checked out; the file on disk keeps
  the accepted pins (`test_orchestrator_pins_are_untouched_by_the_overlay` asserts it).
- Without the environment below every test is skipped, so a plain `pytest tests` is unchanged. `COGNOUS_OVERLAY_REQUIRE=1` (set by
  the workflow) turns a missing variable into a failure.
- No test uses the network. Runners fix `uuid4` and the process id so records compare byte for byte.

## Run locally

Python 3.11+, `pytest`, `pydantic>=2.12`, `cryptography>=43`. Check out the revisions anywhere and name them:

| Variable | Checkout |
|---|---|
| `COGNOUS_OVERLAY_ACTION_MANIFEST` | cognous-action-manifest at the orchestrator's pin (`8d1572d4`) |
| `COGNOUS_OVERLAY_CONTROL_PLANE`, `_RUNTIME` | the candidate Control Plane and Execution Runtime |
| `COGNOUS_OVERLAY_VERIFIER`, `_ODES` | cognous-open-control-stack-verifier; open-decision-evidence-standard (validators) |
| `COGNOUS_OVERLAY_REPLAY`, `_EVIDENCE_PACK` | Replay and Evidence Pack (probe only) |
| `COGNOUS_OVERLAY_BASELINE_CONTROL_PLANE`, `_RUNTIME` | optional: the programme-2 starting revisions (`5f5ae03f`, `10a11d03`) for the byte comparison |
| `COGNOUS_OVERLAY_PRIOR_RUNTIME` | optional: the runtime before the opt-in atomic operation key (`d90a2cae`), for the key-off byte comparison of the default atomic route |
| `COGNOUS_OVERLAY_PIN_CONTROL_PLANE`, `_RUNTIME` | optional: the orchestrator's own pins, for the report-only pin-move delta |
| `COGNOUS_OVERLAY_REPORT_DIR` | where `overlay-report.json` (denominators, outcomes) and the retained bundles are written |

```
python -m pytest -q -p no:cacheprovider tests/overlay
```

## Files

| File | Scenarios |
|---|---|
| `_handoff_runner.py` | The orchestrator's accepted route (Atomic claim) with its own harness: applied, held (no grant), lost acknowledgement then reconcile, duplicate dispatch |
| `_journal_runner.py` | Control Plane journal mode through the Runtime's Control Plane adapter, tenant-bound orchestrator inputs, profile sets `off`, `identity`, `freshness`, `rule_revision`, `full` |
| `_destination_runner.py` | Lost acknowledgement then late landing, the renewal race, and renewal during a lost acknowledgement or after late landing (F-5 probe), on the Runtime's delayed-commit and operation-identity destinations; on the atomic route, the default classes (key off) and the opt-in `operation_identity=True` executor with `OperationIdentityAtomicAuthorityEffectDestination` (F-5); what the atomic route can carry |
| `_assurance_runner.py` | Witness digest (drop and rewrite rejected, append not vouched for) and holder inventory (flagged class holds without one) |
| `_replay_runner.py` | Replay and Evidence Pack outcomes for the same records |
| `test_overlay_handoff.py` | Default path on candidates; byte identity against the programme-2 baseline; pin-move delta; profiles on and off |
| `test_overlay_verifier.py` | `cognous-verify` over the retained records; ODES validators over the report and the records; finding F-1 |
| `test_overlay_destinations.py`, `test_overlay_assurance.py`, `test_overlay_replay.py`, `test_overlay_acp_run.py` | as named |

A new scenario follows the same shape: a runner that writes a bundle (`run-record.json`, `proposal.json`, `manifest.json`,
`result.json`), a test that asserts only what the claim boundary allows, and a `section(...)` call so the denominator lands in the
report.
