# Tracking Our Cash: Calgary (YYC)

Tracks what the City of Calgary commits to spend: job postings, the budget, grants, contracts and council decisions.

Part of [Tracking Our Cash](https://trackingourcash.github.io). The Calgary dashboard will be published at https://trackingourcash.github.io/YYC/.

## What's collected

| Data | Source | How often |
| --- | --- | --- |
| City job postings | [calgary.ca/careers](https://www.calgary.ca/careers.html) | Daily |

More sources (budget, Civic Partners and FCSS grants, ward office expenses, contract awards, council votes) are added in later steps.

## Job postings

`collectors/jobs.py` reads the careers page every morning and keeps one row per posting in `data/jobs/postings.csv`:

- The careers page shows no posting date, so `first_seen` (the first day the collector saw the posting) is used instead. Counts begin on the first day the collector ran.
- Department (business unit), union, pay grade and range, weekly hours, and the number of permanent and temporary positions come from the "Position and Pay Information" block on each posting's own page.
- A raw copy of each day's list is saved in `data/jobs/snapshots/`.

`scripts/build_jobs_summary.py` turns that table into `site/data/jobs_summary.json`, with totals by month, job category, department and overall. Estimated annual cost uses the midpoint of each posted pay range times the number of positions. Hourly rates are annualised from the posting's weekly hours (35 if not stated). Temporary positions count at the same annual rate, so the figure is a yearly run rate, not a total over the term.

## Running locally

```sh
pip install -r requirements.txt
python collectors/jobs.py
python scripts/build_jobs_summary.py
```

The GitHub Action in `.github/workflows/collect.yml` runs both every day at 13:00 UTC and commits any changes. `.github/workflows/pages.yml` then publishes `site/` to GitHub Pages.

## Dashboard

`site/index.html` is a single static page with no build step. It reads `site/data/postings.json` and works out every total in the browser, so the month, department and position-type filters apply to the totals, both charts and the table together. To preview it locally, run `python -m http.server -d site` and open http://localhost:8000.
