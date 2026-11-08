"""Regression R3 for the F3 scope windows after M1-2 (DEVELOPMENT ONLY developer regression; NOT independent qualification).

Expectations frozen in applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md Amendment M2 (M2.5, commit bd3da90) BEFORE the helper change.
Stack-free: pure path classification, read-only git checks of immutable revisions, and a throwaway git repository for the rename case.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _HERE / filename)
    mod = sys.modules.get(name) or importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    if not hasattr(mod, "__loaded_marker__"):
        mod.__loaded_marker__ = True
        spec.loader.exec_module(mod)
    return mod


W = _load("_refund_desk_scope_windows", "_scope_windows.py")
REPO = _HERE.parents[2]
M1_1_MERGE = "2d4999b752e53d26f1a5e89b2310e9417d931043"
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def git(*args):
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)


def have_commits(*shas) -> bool:
    return shutil.which("git") is not None and (REPO / ".git").exists() and all(git("cat-file", "-e", f"{s}^{{commit}}").returncode == 0 for s in shas)


class M12Windows(unittest.TestCase):
    def test_r3_1_m1_1_window_is_closed_at_its_integration_commit(self):
        self.assertEqual(W.W_M1_1.head, M1_1_MERGE)
        if not have_commits(W.W_M1_1.base, W.W_M1_1.head):
            self.skipTest("window commits are not present in this checkout (a skip is not a pass)")
        out = git("diff", "--name-only", "--no-renames", W.W_M1_1.base, W.W_M1_1.head)
        self.assertEqual(out.returncode, 0, out.stderr)
        paths = [p for p in out.stdout.split("\n") if p]
        self.assertTrue(paths)
        self.assertEqual(W.scope_violations(paths, W.W_M1_1), [], "the closed M1-1 window left its allowed paths")

    def test_r3_2_window_declaration_and_selection(self):
        # lifecycle advanced in M1-3 (Amendment M3.6): W-M1-2 is now CLOSED at the PR #159 merge and W-M1-3 is the open last window (originals in git history)
        self.assertEqual([w.id for w in W.WINDOWS], ["W-F3", "W-M1-1", "W-M1-2", "W-M1-3", "W-M1-4", "W-M1-5"])
        self.assertEqual(W.W_M1_2.base, M1_1_MERGE)
        self.assertEqual(W.W_M1_2.head, "ffd97cda085ea9afd5bf14a9c3de4c9d0ae0f2b1")
        self.assertEqual([w.id for w in W.WINDOWS if w.head is None], ["W-M1-5"], "exactly one open window, and it is the last one")
        for w in W.WINDOWS:
            self.assertRegex(w.base, HEX40)
            if w.head is not None:
                self.assertRegex(w.head, HEX40)
        self.assertIs(W.select_window(lambda sha: True), W.W_M1_5)
        self.assertIs(W.select_window(lambda sha: sha in (W.W_F3.base, W.W_M1_1.base)), W.W_M1_1)
        self.assertIs(W.select_window(lambda sha: sha == W.W_F3.base), W.W_F3)
        self.assertIsNone(W.select_window(lambda sha: False))
        self.assertIs(W.window_by_id("W-M1-2"), W.W_M1_2)
        with self.assertRaises(ValueError):
            W.window_by_id("W-M1-6")

    def test_r3_3_f3_product_allowed_but_f1_native_and_workflows_are_violations_in_m1_2(self):
        allowed = ["applications/refund_desk/refund_desk/desk.py", "applications/refund_desk/refund_desk/cli.py",
                   "applications/refund_desk/refund_desk/fixtures/profiles/refund-high-v1/authority_facts.json",
                   "applications/refund_desk/README.md", "applications/refund_desk/SOURCES.json", "applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md",
                   "tests/applications/refund_desk/test_m12_checks.py", "tests/applications/refund_desk/_scope_windows.py"]
        self.assertEqual(W.scope_violations(allowed, W.W_M1_2), [])
        forbidden = ["orchestration/adapters/refund_disposition/dispose.py", "orchestration/adapters/refund_disposition/profiles.py",
                     "tests/adapters/refund_disposition/test_m11_checks.py", ".github/workflows/x.yml", "orchestration/workflow_machine/x.py",
                     "control_plane/x.py", "runtime/x.py", "tests/manual_contract/g3_refund/g3_capture.py", "applications/other/x.py",
                     "applications/refund_desk_other/x.py", "tests/applications/refund_desk_other/x.py", "README.md", "../x", "/abs/x", ""]
        self.assertEqual(W.scope_violations(forbidden, W.W_M1_2), sorted(forbidden))

    def test_r3_4_predecessor_window_detections_still_work(self):
        self.assertEqual(W.scope_violations(["orchestration/adapters/refund_disposition/dispose.py"], W.W_F3), ["orchestration/adapters/refund_disposition/dispose.py"])
        self.assertEqual(W.scope_violations(["applications/refund_desk/refund_desk/desk.py"], W.W_M1_1), ["applications/refund_desk/refund_desk/desk.py"])
        self.assertEqual(W.scope_violations(["orchestration/adapters/refund_disposition/profiles.py"], W.W_M1_1), [])

    def test_r3_5_rename_evasion_is_still_caught_in_m1_2(self):
        if shutil.which("git") is None:
            self.skipTest("git is unavailable (a skip is not a pass)")
        with tempfile.TemporaryDirectory(prefix="r3-5-") as td:
            def g(*a):
                return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *a], cwd=td, capture_output=True, text=True)
            self.assertEqual(g("init", "-q").returncode, 0)
            body = "".join(f"line {i} of the F1 implementation file\n" for i in range(40))
            for rel in ("orchestration/adapters/refund_disposition/dispose.py", "applications/refund_desk/refund_desk/desk.py"):
                p = Path(td) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body)
            g("add", "-A")
            self.assertEqual(g("commit", "-q", "-m", "base").returncode, 0)
            base = g("rev-parse", "HEAD").stdout.strip()
            (Path(td) / "applications/refund_desk/refund_desk/fixtures").mkdir(parents=True, exist_ok=True)
            self.assertEqual(g("mv", "orchestration/adapters/refund_disposition/dispose.py", "applications/refund_desk/refund_desk/fixtures/dispose_moved.py").returncode, 0)
            self.assertEqual(g("commit", "-q", "-m", "move an F1 file into the allowed F3 directory").returncode, 0)
            paths = W.changed_paths(g, base)
            self.assertIn("orchestration/adapters/refund_disposition/dispose.py", paths)
            self.assertEqual(W.scope_violations(sorted(paths), W.W_M1_2), ["orchestration/adapters/refund_disposition/dispose.py"])


if __name__ == "__main__":
    unittest.main()
