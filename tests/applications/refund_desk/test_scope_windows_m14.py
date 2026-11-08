"""M1-4 scope-window regressions R5.1-R5.4 (Amendment M4.9). DEVELOPMENT ONLY test-owner checks."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_refund_desk_scope_windows", Path(__file__).with_name("_scope_windows.py"))
W = sys.modules.get("_refund_desk_scope_windows") or importlib.util.module_from_spec(_spec)
sys.modules["_refund_desk_scope_windows"] = W
if not hasattr(W, "WINDOWS"):
    _spec.loader.exec_module(W)

REPO = Path(__file__).resolve().parents[3]
M1_3_MERGE = "41ac5f32d2d685e3f74a1ca828b0bef9e02de974"
M1_2_MERGE = "ffd97cda085ea9afd5bf14a9c3de4c9d0ae0f2b1"


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True)


class M14Windows(unittest.TestCase):
    def test_r5_1_declaration_and_closure(self):
        self.assertEqual([w.id for w in W.WINDOWS], ["W-F3", "W-M1-1", "W-M1-2", "W-M1-3", "W-M1-4"])
        self.assertEqual(W.W_M1_3.head, M1_3_MERGE)
        self.assertEqual(W.W_M1_3.base, M1_2_MERGE)
        self.assertEqual(W.W_M1_4.base, M1_3_MERGE)
        self.assertIsNone(W.W_M1_4.head)
        self.assertEqual([w.id for w in W.WINDOWS if w.head is None], ["W-M1-4"])
        self.assertIs(W.select_window(lambda sha: True), W.W_M1_4)
        self.assertIs(W.select_window(lambda sha: sha != M1_3_MERGE), W.W_M1_3)
        self.assertIs(W.window_by_id("W-M1-4"), W.W_M1_4)
        with self.assertRaises(ValueError):
            W.window_by_id("W-M1-5")

    def test_r5_2_closed_m1_3_range_stays_inside_its_allowed_set(self):
        if shutil.which("git") is None or git("cat-file", "-e", f"{M1_3_MERGE}^{{commit}}").returncode != 0:
            self.skipTest("window commits are not present in this checkout (a skip is not a pass)")
        out = git("diff", "--name-only", "--no-renames", W.W_M1_3.base, W.W_M1_3.head)
        self.assertEqual(out.returncode, 0, out.stderr)
        paths = [p for p in out.stdout.split("\n") if p]
        self.assertTrue(paths)
        self.assertEqual(W.scope_violations(paths, W.W_M1_3), [])

    def test_r5_3_only_the_declared_installation_paths_are_allowed(self):
        allowed = ["development/refund-desk-local/dev.sh", "development/refund-desk-local/devtool.py", "development/refund-desk-local/README.md",
                   "applications/refund_desk/README.md", "applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md",
                   "tests/applications/refund_desk/test_m14_install.py", "tests/applications/refund_desk/_scope_windows.py"]
        self.assertEqual(W.scope_violations(allowed, W.W_M1_4), [])
        forbidden = ["applications/refund_desk/refund_desk/desk.py", "applications/refund_desk/refund_desk/cli.py",
                     "applications/refund_desk/refund_desk/fixtures/authority_facts.json", "applications/refund_desk/SOURCES.json",
                     "orchestration/adapters/refund_disposition/dispose.py", "orchestration/adapters/refund_disposition/profiles.py",
                     "tests/adapters/refund_disposition/_fault_injection.py", ".github/workflows/x.yml", ".github/locks/x.txt", "control_plane/x.py",
                     "development/README.md", "development/refund-desk-local-other/x.sh", "development/refund-desk-local", "README.md",
                     "../x", "/abs/x", ""]
        self.assertEqual(W.scope_violations(forbidden, W.W_M1_4), sorted(forbidden))

    def test_r5_4_predecessor_detections_unchanged(self):
        self.assertEqual(W.scope_violations(["development/refund-desk-local/dev.sh"], W.W_M1_3), ["development/refund-desk-local/dev.sh"])
        self.assertEqual(W.scope_violations(["applications/refund_desk/refund_desk/desk.py"], W.W_M1_3), [])
        self.assertEqual(W.scope_violations(["applications/refund_desk/refund_desk/desk.py"], W.W_M1_4), ["applications/refund_desk/refund_desk/desk.py"])
        self.assertEqual(W.scope_violations(["orchestration/adapters/refund_disposition/dispose.py"], W.W_M1_2), ["orchestration/adapters/refund_disposition/dispose.py"])


if __name__ == "__main__":
    unittest.main()
