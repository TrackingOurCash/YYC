"""Collect City of Calgary council and committee votes from Open Calgary.

Dataset: Council and Committee Votes (ruq3-99hx), one row per member per
recorded vote since eVoting began on October 7, 2020. The dataset has no
motion ID, so rows are grouped into motions here by meeting date, meeting
type, resolution text and result (see group_motions).

Writes two tables:
  data/votes/motions.csv  one row per motion
  data/votes/ballots.csv  one row per member per motion

Meetings already in those tables but missing from the City's file are kept
(see keep_missing_meetings).
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

from opencalgary import fetch_all, last_updated, write_csv

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
    """Group ballot rows into motions; returns (motions, ballots).

    The dataset has no motion ID and rows for identically worded motions in
    one meeting are interleaved, so each ballot goes to the first motion with
    the same date, meeting, wording and result that doesn't have that member
    yet. Per-member counts are exact either way; only how ballots split
    between identically worded motions is approximate.
    """
    motions: list[dict] = []
    ballots: list[dict] = []
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        date = (r.get("meetingdate") or "")[:10]
        key = (date, r.get("meetingtype", ""), clean(r.get("resolution", "")), r.get("result", ""))
        voter = clean(r.get("voter", ""))
        candidates = groups.setdefault(key, [])
        g = next((m for m in candidates if voter not in m["voters"]), None)
        if g is None:
            motion_id = hashlib.sha1("|".join([*key, str(len(candidates))]).encode()).hexdigest()[:12]
            g = {
                "id": motion_id,
                "date": date,
                "meeting_type": key[1],
                "resolution": key[2],
                "result": key[3],
                "voters": set(),
            }
            candidates.append(g)
            motions.append(g)
        g["voters"].add(voter)
        ballots.append({"motion_id": g["id"], "voter": voter, "vote": r.get("vote", "")})

    for m in motions:
        del m["voters"]
        m["mentions_money"] = "yes" if MONEY_RE.search(m["resolution"]) else ""
        amount = largest_amount(m["resolution"])
        m["largest_amount"] = "" if amount is None else str(amount)
    return motions, ballots


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def keep_missing_meetings(motions: list[dict], ballots: list[dict]) -> int:
    """Add back meetings from our copy that the City's file leaves out.

    On 2026-10-30 the City's refresh replaced the dataset with one month of
    votes instead of the full record since 2020. The City's rows still win
    for any meeting (date and meeting type) they include; earlier meetings
    they drop are kept from data/votes, so a short refresh can't wipe the
    history. Returns how many motions were kept this way.
    """
    have = {(m["date"], m["meeting_type"]) for m in motions}
    kept = {m["id"]: m for m in read_csv(OUT / "motions.csv") if (m["date"], m["meeting_type"]) not in have}
    motions += kept.values()
    ballots += [b for b in read_csv(OUT / "ballots.csv") if b["motion_id"] in kept]
    return len(kept)


def run() -> dict:
    rows = fetch_all(DATASET, **{"$select": ":id,meetingtype,meetingdate,resolution,voter,vote,result"})
    if not rows:
        raise SystemExit("Open Calgary returned no votes.")
    motions, ballots = group_motions(rows)
    kept = keep_missing_meetings(motions, ballots)
    write_csv(
        OUT / "motions.csv",
        motions,
        ["id", "date", "meeting_type", "result", "mentions_money", "largest_amount", "resolution"],
        sort_key=lambda m: (m["date"], m["meeting_type"], m["id"]),
    )
    write_csv(OUT / "ballots.csv", ballots, ["motion_id", "voter", "vote"], sort_key=lambda b: (b["motion_id"], b["voter"]))
    # The City refreshes this dataset about monthly, so recent meetings lag;
    # the page shows when it last did. Keep the old date if the portal is quiet.
    updated = last_updated(DATASET)
    if updated:
        (OUT / "dataset.json").write_text(json.dumps({"city_updated": updated}) + "\n")
    return {"rows": len(rows), "motions": len(motions), "kept_from_our_copy": kept,
            "money_motions": sum(1 for m in motions if m["mentions_money"]), "city_updated": updated}


if __name__ == "__main__":
    print(json.dumps(run()))
