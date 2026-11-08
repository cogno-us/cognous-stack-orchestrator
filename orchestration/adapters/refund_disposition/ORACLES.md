# F1 developer oracles - FROZEN BEFORE EXECUTION

DEVELOPMENT ONLY / SYNTHETIC / NONPRODUCTION / NON-AUTHORIZING. These are builder-lineage developer checks (CA04). They are not
independent qualification, not certification and not a production claim. This file was committed before the adapter code existed and
before any of the three checks ran. If a run disagrees with an expectation below, the run is reported as a FAIL; the oracle is not edited
to fit the implementation. A change would be a new, visibly dated amendment appended at the end.

Shared preconditions (all three): the assembled stack root passes the pin check in `source_pins.json` for control_plane, runtime, replay and
institutional_governance (HEAD == pin, tracked tree clean); a fresh, empty, caller-owned `state_dir`; request tenant `tenant-alpha`,
customer `customer-001`, 50.0 USD, evaluation time 2026-10-05T19:00:00Z; authority facts = the pinned IG `synthetic_facts.json`
(resolver `authenticated=false`). Independent measurements use their own read-only SQLite connection and call counters installed on the
native `PinnedControlPlaneExecutor.execute` and `DurableRefundDestination.commit`, not the adapter's self-report.

## A. Authorized proposal
Authority bundle: pinned IG `root_lineage.json`.
Call 1 expects: disposition `executed`; CP decision `authorized` with no reasons; native Runtime status `executed`, `newly_executed=true`;
`runtime_invocations == 1`; independent `commit` count 1; exactly one row in `effects`, state `applied`, amount 50.0, unit USD, row
`effect_id` == result `effect_id` == CP decision effect id; a Replay reference whose file exists, whose sha256 matches the file bytes, whose
bundle status is `reconstruction_complete` and whose records name the same effect id; labels `synthetic_authority=true`,
`authenticated=false`, `evidence_basis=producer_reported`, `nonproduction=true`; `retry_permission == "not_established"`; next step
`none`; workspace cleanup reported ok and the adapter scratch directory absent afterwards.
Call 2 (identical request, same `state_dir`) expects: `effects` still exactly one row, byte-identical to after call 1; same effect id;
`newly_executed=false`; native status `reconciled`; independent `commit` count increases by at most 0 beyond the native duplicate-aware path
(row count is the binding assertion); no claim of a second execution.

## B. Revoked authority
Authority bundle: pinned IG `root_lineage_revoked.json`.
Expects: disposition `held`; CP decision `hold` with reason `grant_revoked`; `runtime_invoked == false`, adapter `runtime_invocations == 0`;
independent `PinnedControlPlaneExecutor.execute` count 0 and `DurableRefundDestination.commit` count 0; zero rows in `effects` (or no
database file); no row in `effective_grants_v1` (the adapter writes no grant mirror before CP authorizes); no Replay file produced and the
Replay reference states `not_run`; a source reference to the retained CP run record with matching sha256; next step `resolve_authority_hold`;
`retry_permission == "not_established"`; the same labels as A.

## C. Post-commit lost acknowledgment
Authority bundle: pinned IG `root_lineage.json`. Fault seam: the development-only `lost_ack_observation_unavailable` option, which uses the
native Runtime `simulate="lost_ack"` path (durable commit, then acknowledgment withheld) and additionally makes the destination
observation unavailable until reconciliation. It lives only in the adapter and changes no component source.
Expects after `dispose_refund`: disposition `unknown`; native Runtime status `unknown`; `acknowledged=false`; independent `commit` count
exactly 1 and `execute` count exactly 1 (no automatic retry); the independent SQLite read shows exactly one `applied` row (the effect did
commit) while the result makes NO claim of absence (`effect_absence_established == false`, observed state is not `absent`); disposition is
never `executed`/`failed`/`held`; `retry_permission == "not_established"`; next step `reconcile_read_only`; labels as A.
Then `reconcile_refund` on a healthy destination expects: effect-free (no new `execute`/`commit` call, row count 1, the row's columns
identical to the pre-reconcile read), observed state `applied`, disposition `executed` with native status `observed` and
`newly_executed=false`, still `retry_permission == "not_established"`.

## Amendments
- 2026-11-08 (access path only; **no oracle expectation changed**): the fault of check C was originally reachable through a `dev_fault` field on the request. Following Architect
  direction on PR #155 it is now injected only by the test tree through a private entry point (`_dispose_refund(request, _TestInjection)`), and the request contract has no fault
  field. The injected fault (native `simulate="lost_ack"` plus an unavailable destination read path until the call returns) and every expected result of A, B and C are unchanged.
