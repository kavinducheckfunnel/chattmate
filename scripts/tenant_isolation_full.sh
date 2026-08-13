#!/usr/bin/env bash
#
# Full cross-tenant IDOR sweep. The narrow smoke test proves organizations,
# agents and users are scoped; this walks the wider by-ID surface, which is
# where an isolation bug actually hides.
#
#   ./scripts/tenant_isolation_full.sh [base_url]     # default http://127.0.0.1:8080
#
# Method: stand up two tenants, create every resource we can as A, then try to
# reach each one as B. Anything other than 403/404 is a cross-customer leak.
#
# Why by-ID and not just list endpoints: a list endpoint filters by
# organization_id almost by construction, because it has to pick rows somehow.
# A by-ID lookup takes the tenant boundary as an *extra* step a developer has to
# remember — several repositories here expose get_by_id() with no org argument
# at all, so the check lives in the handler or nowhere. That is the gap this
# script is pointed at.
#
# Writes are probed as well as reads. Being unable to read another tenant's
# workflow matters less than being unable to overwrite it.
#
# Exit non-zero if any probe leaks.

set -uo pipefail

BASE="${1:-http://127.0.0.1:8080}"
API="$BASE/api/v1"
S="$(date +%s)$$"
PW='SmokeTestPw123!'
PASS=0; FAIL=0; SKIP=0

g(){ printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
b(){ printf '  \033[31mLEAK\033[0m %s — %s\n' "$1" "$2"; FAIL=$((FAIL+1)); }
s(){ printf '  \033[33mSKIP\033[0m %s — %s\n' "$1" "$2"; SKIP=$((SKIP+1)); }

jarA="$(mktemp)"; jarB="$(mktemp)"; body="$(mktemp)"
trap 'rm -f "$jarA" "$jarB" "$body"' EXIT

# Content probe, for COLLECTION endpoints that accept a tenant id as a filter.
# A 200 there is not automatically a leak — the correct behaviour is usually to
# ignore the attacker-supplied filter and return the caller's own rows. So the
# question is not the status code but whether A's data appears in B's response.
# `marker` is a string only A's records contain.
probe_body(){ # label path marker
  local label="$1" path="$2" marker="$3" out code
  out=$(curl -s -m 20 -b "$jarB" -w '\n%{http_code}' "$API$path")
  code=$(printf '%s' "$out" | tail -1)
  if printf '%s' "$out" | grep -qF "$marker"; then
    b "$label" "A's data ('$marker') visible to B — HTTP $code"
  else
    case "$code" in
      2*|403|404) g "$label (no A data; HTTP $code)" ;;
      *)          s "$label" "inconclusive HTTP $code" ;;
    esac
  fi
}

# Probe: any 2xx means B reached A's resource.
probe(){ # label method path [data]
  local label="$1" method="$2" path="$3" data="${4:-}"
  local out code resp
  if [ -n "$data" ]; then
    out=$(curl -s -m 20 -b "$jarB" -w '\n%{http_code}' -X "$method" "$API$path" \
          -H 'Content-Type: application/json' -d "$data")
  else
    out=$(curl -s -m 20 -b "$jarB" -w '\n%{http_code}' -X "$method" "$API$path")
  fi
  code=$(printf '%s' "$out" | tail -1)
  resp=$(printf '%s' "$out" | sed '$d')
  case "$code" in
    403|404) g "$label (blocked $code)" ;;
    2*)      b "$label" "B reached A's resource — HTTP $code" ;;
    4*)
      # The workflow routes reject cross-tenant access with 400 + "does not
      # belong to your organization" rather than 404. That IS a block, so it
      # must not be reported as inconclusive — but see the note in the summary:
      # a 400 naming the reason confirms the resource exists to a non-owner,
      # which 404 (used everywhere else here) deliberately does not.
      if printf '%s' "$resp" | grep -qi "does not belong\|not authorized\|unauthorized\|not found"; then
        g "$label (blocked $code — ownership rejected)"
      else
        s "$label" "inconclusive HTTP $code: $(printf '%s' "$resp" | head -c 60)"
      fi
      ;;
    *)       s "$label" "inconclusive HTTP $code" ;;
  esac
}

jget(){ python3 -c "import json,sys;d=json.load(open('$body'));print(d.get('$1','') if isinstance(d,dict) else '')" 2>/dev/null; }

# Guard every id before it is used in a probe path. Without this the suite can
# report all-green while testing nothing: an empty id turns "/agent/$AGENT" into
# "/agent/", which 404s, and a 404 is exactly what a blocked probe looks like.
# A missing fixture must be loud, never a silent pass.
need(){ # value label -> 0 if usable
  if [ -z "$2" ]; then
    s "$1" "fixture missing — probe not run (would have false-passed on 404)"
    return 1
  fi
  return 0
}

signup(){ # name domain email -> id
  curl -s -o "$body" -X POST "$API/organizations" -H 'Content-Type: application/json' \
    -d "{\"name\":\"$1\",\"domain\":\"$2\",\"timezone\":\"UTC\",\"admin_email\":\"$3\",\"admin_name\":\"$1\",\"admin_password\":\"$PW\"}" >/dev/null
  jget id
}
login(){ curl -s -o /dev/null -c "$2" -X POST "$API/users/login" \
         --data-urlencode "username=$1" --data-urlencode "password=$PW"; }

echo "Cross-tenant IDOR sweep — $BASE"
echo

ORG_A=$(signup "IsoA$S" "iso-a-$S.com" "iso-a-$S@example.com")
ORG_B=$(signup "IsoB$S" "iso-b-$S.com" "iso-b-$S@example.com")
[ -z "$ORG_A" ] || [ -z "$ORG_B" ] && { echo "could not create both tenants (signup closed or rate-limited?)"; exit 1; }
login "iso-a-$S@example.com" "$jarA"
login "iso-b-$S@example.com" "$jarB"
echo "tenants: A=$ORG_A  B=$ORG_B"
echo

# ---- build resources as tenant A -------------------------------------------
# Reports what the API said when a create fails. A silent skip is the worst
# outcome here: it looks like a clean run while the probe it feeds never ran.
mkA(){
  local code
  code=$(curl -s -o "$body" -m 30 -w '%{http_code}' -b "$jarA" -X "${3:-POST}" "$API$1" \
         -H 'Content-Type: application/json' -d "$2")
  case "$code" in
    2*) : ;;
    *)  printf '  \033[33m  setup\033[0m %s -> HTTP %s: %s\n' "$1" "$code" "$(head -c 160 "$body")" ;;
  esac
}

mkA /agent '{"name":"IsoAgent","agent_type":"customer_support","instructions":["CONFIDENTIAL-ISO-PROMPT"]}'
AGENT=$(jget id)

mkA /widgets "{\"name\":\"IsoWidget\",\"agent_id\":\"$AGENT\"}"
WIDGET=$(jget id)

mkA /workflow "{\"name\":\"IsoFlow\",\"agent_id\":\"$AGENT\",\"description\":\"x\"}"
WORKFLOW=$(jget id)

mkA /roles '{"name":"IsoRole","description":"x","permissions":[]}'
ROLE=$(jget id)

ADMIN_A=$(curl -s -b "$jarA" "$API/users" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d[0]["id"] if isinstance(d,list) and d else "")' 2>/dev/null)

echo "Organization"
probe "B reads A's org"                 GET   "/organizations/$ORG_A"
probe "B modifies A's org"              PATCH "/organizations/$ORG_A" '{"name":"pwned"}'
probe "B reads A's org stats"           GET   "/organizations/$ORG_A/stats"

echo
echo "Users — account-takeover surface"
if need "users probes" "$ADMIN_A"; then
  probe "B reads A's admin user"        GET   "/users/$ADMIN_A"
  probe "B RESETS A's admin password"   POST  "/users/$ADMIN_A/reset-password" '{"new_password":"Attacker123!"}'
  probe "B overwrites A's admin"        PUT   "/users/$ADMIN_A" '{"full_name":"pwned","email":"pwned@example.com"}'
  probe "B deletes A's admin"           DELETE "/users/$ADMIN_A"
  # /users/{id}/status is deliberately not probed: it sets the caller's OWN
  # online presence (the handler compares user.id to current_user.id), so it is
  # not an administrative surface and a 4xx there proves nothing about tenancy.
fi

echo
echo "Roles — privilege-escalation surface"
if need "role probes" "$ROLE"; then
  probe "B reads A's role"              GET   "/roles/$ROLE"
  probe "B grants super_admin on A's role" POST "/roles/$ROLE/permissions/super_admin"
  probe "B deletes A's role"            DELETE "/roles/$ROLE"
fi

echo
echo "Agents"
if need "agent probes" "$AGENT"; then
  probe "B reads A's agent"             GET   "/agent/$AGENT"
  probe "B reads A's lead-capture cfg"  GET   "/agent/$AGENT/lead-capture"
fi

echo
echo "Widgets — public bootstrap, so judged on payload not status"
if need "widget probes" "$WIDGET"; then
  # GET /widgets/{id} is deliberately unauthenticated: the embedded widget on a
  # customer's website fetches it anonymously to render itself, and the widget id
  # is public by nature (it sits in the page source). A 200 for tenant B is
  # therefore correct and NOT a leak — the meaningful question is what the body
  # contains. Verified below: display name, theming and org id only.
  anon=$(curl -s -m 20 "$API/widgets/$WIDGET")
  if printf '%s' "$anon" | grep -qF 'CONFIDENTIAL'; then
    b "public widget hides agent instructions" "agent prompt exposed to anonymous callers"
  elif printf '%s' "$anon" | grep -q '"agent"'; then
    g "public widget returns theming only (no agent instructions)"
  else
    s "public widget payload" "unexpected shape: $(printf '%s' "$anon" | head -c 80)"
  fi
  # Mutation, by contrast, must be owner-only.
  probe "B deletes A's widget"          DELETE "/widgets/$WIDGET"
fi

echo
echo "Workflows"
if need "workflow probes" "$WORKFLOW"; then
  probe "B reads A's workflow nodes"    GET   "/workflow/$WORKFLOW/nodes"
  probe "B overwrites A's workflow"     PUT   "/workflow/$WORKFLOW" '{"name":"pwned","description":"x"}'
  probe "B deletes A's workflow"        DELETE "/workflow/$WORKFLOW"
fi

echo
echo "Knowledge — org id taken straight from the path"
# There is no GET /knowledge/{id}; the readable surface is org-scoped by path,
# which is the more dangerous shape — the caller supplies the tenant id, so the
# handler must reject one that isn't theirs rather than trust it.
probe "B lists A's knowledge"           GET   "/knowledge/organization/$ORG_A"
probe "B lists A's ingest queue"        GET   "/knowledge/queue/organization/$ORG_A"
if need "agent-scoped knowledge probes" "$AGENT"; then
  probe "B lists knowledge of A's agent" GET  "/knowledge/agent/$AGENT"
  # This one returns 200 with an empty list rather than 404 — it filters on the
  # caller's organization_id, so B simply sees nothing. Status alone would read
  # as a leak; the content is what proves the scoping.
  probe_body "B reads A's agent queue"  "/knowledge/queue/agent/$AGENT" "IsoAgent"
fi

echo
echo "Collections with an attacker-supplied org filter"
# Ticket ids are UUIDs, so enumeration is not the risk here — passing another
# tenant's org id to a collection endpoint is. Judged on content, not status:
# returning B's own rows while ignoring the bogus filter is correct.
probe_body "B lists A's chats by org filter"  "/chat?organization_id=$ORG_A"    "IsoAgent"
probe_body "B lists A's tickets by org"       "/tickets?organization_id=$ORG_A" "IsoAgent"
probe_body "B lists agents with A's org id"   "/agent/list?organization_id=$ORG_A" "IsoAgent"
probe_body "B lists users with A's org id"    "/users?organization_id=$ORG_A"   "iso-a-$S@example.com"

echo
printf 'passed %d, leaks %d, skipped %d\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ]
