#!/usr/bin/env bash
#
# Restore a ChatterMate backup.
#
#   restore.sh --verify <db-dump>            rehearse into a throwaway database (SAFE)
#   restore.sh --into-live <db-dump>         overwrite the live database (DESTRUCTIVE)
#   restore.sh --list                        show available backups
#
# --verify is the one to run on a schedule. It spins up a separate Postgres
# container, restores into it, counts what came back, and destroys it — proving
# the dump is loadable without touching production. An untested backup is a
# hypothesis, not a recovery plan.
#
# Restoring the database alone is not a full recovery. You also need:
#   * uploads-<stamp>.tar.gz  — attachments and knowledge files
#   * env-<stamp>.tar.gz      — ENCRYPTION_KEY, without which restored message
#                               bodies and stored credentials stay unreadable
# Restore all three from the SAME timestamp.

set -uo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/chattermate}"
APP_DIR="${APP_DIR:-/opt/chattermate}"
DB_CONTAINER="${DB_CONTAINER:-chattermate-db-1}"
VERIFY_CONTAINER="chattermate-restore-check"
PG_IMAGE="${PG_IMAGE:-pgvector/pgvector:pg16}"

die() { echo "ERROR: $*" >&2; exit 1; }

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

MODE="${1:-}"
[ -z "$MODE" ] && usage 1

if [ "$MODE" = "--list" ]; then
  echo "Backups in $BACKUP_DIR:"
  ls -lh "$BACKUP_DIR" 2>/dev/null | grep -E '\.(dump|tar\.gz)$' || echo "  (none)"
  exit 0
fi

DUMP="${2:-}"
[ -z "$DUMP" ] && die "need a dump file. Try: $0 --list"
[ -f "$DUMP" ] || DUMP="$BACKUP_DIR/$DUMP"
[ -f "$DUMP" ] || die "no such dump: $DUMP"

case "$MODE" in
  --verify)
    echo "==> Rehearsing restore of $(basename "$DUMP") in a throwaway container"
    docker rm -f "$VERIFY_CONTAINER" >/dev/null 2>&1 || true
    # Not published on any port and torn down at the end — it cannot collide
    # with the live stack or the native Postgres on this host.
    docker run -d --name "$VERIFY_CONTAINER" \
      -e POSTGRES_PASSWORD=verify -e POSTGRES_USER=postgres -e POSTGRES_DB=chattermate \
      "$PG_IMAGE" >/dev/null || die "could not start verification container"

    trap 'docker rm -f "$VERIFY_CONTAINER" >/dev/null 2>&1 || true' EXIT

    printf '    waiting for postgres'
    for _ in $(seq 1 30); do
      docker exec "$VERIFY_CONTAINER" pg_isready -U postgres -d chattermate >/dev/null 2>&1 && break
      printf '.'; sleep 2
    done
    echo
    docker exec "$VERIFY_CONTAINER" pg_isready -U postgres -d chattermate >/dev/null 2>&1 \
      || die "verification postgres never became ready"

    # pgvector must exist before restore: several tables carry vector columns and
    # the dump's CREATE EXTENSION runs as a non-superuser-safe no-op if absent.
    docker exec "$VERIFY_CONTAINER" psql -U postgres -d chattermate -c 'CREATE EXTENSION IF NOT EXISTS vector;' >/dev/null 2>&1

    echo "==> Restoring"
    # --clean --if-exists so a rerun is idempotent. Non-zero exit is common and
    # not necessarily fatal (ownership/extension notices), so judge by the data.
    docker exec -i "$VERIFY_CONTAINER" pg_restore -U postgres -d chattermate \
      --clean --if-exists --no-owner --no-privileges < "$DUMP" > /tmp/cm-restore.log 2>&1 || true

    echo "==> What came back"
    # No `tr -d ' '` here — it would strip the separators out of the summary and
    # run the counts together as one unreadable string.
    ROWS=$(docker exec "$VERIFY_CONTAINER" psql -U postgres -d chattermate -tAc "
      SELECT 'organizations=' || (SELECT count(*) FROM organizations)
          || ' users='        || (SELECT count(*) FROM users)
          || ' agents='       || (SELECT count(*) FROM agents)
          || ' tables='       || (SELECT count(*) FROM information_schema.tables WHERE table_schema='public');
    " 2>/dev/null | xargs)

    if [ -z "$ROWS" ]; then
      echo "    RESTORE FAILED — could not query restored data. Log:"
      tail -20 /tmp/cm-restore.log
      exit 1
    fi
    echo "    $ROWS"
    # `grep -c` already prints 0 when it matches nothing, and exits 1 doing so —
    # a `|| echo 0` fallback appends a second zero and prints "0\n0".
    ERRS=$(grep -ci "^pg_restore: error" /tmp/cm-restore.log 2>/dev/null); ERRS="${ERRS:-0}"
    echo "    pg_restore errors: $ERRS (see /tmp/cm-restore.log)"
    echo
    echo "RESTORE VERIFIED — dump is loadable."
    echo "Reminder: a real recovery also needs uploads-*.tar.gz and env-*.tar.gz from the same timestamp."
    ;;

  --into-live)
    echo "!!  This OVERWRITES the live database in $DB_CONTAINER."
    echo "!!  Dump: $DUMP"
    printf '!!  Type RESTORE to continue: '
    read -r confirm
    [ "$confirm" = "RESTORE" ] || die "aborted"

    cd "$APP_DIR" || die "no $APP_DIR"
    DC="docker compose -p chattermate -f docker-compose.growmiq.yml --env-file .env.growmiq"

    echo "==> Stopping app services (db stays up to receive the restore)"
    $DC stop backend knowledge_processor frontend

    echo "==> Restoring"
    docker exec -i "$DB_CONTAINER" pg_restore -U postgres -d chattermate \
      --clean --if-exists --no-owner --no-privileges < "$DUMP" 2>&1 | tail -20

    echo "==> Restarting"
    $DC up -d
    echo "==> Done. Verify at https://chat.growmiq.io/health"
    echo "    If uploads were lost too, restore the matching uploads archive:"
    echo "      docker run --rm -i -v chattermate_uploads:/data -w /data alpine:3 tar xzf - < uploads-<stamp>.tar.gz"
    ;;

  *) usage 1 ;;
esac
