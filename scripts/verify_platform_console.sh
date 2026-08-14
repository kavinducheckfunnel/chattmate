#!/usr/bin/env bash
#
# Copyright 2024-2026 ChatterMate
# Licensed under the Apache License, Version 2.0 — see LICENSE.
#
# Exercise every operator-console endpoint against a running deployment, and
# check that the tenant boundary still holds.
#
#   ./scripts/verify_platform_console.sh https://chat.growmiq.io ops@growmiq.io 'password'
#
# Read-only apart from one deliberate write: reading a transcript records an
# audit row, which is the point — the last check confirms that row exists.

set -uo pipefail

BASE="${1:?usage: verify_platform_console.sh <base-url> <operator-email> <password>}"
EMAIL="${2:?operator email required}"
PASSWORD="${3:?operator password required}"
API="$BASE/api/v1"
JAR=$(mktemp)
trap 'rm -f "$JAR"' EXIT

pass=0; fail=0

check() {
  local label="$1" expected="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    printf '  ok    %-52s %s\n' "$label" "$actual"; pass=$((pass + 1))
  else
    printf '  FAIL  %-52s got %s, want %s\n' "$label" "$actual" "$expected"; fail=$((fail + 1))
  fi
}

code() { curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" -m 30 "$@"; }
body() { curl -s -b "$JAR" -c "$JAR" -m 30 "$@"; }

echo "==> Signing in as $EMAIL"
LOGIN=$(curl -s -c "$JAR" -m 30 -X POST "$API/users/login" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode "username=$EMAIL" --data-urlencode "password=$PASSWORD")

ORG=$(printf '%s' "$LOGIN" | python3 -c 'import json,sys; print(json.load(sys.stdin)["user"].get("organization_id"))' 2>/dev/null || echo PARSE_ERROR)
ADMIN=$(printf '%s' "$LOGIN" | python3 -c 'import json,sys; print(json.load(sys.stdin)["user"].get("is_platform_admin"))' 2>/dev/null || echo PARSE_ERROR)

check "login returns is_platform_admin" "True" "$ADMIN"
# A standalone operator belongs to no tenant, so it cannot act inside one even
# by accident. That structural separation is the whole point of the account.
check "operator belongs to no workspace" "None" "$ORG"

echo "==> Console reads"
check "GET /platform/overview"  200 "$(code "$API/platform/overview")"
check "GET /platform/stats"     200 "$(code "$API/platform/stats")"
check "GET /platform/tenants"   200 "$(code "$API/platform/tenants")"
check "GET /platform/users"     200 "$(code "$API/platform/users")"
check "GET /platform/plans"     200 "$(code "$API/platform/plans")"
check "GET /platform/features"  200 "$(code "$API/platform/features")"
check "GET /platform/analytics" 200 "$(code "$API/platform/analytics?range=30d")"
check "GET /platform/health"    200 "$(code "$API/platform/health")"
check "GET /platform/ai"        200 "$(code "$API/platform/ai")"
check "GET /platform/audit"     200 "$(code "$API/platform/audit")"
check "GET /platform/operators" 200 "$(code "$API/platform/operators")"

echo "==> Tenant routes stay closed to an org-less operator"
# 403, not 200: these resolve an organization from the session, and there is
# none. If this ever returns 200 the operator has silently acquired a tenant.
check "GET /agent/list (no workspace)" 403 "$(code "$API/agent/list")"

echo "==> Per-tenant reads"
# Prefer a tenant that actually has conversations, so the cross-tenant
# transcript probe below runs instead of silently skipping. A verification
# script whose most important check quietly opts out is worse than one that
# fails, because the summary line still says everything passed.
TENANT=$(body "$API/platform/tenants?limit=50" | python3 -c '
import json,sys
d = json.load(sys.stdin)
ts = d.get("tenants", [])
withchat = [t for t in ts if t.get("conversations")]
print((withchat or ts)[0]["id"] if ts else "")' 2>/dev/null)

if [ -z "$TENANT" ]; then
  echo "  skip  no tenants on this deployment"
else
  check "GET tenant detail"        200 "$(code "$API/platform/tenants/$TENANT")"
  check "GET tenant agents"        200 "$(code "$API/platform/tenants/$TENANT/agents")"
  check "GET tenant knowledge"     200 "$(code "$API/platform/tenants/$TENANT/knowledge")"
  check "GET tenant integrations"  200 "$(code "$API/platform/tenants/$TENANT/integrations")"
  check "GET tenant conversations" 200 "$(code "$API/platform/tenants/$TENANT/conversations")"
  check "GET tenant features"      200 "$(code "$API/platform/tenants/$TENANT/features")"
  check "GET tenant roles"         200 "$(code "$API/platform/roles?organization_id=$TENANT")"

  echo "==> Feature resolution reports all three layers"
  LAYERS=$(body "$API/platform/tenants/$TENANT/features" | python3 -c '
import json,sys
d = json.load(sys.stdin)
f = d["features"][0] if d.get("features") else {}
print("ok" if all(k in f for k in ("plan_default", "override", "effective")) else "missing")' 2>/dev/null)
  check "plan_default / override / effective present" "ok" "$LAYERS"

  echo "==> Cross-tenant guard"
  OTHER=$(TENANT="$TENANT" body "$API/platform/tenants?limit=50" | TENANT="$TENANT" python3 -c '
import json,os,sys
d = json.load(sys.stdin)
ids = [t["id"] for t in d.get("tenants", []) if t["id"] != os.environ["TENANT"]]
print(ids[0] if ids else "")' 2>/dev/null)
  SESSION=$(body "$API/platform/tenants/$TENANT/conversations?limit=1" | python3 -c '
import json,sys
d = json.load(sys.stdin)
c = d.get("conversations", [])
print(c[0]["session_id"] if c else "")' 2>/dev/null)

  if [ -n "$OTHER" ] && [ -n "$SESSION" ]; then
    # A valid session id read through the wrong tenant's URL must 404. Without
    # that check the audit row would name the wrong customer, which makes the
    # log actively misleading rather than merely incomplete.
    check "session via wrong tenant URL" 404 \
      "$(code "$API/platform/tenants/$OTHER/conversations/$SESSION")"
    check "session via own tenant URL"   200 \
      "$(code "$API/platform/tenants/$TENANT/conversations/$SESSION")"

    echo "==> Transcript read was audited"
    AUDITED=$(body "$API/platform/audit?organization_id=$TENANT" | python3 -c '
import json,sys
rows = json.load(sys.stdin)
print("yes" if any(r["action"] == "conversation.read" for r in rows) else "no")' 2>/dev/null)
    check "conversation.read row written" "yes" "$AUDITED"
  else
    echo "  skip  needs two tenants and one conversation to test"
  fi
fi

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
