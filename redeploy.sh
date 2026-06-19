#!/usr/bin/env bash
# Redeploy the cloud-youtube-proxy container on this VPS from the latest git main.
#
# Run on the VPS as a user with sudo:   sudo bash redeploy.sh
# It is idempotent: pull -> build -> restart, re-applying the PROXY_TOKEN that
# the currently running container already has (so you never need the token here).
#
# The repo is owned by 'vluongthanh98' but the SSH/login user differs, so git
# runs as the owner to avoid "dubious ownership"; docker runs as root via sudo.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_OWNER=vluongthanh98
CONTAINER=esp32-youtube-proxy
IMAGE=esp32-youtube-proxy
PORT=8088

echo "== git pull ($REPO_DIR) =="
sudo -u "$REPO_OWNER" git -C "$REPO_DIR" pull --ff-only

echo "== preserve PROXY_TOKEN from the running container =="
TOKEN="$(docker inspect "$CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
         | grep '^PROXY_TOKEN=' | cut -d= -f2- || true)"
if [ -z "$TOKEN" ]; then
  # First deploy / container gone: fall back to a PROXY_TOKEN env passed to this script.
  TOKEN="${PROXY_TOKEN:-}"
fi
if [ -z "$TOKEN" ]; then
  echo "!! No PROXY_TOKEN found (no running container and no PROXY_TOKEN env)." >&2
  echo "!! Re-run as: sudo PROXY_TOKEN=xxxx bash redeploy.sh" >&2
  exit 1
fi
echo "   token length: ${#TOKEN}"

echo "== docker build =="
docker build -t "$IMAGE" "$REPO_DIR"

echo "== restart container =="
docker rm -f "$CONTAINER" 2>/dev/null || true
docker run -d --restart unless-stopped --name "$CONTAINER" \
  -p "${PORT}:${PORT}" -e PROXY_TOKEN="$TOKEN" "$IMAGE" >/dev/null

echo "== wait for health =="
healthy=0
for i in $(seq 1 15); do
  sleep 2
  if curl -fsS "localhost:${PORT}/health" >/dev/null 2>&1; then
    echo "   healthy after $((i * 2))s"
    healthy=1
    break
  fi
done
[ "$healthy" = 1 ] || echo "   !! health check did not pass within 30s (see: docker logs $CONTAINER)"

echo "== status =="
docker ps --filter "name=$CONTAINER" --format '{{.Names}} {{.Status}} {{.Ports}}'
echo "== active config (verify your changes landed) =="
docker exec "$CONTAINER" grep -nE 'readrate|DEFAULT_FPS|DEFAULT_QUALITY' /app/app.py || true
echo "== done =="
