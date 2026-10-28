"""Collect City staff counts (full-time equivalents) and payroll.

Two kinds of City document carry them:

- Each Annual Financial Report ends with five-year tables: "Expenses by
  object" (salaries, wages and benefits) and "Demographic and other
  information" (full-time equivalents, and FTEs per 1,000 people). The
  reports from 2018 on are listed on calgary.ca; older ones are still online
  at the same address pattern but no longer linked.
- Budget books list budgeted FTEs by department, by business unit, and as
  management exempt or union positions. The 2026 budget as approved on
  December 3, 2025 covers 2023 to 2026. The budget pages are checked for new
  books, such as the 2027-2030 budget.

Writes data/workforce/annual_reports.csv (one row per report, year and
measure), data/workforce/budget_fte.csv (one row per budget book, line and
year) and data/workforce/documents.csv (every document read, with how many
rows it gave). A document is read once; delete its row in documents.csv to
read it again.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import pdfplumber
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "workforce"
REPORTS_CSV = DATA / "annual_reports.csv"
BUDGET_CSV = DATA / "budget_fte.csv"
DOCS_CSV = DATA / "documents.csv"

SITE = "https://www.calgary.ca"
FINANCE = SITE + "/content/dam/www/cfod/finance/documents/plans-budgets-and-financial-reports/"
REPORTS_PAGE = SITE + "/our-finances/annual-reports.html"
OLD_REPORT = FINANCE + "annual-reports/annual-report-{year}.pdf"
FIRST_REPORT = 2010
BUDGET_PAGES = [SITE + "/our-finances/2026-budget.html", SITE + "/our-finances/2027-budget.html"]
KNOWN_BUDGETS = [FINANCE + "2023-2026-service-plans-budgets/2026-budget-as-approved-dec-3-2025.pdf"]
USER_AGENT = (
    "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; "
    "+https://github.com/TrackingOurCash/YYC)"
)

REPORT_FIELDS = ["report_year", "year", "measure", "value", "url"]
BUDGET_FIELDS = ["url", "department", "line", "kind", "year", "fte"]
DOC_FIELDS = ["url", "kind", "read", "rows", "pdf_sha256"]

# Annual report lines. Each table lists the report's year and the four
# before it, newest first. "City" and "Related Authorities" are split from
# the 2019 report on; earlier reports give one combined total.
DASH = r"\s*[–—-]\s*"
REPORT_LINES = [
    ("fte_city", re.compile(r"^total full-time equivalents" + DASH + "city\\b", re.I)),
    ("fte_related", re.compile(r"^total full-time equivalents" + DASH + "related", re.I)),
    ("fte_all", re.compile(r"^total full-time equivalents\b(?!" + DASH + ")", re.I)),
    ("per_1000_city", re.compile(r"per 1,000 population" + DASH + "city\\b", re.I)),
    ("per_1000_related", re.compile(r"per 1,000 population" + DASH + "related", re.I)),
    ("per_1000_all", re.compile(r"^(full-time equivalents )?per 1,000 population\b(?!" + DASH + ")", re.I)),
]
NUMBER = re.compile(r"^\(?\d[\d,.]*\)?$")


def get(s: requests.Session, url: str) -> requests.Response | None:
    r = s.get(url, timeout=120)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r


def numbers(text: str) -> list[str]:
    return [t for t in text.replace("$", " ").split() if NUMBER.match(t)]


def page_texts(data: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def parse_report(texts: list[str], year: int) -> dict[tuple[int, str], float]:
    """The five-year payroll and FTE figures from one annual report."""
    found: dict[tuple[int, str], float] = {}

    def keep(measure: str, values: list[str]) -> None:
        if len(values) < 5 or any((y, measure) in found for y in range(year - 4, year + 1)):
            return
        for k, v in enumerate(values[-5:]):
            n = float(v.strip("()").replace(",", "")) if measure.startswith("per_1000") else int(re.sub(r"\D", "", v))
            found[(year - k, measure)] = n

    for text in texts:
        if re.search(r"expenses by object\s+unaudited", text, re.I):
            for line in text.splitlines():
                if line.strip().lower().startswith("salaries, wages and benefits"):
                    vals = numbers(line)
                    if len(vals) == 5:
                        keep("payroll", [str(int(re.sub(r"\D", "", v)) * 1000) for v in vals])
        if re.search(r"municipal full-time equivalents", text, re.I):
            for line in text.splitlines():
                line = line.strip()
                for measure, pattern in REPORT_LINES:
                    if pattern.search(line):
                        keep(measure, numbers(line))
                        break
    return found


def report_links(s: requests.Session) -> dict[int, str]:
    """Annual Financial Report PDFs by year: the listed ones, then the older pattern."""
    links = {}
    r = get(s, REPORTS_PAGE)
    for href in re.findall(r'href="([^"]+\.pdf)"', r.text if r else ""):
        name = href.rsplit("/", 1)[-1].lower()
        m = re.search(r"(20\d\d)", name)
        if m and "annual" in name and "report" in name and "investment" not in name:
            links.setdefault(int(m.group(1)), urljoin(SITE, href))
    for year in range(FIRST_REPORT, min(links or [dt.date.today().year])):
        links[year] = OLD_REPORT.format(year=year)
    return links


# Budget books. Lines that end in a value for each year, then sometimes a
# "change" column (a percentage or a dash).
YEARS = re.compile(r"\b(20\d\d)\b")
VALUE = re.compile(r"^(\(?[\d,]+\)?|-|–)$")
STAFF_TYPES = {"management exempt": "Management exempt", "union and other": "Union and other"}


def split_row(line: str, n: int) -> tuple[str, list[int]] | None:
    parts = line.split()
    for extra in (0, 1):
        tail = parts[len(parts) - n - extra: len(parts) - extra] if len(parts) > n + extra else None
        if tail and all(VALUE.match(t) for t in tail) and (extra == 0 or re.match(r"^\(?-?[\d.]+%\)?$|^[-–]$", parts[-1])):
            label = " ".join(parts[: len(parts) - n - extra])
            if label and not VALUE.match(parts[len(parts) - n - extra - 1]):
                return label, [0 if t in "-–" else int(t.strip("()").replace(",", "")) for t in tail]
    return None


def dept_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("&", "and")).strip().lower()


def parse_budget(texts: list[str]) -> list[dict]:
    """Budgeted FTEs from a budget book's department summary and business unit tables."""
    rows: list[dict] = []
    departments: dict[str, str] = {}

    def add(department: str, line: str, kind: str, years: list[int], values: list[int]) -> None:
        for y, v in zip(years, values):
            rows.append({"department": department, "line": line, "kind": kind, "year": y, "fte": v})

    for text in texts:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for i, line in enumerate(lines):
            if not re.match(r"^full time equivalents(?! per)", line, re.I):
                continue
            years = [int(y) for y in YEARS.findall(line)]
            start = i + 1
            if not years and start < len(lines) and re.fullmatch(r"(20\d\d\s*)+", lines[start]):
                years = [int(y) for y in YEARS.findall(lines[start])]
                start += 1
            # A repeated last year is the "change in" column.
            while len(years) > 1 and years[-1] <= years[-2]:
                years.pop()
            if len(years) < 2:
                continue
            summary = i > 0 and lines[i - 1].lower().startswith("change in")
            current = None
            for line2 in lines[start:]:
                if re.match(r"^full time equivalents", line2, re.I):
                    break
                row = split_row(line2, len(years))
                if not summary:
                    if not row:
                        break
                    label, values = row
                    department = lines[0]
                    if label.lower() == "total":
                        add(department, department, "department", years, values)
                    elif dept_key(label) == dept_key(department):
                        # A department that is a single unit, such as the Police Service.
                        add(department, label, "business unit", years, values)
                        add(department, department, "department", years, values)
                    else:
                        add(department, label, "business unit", years, values)
                    continue
                if not row:
                    current = None if line2.lower() == "totals" else line2
                    continue
                label, values = row
                if current and dept_key(label) in STAFF_TYPES:
                    add(current, STAFF_TYPES[dept_key(label)], "staff type", years, values)
                elif label.lower().endswith(" total"):
                    name = label[: -len(" total")]
                    departments[dept_key(name)] = name
                    add(name, name, "department", years, values)
                elif label.lower().startswith("total city administration"):
                    add("", "City administration, " + label[len("Total City Administration "):].lower(), "city", years, values)
                elif label.lower() in ("outside city administration", "total"):
                    add("", label, "city", years, values)

    # Business unit pages spell some departments differently ("&" for "and");
    # use the summary table's spelling.
    for r in rows:
        r["department"] = departments.get(dept_key(r["department"]), r["department"])
        if r["kind"] == "department":
            r["line"] = r["department"]
    # A department's total can come from both its summary row and its own page.
    seen, unique = set(), []
    for r in rows:
        key = (r["department"], r["line"], r["kind"], r["year"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def budget_links(s: requests.Session) -> list[str]:
    links = list(KNOWN_BUDGETS)
    for page in BUDGET_PAGES:
        r = get(s, page)
        for href in re.findall(r'href="([^"]+\.pdf)"', r.text if r else ""):
            url = urljoin(SITE, href)
            if url not in links:
                links.append(url)
    return links


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def run() -> dict:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    docs = {d["url"]: d for d in read_csv(DOCS_CSV)}
    reports = [r for r in read_csv(REPORTS_CSV) if r["url"] in docs]
    budget = [r for r in read_csv(BUDGET_CSV) if r["url"] in docs]
    report = {"reports_read": [], "budgets_read": [], "missing": []}
    today = dt.date.today().isoformat()

    for year, url in sorted(report_links(s).items()):
        if url in docs:
            continue
        r = get(s, url)
        if r is None:
            report["missing"].append(url)
            continue
        found = parse_report(page_texts(r.content), year)
        measures = {m for _, m in found}
        if "payroll" not in measures or not measures & {"fte_city", "fte_all"}:
            # Leave it unrecorded so tomorrow's run tries again.
            print(f"Couldn't find the payroll and FTE tables in {url}: found {sorted(measures)}", file=sys.stderr)
            continue
        reports = [x for x in reports if x["url"] != url]
        reports += [{"report_year": year, "year": y, "measure": m, "value": v, "url": url} for (y, m), v in sorted(found.items())]
        docs[url] = {"url": url, "kind": "annual report", "read": today, "rows": len(found),
                     "pdf_sha256": hashlib.sha256(r.content).hexdigest()}
        report["reports_read"].append(year)

    for url in budget_links(s):
        if url in docs:
            continue
        r = get(s, url)
        if r is None:
            report["missing"].append(url)
            continue
        found = parse_budget(page_texts(r.content)) if r.content[:4] == b"%PDF" else []
        budget = [x for x in budget if x["url"] != url] + [{"url": url, **x} for x in found]
        docs[url] = {"url": url, "kind": "budget", "read": today, "rows": len(found),
                     "pdf_sha256": hashlib.sha256(r.content).hexdigest()}
        report["budgets_read"].append({"url": url, "rows": len(found)})

    reports.sort(key=lambda x: (int(x["report_year"]), int(x["year"]), x["measure"]))
    write_csv(REPORTS_CSV, reports, REPORT_FIELDS)
    write_csv(BUDGET_CSV, budget, BUDGET_FIELDS)
    write_csv(DOCS_CSV, sorted(docs.values(), key=lambda d: (d["kind"], d["url"])), DOC_FIELDS)
    return report


if __name__ == "__main__":
    print(json.dumps(run()))
