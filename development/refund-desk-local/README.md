# Refund Desk — CORE-LOCAL developer installation (M1-4)

**CORE-LOCAL development packaging. SYNTHETIC. NONPRODUCTION. Developer-tested only: not independently qualified, certified or production-ready.**
Nothing here authorizes anything; authority is a synthetic fixture (`authenticated=false`). The only effect is a row in a local SQLite file. No credential, paid API or production service is used.

Contract: Amendment M4 in [`../../applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md`](../../applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md). Plan: [cognous-open-control-stack#282](https://github.com/cogno-us/cognous-open-control-stack/issues/282). Application docs: [`../../applications/refund_desk/README.md`](../../applications/refund_desk/README.md).

## Requirements
Linux, `bash`, `git`, `python3` >= 3.11 with `venv` (Debian/Ubuntu: `apt install python3-venv`), network access to `github.com` and the Python package index for the first `setup`. Nothing is installed globally; no `sudo`.

## Install (one procedure)
```bash
git clone https://github.com/cogno-us/cognous-stack-orchestrator.git && cd cognous-stack-orchestrator
development/refund-desk-local/dev.sh setup            # default workspace: $HOME/.cognous-refund-desk-dev
# or choose one:  development/refund-desk-local/dev.sh --workspace /abs/path setup   (or export COGNOUS_RD_DEV_WORKSPACE=/abs/path)
```
`setup` (a) checks the tools, (b) creates the workspace (it refuses an existing non-empty directory that this tool does not own), (c) creates `venv/` and installs the repository's existing **hash-locked** files `.github/locks/cryptography-pydantic-pytest-513753.txt` and `.github/locks/jsonschema-424038.txt` (`--require-hashes --only-binary=:all:`), (d) obtains the four native components at the commits recorded in `applications/refund_desk/SOURCES.json` (cross-checked against F1's `source_pins.json`; no SHA is hard-coded in the script):

| Component | Repository | Pin |
|---|---|---|
| `control_plane` | `cogno-us/cognous-control-plane` | `484fdbd297235dd24148ddb0703f2055a31eabff` |
| `runtime` | `cogno-us/cognous-execution-runtime` | `f7a55e2a8494801e49193f9f46935f0a971c248d` |
| `replay` | `cogno-us/cognous-replay-bundle` | `7eb7d76eda10ca1ff997bb86853e903e57da625c` |
| `institutional_governance` | `cogno-us/cognous-institutional-governance` | `1ebe85be4cfe9e221ebd2618120687eb0b325d24` |

and (e) writes `install-record.json` (tool versions, component heads/trees, lock-file digests, installed packages). A component that already exists is only verified (HEAD == pin, clean tracked tree) and left untouched; **a component at another revision or with modified tracked files is refused, never reset or cleaned.** Repeating `setup` is safe. `COGNOUS_RD_DEV_GIT_BASE` may point at a mirror of the four repositories; the pin is still verified.

Workspace layout (all owned by this tool): `venv/`, `stack/<component>/`, `state/<run>/…`, `install-record.json`, `.cognous-refund-desk-dev-owner`.

## Use the published CLI directly
```bash
eval "$(development/refund-desk-local/dev.sh env)"      # REFUND_DESK_STACK_ROOT, PYTHONPATH, PATH (prints exports; changes nothing itself)
python -m refund_desk process --case-id HV-DEV-1 --tenant harborview-retail --customer-account customer-001 \
  --amount 64.25 --reason damaged_item --authority valid --state-dir "$HOME/.cognous-refund-desk-dev/state/mine"
```
Use a state directory under `<workspace>/state/` so `evidence` and `cleanup` can see it. Exit codes: 0 executed, 1 failed, 2 held/refused/denied, 3 uncertain. High profile: add `--profile refund-high-v1 --case-reference CASE-1` with `--customer-account customer-002`.

## Guided demonstration
```bash
development/refund-desk-local/dev.sh demo --name first      # refuses to overwrite an existing name
```
Each scenario uses a fresh state directory `<workspace>/state/first/<scenario>/`, saves the actual JSON as `<tag>.result.json`, checks it against the SQLite file (opened read-only) and prints `PASS`/`FAIL`:

| Scenario | What runs | Expected |
|---|---|---|
| `routine` | routine profile, customer-001, 64.25 USD, valid authority | exit 0, `executed`, native CP `authorized`, one `applied` row, matching effect id |
| `high` | `refund-high-v1`, customer-002, 150.00 USD, `CASE-DEV-0001` | exit 0, `executed`, profile `refund-high-v1`, one `applied` row, effect id distinct from routine |
| `hold` | routine, `--authority revoked` | exit 2, `held`, reason `grant_revoked`, zero rows, no execution claim |
| `mismatch` | customer-001 under `refund-high-v1`; and `--profile refund-ghost-v1` | exit 2 `held` (scope) and exit 2 `refused` `profile_unsupported`, zero rows |
| `uncertain` | F1 **test-tree** fault fixture (lost acknowledgment, unreadable observation) → present → CLI `process` repeat → CLI `reconcile` | `uncertain`; repeat exit 3, `prior_uncertain_dispatch`, no new row; reconcile exit 0, `observed`, nothing dispatched, rows unchanged; `retry_permission=not_established` throughout |

The fault is injected only by `devtool.py` through the F1 test tree (`tests/adapters/refund_disposition/_fault_injection.py`); the application and its CLI contain no fault injection. The demo also uses the application's private request builder (`refund_desk.desk._build_request`) in-process so the faulted F1 request equals what the CLI sends.

## Inspect raw evidence
```bash
development/refund-desk-local/dev.sh evidence --state "$HOME/.cognous-refund-desk-dev/state/first/routine"
```
Lists, with size and sha256 (read-only; nothing is created, modified or deleted): the application JSON results; the Control Plane decision/run record `cp/<case>.json` (and its `.lock` files); the evidence copies `evidence/<case>/cp_run_record-*.json`, `runtime_export-*.json` (Runtime observation/export) and `replay_bundle-*.json`; `sqlite/refunds.sqlite3` and its rows (table `effects`, opened `mode=ro`). A fixed legend explains how to tell apart:
- **authorized vs held:** `control_plane.result` and `control_plane.reasons`;
- **executed vs uncertain:** `outcome`; `uncertain` means UNKNOWN, reconcile only, no retry granted;
- **native effect vs application claim:** the SQLite rows and `native.*` are the effect; `execution_claim` is the application's claim;
- **producer-reported vs independent:** every artifact here is producer-reported (`labels.evidence_basis`); nothing is independently verified;
- **Replay `imported` vs `import_failed`:** `evidence.replay_state`, with F1's reason in `evidence.replay_note` (for example a repeat of an authorized request reports `import_failed` because the pinned single-proposal importer rejects a second bound decision — an evidence limitation, not an execution failure).
Note that SQLite may keep recent writes in `refunds.sqlite3-wal`/`-shm`; the main-file digest can omit them.

## Clean up (exact, owned state only)
```bash
development/refund-desk-local/dev.sh cleanup --state-only       # shows the exact targets; exit 3, removes nothing
development/refund-desk-local/dev.sh cleanup --state-only --yes # removes <workspace>/state only
development/refund-desk-local/dev.sh cleanup --all --yes        # removes state/, venv/, stack/, install-record.json, the marker, then the workspace if empty
```
Refused (exit 1, nothing removed): a relative path, a path with `..`, a symlink, `/`, `$HOME` or an ancestor, the source checkout or any ancestor/descendant, a directory without a matching owner marker, a marker written for another path, or an owned child that is a symlink. Unknown files in the workspace are never removed (they are listed). The source repository is never a target. Evidence under `state/` is kept until you run `cleanup`. A removal error is reported with its path and exit 1.

## Exit codes
`0` ok · `1` refused or failed · `2` usage error · `3` cleanup not executed (no `--yes`).

## Known limitations
- Linux only; the first `setup` needs network access. Dependency versions are those of the repository's hash-lock files (not chosen here).
- Pins are the existing development pins from `SOURCES.json`, not a formal source lock; `setup` verifies them but does not attest them.
- Evidence is producer-reported; Replay import of a same-correlation repeat reports `import_failed` (Issue #157, documented, unchanged).
- The inherited synthetic-fixture field `identity.authenticated: true` is not an authentication claim; results state `authenticated=false`.
- No Evidence Pack, Verifier, Attestation, Registry, ODES/GAX, CDC/ISS, container or CI integration. No independent qualification or certification.

## Rollback
Delete `development/refund-desk-local/` (and revert this PR); nothing else depends on it. To remove an installed workspace use `cleanup --all --yes`.
