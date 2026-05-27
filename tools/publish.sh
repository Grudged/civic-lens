#!/bin/bash
# Export the current DB to data/civic.json and push it to GitHub. Hetzner's cron pulls it and
# rebuilds its serving DB. Runs nightly on Arch after the summarizer. Idempotent: no commit if
# the data didn't change. (Arch pushes data; the Mac pushes code — both to master, so rebase.)
set -e
cd /home/grudged/repos/civic-lens
venv/bin/python export.py
if [ -n "$(git status --porcelain data/civic.json)" ]; then
  git add data/civic.json
  git -c user.name="Grudged Civic" -c user.email="cmoore@grudged.io" \
      commit -q -m "data: refresh civic.json ($(date +%F))"
  git pull --rebase -q origin master || true
  git push -q origin master && echo "published civic.json"
else
  echo "no data change — nothing to publish"
fi
