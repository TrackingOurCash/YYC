"""Turn data/votes/*.csv into site/data/votes.json for the council votes page.

Votes come from the City's dataset, plus votes read from the published
minutes (collectors/votes_minutes.py), which carry a link to their minutes:
- meetings after the dataset's newest one, or of a kind the dataset never
  covers (public hearings, most committees), come from the minutes;
- for meetings the dataset has, each vote in the minutes is matched to the
  City's record by date, meeting, wording and vote counts. Votes the City
  left out are kept and marked, and the result of the check is saved in
  data/votes/check.json and shown on the page.

The JSON is compact: names and meeting types are stored once and motions
refer to them by index.

Each motion also gets the phrase, if any, that shows it approves new or
extra spending: allocating, approving or drawing a dollar amount, a budget
increase, new one-time or ongoing funding, approving a budget, an
amendment that raises an amount, or approving a growth application with
the operating funding it needs. Motions are left out when the words around
the money make it a study or referral, a cut, a swap of money already
approved, a loan or borrowing, a move into a reserve, or tax relief. The
rules were checked by hand against every council motion with a dollar
figure; they lean towards missing a spending motion over counting one that
isn't.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "votes"
OUT = ROOT / "site" / "data" / "votes.json"

MAYOR_RE = re.compile(r"^Mayor (\w)\. (.+)$")

AMT = r"\$\s?\d[\d,]*(?:\.\d+)?\s*(?:billion|million|thousand|[BMK]\b)?"
SCALE = {"billion": 1e9, "million": 1e6, "thousand": 1e3, "b": 1e9, "m": 1e6, "k": 1e3}


def amount(s: str) -> float:
    m = re.search(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(billion|million|thousand|[BMK]\b)?", s, re.I)
    return float(m.group(1).replace(",", "")) * SCALE.get((m.group(2) or "").lower(), 1)


# Whole motions that never decide spending themselves.
PROCEDURAL = re.compile(r"Closed Meeting|\breconsider|\bbe referred\b|\brefer (?:the|this|Report)|\brise and report|\bpostpone|\bbe tabled\b|\bbe received for (?:the corporate record|information)", re.I)
VERB = r"(?:allocat\w*|approv(?:e|es|ing|al)(?: of)?|provid\w*|invest\w*|award\w*|contribut\w*|commit(?:s|ted|ting)?|draw\w*|disburs\w*|grant\w*|reimburs\w*|set(?:ting)? aside|direct\w* (?:up to |an additional |a one-time )?)"
POSITIVE = [
    re.compile(rf"\b{VERB}\b[^.;$]{{0,70}}{AMT}", re.I),
    re.compile(rf"{AMT}[^.;$]{{0,40}}?\b(?:(?:in|of|as)\s+(?:one-?time|ongoing|additional|new|base)\b|(?:one-?time|ongoing|base)\s+(?:operating|capital|funding|budget|investment))", re.I),
    re.compile(r"\b(?:approv\w*|allocat\w*|provid\w*)\b[^.;]{0,60}\b(?:additional|new|one-?time|ongoing)\b[^.;]{0,30}\b(?:funding|budget|(?:operating|capital) investment)\b", re.I),
    re.compile(rf"\bincreas\w*\b[^.;$]{{0,60}}\b(?:budget|funding|grant|appropriation)\b[^.;$]{{0,80}}{AMT}", re.I),
    re.compile(rf"\bincreas\w*\b[^.;$]{{0,20}}{AMT}[^.;$]{{0,60}}\b(?:budget|funding|appropriation)\b", re.I),
    re.compile(r"\b(?:budget|funding) increase\b", re.I),
    re.compile(r"\badd\w*\s+(?:a\s+)?new\s+(?:investment|budget|funding)\b", re.I),
    re.compile(r"\bapprov(?:e|es|ing|al)\b[^.;]{0,40}\b(?:\d{4}(?:-\d{4})? )?(?:Service Plans and Budgets|(?:operating|capital) budget(?: items)?|budget adjustments|adjustments to the \d{4}-\d{4} Service Plans)\b", re.I),
    re.compile(rf"{AMT}[^.;$]{{0,60}}\bfrom the\b[^.;$]{{0,60}}\b(?:Reserve|Account|surplus)\b", re.I),
    re.compile(rf"\b(?:funding|grant|budget) of {AMT}[^.;$]{{0,30}}\b(?:is|be|are)\s+(?:directed|allocated|provided|granted|approved|committed)\b", re.I),
    re.compile(rf"\b(?:approv\w*|adopt\w*)\b[^.;]{{0,30}}\bapplication\b[^.;$]{{0,150}}\bin the amount of {AMT}", re.I),
    # Approving a growth application commits the City to fund its services:
    # "include the required operating funding in the 2028 adjustments to the
    # 2027-2030 Business Plans and Budgets".
    re.compile(r"\binclude the required (?:operating|capital)(?: and (?:operating|capital))? funding in\b[^.;]{0,60}\b(?:Budgets?|Business Plans)\b", re.I),
]
# Words up to the money that make it a study, a request or a referral.
STUDY = re.compile(r"\b(report back|return(?:ing)? to (?:Council|Committee|the)|review|consider\w*|explor\w+|options?|scoping|investigat\w+|prepare|bring forward|advocat\w+|request\w*|refer\w*|lobby|seek|identify|assess\w*|analy\w+|potential|future|if any|the plan for|subject to)\b", re.I)
# Words near the money that make it a cut, a swap, a loan or a move of money
# already approved, rather than new spending.
CUT = re.compile(r"\b(reduc\w+|decreas\w+|cut|cuts|cutting|relinquish\w*|remov\w+|eliminat\w+|savings|waiv\w+|rebate|refund|deferr?\w*|redirect\w*|reallocat\w*|mov(?:e|ed|es|ing)|previously|originally|recast|compensation|disposition|rate|borrow\w*|indebtedness|debentures?|loan|guarantee)\b", re.I)
TAX_RELIEF = re.compile(r"\btax relief\b", re.I)
TRANSFER = re.compile(r"\btransfer\w*\b", re.I)
FROM_RESERVE = re.compile(r"\bfrom the\b[^.;]{0,80}\bReserve\b", re.I)
INTO_RESERVE = re.compile(rf"{AMT}[^$.;]{{0,90}}\bto the\b[^$.;]{{0,50}}\bReserve\b(?![^.;]{{0,80}}\bto be allocated)", re.I)
REPLACE = re.compile(rf"(?:delet\w+|replac\w+) (?:the )?(?:amount |figure |number |words? )?(?:of )?[\"“]?({AMT})[^.;]{{0,80}}?(?:insert\w*|replac\w*|substitut\w*|with)[^$.;]{{0,30}}({AMT})", re.I)


# Names and phrases that contain veto words, swapped out while matching.
MASKS = {"Reserve for Future Capital": "RFC Reserve", "Budget Savings Account": "BSA Account", "Budget Requests": "Budget Asks"}


def clean(text: str) -> str:
    # The City's text has stray semicolons where line breaks were (" ;million").
    text = re.sub(r"\s;+(?=\S)", " ", text)
    for name, mask in MASKS.items():
        text = re.sub(re.escape(name), mask, text, flags=re.I)
    return text


def unmask(phrase: str) -> str:
    for name, mask in MASKS.items():
        phrase = phrase.replace(mask, name)
    return phrase


def clauses(text: str) -> list[str]:
    return [c for c in re.split(r";\s|(?<=[a-z0-9\)])\.\s+(?=[A-Z])|\s(?=[a-z]\.\s|[ivx]+\.\s|\d+\.\s)", text) if c.strip()]


def adds_spending(text: str) -> str | None:
    """The phrase that marks a motion as approving new or extra spending, or None."""
    text = clean(text)
    if PROCEDURAL.search(text):
        return None
    replaced = False
    for m in REPLACE.finditer(text):
        replaced = True
        if amount(m.group(2)) > amount(m.group(1)) and not CUT.search(text[max(0, m.start() - 60): m.end()]):
            return unmask(m.group(0))
    if replaced:
        return None
    for c in clauses(text):
        for p in POSITIVE:
            m = p.search(c)
            if not m:
                continue
            near = c[: m.end() + 40]
            if STUDY.search(c[: m.end()]) or CUT.search(near) or INTO_RESERVE.search(c) or TAX_RELIEF.search(c):
                continue
            if TRANSFER.search(near) and not FROM_RESERVE.search(c):
                continue
            return unmask(c[m.start(): m.end()].strip())
    return None


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


def read(name: str) -> list[dict]:
    path = SRC / name
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(text).lower()).strip()[:600]


def from_minutes(motions, ballots, m_motions, m_ballots, city_latest: str):
    """The minutes votes to show, each with a kind:
    "new"  the meeting is after the City's newest one;
    "extra" the City's data never covers this kind of meeting;
    "gap"  the City's data has the meeting but not this vote.
    Also returns the check of the City's data against the minutes."""
    types = {m["meeting_type"] for m in motions}
    counts = defaultdict(lambda: [0, 0])
    for b in ballots:
        if b["vote"] in ("Yes", "No"):
            counts[b["motion_id"]][b["vote"] == "No"] += 1
    m_counts = defaultdict(lambda: [0, 0])
    for b in m_ballots:
        m_counts[b["motion_id"]][b["vote"] == "No"] += 1
    city = defaultdict(list)
    for m in motions:
        city[(m["date"], m["meeting_type"])].append(m)

    keep, gaps = [], defaultdict(int)
    checked = matched = 0
    meetings = set()
    for (date, kind), group in sorted(_group(m_motions).items()):
        if kind not in types:
            keep += [{**m, "kind": "extra"} for m in group]
            continue
        if date > city_latest:
            keep += [{**m, "kind": "summary" if "FileStream" in m["minutes_url"] else "new"} for m in group]
            continue
        meetings.add((date, kind))
        left = match(group, city.get((date, kind), []), m_counts, counts)
        checked += len(group)
        matched += len(group) - len(left)
        keep += [{**m, "kind": "gap"} for m in left]
        if left:
            gaps[(date, kind)] += len(left)
    check = {
        "city_latest": city_latest,
        "meetings": len(meetings),
        "minutes_votes": checked,
        "matched": matched,
        "missing": checked - matched,
        "missing_by_meeting": [{"date": d, "meeting": k, "votes": n} for (d, k), n in sorted(gaps.items())],
    }
    return keep, check


def match(minutes, city, m_counts, counts) -> list[dict]:
    """Pair one meeting's votes from the minutes with the City's records of
    it; returns the minutes votes left without a partner. Same wording first,
    then the closest wording (85% alike, or 75% with the same vote counts),
    then whatever is left with the same result and the same vote counts."""
    pool = {c["id"]: c for c in city}
    ctext = {c["id"]: norm(c["resolution"]) for c in city}
    left = []
    for m in minutes:
        t = norm(m["resolution"])
        same = [i for i in pool if ctext[i] == t]
        if same:
            del pool[next((i for i in same if counts[i] == m_counts[m["id"]]), same[0])]
        else:
            left.append(m)
    pairs = []
    for m in left:
        t = norm(m["resolution"])
        for i in pool:
            sm = SequenceMatcher(None, t, ctext[i], autojunk=False)
            if sm.real_quick_ratio() < 0.6 or sm.quick_ratio() < 0.6:
                continue
            r = sm.ratio() + (0.1 if counts[i] == m_counts[m["id"]] else 0)
            if r >= 0.85:
                pairs.append((r, m["id"], i))
    done = set()
    for _, mid, i in sorted(pairs, reverse=True):
        if mid in done or i not in pool:
            continue
        done.add(mid)
        del pool[i]
    left = [m for m in left if m["id"] not in done]
    still = []
    for m in left:
        i = next((i for i, c in pool.items() if counts[i] == m_counts[m["id"]] and c["result"] == m["result"]), None)
        if i is None:
            still.append(m)
        else:
            del pool[i]
    return still


def _group(rows):
    out = defaultdict(list)
    for m in rows:
        out[(m["date"], m["meeting_type"])].append(m)
    return out


def main() -> None:
    motions = read("motions.csv")
    ballots = read("ballots.csv")
    city_latest = max(m["date"] for m in motions)
    recent, check = from_minutes(motions, ballots, read("minutes_motions.csv"), read("minutes_ballots.csv"), city_latest)
    recent_ids = {m["id"] for m in recent}
    motions += recent
    ballots += [b for b in read("minutes_ballots.csv") if b["motion_id"] in recent_ids]

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
            adds_spending(m["resolution"]),
            m.get("minutes_url") or None,
            m.get("kind") or None,
        ])

    meta = SRC / "dataset.json"
    city_updated = json.loads(meta.read_text()).get("city_updated") if meta.exists() else None

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "city_updated": city_updated,
        "city_latest": city_latest,
        "fields": ["date", "meeting_type", "carried", "mentions_money", "largest_amount", "resolution", "yes", "no", "absent", "adds_spending", "minutes_url", "minutes_kind"],
        "check": check,
        "voters": voters,
        "meeting_types": types,
        "motions": out,
    }, separators=(",", ":"), ensure_ascii=False) + "\n")
    (SRC / "check.json").write_text(json.dumps(check, indent=1) + "\n")
    print(f"check: {check['minutes_votes']} votes in minutes of {check['meetings']} meetings the City's data covers; "
          f"{check['matched']} matched, {check['missing']} missing from the City's data")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} motions ({len(recent)} from minutes, {sum(1 for m in out if m[9])} adding spending), {len(voters)} members")


if __name__ == "__main__":
    main()
