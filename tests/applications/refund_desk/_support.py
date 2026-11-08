"""Shared support for the Refund Desk (F3) developer checks.

DEVELOPMENT ONLY / SYNTHETIC / test-owner developer checks, NOT independent qualification.
Expectations are frozen in applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md.

Test-owned measurement (native call counters, read-only SQLite reads, the F1 test-only fault fixture) lives here and never in the application.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
APP_ROOT = REPO / "applications" / "refund_desk"
APP_PKG = APP_ROOT / "refund_desk"
FIXTURES = APP_PKG / "fixtures"
F1_TESTS = REPO / "tests" / "adapters" / "refund_disposition"
for _p in (str(REPO), str(APP_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

AUTHORITY_ID = "urn:cognous:authority:harborview-refund-desk-1"
TENANT = "harborview-retail"
CUSTOMER = "customer-001"

CASE_A = dict(case_id="HV-2026-1102-0001", tenant_id=TENANT, customer_account=CUSTOMER, amount=64.25, reason="damaged_item", authority="valid")
CASE_B = dict(case_id="HV-2026-1102-0002", tenant_id=TENANT, customer_account=CUSTOMER, amount=64.25, reason="damaged_item", authority="revoked")
CASE_C = dict(case_id="HV-2026-1102-0003", tenant_id=TENANT, customer_account=CUSTOMER, amount=31.10, reason="late_delivery", authority="valid")


def stack_root() -> Path | None:
    raw = os.environ.get("F3_STACK_ROOT") or os.environ.get("G3_STACK_ROOT")
    return Path(raw) if raw and (Path(raw) / "control_plane").is_dir() else None


def require_stack(case: unittest.TestCase) -> Path:
    """Fail when F3_REQUIRE=1 and no assembled stack root is given; otherwise skip (a skip is not a pass)."""
    root = stack_root()
    if root is None:
        if os.environ.get("F3_REQUIRE") == "1":
            case.fail("F3_REQUIRE=1 but neither F3_STACK_ROOT nor G3_STACK_ROOT is an assembled pinned stack root")
        case.skipTest("F3_STACK_ROOT/G3_STACK_ROOT not set (a skip is not a pass)")
    return root


def tempdir(prefix: str):
    return tempfile.TemporaryDirectory(prefix=prefix)


def db_path(state_dir: Path) -> Path:
    return Path(state_dir) / "sqlite" / "refunds.sqlite3"


def effect_rows(state_dir: Path) -> list[dict]:
    """Independent read-only SQLite read (own connection, read-only URI)."""
    db = db_path(state_dir)
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM effects ORDER BY effect_id")]
    finally:
        conn.close()


def sha256_file(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def all_files(state_dir: Path) -> list[str]:
    return sorted(str(p.relative_to(state_dir)) for p in Path(state_dir).rglob("*") if p.is_file())


@contextmanager
def native_counters(root: Path):
    """Independent call counters on the NATIVE Runtime executor `execute` and destination `commit` (test-owned measurement)."""
    from orchestration.adapters.refund_disposition.stack import load_stack

    S = load_stack(root)
    counts = {"execute": 0, "commit": 0}
    real_execute = S.engine_adapter.PinnedControlPlaneExecutor.execute
    real_commit = S.engine_safe_executor.DurableRefundDestination.commit

    def execute(self, *a, **k):
        counts["execute"] += 1
        return real_execute(self, *a, **k)

    def commit(self, *a, **k):
        counts["commit"] += 1
        return real_commit(self, *a, **k)

    with mock.patch.object(S.engine_adapter.PinnedControlPlaneExecutor, "execute", execute), \
            mock.patch.object(S.engine_safe_executor.DurableRefundDestination, "commit", commit):
        yield counts


def make_case(spec: dict):
    from refund_desk import RefundCase

    return RefundCase(**spec)


def make_config(root: Path, state_dir: Path):
    from refund_desk import DeskConfig

    return DeskConfig(stack_root=Path(root), state_dir=Path(state_dir))


def build_f1_request_for_case_c(root: Path, state_dir: Path):
    """Test-owned F1 request for Case C built from the app's SHIPPED fixtures (not through the application)."""
    from orchestration.adapters.refund_disposition import (AuthorityFacts, DispositionRequest, RefundProposal, SyntheticEnvironment)

    facts = fixture_json("authority_facts.json")
    return DispositionRequest(
        proposal=RefundProposal(tenant_id=CASE_C["tenant_id"], customer_id=CASE_C["customer_account"], refund_reason=CASE_C["reason"],
                                amount=CASE_C["amount"], unit="USD"),
        authority=AuthorityFacts(authority_id=AUTHORITY_ID, lineage_bundle=fixture_json("authority_valid.json"), facts=facts),
        correlation_id=CASE_C["case_id"],
        evaluation_time=datetime.fromisoformat(facts["evaluation"]["observed_at"]),
        environment=SyntheticEnvironment(stack_root=Path(root), state_dir=Path(state_dir)))


def f1_unknown_for_case_c(case: unittest.TestCase, root: Path, state_dir: Path):
    """Produce the genuine F1 UNKNOWN using the F1 TEST-TREE fault fixture; assert it really is `unknown` first."""
    if str(F1_TESTS) not in sys.path:
        sys.path.append(str(F1_TESTS))
    import _fault_injection as F

    u = F.dispose_with_lost_ack_unavailable_observation(build_f1_request_for_case_c(root, state_dir))
    case.assertEqual(u.disposition, "unknown", u)
    return u


def run_cli(args: list[str], *, root: Path | None, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Run `python3 -m refund_desk ...` from the repo root in a subprocess."""
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{REPO}{os.pathsep}{APP_ROOT}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("REFUND_DESK_STACK_ROOT", None)
    if root is not None:
        env["REFUND_DESK_STACK_ROOT"] = str(root)
    env.update(extra_env or {})
    return subprocess.run([sys.executable, "-m", "refund_desk", *args], cwd=str(REPO), env=env, capture_output=True, text=True, timeout=300)


def cli_args(command: str, spec: dict, state_dir: Path) -> list[str]:
    return [command, "--case-id", spec["case_id"], "--tenant", spec["tenant_id"], "--customer-account", spec["customer_account"],
            "--amount", str(spec["amount"]), "--reason", spec["reason"], "--authority", spec["authority"], "--state-dir", str(state_dir)]


def key_shape(value):
    """Recursive key structure of a JSON value (dict keys; lists collapse to the shape of their first element)."""
    if isinstance(value, dict):
        return {k: key_shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [key_shape(value[0])] if value else []
    return None
