"""Shared support for the F1 developer checks. DEVELOPMENT ONLY / SYNTHETIC / builder-lineage; not independent qualification."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from orchestration.adapters.refund_disposition import (AuthorityFacts, DispositionRequest, RefundProposal, SyntheticEnvironment)  # noqa: E402
from orchestration.adapters.refund_disposition.stack import load_stack  # noqa: E402

AT = datetime(2026, 10, 5, 19, 0, tzinfo=timezone.utc)
AUTHORITY_ID = "urn:cognous:authority:g2-synthetic-refund-root-1"
FIXTURES = Path("institutional_governance/process/implementation/g2-cp-resolver-dev/fixtures")


def stack_root() -> Path | None:
    raw = os.environ.get("G3_STACK_ROOT")
    return Path(raw) if raw and (Path(raw) / "control_plane").is_dir() else None


def require_stack(case: unittest.TestCase) -> Path:
    root = stack_root()
    if root is None:
        if os.environ.get("F1_REQUIRE") == "1":
            case.fail("F1_REQUIRE=1 but G3_STACK_ROOT is not an assembled pinned stack root")
        case.skipTest("G3_STACK_ROOT not set (a skip is not a pass)")
    return root


def fixture(root: Path, name: str) -> dict:
    return json.loads((root / FIXTURES / name).read_text(encoding="utf-8"))


def make_request(root: Path, state_dir: Path, *, bundle: str = "root_lineage.json", correlation: str = "f1-check") -> DispositionRequest:
    return DispositionRequest(
        proposal=RefundProposal(tenant_id="tenant-alpha", customer_id="customer-001", refund_reason="duplicate", amount=50.0, unit="USD"),
        authority=AuthorityFacts(authority_id=AUTHORITY_ID, lineage_bundle=fixture(root, bundle), facts=fixture(root, "synthetic_facts.json")),
        correlation_id=correlation, evaluation_time=AT, environment=SyntheticEnvironment(stack_root=root, state_dir=state_dir))


def db_path(state_dir: Path) -> Path:
    return state_dir / "sqlite" / "refunds.sqlite3"


def effect_rows(state_dir: Path) -> list[dict]:
    """Independent read-only SQLite read (own connection, read-only URI)."""
    db = db_path(state_dir)
    if not db.exists():
        return []
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM effects ORDER BY effect_id")]


def grant_rows(state_dir: Path) -> list[dict]:
    db = db_path(state_dir)
    if not db.exists():
        return []
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM effective_grants_v1")]


@contextmanager
def native_counters(root: Path):
    """Independent call counters on the NATIVE Runtime executor and destination commit (not the adapter's self-report)."""
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


def sha256_file(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
