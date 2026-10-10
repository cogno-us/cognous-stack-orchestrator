"""Negative controls prove docs validator fails on malformed links and shell blocks."""
from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("check_links.py")
spec = importlib.util.spec_from_file_location("docs_checker", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_local_path_heading_shell_checks(tmp_path):
    target = tmp_path / "target.md"
    target.write_text("# Hello Example\n\n## Hello Example\n\n## Hello Example\n")
    page = tmp_path / "README.md"
    page.write_text(
        "# Introduction\n\n"
        "[first](target.md#hello-example)\n"
        "[duplicate](target.md#hello-example-1)\n"
        "```bash\nprintf '%s\\n' ok\n```\n"
    )
    errors, links, fences = module.check_page(page, tmp_path)
    assert not errors
    assert links == 2 and fences == 1
    assert "hello-example-2" in module.headings(target.read_text())


def test_missing_path_cannot_pass(tmp_path):
    page = tmp_path / "README.md"
    page.write_text("[bad](missing.md)")
    errors, _, _ = module.check_page(page, tmp_path)
    assert len(errors) == 1 and "missing local target" in errors[0]


def test_missing_heading_cannot_pass(tmp_path):
    (tmp_path / "target.md").write_text("# Exists\n")
    page = tmp_path / "README.md"
    page.write_text("[bad](target.md#missing-heading)")
    errors, _, _ = module.check_page(page, tmp_path)
    assert len(errors) == 1 and "missing heading" in errors[0]


def test_malformed_shell_cannot_pass_without_execution(tmp_path):
    page = tmp_path / "README.md"
    page.write_text("```bash\nif true; then\necho broken\n```\n")
    errors, _, fences = module.check_page(page, tmp_path)
    assert fences == 1 and len(errors) == 1
    assert "shell fence" in errors[0]


def test_reject_repo_escaping_local_link(tmp_path):
    page = tmp_path / "README.md"
    page.write_text("[outside](../outside.md)")
    errors, _, _ = module.check_page(page, tmp_path)
    assert "escapes repository" in errors[0]
