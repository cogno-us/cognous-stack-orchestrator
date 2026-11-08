"""Refund Desk (F3) static scope checks (no stack required).

DEVELOPMENT ONLY / SYNTHETIC / test-owner developer checks, NOT independent qualification.
Expectations are frozen in applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md ("Static scope checks", "Independence rules").
"""
from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_refund_desk_test_support", Path(__file__).with_name("_support.py"))
S = sys.modules.get("_refund_desk_test_support") or importlib.util.module_from_spec(_spec)
sys.modules["_refund_desk_test_support"] = S
if not hasattr(S, "REPO"):
    _spec.loader.exec_module(S)

F1_PKG = "orchestration.adapters.refund_disposition"
F1_PUBLIC = {"CONTRACT_VERSION", "AuthorityFacts", "DispositionRequest", "DispositionResult", "RefundProposal", "SyntheticEnvironment",
             "dispose_refund", "reconcile_refund"}
BASE = "09e1ba3d33aa64dd7054746838d16b64d868cf9f"
FORBIDDEN_WORDS = ("fault", "inject", "simulate")
G3_IDS = ("g2-synthetic", "tenant-alpha", "ocs-vnext-ig")
STDLIB = set(sys.stdlib_module_names)
# Not required by the independence rules but forbidden by the repository default path (no network/subprocess effects, no dynamic imports).
EFFECT_MODULES = {"subprocess", "socket", "urllib", "http", "ftplib", "smtplib", "importlib", "ctypes", "multiprocessing", "asyncio"}


def has_forbidden(text: str) -> bool:
    """Case-insensitive; matches words (split on _, -, camelCase, non-alnum) that start with fault/inject/simulate, so `default` is not a false hit."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return any(w.lower().startswith(FORBIDDEN_WORDS) for w in re.split(r"[^A-Za-z0-9]+", spaced) if w)


def app_files() -> list[Path]:
    return sorted(S.APP_PKG.rglob("*.py"))


class StaticScope(unittest.TestCase):
    def setUp(self):
        if not S.APP_PKG.is_dir() or not app_files():
            self.fail("application package applications/refund_desk/refund_desk has no python files")

    def test_imports_follow_independence_rules(self):
        problems = []
        for f in app_files():
            rel = f.relative_to(S.REPO)
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"), filename=str(f))):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        top = a.name.split(".")[0]
                        if a.name == F1_PKG:
                            continue
                        if top == "refund_desk" or (top in STDLIB and top not in EFFECT_MODULES):
                            continue
                        problems.append(f"{rel}:{node.lineno} import {a.name}")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    top = mod.split(".")[0]
                    if node.level > 0 or top == "refund_desk":
                        continue
                    if mod == F1_PKG:
                        for a in node.names:
                            if a.name not in F1_PUBLIC:
                                problems.append(f"{rel}:{node.lineno} non-public F1 name {a.name!r}")
                        continue
                    if top in STDLIB and top not in EFFECT_MODULES:
                        continue
                    problems.append(f"{rel}:{node.lineno} from {mod} import ...")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("__import__", "exec", "eval"):
                    problems.append(f"{rel}:{node.lineno} dynamic {node.func.id}")
        self.assertEqual(problems, [], "forbidden imports (only stdlib and package-level public F1 names are allowed): " + "; ".join(problems))

    def test_no_fault_identifiers_in_application(self):
        problems = []
        for f in app_files():
            rel = f.relative_to(S.REPO)
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Name):
                    names.append(node.id)
                elif isinstance(node, ast.Attribute):
                    names.append(node.attr)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.append(node.name)
                elif isinstance(node, ast.arg):
                    names.append(node.arg)
                elif isinstance(node, ast.keyword) and node.arg:
                    names.append(node.arg)
                elif isinstance(node, ast.alias):
                    names.extend([node.name, node.asname or ""])
                for n in names:
                    if has_forbidden(n):
                        problems.append(f"{rel}:{getattr(node, 'lineno', '?')} identifier {n!r}")
        self.assertEqual(problems, [], "; ".join(problems))

    def test_cli_has_no_fault_option_strings(self):
        cli = S.APP_PKG / "cli.py"
        self.assertTrue(cli.is_file(), "cli.py missing")
        problems = []
        for f in (cli, S.APP_PKG / "__main__.py"):
            if not f.is_file():
                continue
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
                    for a in node.args:
                        if isinstance(a, ast.Constant) and isinstance(a.value, str) and has_forbidden(a.value):
                            problems.append(f"{f.name}:{node.lineno} option {a.value!r}")
                    for k in node.keywords:
                        if k.arg == "dest" and isinstance(k.value, ast.Constant) and has_forbidden(str(k.value.value)):
                            problems.append(f"{f.name}:{node.lineno} dest {k.value.value!r}")
        self.assertEqual(problems, [], "; ".join(problems))

    def test_fixtures_have_no_g3_identifiers(self):
        files = sorted(S.FIXTURES.rglob("*"))
        self.assertTrue([f for f in files if f.is_file()], "no fixtures found")
        for f in files:
            if f.is_file():
                text = f.read_text(encoding="utf-8").lower()
                for ident in G3_IDS:
                    self.assertNotIn(ident, text, f"{f.name} contains G3 identifier {ident!r}")

    def test_only_allowed_paths_touched(self):
        if shutil.which("git") is None or not (S.REPO / ".git").exists():
            self.skipTest("git or a git checkout is unavailable (a skip is not a pass)")

        def git(*a):
            return subprocess.run(["git", *a], cwd=str(S.REPO), capture_output=True, text=True)

        if git("cat-file", "-e", f"{BASE}^{{commit}}").returncode != 0:
            self.skipTest(f"base commit {BASE} not present in this checkout")
        diff = git("diff", "--name-only", BASE)
        status = git("status", "--porcelain", "--untracked-files=all")
        self.assertEqual(diff.returncode, 0, diff.stderr)
        self.assertEqual(status.returncode, 0, status.stderr)
        paths = set(diff.stdout.split("\n"))
        for line in status.stdout.splitlines():
            paths.update(p.strip().strip('"') for p in line[3:].split(" -> "))
        paths.discard("")
        allowed = ("applications/refund_desk/", "tests/applications/refund_desk/")
        outside = sorted(p for p in paths if not p.startswith(allowed))
        self.assertEqual(outside, [], f"paths outside {allowed}: {outside}")


if __name__ == "__main__":
    unittest.main()
