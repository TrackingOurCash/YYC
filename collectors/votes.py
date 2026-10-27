"""Collect City of Calgary council and committee votes from Open Calgary.

Dataset: Council and Committee Votes (ruq3-99hx), one row per member per
recorded vote since eVoting began on October 7, 2020. The dataset has no
motion ID, so rows are grouped into motions here: same meeting date,
meeting type and resolution text, split again whenever a member appears a
second time (the same wording voted on twice in one meeting).

Writes two tables:
  data/votes/motions.csv  one row per motion
  data/votes/ballots.csv  one row per member per motion
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from opencalgary import fetch_all, write_csv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "votes"
DATASET = "ruq3-99hx"

# Words that mark a motion as being about money. Deliberately broad; the
# dashboard labels these "mentions money", not "approves spending".
MONEY_RE = re.compile(
    r"\$\s?\d|\bbudget|\bfund(?:s|ing|ed)?\b|\bgrants?\b|\bcapital\b|\blev(?:y|ies)\b|\btax(?:es|ation)?\b"
    r"|\bprocure|\bcontracts?\b|\bexpenditure|\ballocat|\bappropriat|\bfinanc|\breserves?\b|\bborrow"
    r"|\bdebenture|\bcosts?\b|\binvest",
    re.I,
)
AMOUNT_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(billion|million|thousand|[BMK]\b)?", re.I)
SCALE = {"billion": 1e9, "b": 1e9, "million": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}


def largest_amount(text: str) -> int | None:
    amounts = []
    for num, unit in AMOUNT_RE.findall(text):
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        amounts.append(v * SCALE.get(unit.lower(), 1) if unit else v)
    return round(max(amounts)) if amounts else None


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def group_motions(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Rows must be in dataset order; returns (motions, ballots)."""
    motions: list[dict] = []
    ballots: list[dict] = []
    open_groups: dict[tuple, dict] = {}
    seq: dict[tuple, int] = {}
    for r in rows:
        date = (r.get("meetingdate") or "")[:10]
        key = (date, r.get("meetingtype", ""), clean(r.get("resolution", "")))
        voter = clean(r.get("voter", ""))
        g = open_groups.get(key)
        if g is None or voter in g["voters"] or r.get("result", "") != g["result"]:
            n = seq.get(key, 0)
            seq[key] = n + 1
            motion_id = hashlib.sha1("|".join([*key, str(n)]).encode()).hexdigest()[:12]
            g = {
                "id": motion_id,
                "date": date,
                "meeting_type": key[1],
                "resolution": key[2],
                "result": r.get("result", ""),
                "voters": set(),
            }
            open_groups[key] = g
            motions.append(g)
        g["voters"].add(voter)
        ballots.append({"motion_id": g["id"], "voter": voter, "vote": r.get("vote", "")})

    for m in motions:
        del m["voters"]
        m["mentions_money"] = "yes" if MONEY_RE.search(m["resolution"]) else ""
        amount = largest_amount(m["resolution"])
        m["largest_amount"] = "" if amount is None else str(amount)
    return motions, ballots


def run() -> dict:
    rows = fetch_all(DATASET, **{"$select": ":id,meetingtype,meetingdate,resolution,voter,vote,result"})
    if not rows:
        raise SystemExit("Open Calgary returned no votes.")
    motions, ballots = group_motions(rows)
    write_csv(
        OUT / "motions.csv",
        motions,
        ["id", "date", "meeting_type", "result", "mentions_money", "largest_amount", "resolution"],
        sort_key=lambda m: (m["date"], m["meeting_type"], m["id"]),
    )
    write_csv(OUT / "ballots.csv", ballots, ["motion_id", "voter", "vote"], sort_key=lambda b: (b["motion_id"], b["voter"]))
    return {"rows": len(rows), "motions": len(motions), "money_motions": sum(1 for m in motions if m["mentions_money"])}


if __name__ == "__main__":
    print(json.dumps(run()))
