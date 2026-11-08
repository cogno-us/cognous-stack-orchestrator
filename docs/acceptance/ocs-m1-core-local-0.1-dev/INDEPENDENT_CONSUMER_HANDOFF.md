# Independent consumer handoff — OCS-M1 CORE-LOCAL/0.1-dev (T-OCS-E)

**For:** one person or organization **outside the builder lineage** (the Claude-assisted team that built, merged and self-tested this stack). **Purpose:** run the published installation yourself, on your own Linux machine, and report exactly what happened. **This is a developer-consumption check of a synthetic, nonproduction stack. It is not a security review, certification or qualification, and nothing you do has production effect.**

Please do not accept help from the builders while you run it. If you cannot proceed without help, that is itself the result: report where you got stuck.

## 1. What you are running
| | |
|---|---|
| Repository | `https://github.com/cogno-us/cognous-stack-orchestrator` |
| **Exact source to use (commit)** | **`41f651d27e159f7b348e87f83475bf1bda7a6214`** (merge of PR #161). Do not use a branch tip. Later commits on `main` only add acceptance documentation and test-scope declarations; check out the SHA above anyway. |
| Installer | `development/refund-desk-local/` (`dev.sh`, `devtool.py`, `README.md` — the published instructions) |
| Native components it fetches (pinned, verified by the installer) | Control Plane `484fdbd297235dd24148ddb0703f2055a31eabff` · Runtime `f7a55e2a8494801e49193f9f46935f0a971c248d` · Replay `7eb7d76eda10ca1ff997bb86853e903e57da625c` · Institutional Governance `1ebe85be4cfe9e221ebd2618120687eb0b325d24` (all under `github.com/cogno-us/`) |
| What it does | a synthetic refund "desk": native Control Plane decides admission; the only effect is one row in a **local SQLite file**; Replay evidence is produced; no payment, network service, credential or paid API is involved |

## 2. Prerequisites (the minimum)
Linux with `bash`, `git`, `python3` ≥ 3.11 including the `venv` module (Debian/Ubuntu: `apt install python3-venv`), and outbound HTTPS to `github.com` and the Python package index (for hash-locked dependency wheels) during the first `setup` only. No `sudo`, credential or API key is needed. If you needed **anything else**, report it as an undocumented dependency.

## 3. Steps (copy exactly; record every exit code)
```bash
# 0. identity of your environment
uname -a; git --version; python3 --version

# 1. get the exact source
git clone https://github.com/cogno-us/cognous-stack-orchestrator.git && cd cognous-stack-orchestrator
git checkout --detach 41f651d27e159f7b348e87f83475bf1bda7a6214
git rev-parse HEAD            # must print 41f651d27e159f7b348e87f83475bf1bda7a6214

# 2. read the published instructions, then follow them
less development/refund-desk-local/README.md
export RD_WS="$HOME/.cognous-refund-desk-dev"      # the default workspace; all state lives here
development/refund-desk-local/dev.sh --workspace "$RD_WS" setup;  echo "exit=$?"
development/refund-desk-local/dev.sh --workspace "$RD_WS" setup;  echo "exit=$?"     # repeat is safe

# 3. guided demonstration (routine, high, hold, mismatch, uncertain+reconcile)
development/refund-desk-local/dev.sh --workspace "$RD_WS" demo --name consumer1;  echo "exit=$?"

# 4. use the published CLI yourself (not only the demo)
eval "$(development/refund-desk-local/dev.sh --workspace "$RD_WS" env)"
mkdir -p "$RD_WS/state/mine"
python -m refund_desk process --case-id MY-ROUTINE-1 --tenant harborview-retail --customer-account customer-001 \
  --amount 20.00 --reason damaged_item --authority valid --state-dir "$RD_WS/state/mine/routine";  echo "exit=$?"
python -m refund_desk process --case-id MY-REVOKED-1 --tenant harborview-retail --customer-account customer-001 \
  --amount 20.00 --reason damaged_item --authority revoked --state-dir "$RD_WS/state/mine/revoked";  echo "exit=$?"

# 5. inspect the raw evidence (read-only)
development/refund-desk-local/dev.sh --workspace "$RD_WS" evidence --state "$RD_WS/state/consumer1/routine"
development/refund-desk-local/dev.sh --workspace "$RD_WS" evidence --state "$RD_WS/state/consumer1/uncertain"
cat "$RD_WS/install-record.json"

# 6. cleanup: first the plan (removes nothing), then the real thing
development/refund-desk-local/dev.sh --workspace "$RD_WS" cleanup --all;        echo "exit=$?"
development/refund-desk-local/dev.sh --workspace "$RD_WS" cleanup --all --yes;  echo "exit=$?"
ls -A "$RD_WS" 2>&1 | head
```
Your cloned repository is never touched by `cleanup`. (pip may leave its normal cache under `~/.cache`; that is outside this tool's state — report it if it surprises you.)

## 4. Expected results (compare; report every difference)
| Step | Expected |
|---|---|
| clone / checkout | `git rev-parse HEAD` prints the SHA in §1 |
| `setup` (first) | exit **0**; four lines `<component>: at pin <sha>` equal to the pins in §1; ends with `setup complete`; takes roughly 10–60 s |
| `setup` (repeat) | exit **0**; four lines `<component>: already at pin <sha>` |
| `demo` | exit **0**; five lines starting `PASS` for `routine`, `high`, `hold`, `mismatch`, `uncertain`; then `ALL PASS`. Meaning: **routine** executed (native Control Plane `authorized`, one `applied` SQLite row whose id matches the result); **high** (`refund-high-v1`, customer-002, 150.00 USD) executed with its own distinct effect; **hold** revoked authority → exit 2, `held`, reason `grant_revoked`, zero rows; **mismatch** customer-001 under the high profile → `held`, and an unsupported profile → `refused`/`profile_unsupported`, zero rows; **uncertain** a lost acknowledgment → `uncertain`, a repeat is refused (exit 3, no new row), a read-only reconcile observes the committed row and dispatches nothing |
| your routine CLI call | exit **0**; one JSON object; `outcome: executed`; `control_plane.result: authorized`; `labels.authenticated: false`, `labels.nonproduction: true`, `labels.evidence_basis: producer_reported`; `limitations` mention synthetic/nonproduction; `evidence.replay_state: imported` |
| your revoked CLI call | exit **2**; `outcome: held`; `control_plane.reasons` contains `grant_revoked`; `execution_claim.supported: false`; no `sqlite` effect row |
| `evidence` | lists, with sha256: application JSON results, Control Plane run record(s), Runtime export, Replay bundle, the SQLite file and its rows; ends with a legend |
| `cleanup --all` (no `--yes`) | prints the exact targets; **removes nothing**; exit **3** |
| `cleanup --all --yes` | removes `state`, `venv`, `stack`, `install-record.json` and the marker, then the workspace; exit **0** |
Notes you should be able to confirm from the output: the uncertain scenario is produced with a **test-only fault fixture** (the public CLI cannot create an uncertain state; the README says so); a *repeat* of an already executed request may show `evidence.replay_state: import_failed` with a `replay_note` — that is a documented Replay limitation, not an execution failure.

## 5. If something fails
Stop at the **first** failure. Capture the exact command, its exit code, and stdout/stderr **verbatim**. You may retry once only to distinguish a transient network error — say so. **Do not edit the scripts or repair the environment silently;** if you must work around something, describe the intervention exactly (it is a finding, not a defect on your side). Do not post secrets; none are required.

## 6. Results-return template (copy, fill, return with the raw output attached)
```
CONSUMER IDENTITY AND INDEPENDENCE
Name / organization:
Contact (as you wish it recorded):
Relationship to the builders (employment, contract, prior work on OCS/Cognous):
I am not part of the builder lineage and ran every step myself:  [ yes / no ]
Help received from builders during the run (describe or "none"):
Date/time (UTC) and duration:

ENVIRONMENT
uname -a:
git --version:
python3 --version:
Linux distribution / container / VM:
Network restrictions (proxy etc.):

SOURCE IDENTITY
git rev-parse HEAD (expect 41f651d27e159f7b348e87f83475bf1bda7a6214):
Component heads from install-record.json (attach the file):

RESULTS (exit code and one line each; attach full raw output)
setup (first):            exit=   at-pin lines match pins? [y/n]
setup (repeat):           exit=   "already at pin"? [y/n]
demo:                     exit=   PASS lines: routine[ ] high[ ] hold[ ] mismatch[ ] uncertain[ ]  ALL PASS[ ]
CLI routine:              exit=   outcome=        control_plane.result=
CLI revoked:              exit=   outcome=        reasons=
evidence index worked:    [y/n]   could you tell authorized vs held / executed vs uncertain / replay imported vs import_failed? [y/n + notes]
cleanup plan:             exit=   nothing removed? [y/n]
cleanup --yes:            exit=   workspace removed? [y/n]   anything left behind (e.g. ~/.cache/pip)?

UNDOCUMENTED INTERVENTIONS AND DEFECTS
Any step, package, permission or knowledge that was NOT in the published instructions (or "none"):
Any command that failed, with verbatim output:
Anything confusing, misleading or unsafe:

ATTACHMENTS: full terminal transcript; install-record.json; one <scenario>.result.json for routine, uncertain and reconcile.
```
Return the filled template and attachments to whoever sent you this handoff (the Chief Architect's designated channel). Your report becomes evidence for OCS-12 / T-OCS-E as submitted; it will not be edited, and an unfavourable result is a valid and useful result.
