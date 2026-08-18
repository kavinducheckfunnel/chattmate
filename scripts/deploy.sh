#!/usr/bin/env bash
#
# Deploy ChatterMate to the growmiq VPS. Run ON the server:
#
#   /opt/chattermate/scripts/deploy.sh            # rebuild changed images + restart
#   /opt/chattermate/scripts/deploy.sh --no-build # restart only
#
# Safe to run while Checkfunnel is live: builds are niced off the foreground,
# only this compose project is touched, and the run aborts before restarting
# anything if a build fails.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/chattermate}"
PROJECT="chattermate"
COMPOSE_FILE="docker-compose.growmiq.yml"
DOMAIN="https://chat.growmiq.io"
BUILD=1
[ "${1:-}" = "--no-build" ] && BUILD=0

cd "$APP_DIR"
dc() { docker compose -p "$PROJECT" -f "$COMPOSE_FILE" --env-file .env.growmiq "$@"; }

echo "==> Deploying from $APP_DIR"

if [ "$BUILD" = "1" ]; then
  # Build the backend image first and alone. All Python services share this
  # Dockerfile, and building them in parallel means several simultaneous
  # downloads of the ~200MB torch wheel — which is what corrupted the wheel and
  # failed the build with a pip hash mismatch the first time round.
  #
  # No nice/ionice here. It cannot wrap `dc` (a shell function, not a binary),
  # and wrapping the docker CLI would achieve nothing regardless: the build runs
  # inside the Docker daemon, which does not inherit the client's priority.
  # Constrain build load through the daemon (BuildKit) if it ever becomes a
  # problem for Checkfunnel.
  echo "==> Building backend (shares 2 vCPU with Checkfunnel)"
  dc build backend
  # knowledge_processor is a *separate image*, not another container off the backend
  # one, so leaving it out here meant `up -d` kept recreating it from whatever was
  # built the first time. The service that does all the crawling and embedding was
  # therefore running code from an unknown earlier deploy, indefinitely and silently.
  # It shares the backend's Dockerfile and context, so this is a cache hit and costs
  # seconds — but it must be sequential: parallel builds of the same layers race on
  # the ~200MB torch wheel, which is what corrupted it and failed the very first build.
  echo "==> Building knowledge_processor"
  dc build knowledge_processor
  echo "==> Building frontend"
  dc build frontend
fi

echo "==> Starting services"
dc up -d

echo "==> Waiting for backend health"
for i in $(seq 1 60); do
  if curl -sf -m 5 http://127.0.0.1:8080/health >/dev/null 2>&1; then
    echo "    backend healthy after ${i}0s"; break
  fi
  [ "$i" = "60" ] && { echo "    backend did not come up; recent logs:"; dc logs --tail=40 backend; exit 1; }
  sleep 10
done

echo "==> Public endpoint"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$DOMAIN/" || echo 000)
echo "    $DOMAIN -> HTTP $code"

echo "==> Checkfunnel untouched?"
systemctl is-active --quiet checkfunnel-daphne && echo "    checkfunnel-daphne: active" || echo "    WARNING: checkfunnel-daphne is NOT active"
systemctl is-active --quiet nginx && echo "    nginx: active" || echo "    WARNING: nginx is NOT active"

echo "==> Done. Containers:"
dc ps --format "table {{.Service}}\t{{.Status}}"
