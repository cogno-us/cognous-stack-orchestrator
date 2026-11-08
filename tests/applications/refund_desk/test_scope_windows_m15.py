"""M1-5 scope-window regressions R6.1-R6.3 (documentation-only acceptance package). DEVELOPMENT ONLY test-owner checks."""
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
M1_4_MERGE = "41f651d27e159f7b348e87f83475bf1bda7a6214"
M1_3_MERGE = "41ac5f32d2d685e3f74a1ca828b0bef9e02de974"


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True)


class M15Windows(unittest.TestCase):
    def test_r6_1_declaration_and_closure(self):
        self.assertEqual([w.id for w in W.WINDOWS], ["W-F3", "W-M1-1", "W-M1-2", "W-M1-3", "W-M1-4", "W-M1-5"])
        self.assertEqual(W.W_M1_4.base, M1_3_MERGE)
        self.assertEqual(W.W_M1_4.head, M1_4_MERGE)
        self.assertEqual(W.W_M1_5.base, M1_4_MERGE)
        self.assertIsNone(W.W_M1_5.head)
        self.assertEqual([w.id for w in W.WINDOWS if w.head is None], ["W-M1-5"])
        self.assertIs(W.select_window(lambda sha: True), W.W_M1_5)
        self.assertIs(W.window_by_id("W-M1-5"), W.W_M1_5)
        with self.assertRaises(ValueError):
            W.window_by_id("W-M1-6")

    def test_r6_2_closed_m1_4_range_stays_inside_its_allowed_set(self):
        if shutil.which("git") is None or git("cat-file", "-e", f"{M1_4_MERGE}^{{commit}}").returncode != 0:
            self.skipTest("window commits are not present in this checkout (a skip is not a pass)")
        out = git("diff", "--name-only", "--no-renames", W.W_M1_4.base, W.W_M1_4.head)
        self.assertEqual(out.returncode, 0, out.stderr)
        paths = [p for p in out.stdout.split("\n") if p]
        self.assertTrue(paths)
        self.assertEqual(W.scope_violations(paths, W.W_M1_4), [])

    def test_r6_3_only_the_acceptance_package_and_tests_are_allowed(self):
        allowed = ["docs/acceptance/ocs-m1-core-local-0.1-dev/README.md", "docs/acceptance/ocs-m1-core-local-0.1-dev/evidence/verify_ocs07_readonly.py",
                   "tests/applications/refund_desk/test_scope_windows_m15.py", "tests/applications/refund_desk/_scope_windows.py"]
        self.assertEqual(W.scope_violations(allowed, W.W_M1_5), [])
        forbidden = ["development/refund-desk-local/dev.sh", "applications/refund_desk/refund_desk/desk.py", "applications/refund_desk/README.md",
                     "applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md", "applications/refund_desk/SOURCES.json",
                     "orchestration/adapters/refund_disposition/dispose.py", ".github/workflows/x.yml", ".github/locks/x.txt", "docs/README.md",
                     "docs/acceptance/other/x.md", "docs/acceptance/ocs-m1-core-local-0.1-dev", "docs/acceptance/ocs-m1-core-local-0.1-dev-x/y.md",
                     "README.md", "../x", "/abs/x", ""]
        self.assertEqual(W.scope_violations(forbidden, W.W_M1_5), sorted(forbidden))
        self.assertEqual(W.scope_violations(["docs/acceptance/ocs-m1-core-local-0.1-dev/README.md"], W.W_M1_4),
                         ["docs/acceptance/ocs-m1-core-local-0.1-dev/README.md"])


if __name__ == "__main__":
    unittest.main()
