"""M1-3 scope-window regressions R4.1-R4.4 (Amendment M3.6). DEVELOPMENT ONLY test-owner checks."""
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
M1_2_MERGE = "ffd97cda085ea9afd5bf14a9c3de4c9d0ae0f2b1"
M1_1_MERGE = "2d4999b752e53d26f1a5e89b2310e9417d931043"


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True)


class M13Windows(unittest.TestCase):
    def test_r4_1_declaration_and_closure(self):
        self.assertEqual([w.id for w in W.WINDOWS], ["W-F3", "W-M1-1", "W-M1-2", "W-M1-3", "W-M1-4", "W-M1-5"])
        self.assertEqual(W.W_M1_2.head, M1_2_MERGE)
        self.assertEqual(W.W_M1_2.base, M1_1_MERGE)
        self.assertEqual(W.W_M1_3.base, M1_2_MERGE)
        self.assertEqual(W.W_M1_3.head, "41ac5f32d2d685e3f74a1ca828b0bef9e02de974")  # closed in M1-4 (Amendment M4.9)
        self.assertEqual([w.id for w in W.WINDOWS if w.head is None], ["W-M1-5"], "exactly one open window, the last")
        self.assertIs(W.select_window(lambda sha: True), W.W_M1_5)
        self.assertIs(W.select_window(lambda sha: sha not in (M1_2_MERGE, "41ac5f32d2d685e3f74a1ca828b0bef9e02de974", "41f651d27e159f7b348e87f83475bf1bda7a6214")), W.W_M1_2)  # lifecycle advanced in M1-4: W-M1-3 and W-M1-4 bases are also excluded
        self.assertIs(W.window_by_id("W-M1-3"), W.W_M1_3)
        with self.assertRaises(ValueError):
            W.window_by_id("W-M1-6")

    def test_r4_2_closed_m1_2_range_stays_inside_its_allowed_set(self):
        if shutil.which("git") is None or git("cat-file", "-e", f"{M1_2_MERGE}^{{commit}}").returncode != 0:
            self.skipTest("window commits are not present in this checkout (a skip is not a pass)")
        out = git("diff", "--name-only", "--no-renames", W.W_M1_2.base, W.W_M1_2.head)
        self.assertEqual(out.returncode, 0, out.stderr)
        paths = [p for p in out.stdout.split("\n") if p]
        self.assertTrue(paths)
        self.assertEqual(W.scope_violations(paths, W.W_M1_2), [])

    def test_r4_3_only_the_exact_f3_correction_files_are_allowed(self):
        allowed = ["applications/refund_desk/refund_desk/desk.py", "applications/refund_desk/README.md",
                   "applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md", "tests/applications/refund_desk/test_m13_checks.py",
                   "tests/applications/refund_desk/_scope_windows.py"]
        self.assertEqual(W.scope_violations(allowed, W.W_M1_3), [])
        forbidden = ["applications/refund_desk/refund_desk/cli.py", "applications/refund_desk/refund_desk/__init__.py",
                     "applications/refund_desk/refund_desk/fixtures/authority_facts.json", "applications/refund_desk/SOURCES.json",
                     "orchestration/adapters/refund_disposition/dispose.py", "orchestration/adapters/refund_disposition/profiles.py",
                     "tests/adapters/refund_disposition/test_m11_checks.py", ".github/workflows/x.yml", "control_plane/x.py", "runtime/x.py",
                     "applications/refund_desk/README.md.bak", "applications/refund_desk_other/x.py", "tests/applications/refund_desk_other/x.py",
                     "README.md", "../x", "/abs/x", ""]
        self.assertEqual(W.scope_violations(forbidden, W.W_M1_3), sorted(forbidden))

    def test_r4_4_predecessor_detections_unchanged(self):
        self.assertEqual(W.scope_violations(["orchestration/adapters/refund_disposition/dispose.py"], W.W_M1_2),
                         ["orchestration/adapters/refund_disposition/dispose.py"])
        self.assertEqual(W.scope_violations(["applications/refund_desk/refund_desk/cli.py"], W.W_M1_2), [])
        self.assertEqual(W.scope_violations(["applications/refund_desk/refund_desk/desk.py"], W.W_M1_1), ["applications/refund_desk/refund_desk/desk.py"])


if __name__ == "__main__":
    unittest.main()
