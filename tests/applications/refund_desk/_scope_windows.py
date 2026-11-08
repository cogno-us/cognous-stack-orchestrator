"""Source-bound scope windows for the F3 PR-scope check (DEVELOPMENT ONLY test helper; Amendment R2 in applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md).

A window is (id, base, head, allowed): the paths changed between two named revisions must stay inside an explicit allowed set. Windows are declared here by
exact commit identity; there is no wildcard, default or catch-all window. A later authorized change must add its own window by a dated amendment
(recording its base and the head commit that closes the previous open window).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Window:
    id: str
    base: str
    head: str | None  # None = the open window: the current checkout
    allowed_prefixes: tuple[str, ...]  # directory prefixes, each ending in "/"
    allowed_files: tuple[str, ...] = ()  # exact files


# Original F3 implementation window (PR #156). CLOSED and immutable; allowed = the original rule, unchanged.
W_F3 = Window("W-F3", "09e1ba3d33aa64dd7054746838d16b64d868cf9f", "77701cfcc46d52658ffcec10b6a38516c82feeaf",
              ("applications/refund_desk/", "tests/applications/refund_desk/"))
# M1-1 window (PR #158): F1 package and its tests, plus the exact F3 files the authorized scope-test maintenance touches. F3 product code is NOT allowed.
W_M1_1 = Window("W-M1-1", "77701cfcc46d52658ffcec10b6a38516c82feeaf", None,
                ("orchestration/adapters/refund_disposition/", "tests/adapters/refund_disposition/"),
                ("applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md", "tests/applications/refund_desk/test_static.py",
                 "tests/applications/refund_desk/_scope_windows.py", "tests/applications/refund_desk/test_scope_windows.py"))
WINDOWS = (W_F3, W_M1_1)


def window_by_id(window_id: str) -> Window:
    for w in WINDOWS:
        if w.id == window_id:
            return w
    raise ValueError(f"undeclared scope window {window_id!r}")


def select_window(is_ancestor: Callable[[str], bool]) -> Window | None:
    """The LAST declared window whose base is an ancestor-or-equal of HEAD; None if no declared window applies (the caller must fail closed)."""
    for w in reversed(WINDOWS):
        if is_ancestor(w.base):
            return w
    return None


def scope_violations(paths, window: Window) -> list[str]:
    """Paths outside the window's explicit allowed set (sorted). Non-string, empty, absolute and parent-traversing paths are violations (fail closed)."""
    if not isinstance(window, Window):
        raise ValueError("a declared Window is required")
    bad: list[str] = []
    for p in paths:
        if not isinstance(p, str):
            bad.append(repr(p))
            continue
        if not p or p.startswith("/") or ".." in p.split("/"):
            bad.append(p)
            continue
        if p in window.allowed_files or any(p.startswith(prefix) for prefix in window.allowed_prefixes):
            continue
        bad.append(p)
    return sorted(bad)


def changed_paths(git: Callable[..., "subprocess.CompletedProcess"], base: str) -> set[str]:  # noqa: F821
    """Committed diff against `base` plus uncommitted and untracked paths of the current checkout."""
    diff = git("diff", "--name-only", "--no-renames", base)  # no rename detection: both sides of a rename must be reported
    status = git("status", "--porcelain", "--untracked-files=all")
    if diff.returncode != 0 or status.returncode != 0:
        raise RuntimeError(f"git failed: {diff.stderr or status.stderr}")
    paths = set(diff.stdout.split("\n"))
    for line in status.stdout.splitlines():
        paths.update(p.strip().strip('"') for p in line[3:].split(" -> "))
    paths.discard("")
    return paths
