#!/usr/bin/env python3
"""OCS-07 independent read-only check (developer check, NOT independent qualification; stdlib only; run as: python3 -I verify_ocs07_readonly.py RESULT.json).

Separate process from the application. It writes nothing. For one Refund Desk result JSON it (1) recomputes the sha256 of the Replay bundle and of every
source file named in the result and compares with the digest the application reported; (2) opens the SQLite destination read-only and reads the effect rows;
(3) checks that the Replay bundle contains an execution record for the same effect_id and the same amount/unit/state as the destination row.
Exit 0 only if every check holds; prints each check."""
import hashlib, json, sqlite3, sys
from pathlib import Path

def sha(p):
    return "sha256:" + hashlib.sha256(Path(p).read_bytes()).hexdigest()

def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)

def main(path):
    res = json.loads(Path(path).read_text())
    ok = True
    def chk(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name + (f" - {detail}" if detail else ""))
    ev = res["evidence"]
    replay = ev.get("replay")
    chk("replay reference present", replay is not None, f"replay_state={ev['replay_state']} replay_note={ev.get('replay_note')!r}")
    if replay is None:
        return 1
    chk("replay file exists", Path(replay["path"]).is_file(), replay["path"])
    chk("replay sha256 recomputed equals reported", sha(replay["path"]) == replay["sha256"])
    for s in ev["source"]:
        chk(f"source {s['kind']} sha256 recomputed equals reported", sha(s["path"]) == s["sha256"])
    state = Path(replay["path"]).parents[2]
    db = state / "sqlite" / "refunds.sqlite3"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM effects ORDER BY effect_id")]
    con.close()
    chk("exactly one destination row", len(rows) == 1, f"{len(rows)} row(s)")
    row = rows[0]
    chk("row effect_id equals result effect_id", row["effect_id"] == res["effect"]["effect_id"])
    chk("row state applied", row["state"] == "applied")
    bundle = json.loads(Path(replay["path"]).read_text())
    hits = [d for d in walk(bundle) if d.get("effect_id") == row["effect_id"] and d.get("amount") is not None]
    chk("replay bundle carries the same effect_id with an amount", bool(hits))
    chk("replay amount equals row amount", any(float(d["amount"]) == float(row["amount"]) for d in hits), f"row amount {row['amount']} {row['unit']}")
    units = [d.get("unit") or d.get("currency") for d in hits]
    chk("replay unit equals row unit", row["unit"] in units, f"replay units {sorted(set(map(str, units)))}")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
