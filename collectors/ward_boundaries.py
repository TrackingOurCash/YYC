"""Collect the current ward boundaries from Open Calgary.

Dataset: Ward Boundaries (tz8z-hyaz), one multipolygon per ward with the
councillor's name. Coordinates are rounded to 6 decimals (about 10 cm) and
features sorted by ward so the file only changes when a boundary does.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

from opencalgary import BASE, USER_AGENT

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "wards" / "ward_boundaries.geojson"
DATASET = "tz8z-hyaz"


def rounded(coords):
    if isinstance(coords[0], (int, float)):
        return [round(c, 6) for c in coords]
    return [rounded(c) for c in coords]


def run() -> dict:
    r = requests.get(f"{BASE}/{DATASET}.geojson", headers={"User-Agent": USER_AGENT}, timeout=120)
    r.raise_for_status()
    features = r.json()["features"]
    if len(features) < 14:
        raise SystemExit(f"Expected 14 wards, got {len(features)}.")
    out = {
        "type": "FeatureCollection",
        "features": sorted(
            (
                {
                    "type": "Feature",
                    "properties": {"ward": int(f["properties"]["ward_num"]), "councillor": f["properties"].get("councillor", "")},
                    "geometry": {"type": f["geometry"]["type"], "coordinates": rounded(f["geometry"]["coordinates"])},
                }
                for f in features
            ),
            key=lambda f: f["properties"]["ward"],
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    return {"wards": len(features)}


if __name__ == "__main__":
    print(json.dumps(run()))
