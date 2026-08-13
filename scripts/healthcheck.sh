#!/usr/bin/env bash
#
# Resource and liveness watch for the ChatterMate stack. Runs every 10 minutes
# from /etc/cron.d/chattermate-health.
#
# This box runs Checkfunnel too, on 2 vCPU and 7.8 GB. The failure that actually
# matters here is not ChatterMate dying on its own — it is ChatterMate consuming
# enough memory that the kernel OOM-kills something in the *other* project. So
# the thresholds are deliberately early (80%, not 95%): there needs to be room to
# react before the kernel starts choosing victims.
#
# Alerting: writes to the log always, and emails root when something trips.
# Point ALERT_WEBHOOK at a Slack/Discord incoming webhook for push alerts.

set -uo pipefail

DISK_PCT_MAX="${DISK_PCT_MAX:-80}"
MEM_PCT_MAX="${MEM_PCT_MAX:-85}"
SWAP_PCT_MAX="${SWAP_PCT_MAX:-50}"
URL="${URL:-https://chat.growmiq.io/health}"
STATE=/var/lib/chattermate-health.state

[ -f /etc/chattermate-backup.env ] && . /etc/chattermate-backup.env

ALERTS=()
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
alert() { ALERTS+=("$1"); log "ALERT: $1"; }

# --- disk ---
DISK=$(df --output=pcent / | tail -1 | tr -dc '0-9')
[ "${DISK:-0}" -ge "$DISK_PCT_MAX" ] && alert "disk at ${DISK}% (limit ${DISK_PCT_MAX}%) — docker images here are ~5 GB, prune with 'docker image prune -a'"

# --- memory ---
read -r MEM_TOTAL MEM_AVAIL <<<"$(free -m | awk '/^Mem:/{print $2, $7}')"
MEM_USED_PCT=$(( (MEM_TOTAL - MEM_AVAIL) * 100 / MEM_TOTAL ))
[ "$MEM_USED_PCT" -ge "$MEM_PCT_MAX" ] && alert "memory at ${MEM_USED_PCT}% (${MEM_AVAIL}MB available) — risk of OOM-killing Checkfunnel"

# --- swap ---
# Sustained swap use on this box means the working set no longer fits. It is the
# early warning for the memory alert above, not a problem in itself.
read -r SWAP_TOTAL SWAP_USED <<<"$(free -m | awk '/^Swap:/{print $2, $3}')"
if [ "${SWAP_TOTAL:-0}" -gt 0 ]; then
  SWAP_PCT=$(( SWAP_USED * 100 / SWAP_TOTAL ))
  [ "$SWAP_PCT" -ge "$SWAP_PCT_MAX" ] && alert "swap at ${SWAP_PCT}% (${SWAP_USED}MB) — the box is over-committed"
fi

# --- containers ---
EXPECTED="chattermate-db-1 chattermate-redis-1 chattermate-backend-1 chattermate-frontend-1 chattermate-knowledge_processor-1"
for c in $EXPECTED; do
  state=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo missing)
  [ "$state" = "running" ] || alert "container $c is '$state'"
done

# Restart loops are invisible in a plain status check — a container that has
# restarted repeatedly reports "running" between crashes.
for c in $EXPECTED; do
  rc=$(docker inspect -f '{{.RestartCount}}' "$c" 2>/dev/null || echo 0)
  prev=$(grep -E "^${c}=" "$STATE" 2>/dev/null | cut -d= -f2)
  if [ -n "$prev" ] && [ "${rc:-0}" -gt "$((prev + 2))" ]; then
    alert "container $c restarted $((rc - prev)) times since last check — crash loop"
  fi
done
mkdir -p "$(dirname "$STATE")"
: > "$STATE"
for c in $EXPECTED; do
  printf '%s=%s\n' "$c" "$(docker inspect -f '{{.RestartCount}}' "$c" 2>/dev/null || echo 0)" >> "$STATE"
done

# --- public endpoint ---
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$URL" || echo 000)
[ "$CODE" = "200" ] || alert "health endpoint returned $CODE (expected 200)"

# --- the neighbour ---
# ChatterMate must never be the reason Checkfunnel is down.
for svc in checkfunnel-daphne nginx; do
  systemctl is-active --quiet "$svc" || alert "$svc is NOT active"
done

# --- backup freshness ---
NEWEST=$(find /var/backups/chattermate -name 'db-*.dump' -mtime -2 2>/dev/null | head -1)
[ -z "$NEWEST" ] && alert "no database backup newer than 48h"

# --- report ---
if [ "${#ALERTS[@]}" -eq 0 ]; then
  log "OK disk=${DISK}% mem=${MEM_USED_PCT}% swap=${SWAP_PCT:-0}% http=${CODE}"
  exit 0
fi

BODY=$(printf 'ChatterMate health alerts on %s:\n\n' "$(hostname)"; printf '  - %s\n' "${ALERTS[@]}")
echo "$BODY" | mail -s "ChatterMate: ${#ALERTS[@]} alert(s)" root 2>/dev/null || true
if [ -n "${ALERT_WEBHOOK:-}" ]; then
  payload=$(printf '%s' "$BODY" | python3 -c 'import json,sys; print(json.dumps({"text": sys.stdin.read()}))')
  curl -s -m 15 -X POST -H 'Content-Type: application/json' -d "$payload" "$ALERT_WEBHOOK" >/dev/null || true
fi
exit 1
