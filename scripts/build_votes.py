"""Turn data/votes/*.csv into site/data/votes.json for the council votes page.

The JSON is compact: names and meeting types are stored once and motions
refer to them by index.

Each motion also gets the phrase, if any, that shows it approves new or
extra spending: allocating, approving or drawing a dollar amount, a budget
increase, new one-time or ongoing funding, approving a budget, or an
amendment that raises an amount. Motions are left out when the words around
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
            adds_spending(m["resolution"]),
        ])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "fields": ["date", "meeting_type", "carried", "mentions_money", "largest_amount", "resolution", "yes", "no", "absent", "adds_spending"],
        "voters": voters,
        "meeting_types": types,
        "motions": out,
    }, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} motions ({sum(1 for m in out if m[-1])} adding spending), {len(voters)} members")


if __name__ == "__main__":
    main()
