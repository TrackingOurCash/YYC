"""Turn data/votes/*.csv into site/data/votes.json for the council votes page.

The JSON is compact: names and meeting types are stored once and motions
refer to them by index.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "votes"
OUT = ROOT / "site" / "data" / "votes.json"

MAYOR_RE = re.compile(r"^Mayor (\w)\. (.+)$")


def person_aliases(names: set[str]) -> dict[str, str]:
    """The dataset lists mayors as "Mayor J. Gondek"; use their full name
    when the same person also appears by full name (e.g. as a councillor)."""
    aliases = {}
    for name in names:
        m = MAYOR_RE.match(name)
        if not m:
            continue
        initial, surname = m.groups()
        full = [n for n in names if not n.startswith("Mayor ") and n.endswith(" " + surname) and n.startswith(initial)]
        if len(full) == 1:
            aliases[name] = full[0]
    return aliases


def main() -> None:
    with (SRC / "motions.csv").open(newline="") as f:
        motions = list(csv.DictReader(f))
    with (SRC / "ballots.csv").open(newline="") as f:
        ballots = list(csv.DictReader(f))

    aliases = person_aliases({b["voter"] for b in ballots})
    voters = sorted({aliases.get(b["voter"], b["voter"]) for b in ballots})
    voter_idx = {v: i for i, v in enumerate(voters)}
    types = sorted({m["meeting_type"] for m in motions})
    type_idx = {t: i for i, t in enumerate(types)}

    by_motion: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"Yes": [], "No": [], "Absent": []})
    for b in ballots:
        by_motion[b["motion_id"]].setdefault(b["vote"], []).append(voter_idx[aliases.get(b["voter"], b["voter"])])

    out = []
    for m in sorted(motions, key=lambda m: (m["date"], m["id"]), reverse=True):
        v = by_motion[m["id"]]
        out.append([
            m["date"],
            type_idx[m["meeting_type"]],
            1 if re.search(r"\bCARRIED\b", m["result"].upper()) and not re.search(r"\bNOT\b|\bDEFEATED\b|\bLOST\b", m["result"].upper()) else 0,
            1 if m["mentions_money"] else 0,
            int(m["largest_amount"]) if m["largest_amount"] else None,
            m["resolution"],
            sorted(v["Yes"]),
            sorted(v["No"]),
            sorted(v["Absent"]),
        ])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "fields": ["date", "meeting_type", "carried", "mentions_money", "largest_amount", "resolution", "yes", "no", "absent"],
        "voters": voters,
        "meeting_types": types,
        "motions": out,
    }, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} motions, {len(voters)} members")


if __name__ == "__main__":
    main()
