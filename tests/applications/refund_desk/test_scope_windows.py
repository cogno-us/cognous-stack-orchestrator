"""Regression R2 for the F3 PR-scope check's applicability (DEVELOPMENT ONLY / developer regression; NOT independent qualification).

Expectations frozen in applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md Amendment R2 (commit ac12389) BEFORE this file and the helper existed.
Stack-free: pure path classification plus read-only git checks of immutable revisions.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
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
F3_APP = "applications/refund_desk/refund_desk/desk.py"


def git(*args):
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)


def have_commits(*shas) -> bool:
    return shutil.which("git") is not None and (REPO / ".git").exists() and all(git("cat-file", "-e", f"{s}^{{commit}}").returncode == 0 for s in shas)


class WindowRules(unittest.TestCase):
    def test_r2_1_original_historical_violation_still_detected(self):
        # an F1 change inside the F3 implementation window is a violation, exactly as the original rule required
        self.assertEqual(W.scope_violations(["orchestration/adapters/refund_disposition/dispose.py"], W.W_F3),
                         ["orchestration/adapters/refund_disposition/dispose.py"])
        self.assertEqual(W.scope_violations(["tests/adapters/refund_disposition/test_m11_checks.py"], W.W_F3), ["tests/adapters/refund_disposition/test_m11_checks.py"])
        self.assertEqual(W.scope_violations(["applications/refund_desk/refund_desk/desk.py", "tests/applications/refund_desk/test_checks.py"], W.W_F3), [])

    def test_r2_2_legitimate_m1_1_f1_only_change_is_not_an_f3_violation(self):
        legit = ["orchestration/adapters/refund_disposition/profiles.py", "orchestration/adapters/refund_disposition/dispose.py",
                 "tests/adapters/refund_disposition/test_m11_checks.py", "tests/adapters/refund_disposition/m11_fixtures/high_facts.json",
                 "applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md", "tests/applications/refund_desk/test_static.py",
                 "tests/applications/refund_desk/_scope_windows.py", "tests/applications/refund_desk/test_scope_windows.py"]
        self.assertEqual(W.scope_violations(legit, W.W_M1_1), [])
        # window selection by explicit source identity
        self.assertIs(W.select_window(lambda sha: True), W.W_M1_1)  # 77701cf is an ancestor-or-equal of HEAD
        self.assertIs(W.select_window(lambda sha: sha == W.W_F3.base), W.W_F3)  # only 09e1ba3 is
        self.assertIsNone(W.select_window(lambda sha: False))  # neither: no declared window applies -> caller must fail closed

    def test_r2_3_forbidden_f3_implementation_and_unrelated_changes_still_fail(self):
        forbidden = [F3_APP, "applications/refund_desk/refund_desk/cli.py", "applications/refund_desk/refund_desk/fixtures/authority_facts.json",
                     "applications/refund_desk/README.md", "applications/refund_desk/SOURCES.json", "applications/refund_desk/refund_desk/__init__.py",
                     ".github/workflows/x.yml", "orchestration/workflow_machine/x.py", "control_plane/x.py", "tests/manual_contract/g3_refund/g3_capture.py",
                     "tests/applications/refund_desk/test_checks.py", "tests/applications/refund_desk/_support.py"]
        self.assertEqual(W.scope_violations(forbidden, W.W_M1_1), sorted(forbidden))
        # under the closed F3 window anything that is not an F3 path is a violation
        self.assertEqual(W.scope_violations([".github/workflows/x.yml", "README.md"], W.W_F3), [".github/workflows/x.yml", "README.md"])
        # no wildcard / prefix trick: a sibling directory with the same textual prefix is outside the allowed prefix
        self.assertEqual(W.scope_violations(["applications/refund_desk_other/x.py", "tests/adapters/refund_disposition_x/y.py"], W.W_M1_1),
                         ["applications/refund_desk_other/x.py", "tests/adapters/refund_disposition_x/y.py"])

    def test_fail_closed_inputs(self):
        for bad in ("", None, 5, "../x", "/abs/x"):
            self.assertEqual(W.scope_violations([bad], W.W_M1_1), [bad if isinstance(bad, str) else repr(bad)] if bad != "" else [""])
        with self.assertRaises(ValueError):
            W.scope_violations(["a"], None)
        with self.assertRaises(ValueError):
            W.window_by_id("W-UNDECLARED")
        self.assertEqual([w.id for w in W.WINDOWS], ["W-F3", "W-M1-1"])
        self.assertTrue(all(isinstance(w.base, str) and len(w.base) == 40 for w in W.WINDOWS))


class LiveWindows(unittest.TestCase):
    def test_r2_4_closed_f3_window_contains_only_f3_paths(self):
        if not have_commits(W.W_F3.base, W.W_F3.head):
            self.skipTest("window commits are not present in this checkout (a skip is not a pass)")
        out = git("diff", "--name-only", W.W_F3.base, W.W_F3.head)
        self.assertEqual(out.returncode, 0, out.stderr)
        paths = [p for p in out.stdout.split("\n") if p]
        self.assertTrue(paths, "the F3 window cannot be empty")
        self.assertEqual(W.scope_violations(paths, W.W_F3), [])

    def test_r2_5_current_checkout_is_inside_its_selected_window(self):
        if not have_commits(W.W_F3.base, W.W_M1_1.base):
            self.skipTest("window base commits are not present in this checkout (a skip is not a pass)")
        win = W.select_window(lambda sha: git("merge-base", "--is-ancestor", sha, "HEAD").returncode == 0)
        self.assertIsNotNone(win, "HEAD descends from no declared window base: a new window must be declared by a dated amendment")
        paths = W.changed_paths(lambda *a: git(*a), win.base)
        self.assertEqual(W.scope_violations(sorted(paths), win), [], f"paths outside window {win.id}")


if __name__ == "__main__":
    unittest.main()
