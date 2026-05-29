#!/bin/bash
# Bring the development map live in the Arch data pipeline + ship coordinates to production.
# Run on Arch after the code is pushed to GitHub:
#   ssh archlinux 'cd ~/repos/civic-lens && git pull --rebase && bash deploy/ship-map.sh'
# Idempotent — safe to re-run.
set -e
cd /home/grudged/repos/civic-lens

git pull --rebase || true
venv/bin/pip install -q -r requirements.txt

# 1) backfill map coordinates into the live DB (Clark County locator + township centroids)
venv/bin/python geocode_job.py

# 2) export civic.json (now carrying the geocodes table) and push it so prod can rebuild from it
bash tools/publish.sh

# 3) install the nightly geocode timer (runs 22:40, between collect 22:30 and summarize 22:45)
sudo cp deploy/civic-lens-geocode.service deploy/civic-lens-geocode.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now civic-lens-geocode.timer

echo
echo "✓ coordinates backfilled, civic.json published, nightly geocode timer enabled"
echo "→ NEXT: redeploy the civic-lens app in Coolify (Hetzner) to pick up the new /map code."
echo "  (A data-only pull won't add the route — the container image must rebuild.)"
