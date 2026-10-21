#!/usr/bin/env python3
"""Run unittest discovery and fail closed on any skipped test (E-9).

The pinned-upstream attestation integration tests skip silently unless
COGNOUS_EVIDENCE_ATTESTATION_ROOT points at a checkout. This runner makes a
skip a job failure so a green job means the upstream tests actually ran.

Usage: run_unittest_no_skips.py START_DIR [--require-env NAME]...
Exit 0 only if tests ran, none failed or errored, none were skipped, and every
required environment variable names an existing directory.
"""
import argparse
import os
import sys
import unittest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("start_dir")
    parser.add_argument("--pattern", default="test_*.py")
    parser.add_argument("--require-env", action="append", default=[])
    args = parser.parse_args(argv)
    # `python -m unittest` puts the working directory on sys.path; keep that.
    sys.path.insert(0, os.getcwd())

    for name in args.require_env:
        value = os.environ.get(name, "")
        if not value or not os.path.isdir(value):
            print(f"FAIL: {name} is unset or not a directory", file=sys.stderr)
            return 2

    suite = unittest.defaultTestLoader.discover(args.start_dir, pattern=args.pattern)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.testsRun == 0:
        print("FAIL: no tests ran", file=sys.stderr)
        return 1
    if not result.wasSuccessful():
        return 1
    if result.skipped:
        print(f"FAIL: {len(result.skipped)} test(s) skipped; skips are not accepted:", file=sys.stderr)
        for test, reason in result.skipped:
            print(f"  {test}: {reason}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
