"""Collect council and committee votes from the City's published minutes.

Open Calgary's Council and Committee Votes dataset is only refreshed about
once a month, and it leaves out public hearings and most committees. The
City posts each meeting's minutes on its eScribe portal, usually within days
(council's own minutes once council approves them at its next meeting), and
every recorded vote in them lists who voted for and against. Agendas carry
no votes; they only list what will be discussed.

This reads the minutes of every meeting since the start of the council term
that has them, once each, and keeps what it read. build_votes.py then uses
them two ways:
- meetings the City's dataset doesn't have yet, or never covers, are shown
  from the minutes;
- for meetings the dataset does have, each motion in the minutes is matched
  to the City's record, and any the City left out are kept, so the page
  doesn't lose votes when the City's monthly update is incomplete.

Minutes don't list absences.

Writes:
  data/votes/minutes_motions.csv   one row per recorded vote
  data/votes/minutes_ballots.csv   one row per member per vote
  data/votes/minutes_meetings.csv  every meeting whose minutes were read

Usage: python collectors/votes_minutes.py [--since YYYY-MM-DD] [--reread]
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


TERM_START = "2025-10-20"


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def calendar(s: requests.Session, start: str, end: str) -> list[dict]:
    """Meetings between two dates, a month of the calendar at a time."""
    out, day, last = [], dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    while day <= last:
        stop = min(day + dt.timedelta(days=31), last)
        out += meetings(s, day.isoformat(), stop.isoformat())
        day = stop + dt.timedelta(days=1)
    return out


def run(since: str | None = None, reread: bool = False) -> dict:
    _, _, by_surname = dataset_state()
    start = since or TERM_START
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    old_meetings = [] if reread else read_csv(OUT / "minutes_meetings.csv")
    done = {m["escribe_id"] for m in old_meetings}
    old_motions = [] if reread else read_csv(OUT / "minutes_motions.csv")
    old_ballots = [] if reread else read_csv(OUT / "minutes_ballots.csv")
    motions, ballots, read = [], [], []
    seen_ids: set[str] = set()
    for m in sorted(calendar(s, start, dt.date.today().isoformat()), key=lambda m: m.get("StartDate", "")):
        name, date = m.get("MeetingName", "").strip(), m.get("StartDate", "")[:10].replace("/", "-")
        has_minutes = any(d.get("Type") == "PostMinutes" for d in m.get("MeetingDocumentLink") or [])
        if not has_minutes or not date or str(m["ID"]) in done or str(m["ID"]) in seen_ids:
            continue
        seen_ids.add(str(m["ID"]))
        url = f"{PORTAL}/Meeting.aspx?Id={m['ID']}&Agenda=PostMinutes&lang=English"
        r = s.get(url, timeout=60)
        r.raise_for_status()
        seen: dict[str, int] = {}
        count = 0
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
            count += 1
        read.append({"escribe_id": str(m["ID"]), "date": date, "meeting_type": name, "motions": count,
                     "read_on": dt.date.today().isoformat()})
        time.sleep(1)
    # Keep everything read before; minutes don't change once posted.
    new_ids = {m["id"] for m in motions}
    motions += [m for m in old_motions if m["id"] not in new_ids]
    ballots += [b for b in old_ballots if b["motion_id"] not in new_ids]
    write_csv(OUT / "minutes_motions.csv", motions,
              ["id", "date", "meeting_type", "result", "mentions_money", "largest_amount", "resolution", "minutes_url"],
              sort_key=lambda m: (m["date"], m["meeting_type"], m["id"]))
    write_csv(OUT / "minutes_ballots.csv", ballots, ["motion_id", "voter", "vote"], sort_key=lambda b: (b["motion_id"], b["voter"]))
    write_csv(OUT / "minutes_meetings.csv", old_meetings + read, ["escribe_id", "date", "meeting_type", "motions", "read_on"],
              sort_key=lambda m: (m["date"], m["meeting_type"], m["escribe_id"]))
    unmatched = sorted({b["voter"] for b in ballots} - set(by_surname.values()))
    return {"from": start, "meetings_read": [f"{m['date']} {m['meeting_type']} ({m['motions']})" for m in read],
            "motions": len(motions), "unmatched_names": unmatched}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help=f"look for minutes from this date (default {TERM_START}, the start of the council term)")
    ap.add_argument("--reread", action="store_true", help="read every meeting's minutes again instead of only new ones")
    a = ap.parse_args()
    print(json.dumps(run(a.since, a.reread), indent=1))
