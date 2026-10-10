"""Check local Markdown link targets in primary documentation entrypoints.

Only checks target path existence; it does not claim network link or anchor validity.
"""
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[2]
PAGES=[
    ROOT/"README.md",
    ROOT/"development/README.md",
    ROOT/"development/documentation/README.md",
    ROOT/"docs/qualification-ledger.md",
    ROOT/"development/dashboard.md",
    ROOT/"development/scenarios/customer_refunds/connected/contracts/README.md",
    ROOT/"tests/integration/README.md",
    ROOT/"development/scenarios/customer_refunds/README.md",
    ROOT/"development/scenarios/customer_refunds/connected/handoff/README.md",
    ROOT/"development/scenarios/customer_refunds/connected/replay/README.md",
]
errors=[]
for page in PAGES:
    data=page.read_text(encoding="utf-8")
    for target in re.findall(r"(?<!!)\]\(([^)]+)\)",data):
        target=target.strip().split(" ",1)[0].strip("<>")
        if not target or target.startswith(("http://","https://","#","mailto:")):
            continue
        path=unquote(target.split("#",1)[0].split("?",1)[0])
        if path and not (page.parent/path).exists():
            errors.append(f"{page.relative_to(ROOT)}: missing {target}")
if errors:
    print("\n".join(errors))
    sys.exit(1)
print(f"Checked local paths in {len(PAGES)} canonical documentation entrypoints")
