# Programme 2 cross-component gap report

Status: engineering measurement, 2026-10-18. Synthetic records only. **Not** a qualification, **not** release evidence, and it changes
no pin: README claims 1 to 4 are unchanged and operational deployment assurance ([#30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30))
remains **HOLD**. Every number below comes from a run recorded in the overlay report; "ran" means this overlay or a command quoted
here was executed against the named revisions.

## What was measured, and against what

The orchestrator's accepted pins are older than the programme-2 work on the component mains. The opt-in [overlay](../tests/overlay/README.md)
runs the orchestrator's own inputs (pinned Action Manifest refund example, tenant-bound proposal) against candidate revisions without
editing any pin. Revisions under test:

| Component | Candidate (main) | Orchestrator's accepted pin | Programme-2 starting point |
|---|---|---|---|
| Control Plane | `128eaa5e` | `e66e5f16` | `5f5ae03f` |
| Execution Runtime | `d90a2cae` | `da9f5290` (O6 suites: `1b0a9e32`) | `10a11d03` |
| Independent verifier (`cognous-verify`) | `5ed1ffb` (earlier runs: `867402f3`, `07c2eb86`) | none | n/a |
| ODES validators | `7bc7903` (earlier runs: `56edb3f9`) | none | n/a |
| Replay | `d0e7b368` | `2069a0ba` | n/a |
| Evidence Pack | `fa7cd7e` | `87293cfc` | n/a |
| Action Manifest | `8d1572d4` (unchanged pin) | `8d1572d4` | n/a |

Result of the overlay at these revisions: **29 tests, 29 passed**, under Python 3.11 and 3.13, locally and in the dispatched workflow
(run [39091527071](https://github.com/cogno-us/cognous-stack-orchestrator/actions/runs/39091527071), workflow from commit `9273e6b7`, verifier input
`5ed1ffbaf52ce3c999f6574f13fe2e43bd5bf88f`, other inputs `main`, both Python versions green; the earlier run
[39090210798](https://github.com/cogno-us/cognous-stack-orchestrator/actions/runs/39090210798) was at verifier `07c2eb86`). Passing means the stated behaviour and the known-finding
patterns below were observed; it does not mean the findings are resolved. The verifier moved while this work ran (`867402f3`, then `07c2eb86`, then `5ed1ffb`) and the F-1 and F-2 outcomes changed with it: the overlay
fails on any refusal outside a named finding and now pins the exact abstentions, which is how those changes were noticed.

## Programme-2 pieces and what exercises them across components

| Piece (where it lives) | Exercised across components in the orchestrator's default CI | Overlay result |
|---|---|---|
| `rule_revision` profile (Control Plane #44) | No | Applied and held refund through the Runtime adapter: effect id unchanged, top-level member `rule_revisions` added (2 bundles). Replay accepts it only with its rows dropped (F-4) |
| Operation identity (Control Plane #45, Runtime #109) | No | Renewal race with the orchestrator's inputs: profile off, **2 effects** for one operation; profile on, **1 effect**, first attempt refused `operation_already_committed`, 2 attempt joins (F-5 for the atomic route) |
| Freshness / clocks / reaper (Control Plane #47) | No | Profile on adds clock members inside existing rows, no new top-level list; applied and held hold as with the profile off. Replay and the verifier refuse these records (F-3, F-4) |
| Witness digest (Control Plane #49) | No | 3 retained records (atomic route, journal, journal with all profiles): untouched verifies; appended row reported unwitnessed, not intact; dropped row `witness_ledger_shrunk`; rewritten row `witness_ledger_head_mismatch` (3 of 3 each). Atomic-route record covers only `decisions` and `resolution_checks` (F-2) |
| Holder inventory (Control Plane #49) | No | Flagged action class without an inventory: `hold` / `holder_inventory_missing`, 0 ledger rows; with an inventory enumerating a holder: authorized, applied, 1 ledger row, effect id unchanged |
| `acp run` (Control Plane #46) | No | The component's own `authorized` and `held` examples: `acp run` exits 0 and 1, `acp validate-run` exits 0 on both; `cognous-verify` with the command's own ledger: 30 of 30 and 17 of 17 checks confirmed (exit 0); ODES journal validator 0 violations on both |
| Delayed-commit destination (Runtime #110) | No | Lost acknowledgement then late landing, with and without operation identity: first attempt `unknown`, ledger empty while absent, retry denied (no replacement attempt), 3 `observed_absent` reconciliations all `retry_eligible: false`, no `safe_to_retry` row, one effect after landing, reconcile then `applied` |
| Replay retention of profile members (P3) | No | Not on Replay main (`d0e7b368`): F-4 |
| Evidence Pack freshness block (#39) | No | Absent on the default record (byte-identical when absent, as designed); not reachable end to end because Replay refuses freshness records (F-4) |
| Independent verifier over orchestrator records | No | See "Verifier over the orchestrator's records" |
| ODES contracts over orchestrator records | No | See "ODES contracts" |

Default path, profiles off: the candidate's records equal the programme-2 starting revisions' records **byte for byte, 12 of 12 file
pairs** (run record and result for the four atomic-route scenarios, and for the journal-mode route applied and held). The runners fix
`uuid4` and the process id, the only sources of difference; no normalisation is applied to the files.

## Verifier over the orchestrator's records

Records: 4 atomic-route scenarios (applied, held, lost acknowledgement then reconcile, duplicate dispatch), 2 journal-mode default
records (applied, held), 8 profile-on records, 2 delayed-commit default records. Each report was validated with the **ODES**
`verification-report` validator (not the verifier's own copy) and its denominators checked to add up (checks = confirmed + could not check + refuted). The
verifier is run as a subprocess and imports nothing from the stack.

- **Default-path records, no ledger (6 records, verifier `5ed1ffb`; the same counts at `07c2eb86`):** 0 refuted. 26, 24, 26, 26 checks for the four atomic-route
  records (19, 17, 19, 19 confirmed, 7 could not check each) and 32 and 28 for the journal-mode pair (25 and 21 confirmed, 7 could not
  check); exit 3 (abstain) because no ledger was supplied. At `867402f3` the same records gave 24/22/24/24 and 30/26 checks, 0 refuted.
- **Atomic-route records with a ledger projected from the runtime SQLite rows (4 records):** 3 abstain on one check, 0 refuted; see F-2. The projection is the
  orchestrator's own, field for field; the verifier documents the Control Plane's local destination state as its ledger.
- **Adapter-route records with a projected ledger (4 records, 8 runs with and without the `operation_digest` member):** projection A abstains on one check (3 records), projection B is refused at `ledger_shape` (3 records), the held record is accepted in both; see F-1.
- **Profile-on records (8 of 8):** all refused at `v1.structure` (codes `schema_violation`, `undeclared_member`; `undeclared_member` only for `rule_revision`), 24 of
  the 26 checks could not be made (the delegated groups report `earlier_rules_refuted`). See F-3.

A record the verifier accepts is internally consistent and recomputes. It does not show the decision was right, the destination acted, or who
produced the record. Observed bound, not a defect: the legacy renewal race (two effects for one operation) is not refused by any
check about operations, because the verifier cannot know an operation id exists; its only refusals on those records are F-1.

## ODES contracts

- `control-plane-journal` over the raw records: **6 of 6 default-path records conform; 0 of 8 profile-on records** (refused with `schema_violation` /
  `undeclared_member` only; no other code). This is the divergence recorded in ODES decisions 21 to 22 and stream J1; the overlay shows
  it with orchestrator-shaped, tenant-bound records.
- `operation-identity` sidecar projected from the record (2 records) validates with the journal as context. With all three profiles
  on, the identity rows also carry freshness' `evaluated_at`; the identity contract is closed, so the projection drops that member
  (the freshness contract carries it in `clock_rows`). Composition of the profiles in one record therefore needs a projection step
  that no tool outside the ODES fixture builders performs.
- `rule-revision` and `freshness-clocks` sidecars were **not** projected here: the only projection code is in the ODES fixture
  build scripts.

## Findings (recorded, not fixed here)

Each is reproducible with the overlay at the revisions above. None is a claim that a component is wrong in isolation; they are places
where two components do not yet meet.

- **F-1 (verifier / runtime, adapter route; narrowed by verifier PR #9, `5ed1ffb`).** The runtime's destination observation carries `operation_digest`
  inside `destination_state`; the verifier's ledger row shape is closed and has no such member. Ran at `5ed1ffb`, 4 records, 8 runs:
  - Projection A (ledger row omits the member): the 3 records with an effect now **abstain** (exit 3, 0 refutations): `v4.ledger.observations-agree` is
    `could_not_check`, reason `destination_state_has_members_outside_ledger_row` (1 check abstained, 31 or 32 of 32 or 33 confirmed). At `07c2eb86` the same 3 were refused
    (`observation_differs_from_ledger_row`).
  - Projection B (ledger row keeps the member): the same 3 are still **refused** at `v1.structure.ledger` / `ledger_shape` (exit 1; 25 confirmed, 7 could not check,
    1 refuted), by design, because the ledger row shape is closed.
  - The held record (empty ledger) is accepted in both projections (22 of 22 confirmed, exit 0).
  So the verifier no longer refuses the orchestrator's honest projection, but it cannot compare the runtime's observation with the ledger either: the
  members the runtime adds to `destination_state` have no place in the verifier's ledger model. Not seen with the Control Plane's own local destination,
  whose observation has the seven declared members.
- **F-2 (route / verifier; narrowed by verifier PR #9, `5ed1ffb`).** On the orchestrator's accepted route (Atomic claim) the Control Plane record has **no attempt row**; the
  attempt lives only in the runtime SQLite destination. History: accepted at `867402f3` (23, 17, 23, 23 of as many checks confirmed), refused from `2597196` on
  `ledger_row_without_attempt` (3 of 4, `07c2eb86`), and at `5ed1ffb` **abstained**: for the 3 records with an effect, `v4.ledger.rows-agree-with-attempts` is
  `could_not_check`, reason `attempt_rows_not_in_record`, 0 refutations (exit 3; 24 of 25 checks confirmed); the held record is fully confirmed (18 of 18, exit 0).
  The abstention is the honest outcome: the record cannot show an attempt for the ledger row. The same root shows in the witness: the atomic-route record gives the witness
  only `decisions` and `resolution_checks` to cover.
- **F-3 (ODES journal / verifier, expected).** The verifier refuses every profile-on record at `v1.structure` because its vendored
  journal contract declares none of the profile members (8 of 8). Until the journal contract declares them (ODES J1), the verifier cannot
  check any record produced with an opt-in profile, so independent verification of programme-2 behaviour is not available yet.
- **F-4 (Replay / Evidence Pack).** Replay selects its profile from a Control Plane revision *label* the caller supplies and lists
  no programme-2 revision: labelled with `128eaa5e`, all 7 probed records are refused (`unsupported Control Plane revision`). Under its newest listed
  generation (P4, `26a7e659`): the default journal record is accepted (and the Evidence Pack accepts the bundle, with no freshness block);
  `identity` is refused (`runtime authority fields unsupported`); `freshness` and `full` are refused (`attempts[0] has unsupported member(s):
  evaluated_at,recorded_at`); `rule_revision` is accepted but its `rule_revisions` rows are **not retained** (warning `B001:rule_revisions`), and the Evidence
  Pack then refuses that bundle (`retained Replay import_reports differs from accepted reconstruction`). The orchestrator's atomic-route
  records are refused under P4 (`resolution journal missing`) and accepted only under pre-journal labels. So the freshness block (#39) cannot be reached end to
  end and P3 (retention of profile members) is not on Replay main.
- **F-5 (runtime route; adapter-route probe added, atomic route still unprobed).** The opt-in operation-identity and delayed-commit destinations are reachable only through the Control Plane adapter
  route (`PinnedControlPlaneExecutor`). The orchestrator's accepted route (`AtomicLocalControlPlaneExecutor` with
  `AtomicAuthorityEffectDestination`) has no operation-id parameter, is not an operation-identity or delayed-commit class, and its lost
  acknowledgement uses `simulate="lost_ack"` instead. Probed on the adapter route with the runtime's own destination classes (synthetic, no network), two new overlay tests
  beyond the existing renewal race: (a) r1's commit deferred (acknowledgement lost), grant renewed, r2 attempted while r1 is outstanding, r1 lands late: **profile off, 2 effects** for
  one operation; **operation identity on, 1 effect** (r2 commits; r1's late landing is refused by the destination guard, `PermissionError: operation_already_committed`). The control plane does
  not hold r2 while r1 is outstanding; the destination guard is the only barrier. (b) r1 lands late, then the grant is renewed and the operation decided again: **profile off, 2 effects**;
  **identity on, 1 effect** (r2 fails `operation_already_committed`). No double commit with the identity profile on, so no new finding; the profile-off double commit is the legacy gap the profile exists
  to close. Still **not run** on the orchestrator's atomic route (whether the renewal race double-commits there, with the per-grant cap possibly masking it, is unknown).
- **F-6 (runtime pin move, orchestrator side; fixed in the orchestrator, no pin moved).** Runtime `2ee2e525` ("Move cross-component tests and harnesses to cognous-stack-qualification") removed
  `tests/test_local_authority_effect.py`, `tests/test_refund_intent.py`, `tests/test_safe_executor.py` and `tests/test_w2_stop_recovery.py` (they now live under
  `suites/cognous-execution-runtime/tests/` in `cognous-stack-qualification`). `tests/scenarios/customer_refunds/live_components/runtime/test_actual_runtime.py` imported
  helpers from the first, second and fourth, so with the runtime pin moved it failed at collection (`ModuleNotFoundError: No module named 'test_local_authority_effect'`).
  Fix, inside the orchestrator only: the test module still imports the runtime's own helper modules when they exist (so the pinned default `da9f5290` is unchanged: 8 passed before
  and after), and falls back to copies vendored from that pin under `vendored_runtime_helpers/` (helper functions only, verbatim, source file sha256 and the two rewritten imports
  recorded in each header). Ran against runtime `d90a2cae` and Control Plane `128eaa5e`: collection succeeds and 7 of 8 pass; the 8th is
  `test_exact_upstream_revisions_are_exercised`, which asserts the old SHA constants and belongs to the coordinator's pin batch. No runtime change is needed.
- **F-7 (default path between the accepted pin and main, additive, before programme 2).** Control Plane `d489f85` and `2a17b2b` (2026-10-13 to 15): default
  run records gain `resolution_checks`, `input_time_floors` and the empty lists `closeouts`, `refusals`; decisions gain `resolution_inputs`,
  `time_source`, `operation_horizon`; the runtime's denied-result `observation` changed from `{}` to `null`. Effect ids and outcomes are
  identical across all 4 scenarios (ran). Not caused by an opt-in profile, and absent between the programme-2 starting point and main.

## Pin moves this would need (none made)

The coordinator's end batch owns pin moves; this work edited no pin, no refreeze entry, no profile generation. To exercise programme 2
in the orchestrator's **default** CI:

| Pin | Where it is held | Move to | Notes |
|---|---|---|---|
| Control Plane `e66e5f16` | `o5-d-a`, `o5-d-b`, `o5-d-combined`, `o5-e-a`, `o5-e-combined`, `o6-q2`, `o6-q4` workflows and the `CONTROL_PLANE_PIN` constants in `connected_handoff.py`, `control/qualification.py`, `live_components/control/upstream_control.py`, `trace_contract.py`, `source_mapping_v1.json` | at least `3f6a7668` for freshness, `128eaa5e` for witness and holder inventory, `83b49b5e` for `acp run`, `9d00f38` for operation identity, `87f0233` for rule revision | The harness is unchanged by the move (below) |
| Execution Runtime `da9f5290` and `1b0a9e32` | `o5-d-b`, `o5-d-combined`, `o5-e-a`, `o5-e-combined`, `o6-q2`, `o6-q3`, `o6-q4`, `o6-q6`; `COGNOUS_O6_Q2_RUNTIME_CANDIDATE` and the `1b0a9e32` assertions in the O6 tests | `d90a2cae` (operation identity `63a7c0fe`, delayed commit `6bfb77ee`, adapter forwarding `d90a2cae`) | `o5-d-b` no longer blocked (F-6): its two SHA constants and the workflow ref move with the pin |
| Replay `2069a0ba` | `o5-d-c`, `o5-d-combined`, `o5-e-b`, `o5-e-combined`, `o6-q2`, `qualification.py` constants | not yet useful | Replay lists no programme-2 revision and drops profile members (F-4) |
| Evidence Pack `87293cfc` | same workflows and constants | `fa7cd7e` once Replay retains the members | Freshness block cannot be reached before then |
| Verifier, ODES validators | not pinned by the orchestrator | new pins if they are to run in default CI | Candidate pins would be `07c2eb86` and `56edb3f9` |

Readiness of the orchestrator's **existing** suites if those pins were moved (ran in a disposable copy with the pin constants substituted by the
candidate revisions; no file in this repository was edited):

| Suite | Result |
|---|---|
| `o5-d-a` upstream control | 12 passed |
| `o5-e-a` connected handoff | 9 passed |
| `o5-d-c` upstream evidence (candidate Replay and Evidence Pack) | 7 passed |
| `o5-e-b` connected Replay (candidate Replay and Evidence Pack) | 12 passed |
| `o6-q3` three-profile trace | 2 passed |
| `o6-q4` authenticated fence | 4 passed |
| `o6-q6` reconciliation | 23 passed |
| `o5-d-b` upstream runtime | 7 passed, 1 failed (collection fixed, F-6; the failure is the exact-SHA assertion that moves with the pin) |

Not run: `o5-d-combined`, `o5-e-combined` (composition of the above), `o6-q2`, `o6-q5` (needs the hub root), `recovery-resolution-inspection`
(its own pins).

## How to reproduce

`tests/overlay/README.md` lists the variables. In CI: dispatch [Candidate component overlay](../.github/workflows/overlay-candidate-components.yml) with the
refs to test (defaults: `main`). The workflow has no pull-request or push trigger, edits no pin, and uploads `overlay-report.json`
(denominators, outcomes, revisions) as an artifact. It stays a report: a failure means a refusal outside the findings above.
