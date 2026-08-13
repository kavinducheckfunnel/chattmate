#!/usr/bin/env bash
#
# Nightly backup for the ChatterMate stack. Installed at
# /usr/local/bin/chattermate-backup.sh and run from /etc/cron.d/chattermate-backup.
#
# Three things are captured, and all three are needed for a working restore:
#
#   db       pg_dump of the chattermate database (custom format, compressed)
#   uploads  the uploads volume — chat attachments and knowledge-base files,
#            which live on disk and are NOT in the database
#   env      backend/.env, because it holds ENCRYPTION_KEY. Message bodies,
#            agent memory and stored provider credentials are encrypted with it,
#            so a database dump restored without that key is unreadable ciphertext.
#            This is the piece people discover is missing during an incident.
#
# The env archive is written 0600 and is the most sensitive artefact here: anyone
# holding it plus a database dump can read every tenant's conversations. Treat
# off-site copies accordingly.
#
# Exit codes: 0 all good, 1 something failed (cron will mail the output).

set -uo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/chattermate}"
APP_DIR="${APP_DIR:-/opt/chattermate}"
DB_CONTAINER="${DB_CONTAINER:-chattermate-db-1}"
UPLOADS_VOLUME="${UPLOADS_VOLUME:-chattermate_uploads}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
FAILED=0

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { log "ERROR: $*"; FAILED=1; }

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

log "starting backup -> $BACKUP_DIR"

# --- database ---------------------------------------------------------------
# -Fc (custom format) so a restore can be selective and parallel, and because it
# compresses. Written to a .part file first and moved on success, so a crashed
# or half-written dump can never masquerade as a good backup.
DB_OUT="$BACKUP_DIR/db-$STAMP.dump"
if docker exec "$DB_CONTAINER" pg_dump -U postgres -Fc chattermate > "$DB_OUT.part" 2>/tmp/cm-pgdump.err; then
  mv "$DB_OUT.part" "$DB_OUT"
  log "database: $(du -h "$DB_OUT" | cut -f1)"
else
  rm -f "$DB_OUT.part"
  fail "pg_dump failed: $(tail -2 /tmp/cm-pgdump.err 2>/dev/null)"
fi

# --- uploads ----------------------------------------------------------------
# Read through a throwaway container because the volume is not mounted on the
# host. --volumes-from would pin us to a running app container; this works even
# when the stack is down.
UP_OUT="$BACKUP_DIR/uploads-$STAMP.tar.gz"
if docker run --rm -v "$UPLOADS_VOLUME":/data:ro -w /data alpine:3 \
     tar czf - . > "$UP_OUT.part" 2>/tmp/cm-uploads.err; then
  mv "$UP_OUT.part" "$UP_OUT"
  log "uploads:  $(du -h "$UP_OUT" | cut -f1)"
else
  rm -f "$UP_OUT.part"
  fail "uploads archive failed: $(tail -2 /tmp/cm-uploads.err 2>/dev/null)"
fi

# --- secrets and compose config ---------------------------------------------
ENV_OUT="$BACKUP_DIR/env-$STAMP.tar.gz"
if tar czf "$ENV_OUT.part" -C "$APP_DIR" backend/.env frontend/.env .env.growmiq \
     docker-compose.growmiq.yml 2>/tmp/cm-env.err; then
  mv "$ENV_OUT.part" "$ENV_OUT"
  chmod 600 "$ENV_OUT"
  log "env:      $(du -h "$ENV_OUT" | cut -f1) (contains ENCRYPTION_KEY — keep private)"
else
  rm -f "$ENV_OUT.part"
  fail "env archive failed: $(tail -2 /tmp/cm-env.err 2>/dev/null)"
fi

# --- off-site ---------------------------------------------------------------
# A backup on the same disk as the database is not a backup. Configure a target
# in /etc/chattermate-backup.env to enable this; without one the copy is skipped
# loudly rather than silently.
if [ -f /etc/chattermate-backup.env ]; then
  # shellcheck disable=SC1091
  . /etc/chattermate-backup.env
fi
if [ -n "${OFFSITE_RCLONE_REMOTE:-}" ] && command -v rclone >/dev/null 2>&1; then
  if rclone copy "$BACKUP_DIR" "$OFFSITE_RCLONE_REMOTE" \
       --include "*-$STAMP.*" --transfers 2 2>/tmp/cm-offsite.err; then
    log "offsite:  copied to $OFFSITE_RCLONE_REMOTE"
  else
    fail "offsite copy failed: $(tail -2 /tmp/cm-offsite.err 2>/dev/null)"
  fi
else
  log "offsite:  SKIPPED — no OFFSITE_RCLONE_REMOTE configured. Backups exist only on this VPS."
fi

# --- retention --------------------------------------------------------------
# Only prune when this run succeeded. Deleting old good backups because a new one
# failed is how a bad night becomes an unrecoverable one.
if [ "$FAILED" -eq 0 ]; then
  find "$BACKUP_DIR" -maxdepth 1 -name '*.dump' -mtime +"$RETAIN_DAYS" -delete
  find "$BACKUP_DIR" -maxdepth 1 -name '*.tar.gz' -mtime +"$RETAIN_DAYS" -delete
  find "$BACKUP_DIR" -maxdepth 1 -name '*.part' -mtime +1 -delete
  log "retention: pruned artefacts older than ${RETAIN_DAYS}d"
else
  log "retention: SKIPPED because this run had failures — keeping all existing backups"
fi

log "total on disk: $(du -sh "$BACKUP_DIR" | cut -f1) | free: $(df -h "$BACKUP_DIR" | tail -1 | awk '{print $4}')"
[ "$FAILED" -eq 0 ] && log "backup OK" || log "backup FINISHED WITH ERRORS"
exit "$FAILED"
