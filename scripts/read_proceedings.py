"""Add the votes in a Summary of Proceedings PDF to the minutes votes.

For long meetings such as budget deliberations, the City posts a "Summary of
Proceedings" for each day before the meeting's minutes. It lists every motion
with who voted for and against. The City's meetings portal only serves these
PDFs to a browser, so they are downloaded by hand into data/votes/proceedings/
and read with this script:

  python scripts/read_proceedings.py data/votes/proceedings/FILE.pdf \
      --date 2026-11-10 --meeting "Regular Meeting of Council" \
      --url "https://pub-calgary.escribemeetings.com/FileStream.ashx?DocumentId=377669"

The votes go into data/votes/minutes_motions.csv and minutes_ballots.csv
with the PDF's address as their source. When the meeting's minutes are
posted, collectors/votes_minutes.py replaces them with the minutes' votes.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "collectors"))
from votes import MONEY_RE, clean, largest_amount  # noqa: E402
from votes_minutes import OUT, dataset_state, read_csv, voters  # noqa: E402
from opencalgary import write_csv  # noqa: E402

RESULT = re.compile(r"^(?:MOTION )?(CARRIED|DEFEATED|LOST)\b")


def parse(text: str, by_surname: dict[str, str]) -> list[dict]:
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().isdigit()]
    out, i = [], 0
    while i < len(lines):
        if not lines[i].startswith("Moved by"):
            i += 1
            continue
        i += 1
        if i < len(lines) and lines[i].startswith("Seconded by"):
            i += 1
        body, votes, part, result = [], {"Yes": [], "No": []}, None, ""
        while i < len(lines) and not lines[i].startswith("Moved by"):
            l = lines[i]
            m = re.match(r"^(For|Against): \(\d+\):\s*(.*)$", l)
            if m:
                part = "Yes" if m.group(1) == "For" else "No"
                votes[part].append(m.group(2))
            elif RESULT.match(l):
                result = "MOTION " + RESULT.match(l).group(1)
                i += 1
                break
            elif part:
                votes[part].append(l)
            else:
                body.append(l)
            i += 1
        if not result or not (votes["Yes"] or votes["No"]):
            continue
        out.append({
            "resolution": clean(re.sub(r"(\w)- (\d)", r"\1-\2", " ".join(body))),
            "result": result,
            "votes": {k: voters(" ".join(v), by_surname) for k, v in votes.items()},
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--date", required=True)
    ap.add_argument("--meeting", required=True)
    ap.add_argument("--url", required=True)
    a = ap.parse_args()
    _, _, by_surname = dataset_state()
    with pdfplumber.open(a.pdf) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    motions, ballots, seen = [], [], {}
    for p in parse(text, by_surname):
        key = (a.date, a.meeting, p["resolution"], p["result"])
        n = seen[repr(key)] = seen.get(repr(key), -1) + 1
        motion_id = "m" + hashlib.sha1("|".join([*key, str(n)]).encode()).hexdigest()[:11]
        amount = largest_amount(p["resolution"])
        motions.append({
            "id": motion_id, "date": a.date, "meeting_type": a.meeting, "result": p["result"],
            "mentions_money": "yes" if MONEY_RE.search(p["resolution"]) else "",
            "largest_amount": "" if amount is None else str(amount),
            "resolution": p["resolution"], "minutes_url": a.url,
        })
        ballots += [{"motion_id": motion_id, "voter": v, "vote": vote} for vote, names in p["votes"].items() for v in names]
    ids = {m["id"] for m in motions}
    old_m = [m for m in read_csv(OUT / "minutes_motions.csv") if m["id"] not in ids and m["minutes_url"] != a.url]
    old_ids = {m["id"] for m in old_m}
    old_b = [b for b in read_csv(OUT / "minutes_ballots.csv") if b["motion_id"] in old_ids]
    write_csv(OUT / "minutes_motions.csv", old_m + motions,
              ["id", "date", "meeting_type", "result", "mentions_money", "largest_amount", "resolution", "minutes_url"],
              sort_key=lambda m: (m["date"], m["meeting_type"], m["id"]))
    write_csv(OUT / "minutes_ballots.csv", old_b + ballots, ["motion_id", "voter", "vote"], sort_key=lambda b: (b["motion_id"], b["voter"]))
    unmatched = sorted({b["voter"] for b in ballots} - set(by_surname.values()))
    print(f"{len(motions)} votes read; names not matched: {unmatched or 'none'}")
    for m in motions:
        print(" ", m["result"], "|", m["resolution"][:110])


if __name__ == "__main__":
    main()
