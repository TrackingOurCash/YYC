"""Fail the data run once a source has been broken for several runs.

scripts/run_source.py keeps a failed source's last good data and only warns,
so a one-day outage doesn't turn the run red. A source still failing after
FAIL_AFTER runs in a row has most likely changed (a new page layout, a moved
file) and needs a fix, so this fails the run and names it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "data" / "status.json"
FAIL_AFTER = 3


def main() -> int:
    status = json.loads(STATUS.read_text()) if STATUS.exists() else {}
    broken = []
    for key, s in sorted(status.items()):
        state = "ok" if not s.get("fails_in_row") else f"failing {s['fails_in_row']} run(s) since {s['failing_since']}"
        print(f"{s.get('title', key)}: {state}; last good read {s.get('last_ok') or 'not yet recorded'}")
        if s.get("fails_in_row", 0) >= FAIL_AFTER:
            broken.append(s)
    for s in broken:
        shown = f"its data from {s['last_ok']}" if s.get("last_ok") else "its earlier data"
        message = f"failing since {s['failing_since']}; the site still shows {shown}. Last error: {s.get('last_error')}"
        print(f"::error title={s['title']}::{message}" if os.environ.get("GITHUB_ACTIONS") else f"error: {s['title']}: {message}")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
