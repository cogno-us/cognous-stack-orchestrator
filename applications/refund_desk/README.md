# Refund Desk (F3)

**DEVELOPMENT ONLY / SYNTHETIC / NONPRODUCTION / NON-AUTHORIZING.** Contract `refund-desk/0.1.0-dev`. Developer-tested: a local run only (builder-lineage, CA04); the exact-head run record is in the PR description. Not independently qualified, not certified, not production-ready. Frozen expectations: [CONTRACT_AND_EXPECTATIONS.md](CONTRACT_AND_EXPECTATIONS.md). Pins: [SOURCES.json](SOURCES.json) (not a source lock).

## What it is
A tiny CLI business application for one synthetic refund. It consumes only the public F1 library (`dispose_refund`, `reconcile_refund` from `orchestration.adapters.refund_disposition`, contract `refund-disposition/0.1.0-dev`) and presents the native disposition as one JSON object. The destination is synthetic local SQLite only.

## No duplicated native logic
The application imports only the standard library and the F1 package-level public names. It does not import F1 submodules or private names, nor any Control Plane, Runtime, Replay or IG module. It does not authorize, execute, retry or reconstruct anything, contains no fault injection, and never changes, upgrades or downgrades a native outcome. `present()` only maps and labels the F1 result.

## Installation
Reuse the F1 recipe exactly. Requirements: Linux, bash, git, Python >= 3.11 (developed on 3.13), `pydantic` 2.x, `cryptography`, `jsonschema` (versions not locked here). Assemble a stack root with the four pinned checkouts:

```bash
export STACK=/path/to/new/stack-root   # created by the clones below
for pair in control_plane:cognous-control-plane:484fdbd297235dd24148ddb0703f2055a31eabff \
            runtime:cognous-execution-runtime:f7a55e2a8494801e49193f9f46935f0a971c248d \
            replay:cognous-replay-bundle:7eb7d76eda10ca1ff997bb86853e903e57da625c \
            institutional_governance:cognous-institutional-governance:1ebe85be4cfe9e221ebd2618120687eb0b325d24; do
  IFS=: read dir repo sha <<<"$pair"
  git clone "https://github.com/cogno-us/$repo.git" "$STACK/$dir" && git -C "$STACK/$dir" checkout --detach "$sha"
done
export REFUND_DESK_STACK_ROOT="$STACK"
```
Each checkout must have a clean tracked tree; F1 verifies HEAD == pin on every call. Replay is not pip-installed.

## Running
From the repository root, with the package on the path:

```bash
export PYTHONPATH="$PWD:$PWD/applications/refund_desk"
```

```bash
# valid authority
python3 -m refund_desk process --case-id HV-2026-1102-0001 --tenant harborview-retail \
  --customer-account customer-001 --amount 64.25 --currency USD --reason damaged_item \
  --authority valid --state-dir /tmp/rd-a
# revoked authority
python3 -m refund_desk process --case-id HV-2026-1102-0002 --tenant harborview-retail \
  --customer-account customer-001 --amount 64.25 --reason damaged_item \
  --authority revoked --state-dir /tmp/rd-b
# read-only reconciliation of an earlier attempt (never dispatches)
python3 -m refund_desk reconcile --case-id HV-2026-1102-0003 --tenant harborview-retail \
  --customer-account customer-001 --amount 31.10 --reason late_delivery --state-dir /tmp/rd-c
```
`--stack-root DIR` may be given instead of the environment variable. Stdout is exactly one JSON object.

| Exit code | Outcome |
|---|---|
| 0 | `executed` |
| 2 | `held`, `refused`, `denied` |
| 3 | `uncertain` |
| 1 | `failed`, or usage error |

## Example outputs
Recorded from real runs against the pinned stack (paths shortened; full raw outputs are in the PR description). Key fields only:

**Authorized (`process`, valid authority) - exit 0**
```json
{
 "control_plane": {
  "reasons": [],
  "result": "authorized"
 },
 "execution_claim": {
  "basis": "native runtime_status=executed with observed_state=applied (producer-reported)",
  "supported": true
 },
 "message": "The refund effect was observed as applied in the synthetic local SQLite; this is producer-reported, not independently verified.",
 "native_runtime_status": "executed",
 "outcome": "executed",
 "permitted_next_actions": [],
 "replay_resolvable": true,
 "replay_status": "reconstruction_complete",
 "retry_permission": "not_established"
}
```

**Revoked authority (`process --authority revoked`) - exit 2**
```json
{
 "control_plane": {
  "reasons": [
   "grant_revoked"
  ],
  "result": "hold"
 },
 "execution_claim": {
  "basis": "no supported native execution evidence (F1 disposition=held)",
  "supported": false
 },
 "message": "The refund was put on hold before anything was dispatched: the authority that would permit this refund has been revoked.",
 "outcome": "held",
 "permitted_next_actions": [],
 "refusal": {
  "code": "control_plane_hold",
  "explanation": "the authority that would permit this refund has been revoked",
  "reasons": [
   "grant_revoked"
  ]
 },
 "retry_permission": "not_established",
 "runtime_invoked": false
}
```

**Uncertain outcome, presenting a previously generated F1 UNKNOWN result**
```json
{
 "control_plane": {
  "reasons": [],
  "result": "authorized"
 },
 "effect_absence_established": false,
 "execution_claim": {
  "basis": "no supported native execution evidence (F1 disposition=unknown)",
  "supported": false
 },
 "message": "The outcome is UNKNOWN. No retry was made, and the absence of an effect is not established. Only reconciliation is permitted.",
 "native_disposition": "unknown",
 "outcome": "uncertain",
 "permitted_next_actions": [
  "reconcile"
 ],
 "retry_permission": "not_established"
}
```

**After reconciliation (`reconcile`) - exit 0**
```json
{
 "acknowledged": false,
 "control_plane": {
  "reasons": [],
  "result": "authorized"
 },
 "execution_claim": {
  "basis": "native runtime_status=observed with observed_state=applied (producer-reported)",
  "supported": true
 },
 "message": "The refund effect was observed as applied in the synthetic local SQLite; this is producer-reported, not independently verified. No acknowledgment was received.",
 "native_runtime_status": "observed",
 "newly_executed": false,
 "observed_state": "applied",
 "outcome": "executed",
 "permitted_next_actions": [],
 "retry_permission": "not_established"
}
```

Uncertain-outcome path via the CLI: after an F1 UNKNOWN exists for a case, `process` for that case prints `outcome: uncertain` (exit 3, `refusal.code: prior_uncertain_dispatch`, `permitted_next_actions: ["reconcile"]`) and does not dispatch.

## Tests
```bash
python3 -m unittest discover -s tests/applications/refund_desk -p 'test_static.py' -v   # 5 tests, no stack needed
F3_STACK_ROOT="$STACK" F3_REQUIRE=1 python3 -m unittest discover -s tests/applications/refund_desk -p 'test_checks.py' -v   # 7 tests: checks A, B, C
```
The UNKNOWN used by check C is produced by a test-owned fixture that borrows the F1 **test-tree** fault injection; the application itself contains no fault injection.
`F3_REQUIRE=1` turns a missing stack into a failure (a skip is not a pass).

## CI scope declaration
No workflow is added or changed. Existing path-matched workflows do not collect these tests. The F3 tests were run locally; that run is the only basis for "developer-tested". No CI coverage is claimed.

## Limitations
- Authority is a synthetic fixture (`authenticated=false`), not institutional authority.
- Evidence is producer-reported; the SQLite write is local and not independently verified.
- The evaluation time is a fixed synthetic clock read from the fixtures, not the wall clock.
- Business inputs are bounded by F1's pinned Control Plane test-fixture manifest, which the caller cannot select: only `customer-001`, up to 100 USD, fixed institution. Anything else is a native HOLD. This is a documented dependency for a separately authorized F2 ("caller-selectable action manifest"); F3 does not work around it.
- Idempotency is per destination database only; no cross-database exactly-once claim.
- A lost acknowledgment alone maps to `executed` with `acknowledged=false`.
- A repeat after an unresolved uncertain attempt is refused (`prior_uncertain_dispatch`); no result grants a retry (`retry_permission=not_established`).
- No fault injection in the application.
- No Pack, Verifier, Attestation or Registry. No independent qualification, certification or production claim.

## Governance note
Engineering Constitution adoption in this repository: UNVERIFIED.

## Rollback
Delete `applications/refund_desk/` and `tests/applications/refund_desk/`. Nothing else changes.
