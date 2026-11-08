# Refund disposition library (F1)

**DEVELOPMENT ONLY / SYNTHETIC / NONPRODUCTION / NON-AUTHORIZING / builder-lineage.** Developer-tested: a local run only (the run record is given in the PR description, not in this repository; no CI job runs these tests). Not independently qualified, not
certified, not production-ready. Contract `refund-disposition/0.1.0-dev`. Plan: Hub #281 (Amendment 0.5, VNext-F); decision packet: Hub #273 (F0).

One in-process Python library call that composes the already-demonstrated G3 native path for one synthetic refund and returns a structured
disposition. It adds no CLI, service, orchestration framework, policy evaluator or authority engine.

```python
from orchestration.adapters.refund_disposition import (AuthorityFacts, DispositionRequest, RefundProposal, SyntheticEnvironment,
                                                       dispose_refund, reconcile_refund)
result = dispose_refund(DispositionRequest(proposal=..., authority=..., correlation_id="case-1", evaluation_time=<tz-aware datetime>,
                                           environment=SyntheticEnvironment(stack_root=..., state_dir=...)))
```

## Ownership (unchanged)
Control Plane (CP) decides authorization. Runtime executes permitted effects. Replay reconstructs evidence. IG supplies the synthetic
authority lineage. This adapter only composes and reports; it never decides, retries, or upgrades an outcome.

## Flow
IG root-lineage resolver -> CP `decide()` (`authorized` or `hold`) -> **only if authorized** the host mirrors the grant into the destination and
the Runtime `PinnedControlPlaneExecutor.execute` runs exactly once into synthetic local SQLite -> Runtime export -> Replay
`import_bounded_workflow` (CP revision `484fdbd2`, Replay `7eb7d76e`). A hold stops before the Runtime, before any grant mirror is written, and before the SQLite destination is created (`decide()` only reads the destination's declared capability).
Excluded: Pack, Verifier, Attestation, Registry, ODES, GAX, CDC, ISS.

## Request
`DispositionRequest(proposal: RefundProposal, authority: AuthorityFacts, correlation_id, evaluation_time, environment)`
- `RefundProposal`: tenant_id, customer_id, refund_reason, amount, unit (default USD), actor, principal. The action, adapter, permission and
  requirement identities are fixed constants of this synthetic profile.
- `AuthorityFacts`: authority_id, IG root-lineage document, IG synthetic facts document. Passed to the pinned IG resolver unevaluated. The
  CP-native two-pass preparation (enumerate gate inputs, then bind commitments) is performed exactly as in G2/G3.
- `evaluation_time`: explicit, timezone-aware; no default clock is invented (CA05).
- `environment`: `stack_root` (the pinned checkouts) and `state_dir` (caller-owned; holds the destination SQLite, the CP run record and evidence
  files; persists across calls; never deleted by the adapter).

## Result: `DispositionResult`
`disposition` is one of `executed | held | denied | refused | unknown | failed`, plus:
- `native` facts verbatim: CP result and reasons, decision id, effect id, Runtime status/error, acknowledged, newly_executed, observed_state.
- `runtime_invoked` / `runtime_invocations`: the adapter's own count of attempts at its single Runtime call site, incremented before the call (self-reported; "attempted", not proof of effect). The tests measure independently with counters on the native executor and destination.
- `evidence`: `source` references (CP run-record snapshot, Runtime export) and a `replay` reference. Each is `{kind, path, sha256, detail}`;
  files are content-addressed under `state_dir/evidence/<correlation_id>/`. `replay_state` is `imported | not_run | import_failed`. A Replay
  problem is reported there and never changes the effect disposition.
- `refusal` (code, reason, source) and `error`; `next_step`; `cleanup` (scratch workspace disposal report); `mode` (`dispose | reconcile`).
- `labels`: `synthetic_authority=true`, `authenticated=false`, `evidence_basis=producer_reported`, `nonproduction=true`,
  `non_authorizing=true`, `retry_permission="not_established"`, and a `not_verified` list. These are present on every result.
- `effect_absence_established` is always `false`.

| Native outcome | disposition | next_step |
|---|---|---|
| request/stack refused before any native call | `refused` | `correct_request` (stack problems: `operator_inspection_no_retry_established`) |
| CP `hold` | `held` | `resolve_authority_hold` |
| authorized, but an earlier attempt for the same effect is still `attempted`/`unknown`/`partial` in the retained CP record | `refused` (`prior_uncertain_dispatch`; Runtime not entered) | `reconcile_read_only` |
| Runtime `denied` | `denied` | `correct_request_or_runtime_policy` |
| Runtime `executed` (acknowledged, newly executed, observed applied) | `executed` | `none` |
| Runtime `reconciled`/`observed` with observed state `applied` (e.g. an idempotent repeat) | `executed` (`newly_executed=false`) | `none` |
| Runtime `unknown`, `partial`, observed `absent`/`unknown`, any unmapped status, or any `Exception` once the Runtime has been entered | `unknown` | `reconcile_read_only` |
| Runtime `failed`, or an adapter error before dispatch | `failed` | `operator_inspection_no_retry_established` |

Uncertain execution is never retried by the adapter, and no result grants a retry. `reconcile_refund(request)` (a second public function, needed because check C requires a read-only reconciliation) is the permitted
read-only next step for `unknown`: it reads the retained CP decision and observes the bound destination through the Runtime's
`observe_historical`. It dispatches nothing, renews no authority and writes no effect or attempt rows; it refuses if no destination database exists
(it never creates one). "Effect-free" is the accurate word, not "read-only": the native destination constructor runs idempotent schema-ensure statements
(`CREATE TABLE IF NOT EXISTS`, WAL) on an existing database, and the CP record store takes its lock sidecar.

## Idempotency and repeats
A caller-initiated repeat is allowed when the earlier attempt was acknowledged; it is **refused** (not re-dispatched) when the earlier attempt for the same
effect is still uncertain, because absence of evidence never grants a retry. Repeats against one correlation id append to one CP run record.

Known conservative consequence (read from the CP source, not exercised by a test): after a lost acknowledgment that the Runtime re-observes as applied
(native `reconciled`, mapped to `executed` with `acknowledged=false`), the CP attempt stays `unknown` (its closeout is a separate record), so a later
caller-initiated `dispose_refund` for the same effect is refused as `prior_uncertain_dispatch`. This fails closed and never double-executes; Architect-approved for F1: the refusal is preserved, and a read-only reconciliation (`reconcile_refund`) grants no retry.

The effect id is derived natively from the proposal commitment, grant id, grant revision and tenant generation. A repeat of the same request
against the same `state_dir` finds the existing applied row and does not insert a second one (native status `reconciled`,
`newly_executed=false`). This holds **per destination database only**. There is no cross-database exactly-once claim.

## Test-only fault injection (not part of the request contract)
The request has no fault field and `dispose_refund(request)` / `reconcile_refund(request)` take nothing else. Check C needs a post-commit lost acknowledgment, so
`dispose.py` has one PRIVATE entry point, `_dispose_refund(request, _TestInjection)`, that is not exported and not reachable through the public call. The injection
itself lives in the test tree (`tests/adapters/refund_disposition/_fault_injection.py`): a subclass of the pinned `EffectiveGrantDestination` plus the native
`simulate="lost_ack"` argument. After the durable commit the native path withholds the acknowledgment and the subclass makes the destination read path unavailable
until the call returns, so the native result is genuinely `unknown` while one row is committed. No Runtime source or semantics change. Check C is therefore a lost
acknowledgment **plus** an unavailable observation. A lost acknowledgment alone is different: the native Runtime re-observes the applied row and reports
`reconciled`, which this adapter maps to `executed` with `acknowledged=false` and `runtime_error` set. That mapping is a native validated observation, not an adapter
assumption, and is Architect-approved for F1: `acknowledged=false` stays visible in `native`.
The Runtime export and Replay import run after the simulated outage ends, so a Replay bundle for an `unknown` result may read the committed row and report
`reconstruction_complete`; that does **not** resolve the `unknown` (only `reconcile_refund` or an operator can, and the result stays producer-reported).

## Workspace and cleanup
Each call allocates one unique scratch directory (CP baseline pass files only) and removes exactly that path. A symlink in its place is refused,
a failed removal or surviving path is reported in `result.cleanup`, and nothing else is deleted. `state_dir` and the destination are caller-owned.
Calls are serialized by a process lock; native modules and the CP clock are process-global (one stack root per process).

## Installation recipe (exact)
Requirements: Linux (CP `BoundedRecordStore` needs local flock), bash, Python >= 3.11 (developed on 3.13; commands below use `python3`), `git`, `pydantic` 2.x, `cryptography`,
`jsonschema` (IG lineage harness). Dependency versions are not locked here; this PR adds no dependency and no requirements file.

Assemble a stack root with these four checkouts at exactly these commits, each with a clean tracked tree (see `source_pins.json`):

| directory | repository | commit |
|---|---|---|
| `control_plane` | cogno-us/cognous-control-plane | `484fdbd297235dd24148ddb0703f2055a31eabff` |
| `runtime` | cogno-us/cognous-execution-runtime | `f7a55e2a8494801e49193f9f46935f0a971c248d` |
| `replay` | cogno-us/cognous-replay-bundle | `7eb7d76eda10ca1ff997bb86853e903e57da625c` |
| `institutional_governance` | cogno-us/cognous-institutional-governance | `1ebe85be4cfe9e221ebd2618120687eb0b325d24` |

```bash
export STACK=/path/to/new/stack-root   # created by the clones below
for pair in control_plane:cognous-control-plane:484fdbd297235dd24148ddb0703f2055a31eabff \
            runtime:cognous-execution-runtime:f7a55e2a8494801e49193f9f46935f0a971c248d \
            replay:cognous-replay-bundle:7eb7d76eda10ca1ff997bb86853e903e57da625c \
            institutional_governance:cognous-institutional-governance:1ebe85be4cfe9e221ebd2618120687eb0b325d24; do
  IFS=: read dir repo sha <<<"$pair"
  git clone "https://github.com/cogno-us/$repo.git" "$STACK/$dir" && git -C "$STACK/$dir" checkout --detach "$sha"
done
```
Replay `7eb7d76e` compatibility: Replay is **not pip-installed**. The library imports it from `$STACK/replay/src` after verifying the pin, and
refuses a Replay lacking the tenant-binding correction (`_validate_operation_tenant`). Pack is not used by F1, so Pack's `replay` extra
(which names Replay `40012b8c`) is irrelevant and must not be installed alongside. The library verifies HEAD == pin and a clean tracked tree on
every call, imports only after that, and checks each imported module lives inside its pinned checkout. The nine-component G3 tuple is kept in
`source_pins.json` (equal to `tests/manual_contract/g3_refund/source_manifest.json`); the five components F1 does not import are not checked.

Run the developer tests (from the repository root):
```bash
python3 -m unittest discover -s tests/adapters/refund_disposition -p 'test_contract.py' -v                      # no stack needed
G3_STACK_ROOT="$STACK" F1_REQUIRE=1 python3 -m unittest discover -s tests/adapters/refund_disposition -p 'test_f1_checks.py' -v
```
`F1_REQUIRE=1` turns a missing stack into a failure (a skip is not a pass).

## Developer checks and frozen oracles
`ORACLES.md` was committed (d4e6eb6) before the adapter existed. `tests/adapters/refund_disposition/test_f1_boundary.py` adds four boundary tests (post-dispatch adapter fault -> `unknown`; refusal of a re-dispatch after `unknown`; reconcile creates nothing; hold creates no database). They were added after independent code review and are not part of the frozen oracles.
`tests/adapters/refund_disposition/test_f1_checks.py` exercises them (the PR description lists where assertions differ from the oracle text):
A authorized + idempotent repeat; B revoked authority with measured Runtime noninvocation; C post-commit lost acknowledgment -> `unknown`, no retry,
read-only reconciliation preserves observed state. Independent measurements use a read-only SQLite connection and call counters on the native
`PinnedControlPlaneExecutor.execute` and `DurableRefundDestination.commit`.

## CI scope declaration
This PR touches only `orchestration/adapters/refund_disposition/**` and `tests/adapters/refund_disposition/**`; no workflow is added or changed.
Existing workflows whose path filters match (`o4-readonly`, `o4b-producer-boundary`, `o4c-combined-qualification`, `o4d-combined-qualification`)
run their own fixed test roots and do **not** collect these tests. The F1 tests were run locally against an assembled pinned stack; that local
run is the only basis for the label "developer-tested". No CI job exercises them (activating one is out of scope).

## Deviations from defaults, named
- `stack.py` runs `git` via `subprocess` to verify pins and prepends the verified checkouts to `sys.path` (process-global); this is the same mechanism as the G3 harness and the IG adapter.
- `reconcile_refund` is a second public function. `_dispose_refund` / `_TestInjection` are private test hooks (underscore-named, unexported, test-only use).

## Limitations
- Authority is a synthetic fixture decision (resolver `authenticated=false`; identity/mandate flags are fixture assertions). Not institutional authority.
- The SQLite write is real and local but **producer-reported**; the Runtime `repository_revision` in its export is caller-asserted.
- The grant mirror (`effective_grants_v1`) is written by the adapter acting as the trusted host after CP authorizes; it is not a new authority and
  is never written on a hold. A grant later revoked in IG is not removed from an existing destination database by this library.
- Replay `bundle_id`/`generated_at` are nondeterministic, so each call writes a new content-addressed Replay file.
- Repeated calls with one correlation id append to one CP run record; the evidence references are point-in-time snapshots.
- No Verifier, Pack, Attestation or Registry; no independent verification of the effect. Historical Q1/Q2/Q3/Q5 findings are not reclassified.
- Single process, single stack root, Linux only; no real payment, network or production effect.

## Rollback
Delete `orchestration/adapters/refund_disposition/` and `tests/adapters/refund_disposition/`. Nothing else changes: no component repository, source
lock, workflow, G3 evidence or historical record is modified. Caller-owned `state_dir` contents are the caller's to remove.
