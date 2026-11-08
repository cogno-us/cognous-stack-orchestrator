#!/usr/bin/env python3
"""Helper for dev.sh (CORE-LOCAL / SYNTHETIC / NONPRODUCTION developer packaging; Amendment M4 in applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md).

Standard library only. Sub-commands: pins, check-workspace, marker, record, env, demo, evidence, cleanup.
Nothing here authorizes anything, validates a refund, or adds evidence: it reads pinned sources, runs the PUBLISHED Refund Desk CLI, and lists what exists.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import platform
import shlex
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

OWNER = "cognous-refund-desk-local"
MARKER = ".cognous-refund-desk-dev-owner"
RECORD = "install-record.json"
COMPONENTS = ("control_plane", "runtime", "replay", "institutional_governance")
LOCKS = (".github/locks/cryptography-pydantic-pytest-513753.txt", ".github/locks/jsonschema-424038.txt")
OWNED_DIRS = ("state", "venv", "stack")
NAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-_")


class Refused(Exception):
    """A truthful refusal (exit 1)."""


def say(*a):
    print(*a, flush=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


# ---------------------------------------------------------------- pins
def read_pins(repo: Path) -> dict:
    """{component: (repository_name, commit)} from SOURCES.json, cross-checked against F1's source_pins.json. No SHA is hard-coded here."""
    sources = json.loads((repo / "applications/refund_desk/SOURCES.json").read_text())["native_components_used"]
    f1 = json.loads((repo / "orchestration/adapters/refund_disposition/source_pins.json").read_text())["components"]
    out = {}
    for c in COMPONENTS:
        if c not in sources or sources[c]["commit"] != f1.get(c):
            raise Refused(f"pin disagreement for {c}: SOURCES.json={sources.get(c)} source_pins.json={f1.get(c)}")
        out[c] = (sources[c]["repository"].split("/")[-1], sources[c]["commit"])
    return out


def cmd_pins(a):
    for c, (repo_name, sha) in read_pins(Path(a.repo)).items():
        say(c, repo_name, sha)


# ---------------------------------------------------------------- workspace safety
def _marker_ok(ws: Path) -> bool:
    m = ws / MARKER
    try:
        if m.is_symlink() or not m.is_file():
            return False
        d = json.loads(m.read_text())
        return isinstance(d, dict) and d.get("owner") == OWNER and d.get("workspace") == str(ws)
    except (OSError, ValueError):
        return False


def resolve_workspace(raw: str, repo: Path, *, mode: str) -> Path:
    """Return the validated absolute workspace path or raise Refused. mode: 'setup' (absent / empty / owned) or 'owned' (marker required)."""
    if not raw or not os.path.isabs(raw):
        raise Refused(f"workspace must be an absolute path: {raw!r}")
    if ".." in Path(raw).parts:
        raise Refused(f"workspace path must not contain '..': {raw!r}")
    p = Path(os.path.abspath(raw))
    if p.is_symlink() or os.path.realpath(p) != str(p):
        raise Refused(f"workspace path must not be or traverse a symbolic link: {raw!r}")
    repo_r = repo.resolve()
    home = Path(os.environ.get("HOME", "/nonexistent")).resolve()
    if p == Path(p.anchor):
        raise Refused("refusing the filesystem root")
    if p == home or p in home.parents:
        raise Refused(f"refusing HOME or an ancestor of HOME: {p}")
    if p == repo_r or p in repo_r.parents or repo_r in p.parents:
        raise Refused(f"refusing the source repository checkout, its ancestors or its descendants: {p}")
    if mode == "owned":
        if not p.is_dir() or not _marker_ok(p):
            raise Refused(f"not an owned workspace (missing or mismatched {MARKER}): {p}")
    else:
        if p.exists():
            if not p.is_dir():
                raise Refused(f"workspace exists and is not a directory: {p}")
            if any(p.iterdir()) and not _marker_ok(p):
                raise Refused(f"workspace is a non-empty directory without a valid {MARKER}; refusing to use it: {p}")
        elif not p.parent.is_dir():
            raise Refused(f"parent directory does not exist: {p.parent}")
    return p


def cmd_check_workspace(a):
    say(resolve_workspace(a.workspace, Path(a.repo), mode=a.mode))


def cmd_marker(a):
    ws = resolve_workspace(a.workspace, Path(a.repo), mode="setup")
    ws.mkdir(exist_ok=True)
    if not _marker_ok(ws):
        (ws / MARKER).write_text(json.dumps({"owner": OWNER, "schema": 1, "workspace": str(ws),
                                             "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}, indent=1) + "\n")
    say(f"owner marker: {ws / MARKER}")


# ---------------------------------------------------------------- install record / env
def _git(d: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, check=True).stdout.strip()


def cmd_record(a):
    repo = Path(a.repo)
    ws = resolve_workspace(a.workspace, repo, mode="owned")
    pins = read_pins(repo)
    comps = {}
    for c in COMPONENTS:
        d = ws / "stack" / c
        comps[c] = {"repository": pins[c][0], "pin": pins[c][1], "head": _git(d, "rev-parse", "HEAD"), "tree": _git(d, "rev-parse", "HEAD^{tree}")}
    pip = subprocess.run([str(ws / "venv/bin/python"), "-m", "pip", "list", "--format=json", "--disable-pip-version-check"], capture_output=True, text=True)
    rec = {"owner": OWNER, "classification": "CORE-LOCAL development packaging; SYNTHETIC; NONPRODUCTION; developer-tested only",
           "time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "orchestrator_head": _git(repo, "rev-parse", "HEAD"),
           "tool_versions": {"git": subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip(),
                             "system_python": platform.python_version(), "venv_python": subprocess.run([str(ws / "venv/bin/python"), "--version"], capture_output=True, text=True).stdout.strip(),
                             "os": platform.platform()},
           "components": comps,
           "lock_files": {l: sha256_file(repo / l) for l in LOCKS},
           "installed_packages": json.loads(pip.stdout) if pip.returncode == 0 else None}
    (ws / RECORD).write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    say(f"install record: {ws / RECORD}")


def cmd_env(a):
    repo = Path(a.repo).resolve()
    ws = resolve_workspace(a.workspace, repo, mode="owned")
    if not (ws / RECORD).is_file() or not (ws / "venv/bin/python").exists():
        raise Refused(f"setup has not completed in {ws}; run: dev.sh setup")
    say(f"export REFUND_DESK_STACK_ROOT={shlex.quote(str(ws / 'stack'))}")
    say(f"export PYTHONPATH={shlex.quote(f'{repo}:{repo}/applications/refund_desk')}")
    say(f"export PATH={shlex.quote(str(ws / 'venv/bin'))}:\"$PATH\"")


# ---------------------------------------------------------------- demo
def _effects(state: Path) -> list:
    db = state / "sqlite" / "refunds.sqlite3"
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM effects ORDER BY effect_id")]
    finally:
        con.close()


class Demo:
    def __init__(self, ws: Path, repo: Path, name: str):
        self.ws, self.repo, self.root = ws, repo, ws / "state" / name
        self.env = dict(os.environ, REFUND_DESK_STACK_ROOT=str(ws / "stack"), PYTHONPATH=f"{repo}:{repo}/applications/refund_desk",
                        PATH=f"{ws / 'venv/bin'}:{os.environ.get('PATH', '')}")
        self.failures = 0

    def cli(self, scenario: str, command: str, case: dict, *, tag: str | None = None, state: Path | None = None):
        state = state or (self.root / scenario)
        state.mkdir(parents=True, exist_ok=True)
        argv = [str(self.ws / "venv/bin/python"), "-m", "refund_desk", command, "--case-id", case["case_id"], "--tenant", "harborview-retail",
                "--customer-account", case["customer"], "--amount", case["amount"], "--reason", "damaged_item", "--authority", case.get("authority", "valid"),
                "--state-dir", str(state)]
        if case.get("profile"):
            argv += ["--profile", case["profile"]]
        if case.get("case_reference"):
            argv += ["--case-reference", case["case_reference"]]
        p = subprocess.run(argv, capture_output=True, text=True, env=self.env, cwd=str(self.ws), timeout=600)
        try:
            res = json.loads(p.stdout)
        except ValueError:
            res = {"unparseable_stdout": p.stdout, "stderr": p.stderr}
        (state / f"{tag or scenario}.result.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
        return p.returncode, res, state

    def report(self, scenario: str, checks: list):
        bad = [m for ok, m in checks if not ok]
        if bad:
            self.failures += 1
        say(f"{'PASS' if not bad else 'FAIL'}  {scenario:<9} " + ("; ".join(m for _, m in checks if _) if not bad else "FAILED: " + "; ".join(bad)))


def cmd_demo(a):
    repo = Path(a.repo).resolve()
    ws = resolve_workspace(a.workspace, repo, mode="owned")
    if not (ws / RECORD).is_file():
        raise Refused(f"setup has not completed in {ws}; run: dev.sh setup")
    name = a.name
    if not name or set(name) - NAME_OK or name.startswith("-"):
        raise Refused(f"demo name must be lowercase letters, digits, '-' or '_': {name!r}")
    d = Demo(ws, repo, name)
    if d.root.exists():
        raise Refused(f"{d.root} already exists; evidence is never overwritten (choose another --name or run cleanup --state-only)")
    d.root.mkdir(parents=True)
    say(f"CORE-LOCAL / SYNTHETIC / NONPRODUCTION demonstration; evidence under {d.root}")

    # 1 routine
    rc, r, st = d.cli("routine", "process", dict(case_id="HV-DEV-R1", customer="customer-001", amount="64.25"))
    rows = _effects(st)
    d.report("routine", [(rc == 0, "exit 0"), (r.get("outcome") == "executed", "executed"), (r.get("control_plane", {}).get("result") == "authorized", "native CP authorized"),
                         (len(rows) == 1 and rows[0]["state"] == "applied", "one applied SQLite row"), (rows[:1] and rows[0]["effect_id"] == r.get("effect", {}).get("effect_id"), "effect id matches SQLite"),
                         (bool(r.get("evidence", {}).get("source")), "replay source references present"), (r.get("labels", {}).get("nonproduction") is True, "nonproduction label")])
    routine_effect = r.get("effect", {}).get("effect_id")
    # 2 high
    rc, r, st = d.cli("high", "process", dict(case_id="HV-DEV-H1", customer="customer-002", amount="150.00", profile="refund-high-v1", case_reference="CASE-DEV-0001"))
    rows = _effects(st)
    d.report("high", [(rc == 0, "exit 0"), (r.get("outcome") == "executed", "executed"), (r.get("profile", {}) and r["profile"].get("profile_id") == "refund-high-v1", "profile refund-high-v1"),
                      (r.get("requested_profile") == "refund-high-v1", "requested_profile echoed"), (len(rows) == 1 and rows[0]["state"] == "applied", "one applied SQLite row"),
                      (rows[:1] and rows[0]["effect_id"] == r.get("effect", {}).get("effect_id") != routine_effect, "own effect id, distinct from routine")])
    # 3 hold
    rc, r, st = d.cli("hold", "process", dict(case_id="HV-DEV-X1", customer="customer-001", amount="64.25", authority="revoked"))
    d.report("hold", [(rc == 2, "exit 2"), (r.get("outcome") == "held", "held"), ("grant_revoked" in r.get("control_plane", {}).get("reasons", []), "reason grant_revoked"),
                      (_effects(st) == [], "zero SQLite rows"), (r.get("execution_claim", {}).get("supported") is False, "no execution claim")])
    # 4 mismatch: routine customer under the high profile (native hold) and an unsupported profile (F1 refusal)
    rc, r, st = d.cli("mismatch", "process", dict(case_id="HV-DEV-M1", customer="customer-001", amount="64.25", profile="refund-high-v1", case_reference="CASE-DEV-0002"), tag="scope-hold")
    ok1 = [(rc == 2, "exit 2"), (r.get("outcome") == "held", "held (customer outside the high profile's scope)"), (_effects(st) == [], "zero rows")]
    rc2, r2, _ = d.cli("mismatch", "process", dict(case_id="HV-DEV-M2", customer="customer-001", amount="64.25", profile="refund-ghost-v1"), tag="ghost-profile", state=st)
    d.report("mismatch", ok1 + [(rc2 == 2, "ghost profile exit 2"), (r2.get("outcome") == "refused" and (r2.get("refusal") or {}).get("code") == "profile_unsupported", "profile_unsupported refusal"),
                                (_effects(st) == [], "still zero rows")])
    # 5 uncertain (test-tree fault fixture, in-process; never the CLI)
    case = dict(case_id="HV-DEV-U1", customer="customer-002", amount="150.00", profile="refund-high-v1", case_reference="CASE-DEV-0003")
    ust = d.root / "uncertain"
    ust.mkdir()
    for k, v in (("REFUND_DESK_STACK_ROOT", d.env["REFUND_DESK_STACK_ROOT"]),):
        os.environ[k] = v
    sys.path[:0] = [str(repo), str(repo / "applications/refund_desk")]
    from refund_desk import DeskConfig, RefundCase, desk, present  # noqa: E402
    fspec = importlib.util.spec_from_file_location("_m14_f1_fault_injection", repo / "tests/adapters/refund_disposition/_fault_injection.py")
    fault = importlib.util.module_from_spec(fspec)
    fspec.loader.exec_module(fault)
    rcase = RefundCase(case_id=case["case_id"], tenant_id="harborview-retail", customer_account=case["customer"], amount=float(case["amount"]), reason="damaged_item",
                       authority="valid", profile=case["profile"], case_reference=case["case_reference"])
    f1 = fault.dispose_with_lost_ack_unavailable_observation(desk._build_request(rcase, DeskConfig(stack_root=ws / "stack", state_dir=ust)))
    pres = present(f1, case["case_id"]).to_dict()
    (ust / "uncertain.result.json").write_text(json.dumps(pres, indent=2, sort_keys=True) + "\n")
    rows = _effects(ust)
    rc3, r3, _ = d.cli("uncertain", "process", case, tag="repeat-process", state=ust)
    rows3 = _effects(ust)
    rc4, r4, _ = d.cli("uncertain", "reconcile", case, tag="reconcile", state=ust)
    rows4 = _effects(ust)
    d.report("uncertain", [(f1.disposition == "unknown", "F1 disposition unknown (fixture)"), (pres.get("outcome") == "uncertain", "presented as uncertain"),
                           (pres.get("effect_absence_established") is False, "absence of effect not claimed"), (pres.get("retry_permission") == "not_established", "retry not established"),
                           (len(rows) == 1, "one row committed"), (rc3 == 3 and r3.get("outcome") == "uncertain" and (r3.get("refusal") or {}).get("code") == "prior_uncertain_dispatch", "repeat: exit 3, refused, no redispatch"),
                           (rows3 == rows, "repeat added no row"), (rc4 == 0 and r4.get("outcome") == "executed" and r4.get("native", {}).get("runtime_status") == "observed", "reconcile: observed, exit 0"),
                           (r4.get("native", {}).get("runtime_invocations") == 0, "reconcile dispatched nothing"), (rows4 == rows, "rows unchanged after reconcile"),
                           (r4.get("retry_permission") == "not_established", "retry still not established")])
    say(f"{'ALL PASS' if not d.failures else 'FAILURES: %d' % d.failures}; inspect with: dev.sh evidence --state {d.root}/<scenario>")
    return 0 if not d.failures else 1


# ---------------------------------------------------------------- evidence index
LEGEND = """\
How to read this (all evidence below is producer-reported by the synthetic local stack; none of it is independently verified):
  authorized vs held     : result.control_plane.result ("authorized" | "hold") and control_plane.reasons - the native Control Plane decision.
  executed vs uncertain  : result.outcome ("executed" | "held" | "refused" | "denied" | "uncertain" | "failed"); "uncertain" = UNKNOWN, reconcile only, no retry granted.
  native effect vs claim : the SQLite rows below and result.native.* are the native effect; result.execution_claim is the application's claim (supported=true only with an applied observation).
  producer-reported      : result.labels.evidence_basis = producer_reported; there is no independent verification in this stack.
  Replay                 : result.evidence.replay_state "imported" | "not_run" | "import_failed"; result.evidence.replay_note carries F1's reason verbatim (or null).
"""


def _summary(p: Path) -> str:
    try:
        r = json.loads(p.read_text())
        ev = r.get("evidence", {})
        return (f"outcome={r.get('outcome')} control_plane={r.get('control_plane', {}).get('result')} execution_claim.supported={r.get('execution_claim', {}).get('supported')} "
                f"native.disposition={r.get('native', {}).get('disposition')} replay_state={ev.get('replay_state')} replay_note={ev.get('replay_note')!r} "
                f"retry_permission={r.get('retry_permission')} effect_id={r.get('effect', {}).get('effect_id')}")
    except (OSError, ValueError, AttributeError):
        return "(not a Refund Desk result)"


def cmd_evidence(a):
    repo = Path(a.repo).resolve()
    ws = resolve_workspace(a.workspace, repo, mode="owned")
    raw = a.state
    if ".." in Path(raw).parts:
        raise Refused(f"state path must not contain '..': {raw!r}")
    st = Path(os.path.abspath(raw))
    base = ws / "state"
    if not (st == base or base in st.parents) or not st.is_dir() or os.path.realpath(st) != str(st):
        raise Refused(f"--state must be an existing real directory inside {base}: {raw!r}")
    say(f"Evidence index for {st}\n")
    kinds = [("result.json", "application JSON result"), ("cp_run_record-", "Control Plane run record (evidence copy)"), ("runtime_export-", "Runtime observation/export"),
             ("replay_bundle-", "Replay bundle"), (".lock", "lock file"), (".sqlite3-shm", "SQLite sidecar (shared memory; the digest of the main file may omit un-checkpointed WAL pages)"),
             (".sqlite3-wal", "SQLite sidecar (write-ahead log)"), (".sqlite3", "SQLite destination")]
    for p in sorted(x for x in st.rglob("*") if x.is_file() and not x.is_symlink()):
        kind = next((k for m, k in kinds if m in p.name), "Control Plane decision/run record" if p.parent.name == "cp" else "file")
        say(f"{kind}\n    path   : {p}\n    size   : {p.stat().st_size}\n    sha256 : {sha256_file(p)}")
        if p.name.endswith(".result.json"):
            say(f"    summary: {_summary(p)}")
    for db in sorted(st.rglob("*.sqlite3")):
        say(f"\nSQLite effects (opened read-only): {db}")
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute("SELECT * FROM effects ORDER BY effect_id")]
            con.close()
        except sqlite3.Error as exc:
            say(f"    could not read: {exc}")
            continue
        say(f"    {len(rows)} row(s)")
        for r in rows:
            say("    " + json.dumps(r, sort_keys=True))
    say("\n" + LEGEND)


# ---------------------------------------------------------------- cleanup
def cmd_cleanup(a):
    repo = Path(a.repo).resolve()
    ws = resolve_workspace(a.workspace, repo, mode="owned")
    if a.all:
        targets = [ws / "state", ws / "venv", ws / "stack", ws / RECORD, ws / MARKER]
    else:
        targets = [ws / "state"]
    for t in targets:
        if t.is_symlink():
            raise Refused(f"owned child is a symbolic link; refusing: {t}")
        if t.exists() and (t.is_dir() != (t.name in OWNED_DIRS)):
            raise Refused(f"owned child has an unexpected type; refusing: {t}")
    known = {t.name for t in (ws / n for n in (*OWNED_DIRS, RECORD, MARKER))}
    unknown = sorted(p.name for p in ws.iterdir() if p.name not in known)
    say("cleanup targets (exact):")
    for t in targets:
        say(f"  {'remove' if t.exists() else 'absent '}  {t}")
    if a.all:
        say(f"  then remove the workspace directory {ws} only if it is empty")
    if unknown:
        say("  never removed (not owned by this installation): " + ", ".join(str(ws / u) for u in unknown))
    if not a.yes:
        say("Nothing removed. Re-run with --yes to remove exactly the targets above.")
        return 3
    for t in targets:
        if not t.exists():
            continue
        try:
            shutil.rmtree(t) if t.is_dir() else t.unlink()
            say(f"removed {t}")
        except OSError as exc:
            raise Refused(f"cleanup failed at {t}: {exc!r} (earlier targets may already be removed)") from exc
    if a.all:
        try:
            ws.rmdir()
            say(f"removed {ws}")
        except OSError:
            say(f"kept {ws} (not empty)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="devtool.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pins", "check-workspace", "marker", "record", "env", "demo", "evidence", "cleanup"):
        sp = sub.add_parser(name)
        sp.add_argument("--repo", required=True)
        if name != "pins":
            sp.add_argument("--workspace", required=True)
        if name == "check-workspace":
            sp.add_argument("--mode", choices=("setup", "owned"), required=True)
        if name == "demo":
            sp.add_argument("--name", default="demo")
        if name == "evidence":
            sp.add_argument("--state", required=True)
        if name == "cleanup":
            g = sp.add_mutually_exclusive_group(required=True)
            g.add_argument("--all", action="store_true")
            g.add_argument("--state-only", action="store_true")
            sp.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    try:
        r = {"pins": cmd_pins, "check-workspace": cmd_check_workspace, "marker": cmd_marker, "record": cmd_record, "env": cmd_env, "demo": cmd_demo,
             "evidence": cmd_evidence, "cleanup": cmd_cleanup}[a.cmd](a)
        return int(r or 0)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
