# Refund Desk (F3)

**DEVELOPMENT ONLY / SYNTHETIC / NONPRODUCTION / NON-AUTHORIZING.** Contract `refund-desk/0.1.0-dev`. Developer-tested: a local run only (builder-lineage, CA04); the exact-head run record is in the PR description. Not independently qualified, not certified, not production-ready. Frozen expectations: [CONTRACT_AND_EXPECTATIONS.md](CONTRACT_AND_EXPECTATIONS.md). Pins: [SOURCES.json](SOURCES.json) (not a source lock).

## What it is
A tiny CLI business application for one synthetic refund. It consumes only the public F1 library (`dispose_refund`, `reconcile_refund` from `orchestration.adapters.refund_disposition`, contract `refund-disposition/0.1.0-dev`) and presents the native disposition as one JSON object. The destination is synthetic local SQLite only.

## No duplicated native logic
The application imports only the standard library and the F1 package-level public names. It does not import F1 submodules or private names, nor any Control Plane, Runtime, Replay or IG module. It does not authorize, execute, retry or reconstruct anything, contains no fault injection, and never upgrades a native outcome or hides one. Its only downgrade is conservative: if F1 reports `executed` without an applied native observation, the application's `outcome` is `uncertain` (the `native.*` fields stay verbatim). `present()` only maps and labels the F1 result.

## Approved profiles (M1-2; Issue https://github.com/cogno-us/cognous-open-control-stack/issues/282, OCS-M1-ARCH-001 v0.9)
Refund Desk consumes the two approved F1 profiles through the public F1 interface. `--profile` is optional: omitted means the historical `refund-routine-v1` (customer-001, up to 100 USD). `--profile refund-high-v1` selects F1's second approved synthetic action (customer-002, native maximum 1000 USD, tier T2) and requires `--case-reference TEXT`. The application **only selects a profile id** and its own synthetic authority fixtures; it supplies no manifest, path, grant, Runtime policy or reviewer permission, performs no profile or case-reference validation (F1 and the native Control Plane own all of it; an unsupported id is refused by F1 with exit 2) and invents no case-reference format. Results gain two additive keys: `profile` (F1's selected profile identity: profile id, registry version, manifest id/version/digest, action id, requirement id; `null` when F1 returned none, e.g. a pre-flight refusal) and `requested_profile` (the id the case asked for, `null` when omitted). For the high profile, F1's disclosures are shown verbatim in `limitations`: the reviewer role is a synthetic alias, not authenticated institutional reviewer authority, and the manifest's evidence obligations are not evaluated natively. **A profile selection is not authorization.**

```bash
python3 -m refund_desk process --case-id HV-M12-0002 --tenant harborview-retail \
  --customer-account customer-002 --amount 150.00 --reason damaged_item \
  --profile refund-high-v1 --case-reference CASE-M12-0001 --state-dir /tmp/rd-high
```
`--case` remains accepted as an explicit alias of `--case-id`.

## Replay evidence note (M1-3; Issue #157, Amendment M3)
`evidence` now also carries `replay_note`: F1's `EvidenceReferences.replay_note` copied **verbatim**, or `null` when F1 gave none (the example outputs above predate this additive field). It is informational only: it never changes `outcome`, `native`, `execution_claim`, `effect`, `retry_permission` or `effect_absence_established`, and the application neither interprets nor adds to it. `evidence.replay_state` is still exactly F1's value (`imported | not_run | import_failed`).

Observed with the pinned stack (Replay `7eb7d76e`): repeating an identical authorized request against the same state directory returns `outcome: executed`, `native.newly_executed: false`, still one `applied` effect row with the same `effect_id`, and no additional native commit, but `evidence.replay_state: "import_failed"`, `evidence.replay: null` and
`evidence.replay_note: "replay_import_failed: ImportContractError('single-proposal importer does not support multiple authorization bindings')"`.
The repeat re-runs the Control Plane decision and appends a second decision to the append-only per-correlation record; the pinned Replay single-proposal importer rejects more than one bound decision. This is a Replay evidence limitation, not an execution failure: the effect and its disposition are unchanged. It was reproduced here for both the routine and the high profile; the application reports whatever F1 returns and does not assume every repeat yields this note. Whether a repeat should report `not_run` instead is an F1-owner decision and is not changed here.

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
| 3 | `uncertain` (including a presentation failure after F1 was called, or F1 `executed` without a supported applied observation) |
| 1 | `failed`, or usage error |

## Example outputs
Recorded from real runs against the pinned stack (paths shortened; the objects below are **excerpts of the real nested output** - every result also carries the other `to_dict()` keys, `labels`, `limitations` and `cleanup`; complete raw outputs are attached in the PR description):

**Authorized (`process`, valid authority) - exit 0**
```json
{
 "control_plane": {
  "reasons": [],
  "result": "authorized"
 },
 "effect_absence_established": false,
 "evidence": {
  "replay": {
   "path": ".../replay_bundle-516d92d4442a4e57.json",
   "resolvable": true,
   "sha256": "sha256:516d92d4442a4e5775d63a385f57fba5b84bdb6e5c00507fbd3ad2980f34acc5",
   "status": "reconstruction_complete"
  },
  "replay_state": "imported"
 },
 "execution_claim": {
  "basis": "native runtime_status=executed with observed_state=applied (producer-reported)",
  "supported": true
 },
 "message": "The refund effect was observed as applied in the synthetic local SQLite; this is producer-reported, not independently verified.",
 "native": {
  "acknowledged": true,
  "newly_executed": true,
  "observed_state": "applied",
  "runtime_invocations": 1,
  "runtime_status": "executed"
 },
 "outcome": "executed",
 "permitted_next_actions": [],
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
 "effect_absence_established": false,
 "evidence": {
  "replay_state": "not_run"
 },
 "execution_claim": {
  "basis": "no supported native execution evidence (F1 disposition=held)",
  "supported": false
 },
 "message": "This request was not dispatched (the authority that would permit this refund has been revoked). This result says nothing about any earlier attempt for this case.",
 "native": {
  "disposition": "held",
  "runtime_invoked": false
 },
 "outcome": "held",
 "permitted_next_actions": [],
 "refusal": {
  "code": "control_plane_hold",
  "explanation": "the authority that would permit this refund has been revoked",
  "reasons": [
   "grant_revoked"
  ]
 },
 "retry_permission": "not_established"
}
```

**Uncertain outcome (application presenting a previously generated F1 UNKNOWN result)**
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
 "native": {
  "acknowledged": false,
  "disposition": "unknown",
  "runtime_status": "unknown"
 },
 "outcome": "uncertain",
 "permitted_next_actions": [
  "reconcile"
 ],
 "retry_permission": "not_established"
}
```

**Repeat `process` for that case (CLI) - exit 3, no dispatch**
```json
{
 "control_plane": {
  "reasons": [],
  "result": "authorized"
 },
 "effect_absence_established": false,
 "execution_claim": {
  "basis": "no supported native execution evidence (F1 disposition=refused)",
  "supported": false
 },
 "message": "The outcome is UNKNOWN. No retry was made, and the absence of an effect is not established. Only reconciliation is permitted.",
 "native": {
  "disposition": "refused",
  "runtime_invocations": 0
 },
 "outcome": "uncertain",
 "permitted_next_actions": [
  "reconcile"
 ],
 "refusal": {
  "code": "prior_uncertain_dispatch",
  "explanation": "an earlier attempt for this effect is unknown/partial/unresolved; reconcile first",
  "reasons": [
   "an earlier attempt for this effect is unknown/partial/unresolved; reconcile first"
  ]
 },
 "retry_permission": "not_established"
}
```

**After explicit `reconcile` (CLI) - exit 0, nothing dispatched**
```json
{
 "control_plane": {
  "reasons": [],
  "result": "authorized"
 },
 "effect_absence_established": false,
 "execution_claim": {
  "basis": "native runtime_status=observed with observed_state=applied (producer-reported)",
  "supported": true
 },
 "message": "The refund effect was observed as applied in the synthetic local SQLite; this is producer-reported, not independently verified. No acknowledgment was received.",
 "native": {
  "acknowledged": false,
  "newly_executed": false,
  "observed_state": "applied",
  "runtime_invocations": 0,
  "runtime_status": "observed"
 },
 "outcome": "executed",
 "permitted_next_actions": [],
 "retry_permission": "not_established"
}
```

The `reconcile` command needs a prior unresolved attempt for the same case (it reads the retained Control Plane record); on a fresh state dir it prints `outcome: refused` with `refusal.code: no_prior_dispatch_record` (exit 2). The UNKNOWN above was produced by a test-owned fixture that uses the F1 test-tree fault injection; the application cannot produce it.

## Example outputs - M1-2 (real runs against the pinned stack; key excerpts)
High profile, authorized (`--profile refund-high-v1`, customer-002, 150.00 USD) - exit 0: `outcome: executed`, `control_plane: {result: authorized, reasons: []}`, `profile: {profile_id: refund-high-v1, registry_version: refund-profiles/0.1.0-dev, manifest_id: refund-integration-pilot-v1, manifest_version: "1.1", manifest_digest: sha256:4d1ad6c9...f6ac, action_id: urn:cognous:action:refund-issue-high-v1, requirement_id: urn:cognous:authority-requirement:refund-high-v1}`, `requested_profile: refund-high-v1`, `limitations` = the four F1 strings + the two high-profile disclosures + application notes.
Routine customer under the high profile (customer-001) - exit 2: `outcome: held`, `control_plane.reasons: [grant_scope_mismatch, requirement_scope_mismatch, target_out_of_scope]`, `refusal.code: control_plane_hold`, `profile` populated (the native hold bound the profile), nothing dispatched.
High profile without `--case-reference` - exit 2: `outcome: refused`, `refusal.code: request_invalid` (`case_reference_required_for_profile`), `profile: null`, `requested_profile: refund-high-v1`.
Unsupported profile (`--profile refund-ghost-v1`) - exit 2: `outcome: refused`, `refusal.code: profile_unsupported`, `profile: null`.

## Tests
```bash
python3 -m unittest discover -s tests/applications/refund_desk -p 'test_static.py' -v   # 5 tests, no stack needed
python3 -m unittest discover -s tests/applications/refund_desk -p 'test_present_unit.py' -v   # 7 tests, no stack needed
python3 -m unittest discover -s tests/applications/refund_desk -p 'test_unsupported_executed.py' -v   # focused R1 regression, no stack needed
F3_STACK_ROOT="$STACK" F3_REQUIRE=1 python3 -m unittest discover -s tests/applications/refund_desk -p 'test_checks.py' -v   # 13 tests: checks A, B, C and review additions
python3 -m unittest discover -s tests/applications/refund_desk -p 'test_scope_windows.py' -v   # scope-window rules R2 (stack-free)
python3 -m unittest discover -s tests/applications/refund_desk -p 'test_scope_windows_m12.py' -v   # scope windows after M1-2, R3 (stack-free)
python3 -m unittest discover -s tests/applications/refund_desk -p 'test_m12_unit.py' -v   # M1-2 profile contract and forwarding (stack-free)
F3_STACK_ROOT="$STACK" F3_REQUIRE=1 python3 -m unittest discover -s tests/applications/refund_desk -p 'test_m12_checks.py' -v   # M1-2 primary checks A, B, C (API + CLI)
python3 -m unittest discover -s tests/applications/refund_desk -p 'test_m13_unit.py' -v   # M1-3 replay_note passthrough (stack-free)
F3_STACK_ROOT="$STACK" F3_REQUIRE=1 python3 -m unittest discover -s tests/applications/refund_desk -p 'test_m13_checks.py' -v   # M1-3 initial/repeat/uncertain/reconcile, both profiles
python3 -m unittest discover -s tests/applications/refund_desk -p 'test_scope_windows_m13.py' -v   # scope windows after M1-3, R4 (stack-free)
python3 -m unittest discover -s tests/applications/refund_desk -p 'test_m13_unit.py' -v   # M1-3 replay_note passthrough (stack-free)
F3_STACK_ROOT="$STACK" F3_REQUIRE=1 python3 -m unittest discover -s tests/applications/refund_desk -p 'test_m13_checks.py' -v   # M1-3 initial/repeat/uncertain/reconcile, both profiles
python3 -m unittest discover -s tests/applications/refund_desk -p 'test_scope_windows_m13.py' -v   # scope windows after M1-3, R4 (stack-free)
```
The UNKNOWN used by check C is produced by a test-owned fixture that borrows the F1 **test-tree** fault injection; the application itself contains no fault injection.
`F3_REQUIRE=1` turns a missing stack into a failure (a skip is not a pass).

## CI scope declaration
No workflow is added or changed. Existing path-matched workflows do not collect these tests. The F3 tests were run locally; that run is the only basis for "developer-tested". No CI coverage is claimed.

## Limitations
- Authority is a synthetic fixture (`authenticated=false`), not institutional authority.
- Evidence is producer-reported; the SQLite write is local and not independently verified.
- The evaluation time is a fixed synthetic clock read from the fixtures, not the wall clock.
- Business inputs are bounded by the two approved F1 profiles of one pinned manifest, which the caller cannot author or select by path: routine = `customer-001`, up to 100 USD; high = `customer-002`, native maximum 1000 USD, `case_reference` required. Anything else is a native HOLD or an F1 refusal. There is no arbitrary profile registration or manifest-authoring interface. (Predecessor wording about a single fixed profile described PR #156 / F1 `09e1ba3` and is superseded by M1-1/M1-2.)
- Idempotency is per destination database only; no cross-database exactly-once claim.
- A lost acknowledgment alone maps to `executed` with `acknowledged=false` (when the native observation is `applied`).
- The high profile's reviewer role is a synthetic alias and its evidence obligations are not natively evaluated; `authenticated=false` throughout. `case_reference` accepts arbitrary text (no separately approved business format).
- A repeat after an unresolved uncertain attempt is refused (`prior_uncertain_dispatch`) and shown as `uncertain`; this stays true even after a `reconcile` has observed the effect as applied (the F1 conservative rule), so the same case can show `executed` from `reconcile` and then `uncertain` from a repeat `process`. No result grants a retry (`retry_permission=not_established`).
- If the application cannot present an F1 result (or F1 raises), it fails closed: `outcome=uncertain`, reconcile only, exit 3. A held/refused/denied message describes only the current request and says nothing about earlier attempts for the case. `failed` is used only for errors before any F1 call.
- If F1 ever reported `executed` without an applied native observation (or with a runtime status other than `executed`/`reconciled`/`observed`), the application prints `outcome=uncertain` (reconcile only, exit 3, `execution_claim.supported=false`, `native.*` unchanged, no claim of absence). F1 currently prevents this case; the stack-free regression `test_unsupported_executed.py` covers it (Amendment R1, frozen before the change).
- A `denied` result comes from the Runtime call, so its message does not say the request was "not dispatched".
- No fault injection in the application.
- No Pack, Verifier, Attestation or Registry. No independent qualification, certification or production claim.

## Architect decisions recorded (PR #156)
*(Historical record of the PR #156 decisions. Decision 1 describes the single fixed profile of F1 `09e1ba3`; it is superseded for the bounded development profile by the two approved F1 profiles consumed in M1-2. Nothing in this section authorizes anything beyond its original scope.)*
1. F3's fixed synthetic manifest (customer-001, <=100 USD, fixed institution) is accepted for the bounded F4 developer-consumption profile; caller-selectable manifests are deferred to a separately authorized F2. 2. An application outcome must be UNCERTAIN whenever a native execution-success disposition lacks sufficient applied-effect observation (implemented as Amendment R1). 3. No new CI workflow is introduced here. 4. Independent F1/F3 security qualification is not required before F4 planning, but all existing assurance obligations remain. These decisions do not authorize F2, F4 implementation, deployment, certification or production use.

## Governance note
Engineering Constitution adoption in this repository: UNVERIFIED.

## Rollback
Delete `applications/refund_desk/` and `tests/applications/refund_desk/`. Nothing else changes.
