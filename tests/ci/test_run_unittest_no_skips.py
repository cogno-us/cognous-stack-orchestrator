import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

GUARD = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "run_unittest_no_skips.py"


def run_guard(case_body, env_extra=None, extra_args=()):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "test_case.py").write_text(textwrap.dedent(case_body))
        env = {k: v for k, v in os.environ.items() if k != "GUARD_TEST_ROOT"}
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, "-B", str(GUARD), tmp, *extra_args],
            capture_output=True, text=True, env=env,
        )


PASSING = """
import unittest
class T(unittest.TestCase):
    def test_ok(self):
        pass
"""
SKIPPING = """
import unittest
class T(unittest.TestCase):
    def test_ok(self):
        pass
    @unittest.skip("nope")
    def test_skipped(self):
        pass
"""
FAILING = """
import unittest
class T(unittest.TestCase):
    def test_bad(self):
        self.fail("x")
"""


class NoSkipGuardTests(unittest.TestCase):
    def test_passing_run_exits_zero(self):
        self.assertEqual(run_guard(PASSING).returncode, 0)

    def test_any_skip_fails_closed(self):
        got = run_guard(SKIPPING)
        self.assertEqual(got.returncode, 3)
        self.assertIn("skipped", got.stderr)

    def test_failure_exits_nonzero(self):
        self.assertNotEqual(run_guard(FAILING).returncode, 0)

    def test_zero_tests_fails(self):
        self.assertEqual(run_guard("x = 1\n").returncode, 1)

    def test_required_env_unset_fails(self):
        got = run_guard(PASSING, extra_args=["--require-env", "GUARD_TEST_ROOT"])
        self.assertEqual(got.returncode, 2)

    def test_required_env_not_a_directory_fails(self):
        got = run_guard(PASSING, {"GUARD_TEST_ROOT": "/nonexistent-dir"},
                        ["--require-env", "GUARD_TEST_ROOT"])
        self.assertEqual(got.returncode, 2)

    def test_required_env_directory_passes(self):
        with tempfile.TemporaryDirectory() as root:
            got = run_guard(PASSING, {"GUARD_TEST_ROOT": root},
                            ["--require-env", "GUARD_TEST_ROOT"])
        self.assertEqual(got.returncode, 0)


if __name__ == "__main__":
    unittest.main()
