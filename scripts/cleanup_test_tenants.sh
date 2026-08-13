#!/usr/bin/env bash
#
# Remove tenants created by the isolation test suites. Run ON the VPS:
#
#   /opt/chattermate/scripts/cleanup_test_tenants.sh
#
# Deletion goes through the ORM, not SQL. `DELETE FROM organizations` fails on
# the roles foreign key — there is no ON DELETE CASCADE at the database level,
# the cascade is declared on the SQLAlchemy relationships. Those relationships
# also had to be corrected: agents, widgets, workflows, knowledge sources, MCP
# tools and groups all carry a NOT NULL organization_id, so without an explicit
# cascade SQLAlchemy tried to SET NULL and every delete failed.
#
# Only fixture domains are matched, so a real customer cannot be caught by it.

set -euo pipefail

CONTAINER="${CONTAINER:-chattermate-backend-1}"

# -i is required: `python -` reads the program from stdin, and without an
# interactive stream docker exec forwards nothing, so python received an empty
# script and exited without doing anything.
# `|| true` on the grep so a run that legitimately prints nothing after
# filtering does not trip pipefail and fail the whole deploy.
# Anchoring the filter at ^ missed everything: importing the app emits log lines
# that begin with a timestamp, so the level appears mid-line.
docker exec -i "$CONTAINER" python - <<'PY' 2>&1 | { grep -viE " - (DEBUG|INFO|WARNING|ERROR) - |enterprise|server init|orm_mode|regex|deprecat" || true; }
from app.database import SessionLocal
from app.models.organization import Organization

# Fixture prefixes used by tenant_isolation_smoke.sh and tenant_isolation_full.sh,
# plus the manual auth-flow checks (verification and password reset).
PATTERNS = [
    "smoke-a-%", "smoke-b-%", "dup-%",
    "iso-a-%", "iso-b-%",
    "vtest-%", "hgate-%",
]

db = SessionLocal()
removed = []
for pattern in PATTERNS:
    for org in db.query(Organization).filter(Organization.domain.like(pattern)).all():
        removed.append(org.domain)
        db.delete(org)
db.commit()
print(f"removed {len(removed)} test tenant(s)")
for d in removed:
    print(f"  - {d}")
print("remaining:", [o.domain for o in db.query(Organization).all()])
db.close()
PY
