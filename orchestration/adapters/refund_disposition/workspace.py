"""Adapter-owned scratch workspace (DEVELOPMENT ONLY / SYNTHETIC).

Each call allocates ONE unique scratch directory and later removes exactly that path. It never globs, never touches the caller-owned
state directory, refuses a symlink in place of the allocated directory, verifies absence afterwards and reports any failure. A failed
disposal is returned to the caller; it is never silent and never reported as success. (Same discipline as the Q4 remediation in
tests/manual_contract/g3_refund/g3_cleanup.py, re-implemented here because that module is frozen G3 evidence.)
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .contract import CleanupReport

PREFIX = "f1-refund-disposition-"


def allocate() -> Path:
    return Path(tempfile.mkdtemp(prefix=PREFIX))


def dispose(work: Path | None) -> CleanupReport:
    """Remove exactly `work`. `ok` is True only when the directory is verifiably gone."""
    if work is None:
        return CleanupReport(ok=True, scratch_path=None)
    errors: list[str] = []
    if work.is_symlink():
        return CleanupReport(ok=False, scratch_path=str(work), errors=(f"refused: {work} is a symlink, not the allocated directory",))
    try:
        shutil.rmtree(work)
    except BaseException as exc:  # noqa: BLE001 - any failure to dispose must be observable
        errors.append(f"rmtree({work}) failed: {exc!r}")
    if work.exists():
        errors.append(f"{work} still exists after removal")
    return CleanupReport(ok=not errors, scratch_path=str(work), errors=tuple(errors))
