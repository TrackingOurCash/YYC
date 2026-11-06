"""Run one collector so that a broken source can't cost the site its data.

  python scripts/run_source.py KEY "Title" --keep PATH [PATH ...] -- python collectors/x.py [args]

- Tries the collector up to three times, waiting longer each time, since the
  City's sites have short outages.
- If every try fails, puts the files and folders under --keep back exactly as
  they were before the step, so the site keeps the source's last good data
  even if the collector stopped halfway through writing.
- Records the outcome in data/status.json, and a copy in site/data for the
  Sources page: when the source last worked, and how many runs in a row it
  has failed.
- Exits 0 either way, after a warning in the run's summary, so one broken
  source doesn't stop the rest. scripts/check_sources.py fails the run once a
  source has been failing for several runs, so a lasting break gets noticed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "data" / "status.json"
SITE_STATUS = ROOT / "site" / "data" / "status.json"
WAITS = [30, 120]  # seconds before the second and third tries


def snapshot(paths: list[Path], into: Path) -> list[tuple[Path, Path | None]]:
    saved = []
    for i, p in enumerate(paths):
        if p.is_dir():
            copy = into / str(i)
            shutil.copytree(p, copy)
        elif p.exists():
            copy = into / str(i)
            shutil.copy2(p, copy)
        else:
            copy = None  # didn't exist: remove whatever the collector made
        saved.append((p, copy))
    return saved


def restore(saved: list[tuple[Path, Path | None]]) -> None:
    for p, copy in saved:
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
        if copy is None:
            continue
        if copy.is_dir():
            shutil.copytree(copy, p)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(copy, p)


def save_status(key: str, title: str, ok: bool, error: str) -> dict:
    status = json.loads(STATUS.read_text()) if STATUS.exists() else {}
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    entry = status.get(key, {})
    entry["title"] = title
    entry["last_run"] = today
    if ok:
        entry.update(last_ok=today, fails_in_row=0, failing_since=None, last_error="")
    else:
        entry["fails_in_row"] = entry.get("fails_in_row", 0) + 1
        entry["failing_since"] = entry.get("failing_since") or today
        entry["last_error"] = error
    status[key] = entry
    text = json.dumps(status, indent=1, sort_keys=True) + "\n"
    for path in (STATUS, SITE_STATUS):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return entry


def annotate(level: str, title: str, message: str) -> None:
    """A note in the GitHub Actions run summary (plain text elsewhere)."""
    print(f"::{level} title={title}::{message}" if os.environ.get("GITHUB_ACTIONS") else f"{level}: {title}: {message}")


def main() -> int:
    argv = sys.argv[1:]
    if "--" not in argv:
        sys.exit('usage: run_source.py KEY "Title" --keep PATH [PATH ...] -- COMMAND [ARGS ...]')
    split = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("title")
    ap.add_argument("--keep", nargs="+", required=True, help="files or folders the collector writes")
    args = ap.parse_args(argv[:split])
    command = argv[split + 1:]
    keep = [ROOT / p for p in args.keep]

    with tempfile.TemporaryDirectory() as tmp:
        saved = snapshot(keep, Path(tmp))
        error = ""
        for attempt in range(len(WAITS) + 1):
            if attempt:
                print(f"{args.title}: trying again in {WAITS[attempt - 1]}s", flush=True)
                time.sleep(WAITS[attempt - 1])
                restore(saved)
            proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            sys.stdout.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            sys.stdout.flush()
            if proc.returncode == 0:
                save_status(args.key, args.title, True, "")
                return 0
            lines = [l for l in (proc.stderr or proc.stdout).strip().splitlines() if l.strip()]
            error = lines[-1][:300] if lines else f"exit code {proc.returncode}"
        restore(saved)

    entry = save_status(args.key, args.title, False, error)
    kept = f"kept its data from {entry['last_ok']}" if entry.get("last_ok") else "kept its earlier data"
    annotate("warning", args.title, f"failed {entry['fails_in_row']} run(s) in a row, {kept}: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
