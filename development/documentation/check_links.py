"""Conservative local Markdown path, GitHub-heading and shell syntax checks.

Scope is canonical active documentation, not every archived or vendored page.
No external URL is fetched and fenced shell commands are NEVER executed.
"""
from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
PAGES = [
    "README.md",
    "development/README.md",
    "development/documentation/README.md",
    "docs/qualification-ledger.md",
    "development/dashboard.md",
    "development/scenarios/customer_refunds/connected/contracts/README.md",
    "tests/integration/README.md",
    "development/scenarios/customer_refunds/README.md",
    "development/scenarios/customer_refunds/connected/handoff/README.md",
    "development/scenarios/customer_refunds/connected/replay/README.md",
]
LINK = re.compile(r"(?<!!)\]\((<[^>]+>|[^)]+)\)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s*```(.*)$")


def github_slug(text: str) -> str:
    """Approximate GitHub's Unicode-preserving heading slug on simple Markdown."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"!?\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_~]", "", text)
    text = text.strip().lower()
    text = "".join(c for c in text if c == "-" or c == "_" or c.isspace()
                   or c.isalnum() or unicodedata.category(c).startswith("M"))
    return re.sub(r"\s+", "-", text)


def headings(document: str) -> set[str]:
    found: set[str] = set()
    counts: dict[str, int] = {}
    fenced = False
    for line in document.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = HEADING.match(line)
        if match:
            slug = github_slug(match.group(1))
            if slug:
                count = counts.get(slug, 0)
                found.add(slug if count == 0 else f"{slug}-{count}")
                counts[slug] = count + 1
    # GitHub also supports explicit HTML anchors in some documentation.
    found.update(re.findall(r'<a\s+(?:name|id)=["\']([^"\']+)["\']', document))
    return found


def shell_blocks(document: str) -> list[str]:
    blocks, current = [], []
    active = False
    collect = False
    for line in document.splitlines():
        match = FENCE.match(line)
        if match:
            if not active:
                active = True
                collect = match.group(1).strip().lower() in ("bash", "sh", "shell")
                current = []
            else:
                if collect:
                    blocks.append("\n".join(current) + "\n")
                active = collect = False
            continue
        if active and collect:
            current.append(line)
    return blocks


def check_page(page: Path, root: Path) -> tuple[list[str], int, int]:
    errors: list[str] = []
    source = page.read_text(encoding="utf-8")
    links = 0
    checked_shell = 0
    for raw in LINK.findall(source):
        link = raw.strip().split(' "', 1)[0].strip("<>")
        if not link or link.startswith(("http://", "https://", "mailto:", "data:")):
            continue
        parts = urlsplit(link)
        if parts.scheme or parts.netloc:
            continue
        path = unquote(parts.path)
        anchor = unquote(parts.fragment)
        target = (page.parent / path).resolve() if path else page.resolve()
        links += 1
        if not target.is_relative_to(root.resolve()):
            errors.append(f"{page.relative_to(root)}: link escapes repository: {link}")
            continue
        if not target.exists():
            errors.append(f"{page.relative_to(root)}: missing local target: {link}")
            continue
        if anchor and target.is_file() and target.suffix.lower() == ".md":
            # Deliberately do not validate GitHub custom line-number fragments.
            if not re.fullmatch(r"L\d+(?:-L\d+)?", anchor):
                if anchor not in headings(target.read_text(encoding="utf-8")):
                    errors.append(f"{page.relative_to(root)}: missing heading #{anchor}: {link}")
    for idx, block in enumerate(shell_blocks(source), start=1):
        result = subprocess.run(["bash", "-n"], input=block, text=True,
                                capture_output=True, check=False)
        checked_shell += 1
        if result.returncode:
            errors.append(f"{page.relative_to(root)}: shell fence {idx}: "
                          f"{result.stderr.strip()}")
    return errors, links, checked_shell


def main() -> int:
    errors = []
    links = fences = 0
    for relative in PAGES:
        page = ROOT / relative
        if not page.is_file():
            errors.append(f"missing canonical document: {relative}")
            continue
        problems, link_count, shell_count = check_page(page, ROOT)
        errors.extend(problems)
        links += link_count
        fences += shell_count
    print(f"Checked {len(PAGES)} canonical Markdown files, {links} local links/anchors "
          f"and {fences} shell fences (syntax only); no external URLs fetched")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
