set -x
mkdir -p dump13/all dump13/default
python collectors/votes_minutes.py --since 2026-09-01 > dump13/all/run.json 2> dump13/all/err.txt || true
cp data/votes/minutes_motions.csv data/votes/minutes_ballots.csv dump13/all/ 2>/dev/null || true
python collectors/votes_minutes.py > dump13/default/run.json 2> dump13/default/err.txt || true
cp data/votes/minutes_motions.csv data/votes/minutes_ballots.csv dump13/default/ 2>/dev/null || true
