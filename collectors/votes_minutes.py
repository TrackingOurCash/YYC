"""Collect recent council and committee votes from the City's published minutes.

Open Calgary's Council and Committee Votes dataset is only refreshed about
once a month, so the latest meetings take weeks to appear in it. The City
posts each meeting's minutes on its eScribe portal within days, and every
recorded vote in them lists who voted for and against. This reads those
minutes for meetings after the newest one in the dataset, so the votes page
can show them until the dataset catches up; build_votes.py then drops them
in favour of the City's own data.

Only meeting types the dataset itself covers are read (it leaves out public
hearings and most committees), so the page doesn't change scope when the
minutes are swapped out. Minutes don't list absences.

Writes:
  data/votes/minutes_motions.csv  one row per recorded vote
  data/votes/minutes_ballots.csv  one row per member per vote

Usage: python collectors/votes_minutes.py [--since YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from opencalgary import write_csv
from votes import MONEY_RE, clean, largest_amount

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "votes"
PORTAL = "https://pub-calgary.escribemeetings.com"
USER_AGENT = "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; +https://github.com/TrackingOurCash/YYC)"
TITLES = re.compile(r"^(?:Deputy Mayor|Acting Mayor|Mayor|Councillor|Commissioner|Citizen Member|Member|General Manager|Director)\s+", re.I)


def dataset_state() -> tuple[str, set[str], dict[str, str]]:
    """From the Open Calgary copy: the newest meeting date, the meeting types
    it covers, and each current member's name keyed by surname."""
    with (OUT / "motions.csv").open(newline="") as f:
        motions = {m["id"]: m for m in csv.DictReader(f)}
    latest = max(m["date"] for m in motions.values())
    types = {m["meeting_type"] for m in motions.values()}
    # Names as the dataset spells them, preferring the last year of votes so
    # a surname shared with a past member goes to the current one.
    since = (dt.date.fromisoformat(latest) - dt.timedelta(days=365)).isoformat()
    recent: dict[str, set[str]] = {}
    ever: dict[str, set[str]] = {}
    with (OUT / "ballots.csv").open(newline="") as f:
        for b in csv.DictReader(f):
            surname = b["voter"].split()[-1].lower()
            ever.setdefault(surname, set()).add(b["voter"])
            if motions[b["motion_id"]]["date"] >= since:
                recent.setdefault(surname, set()).add(b["voter"])
    by_surname = {k: next(iter(v)) for k, v in ever.items() if len(v) == 1}
    by_surname.update({k: next(iter(v)) for k, v in recent.items() if len(v) == 1})
    return latest, types, by_surname


def meetings(s: requests.Session, start: str, end: str) -> list[dict]:
    r = s.post(f"{PORTAL}/MeetingsCalendarView.aspx/GetCalendarMeetings",
               json={"calendarStartDate": start, "calendarEndDate": end}, timeout=60)
    r.raise_for_status()
    return r.json().get("d", [])


def voters(cell: str, by_surname: dict[str, str]) -> list[str]:
    """ "Councillor Ward, Councillor Yule,  and Mayor Farkas" -> dataset names."""
    out = []
    for part in re.split(r",|\band\b", cell):
        name = TITLES.sub("", clean(part))
        if name:
            out.append(by_surname.get(name.split()[-1].lower(), name))
    return out


def rich_text(el) -> str:
    """Motion text the way the dataset writes it: numbered list items, one
    space between paragraphs, none added around bold or italic words."""
    for ol in el.select("ol"):
        for n, item in enumerate(ol.find_all("li", recursive=False), int(ol.get("start") or 1)):
            item.insert(0, f"{n}. ")
    for block in el.select("p, li, br, div, tr"):
        block.append(" ")
    return clean(el.get_text().replace("\u200b", ""))


def parse_minutes(html: str, by_surname: dict[str, str]) -> list[dict]:
    """Every motion in the minutes that has its own wording and a recorded
    vote. Motions with no wording (adopting minutes or receiving a report
    from the agenda as it stands) are left out, as the dataset leaves them out."""
    out = []
    for li in BeautifulSoup(html, "html.parser").select("li.AgendaItemMotion"):
        result = clean(li.select_one("div.MotionResult").get_text(" ") if li.select_one("div.MotionResult") else "")
        text = rich_text(li.select_one("div.MotionText")) if li.select_one("div.MotionText") else ""
        votes = {"Yes": [], "No": []}
        for row in li.select("table.MotionVoters tr"):
            label, users = row.select_one("td.VoterVote"), row.select("td.VotesUsers")
            if not label or not users:
                continue
            kind = label.get_text(" ", strip=True).lower()
            key = "Yes" if kind.startswith("for") else "No" if kind.startswith("against") else None
            if key:
                votes[key] += voters(users[0].get_text(" "), by_surname)
        if not result or not text or not (votes["Yes"] or votes["No"]):
            continue
        out.append({"resolution": text, "result": result, "votes": votes})
    return out


def run(since: str | None = None) -> dict:
    latest, types, by_surname = dataset_state()
    start = since or (dt.date.fromisoformat(latest) + dt.timedelta(days=1)).isoformat()
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    motions, ballots, read = [], [], []
    for m in sorted(meetings(s, start, dt.date.today().isoformat()), key=lambda m: m.get("StartDate", "")):
        name, date = m.get("MeetingName", ""), m.get("StartDate", "")[:10].replace("/", "-")
        has_minutes = any(d.get("Type") == "PostMinutes" for d in m.get("MeetingDocumentLink") or [])
        if name not in types or not has_minutes or not date:
            continue
        url = f"{PORTAL}/Meeting.aspx?Id={m['ID']}&Agenda=PostMinutes&lang=English"
        r = s.get(url, timeout=60)
        r.raise_for_status()
        seen: dict[str, int] = {}
        for p in parse_minutes(r.text, by_surname):
            key = (date, name, p["resolution"], p["result"])
            n = seen[repr(key)] = seen.get(repr(key), -1) + 1
            motion_id = "m" + hashlib.sha1("|".join([*key, str(n)]).encode()).hexdigest()[:11]
            amount = largest_amount(p["resolution"])
            motions.append({
                "id": motion_id, "date": date, "meeting_type": name, "result": p["result"],
                "mentions_money": "yes" if MONEY_RE.search(p["resolution"]) else "",
                "largest_amount": "" if amount is None else str(amount),
                "resolution": p["resolution"], "minutes_url": url,
            })
            ballots += [{"motion_id": motion_id, "voter": v, "vote": vote} for vote, names in p["votes"].items() for v in names]
        read.append(f"{date} {name}")
        time.sleep(1)
    write_csv(OUT / "minutes_motions.csv", motions,
              ["id", "date", "meeting_type", "result", "mentions_money", "largest_amount", "resolution", "minutes_url"],
              sort_key=lambda m: (m["date"], m["meeting_type"], m["id"]))
    write_csv(OUT / "minutes_ballots.csv", ballots, ["motion_id", "voter", "vote"], sort_key=lambda b: (b["motion_id"], b["voter"]))
    unmatched = sorted({b["voter"] for b in ballots} - set(by_surname.values()))
    return {"after": start, "meetings": read, "motions": len(motions), "unmatched_names": unmatched}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="read minutes from this date instead of the day after the dataset's newest meeting")
    print(json.dumps(run(ap.parse_args().since)))
