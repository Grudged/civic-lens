#!/bin/bash
# Start (or restart) the civic-lens container on Hetzner.
#
# Civic Lens is a HAND-RUN docker container — not Coolify-managed in the dashboard —
# but it routes through Coolify's Traefik proxy via container labels on the shared
# `coolify` network. The original `docker run` command lived only in shell history;
# this script captures it so the deploy is reproducible.
#
# Use:
#   ssh hetzner 'cd ~/civic-lens && git pull --rebase && bash deploy/start-prod.sh'
#
# Bind mounts:
#   ./data → /app/data       — civic.json + districts/*.geojson + reps yaml/json
#                              ride the */15 git-pull cron; container sees fresh
#                              data without a rebuild.
#   civic-lens-db (volume) → /data
#                            — SQLite (civic.db) persistence across container
#                              restarts. tools/load_json.py rebuilds the meetings
#                              tables from civic.json on every container start;
#                              the volume keeps the file around so we don't lose
#                              non-civic.json state if we ever add any.
#
# Routing: Traefik labels + the coolify network are what put this container
# behind https://civic.grudged.io. Removing them = 404.
set -e
cd "$(dirname "$0")/.."

echo "→ Building image…"
docker build --quiet -t civic-lens:latest .

echo "→ Stopping any existing container…"
docker rm -f civic-lens 2>/dev/null || true

echo "→ Starting civic-lens…"
docker run -d \
  --name civic-lens \
  --restart unless-stopped \
  --network coolify \
  -v "$(pwd)/data:/app/data:ro" \
  -v civic-lens-db:/data \
  --label "traefik.docker.network=coolify" \
  --label "traefik.enable=true" \
  --label "traefik.http.routers.civiclens2.entrypoints=https" \
  --label "traefik.http.routers.civiclens2.rule=Host(\`civic.grudged.io\`)" \
  --label "traefik.http.routers.civiclens2.tls=true" \
  --label "traefik.http.routers.civiclens2.tls.certresolver=letsencrypt" \
  --label "traefik.http.services.civiclens2.loadbalancer.server.port=8902" \
  civic-lens:latest

echo "→ Waiting for it to settle…"
sleep 3
docker ps --filter "name=civic-lens" --format "  {{.Names}}: {{.Status}}"
echo
echo "→ Logs (last 20 lines):"
docker logs --tail=20 civic-lens 2>&1 | sed 's/^/  /'
echo
echo "✓ Done. Probe:"
echo "    curl https://civic.grudged.io/api/health"
