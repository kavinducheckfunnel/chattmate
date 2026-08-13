#!/usr/bin/env bash
#
# Multi-tenant smoke test — run against a live ChatterMate stack.
#
#   ./scripts/tenant_isolation_smoke.sh [base_url]      # default http://127.0.0.1:8080
#
# Two things are being protected here, and both are easy to regress:
#
#   1. That a SECOND tenant can sign up at all. Upstream's POST /organizations
#      returns 403 once any organization exists; re-merging upstream can quietly
#      restore that lock and turn the product back into a single-tenant appliance.
#
#   2. That one tenant cannot reach another's data. Isolation is enforced by hand
#      in each endpoint — there is no row-level security backstop — so a missed
#      `organization_id` check in any new handler is a cross-customer data leak.
#      Direct-ID access is tested explicitly because list endpoints can look
#      correct while a by-id lookup stays unscoped.
#
# Exits non-zero if anything failed, so CI fails loudly.
#
# Note: this makes 4 signups per run against a default budget of 5 per IP per
# hour (SIGNUP_RATE_LIMIT_PER_HOUR). A second run inside the same hour will hit
# 429 and report false failures — raise the limit in the environment under test,
# or clear the counters first:
#   docker exec <redis> redis-cli --scan --pattern 'public_rl:signup:*' \
#     | xargs -r docker exec <redis> redis-cli DEL

set -uo pipefail

BASE="${1:-http://127.0.0.1:8080}"
API="$BASE/api/v1"
STAMP="$(date +%s)$$"
PASS=0; FAIL=0

ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s — %s\n' "$1" "$2"; FAIL=$((FAIL+1)); }
check(){ [ "$2" = "$3" ] && ok "$1" || bad "$1" "expected $3, got $2"; }

jarA="$(mktemp)"; jarB="$(mktemp)"; body="$(mktemp)"
trap 'rm -f "$jarA" "$jarB" "$body"' EXIT

signup() { # name domain email -> writes json to $body, echoes status
  curl -s -o "$body" -w '%{http_code}' -X POST "$API/organizations" \
    -H 'Content-Type: application/json' \
    -d "{\"name\":\"$1\",\"domain\":\"$2\",\"timezone\":\"UTC\",\"admin_email\":\"$3\",\"admin_name\":\"$1 Admin\",\"admin_password\":\"SmokeTestPw123\"}"
}
orgid() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["id"])' "$body"; }

echo "ChatterMate tenant isolation smoke — $BASE"
echo
echo "Signup"

code=$(signup "SmokeA$STAMP" "smoke-a-$STAMP.com" "a-$STAMP@smoketest.com")
check "tenant A can sign up" "$code" "201"
ORG_A=$(orgid)

code=$(signup "SmokeB$STAMP" "smoke-b-$STAMP.com" "b-$STAMP@smoketest.com")
check "tenant B can sign up (single-org lock is gone)" "$code" "201"
ORG_B=$(orgid)

code=$(signup "Dup$STAMP" "dup-$STAMP.com" "A-$STAMP@SMOKETEST.COM")
check "duplicate email rejected, case-insensitively" "$code" "409"

code=$(signup "Dup2$STAMP" "SMOKE-A-$STAMP.COM" "fresh-$STAMP@smoketest.com")
check "duplicate domain rejected, case-insensitively" "$code" "409"

echo
echo "Authentication"

code=$(curl -s -o /dev/null -w '%{http_code}' -c "$jarA" -X POST "$API/users/login" \
       --data-urlencode "username=A-$STAMP@SMOKETEST.COM" --data-urlencode "password=SmokeTestPw123")
check "login accepts mixed-case email" "$code" "200"

curl -s -o /dev/null -c "$jarB" -X POST "$API/users/login" \
     --data-urlencode "username=b-$STAMP@smoketest.com" --data-urlencode "password=SmokeTestPw123"

echo
echo "Isolation"

code=$(curl -s -o /dev/null -w '%{http_code}' -b "$jarA" "$API/organizations/$ORG_A")
check "A reads its own org" "$code" "200"

code=$(curl -s -o /dev/null -w '%{http_code}' -b "$jarA" "$API/organizations/$ORG_B")
check "A cannot read B's org" "$code" "404"

code=$(curl -s -o /dev/null -w '%{http_code}' -b "$jarA" -X PATCH "$API/organizations/$ORG_B" \
       -H 'Content-Type: application/json' -d '{"name":"pwned"}')
check "A cannot modify B's org" "$code" "404"

curl -s -o "$body" -b "$jarA" -X POST "$API/agent" -H 'Content-Type: application/json' \
     -d '{"name":"SmokeAgent","agent_type":"customer_support","instructions":["test"]}' >/dev/null
AGENT_A=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("id",""))' "$body" 2>/dev/null)

if [ -n "$AGENT_A" ]; then
  n=$(curl -s -b "$jarB" "$API/agent/list" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))' 2>/dev/null)
  check "B's agent list excludes A's agent" "$n" "0"

  code=$(curl -s -o /dev/null -w '%{http_code}' -b "$jarB" "$API/agent/$AGENT_A")
  check "B cannot fetch A's agent by direct id" "$code" "404"
else
  bad "agent creation" "could not create an agent as A"
fi

emails=$(curl -s -b "$jarB" "$API/users" | python3 -c 'import json,sys;print(",".join(u["email"] for u in json.load(sys.stdin)))' 2>/dev/null)
case "$emails" in
  *"a-$STAMP@smoketest.com"*) bad "B's user list excludes A's users" "leaked: $emails" ;;
  *) ok "B's user list excludes A's users" ;;
esac

echo
printf 'passed %d, failed %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
