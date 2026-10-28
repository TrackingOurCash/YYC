"""Turn the ward boundaries and ward office reports into site/data/wards.json.

The map is pre-projected here (a flat projection scaled for Calgary's
latitude, simplified to about half a pixel) so the page only draws paths.
Expense accounts are grouped into a few plain-language categories, and
councillor names are matched to the spelling the council votes data uses
so the page can link a ward to its councillor's voting record.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WARDS = ROOT / "data" / "wards"
VOTES_JSON = ROOT / "site" / "data" / "votes.json"
OUT = ROOT / "site" / "data" / "wards.json"

WIDTH = 600
TOLERANCE = 0.5  # pixels

# Account code -> category. Codes come from the City's chart of accounts.
CATEGORIES = {
    "Community sponsorships": ["62810"],
    "Advertising and communications": ["32700", "32800"],
    "Printing and postage": ["33000", "33050", "31050", "31300"],
    "Meetings, events and meals": ["30992", "30996", "62770", "59993"],
    "Contract staff": ["36295", "37950"],
    "Travel, training and conferences": ["77500", "77520", "77540", "77550", "77660", "30997", "30998"],
    "Phones and IT": ["32540", "32590", "35150", "41000", "53150", "53250", "53300"],
}
OTHER = "Office and other"
CATEGORY_OF = {code: name for name, codes in CATEGORIES.items() for code in codes}
CATEGORY_NAMES = list(CATEGORIES) + [OTHER]


def project(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    return lon * math.cos(math.radians(lat0)), -lat


def simplify(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker."""
    if len(points) < 3:
        return points
    (x1, y1), (x2, y2) = points[0], points[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1e-12
    best, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        x, y = points[i]
        d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
        if d > best:
            best, idx = d, i
    if best <= tol:
        return [points[0], points[-1]]
    return simplify(points[: idx + 1], tol)[:-1] + simplify(points[idx:], tol)


def simplify_ring(ring: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Simplify a closed ring by splitting it at the point farthest from its start."""
    far = max(range(len(ring)), key=lambda i: math.dist(ring[0], ring[i]))
    return simplify(ring[: far + 1], tol)[:-1] + simplify(ring[far:], tol)


def ring_area_centroid(ring):
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        f = x0 * y1 - x1 * y0
        a += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if not a:
        return 0.0, ring[0]
    return a / 2, (cx / (3 * a), cy / (3 * a))


def build_map() -> tuple[list[dict], str]:
    geo = json.loads((WARDS / "ward_boundaries.geojson").read_text())
    feats = geo["features"]
    lats = [pt[1] for f in feats for poly in f["geometry"]["coordinates"] for ring in poly for pt in ring]
    lat0 = (min(lats) + max(lats)) / 2
    projected = []
    for f in feats:
        polys = [[[project(lon, lat, lat0) for lon, lat in ring] for ring in poly] for poly in f["geometry"]["coordinates"]]
        projected.append((f["properties"], polys))
    xs = [x for _, polys in projected for poly in polys for ring in poly for x, _ in ring]
    ys = [y for _, polys in projected for poly in polys for ring in poly for _, y in ring]
    scale = WIDTH / (max(xs) - min(xs))
    height = round((max(ys) - min(ys)) * scale)
    to_px = lambda x, y: ((x - min(xs)) * scale, (y - min(ys)) * scale)  # noqa: E731

    wards = []
    for props, polys in projected:
        parts, biggest = [], (0.0, (0, 0))
        for poly in polys:
            for k, ring in enumerate(poly):
                px = simplify_ring([to_px(x, y) for x, y in ring], TOLERANCE)
                if len(px) < 4:
                    continue
                parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in px[:-1]) + "Z")
                if k == 0:
                    area, c = ring_area_centroid(px[:-1])
                    if abs(area) > abs(biggest[0]):
                        biggest = (area, c)
        wards.append({
            "ward": props["ward"],
            "councillor": props.get("councillor", ""),
            "path": "".join(parts),
            "label": [round(biggest[1][0], 1), round(biggest[1][1], 1)],
        })
    return wards, f"0 0 {WIDTH} {height}"


def voter_names() -> list[str]:
    if not VOTES_JSON.exists():
        return []
    return json.loads(VOTES_JSON.read_text())["voters"]


def tidy_name(raw: str, voters: list[str]) -> str:
    """'ANDRE CHABOT' -> 'Andre Chabot', using the votes data's spelling when
    exactly one member shares the last name."""
    names = []
    for part in [p.strip() for p in raw.split("&") if p.strip()]:
        last = part.split()[-1].lower()
        match = [v for v in voters if v.split()[-1].lower() == last and not v.startswith("Mayor")]
        if len(match) == 1:
            names.append(match[0])
            continue
        # Initials like "DJ" stay upper case; "MCLEAN" becomes "McLean".
        words = [w if len(w) <= 2 and not re.search(r"[AEIOU]", w) else w.title() for w in part.split()]
        names.append(re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), " ".join(words)))
    return " & ".join(names)


def read(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    wards, view_box = build_map()
    voters = voter_names()
    for w in wards:
        w["councillor"] = tidy_name(w["councillor"], voters) if w["councillor"] else ""
    reports = [
        {
            "year": int(r["year"]),
            "ward": int(r["ward"]),
            "councillor": tidy_name(r["councillor"], voters),
            "period_end": r["period_end"],
            "budget": float(r["budget"]),
            "spent": float(r["spent"]) if r["spent"] else None,
            "url": r["url"],
        }
        for r in read(WARDS / "ward_budgets.csv")
    ]
    accounts: list[str] = []
    account_index: dict[str, int] = {}
    expenses = []
    for r in read(WARDS / "ward_expenses.csv"):
        name = f'{r["account_code"]} {r["account"]}'.strip()
        if name not in account_index:
            account_index[name] = len(accounts)
            accounts.append(name)
        cat = CATEGORY_NAMES.index(CATEGORY_OF.get(r["account_code"], OTHER))
        amount = float(r["amount"])
        expenses.append([int(r["year"]), int(r["ward"]), cat, account_index[name], r["month"],
                         int(amount) if amount.is_integer() else amount, r["vendor"], r["description"]])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated": dt.date.today().isoformat(),
        "view_box": view_box,
        "wards": wards,
        "categories": CATEGORY_NAMES,
        "accounts": accounts,
        "reports": reports,
        "expense_fields": ["year", "ward", "category", "account", "month", "amount", "vendor", "description"],
        "expenses": expenses,
    }, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(wards)} wards, {len(reports)} reports, {len(expenses)} expenses")


if __name__ == "__main__":
    main()
