# Tracking Our Cash: Calgary (YYC)

Tracks what the City of Calgary commits to spend: job postings, the budget, grants, contracts and council decisions.

Part of [Tracking Our Cash](https://trackingourcash.github.io). The Calgary dashboard will be published at https://trackingourcash.github.io/YYC/.

## What's collected

| Data | Source | How often |
| --- | --- | --- |
| City job postings | [calgary.ca/careers](https://www.calgary.ca/careers.html) | Daily |
| Operating and capital budget, 2023 to 2032 | [Calgary Open Budget](https://data.calgary.ca/d/fqax-i3nz) on Open Calgary | Daily (the City updates it about once a year) |

Council votes, Civic Partners and FCSS grants, and ward-level spending come next.

## Job postings

`collectors/jobs.py` reads the careers page every morning and keeps one row per posting in `data/jobs/postings.csv`:

- The careers page shows no posting date, so `first_seen` (the first day the collector saw the posting) is used instead. Counts begin on the first day the collector ran.
- Department (business unit), union, pay grade and range, weekly hours, and the number of permanent and temporary positions come from the "Position and Pay Information" block on each posting's own page.
- A raw copy of each day's list is saved in `data/jobs/snapshots/`.

`scripts/build_jobs_summary.py` turns that table into `site/data/jobs_summary.json`, with totals by month, job category, department and overall. Estimated annual cost uses the midpoint of each posted pay range times the number of positions. Hourly rates are annualised from the posting's weekly hours (35 if not stated). Temporary positions count at the same annual rate, so the figure is a yearly run rate, not a total over the term.

## Budget

`collectors/budget.py` downloads the Calgary Open Budget dataset into `data/budget/open_budget.csv`, and `scripts/build_budget.py` turns it into `site/data/budget.json`. Amounts in the source are in millions; the JSON stores whole dollars. Operating figures are net of recoveries. Actual spending is only published for capital, for 2023 and 2024. `collectors/opencalgary.py` is the shared downloader for Open Calgary datasets.

## Running locally

```sh
pip install -r requirements.txt
python collectors/jobs.py
python collectors/budget.py
python scripts/build_jobs_summary.py
python scripts/build_budget.py
```

The GitHub Action in `.github/workflows/collect.yml` runs both every day at 13:00 UTC and commits any changes. `.github/workflows/pages.yml` then publishes `site/` to GitHub Pages.

## Dashboard

`site/` is a static site with no build step: `index.html` (overview), `jobs.html` and `budget.html`, sharing `assets/site.css` and `assets/common.js`. Each page reads its JSON from `site/data/` and works out every total in the browser, so a page's filters apply to its totals, charts and table together. To preview it locally, run `python -m http.server -d site` and open http://localhost:8000.
