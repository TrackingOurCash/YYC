# Tracking Our Cash: Calgary (YYC)

Tracks what the City of Calgary commits to spend: job postings, the budget, grants, contracts and council decisions.

Part of [Tracking Our Cash](https://trackingourcash.github.io). The Calgary dashboard is published at https://trackingourcash.github.io/YYC/.

## What's collected

| Data | Source | How often |
| --- | --- | --- |
| City job postings | [calgary.ca/careers](https://www.calgary.ca/careers.html), plus earlier 2026 copies from the [Internet Archive](https://web.archive.org/web/2026*/calgary.ca/careers.html) | Daily |
| Salary range for each City position title | [Compensation Disclosure List](https://data.calgary.ca/d/9bze-mzx6) on Open Calgary | Daily (the City updates it about once a year) |
| Operating and capital budget, 2023 to 2032 | [Calgary Open Budget](https://data.calgary.ca/d/fqax-i3nz) on Open Calgary | Daily (the City updates it about once a year) |
| Council and committee votes since October 2020 | [Council and Committee Votes](https://data.calgary.ca/d/ruq3-99hx) on Open Calgary | Daily |
| Civic Partners grants (operating, capital, community safety, innovation) by organization | [Civic Partners funding](https://www.calgary.ca/our-finances/civic-partners-funding.html) on calgary.ca | Daily (the City updates it about once a year) |
| FCSS grants by organization and funded program, 2021 onwards | [FCSS funding allocations](https://www.calgary.ca/social-services/funding/organization-allocations.html) on calgary.ca | Daily (the City updates it each funding cycle) |
| Each ward office's budget, spending and itemized expenses, 2024 onwards | Ward budget and expenditure reports (PDF) on calgary.ca, e.g. [Ward 1, 2026](https://www.calgary.ca/content/dam/www/citycouncil/documents/expenses-2026/ward-01-budget-and-expenditure-2026.pdf) | Daily (the City updates them through the year) |
| Ward boundaries and councillors | [Ward Boundaries](https://data.calgary.ca/d/tz8z-hyaz) on Open Calgary | Daily |

## Job postings

`collectors/jobs.py` reads the careers page every morning and keeps one row per posting in `data/jobs/postings.csv`:

- The careers page shows no posting date, so `first_seen` (the first day the collector saw the posting) is used instead. Counts begin on the first day the collector ran.
- Department (business unit), union, pay grade and range, weekly hours, and the number of permanent and temporary positions come from the "Position and Pay Information" block on each posting's own page.
- A raw copy of each day's list is saved in `data/jobs/snapshots/`.

Postings from before the collector started are rebuilt by `scripts/backfill_jobs_from_archive.py` (run it from the "Backfill jobs from the Internet Archive" Action, with a start date). It reads every Internet Archive copy of the careers page since that date, adds any posting not already in the table with `source=archive`, and dates it by the first and last archived copy that lists it. Copies are a few days to weeks apart, so those dates are approximate, and postings open when the first copy was taken all land in that month. The City's posting pages stop working once a job closes, so department, pay and position counts are only known for the few archived postings whose own page was also archived.

`collectors/compensation.py` downloads the City's compensation disclosure list into `data/jobs/compensation.csv`.

`scripts/build_jobs_summary.py` turns the postings into `site/data/postings.json` and `site/data/jobs_summary.json`, with totals by month, job category, department and overall. Estimated annual cost uses the midpoint of the pay range times the number of positions. Pay comes from the posting itself; failing that, from the compensation list entry with the same title for the year it was posted (or the year before); failing that, from another posting with the same title. A posting with no position count counts as one position of unknown type. Hourly rates are annualised from the posting's weekly hours (35 if not stated). Temporary positions count at the same annual rate, so the figure is a yearly run rate, not a total over the term. Postings with no pay from any source count as $0, so the total is a floor.

## Budget

`collectors/budget.py` downloads the Calgary Open Budget dataset into `data/budget/open_budget.csv`, and `scripts/build_budget.py` turns it into `site/data/budget.json`. Amounts in the source are in millions; the JSON stores whole dollars. Operating figures are net of recoveries. Actual spending is only published for capital, for 2023 and 2024. `collectors/opencalgary.py` is the shared downloader for Open Calgary datasets.

## Council votes

`collectors/votes.py` downloads every recorded vote (about 55,000 rows, one per member per vote) and groups them into motions, since the City's data has no motion number. It writes `data/votes/motions.csv` (one row per motion, flagged when the text mentions money, with the largest dollar figure in the text) and `data/votes/ballots.csv` (one row per member per motion). `scripts/build_votes.py` packs both into `site/data/votes.json`.

## Grants

`collectors/grants.py` reads the tables on the Civic Partners and FCSS pages into `data/grants/grants.csv`, one row per organization, grant, funded program, year and figure (actual, approved budget or allocated). The pages only show the current funding years, so rows that drop off the page are kept, with the first and last day each was seen. `scripts/build_grants.py` writes `site/data/grants.json`: it merges recipient names that are spelled differently from year to year, moves capital project names into the funded program column, and keeps the actual amount where a year has both a budget and an actual.

## Wards

`collectors/ward_expenses.py` downloads each ward office's "Ward Budget & Expenditure Disclosure" PDF and reads it with pdfplumber, using the position of each column heading to split every expense line into account, month, amount, vendor and reason. It writes `data/wards/ward_budgets.csv` (budget, total spent including salaries, and period, one row per ward and year) and `data/wards/ward_expenses.csv` (one row per itemized expense). Each report covers the year to date, so the current and previous year are re-read whenever the PDF changes. `collectors/ward_boundaries.py` saves the ward map from Open Calgary. `scripts/build_wards.py` projects and simplifies the map, groups expense accounts into categories, and writes `site/data/wards.json`.

## Running locally

```sh
pip install -r requirements.txt
python collectors/jobs.py
python collectors/budget.py
python collectors/votes.py
python collectors/compensation.py
python collectors/grants.py
python collectors/ward_boundaries.py
python collectors/ward_expenses.py
python scripts/build_jobs_summary.py
python scripts/build_budget.py
python scripts/build_votes.py
python scripts/build_grants.py
python scripts/build_wards.py
```

The GitHub Action in `.github/workflows/collect.yml` runs all of these every day at 13:00 UTC and commits any changes. `.github/workflows/pages.yml` then publishes `site/` to GitHub Pages.

## Dashboard

`site/` is a static site with no build step: `index.html` (overview), `jobs.html`, `budget.html`, `grants.html`, `wards.html`, `votes.html` and `sources.html` (every source, linked from each page's footer), sharing `assets/site.css` and `assets/common.js`. Each page reads its JSON from `site/data/` and works out every total in the browser, so a page's filters apply to its totals, charts and table together. To preview it locally, run `python -m http.server -d site` and open http://localhost:8000.
