"""G3 invocation-owned workspace lifecycle (DEVELOPMENT ONLY / SYNTHETIC). Q4 remediation (qualification PR #274 finding).

One unique workspace is allocated per invocation, its exact path is retained, and ONLY that path is removed. Removal is observable:
a failure is never swallowed (no ``ignore_errors``), absence is verified after removal, and a failed disposal is never reported as
successful. If the body already failed, that original failure is preserved and the cleanup failure is reported next to it.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

CLEANUP_FAILED_EXIT = 5


def dispose(work: Path) -> list[str]:
    """Remove exactly ``work`` (the directory this invocation allocated). Returns [] only when it is verifiably gone."""
    errors: list[str] = []
    if work.is_symlink():
        return [f"refused: {work} is a symlink, not the allocated directory"]
    try:
        shutil.rmtree(work)
    except BaseException as exc:  # noqa: BLE001 - any failure to dispose must be observable
        errors.append(f"rmtree({work}) failed: {exc!r}")
    if work.exists():
        errors.append(f"{work} still exists after removal")
    return errors


def run_in_owned_workspace(prefix: str, body, *, err=None) -> int:
    """Allocate a unique workspace, run ``body(work)``, then dispose of exactly that workspace.

    Returns the process exit code: 0 only when the body succeeded AND disposal is verified. If the body raised, the original exception
    is re-raised after the disposal outcome is reported (and annotated when disposal also failed)."""
    err = err or sys.stderr
    work = Path(tempfile.mkdtemp(prefix=prefix))  # unique, owned by THIS invocation; exact path retained
    primary: BaseException | None = None
    try:
        body(work)
    except BaseException as exc:  # noqa: BLE001 - preserved and re-raised below; cleanup must still run
        primary = exc
    cleanup_errors = dispose(work)
    if cleanup_errors:
        print("CLEANUP-FAILED (owned workspace not disposed): " + " | ".join(cleanup_errors), file=err)
        if primary is not None:
            print(f"PRIMARY-FAILURE (preserved): {primary!r}", file=err)
            primary.add_note("cleanup also failed: " + " | ".join(cleanup_errors))
    if primary is not None:
        raise primary
    if cleanup_errors:
        return CLEANUP_FAILED_EXIT
    print(f"WORKSPACE-DISPOSED {work}")
    return 0
