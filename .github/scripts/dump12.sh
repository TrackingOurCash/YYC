set -x
mkdir -p dump12
python collectors/votes_minutes.py --since 2026-09-01 > dump12/run.json 2> dump12/err.txt || true
cp data/votes/minutes_motions.csv data/votes/minutes_ballots.csv dump12/ 2>/dev/null || true
