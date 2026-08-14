"""
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

The gate and the audit pen for the operator console.

Lives in core rather than beside the routes because the console now spans
several API modules (tenants, analytics, health, AI, billing, backups) and all
of them must gate identically. One copy means a change to the rule — or a bug
in it — cannot apply to some console routes and not others.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.logger import get_logger
from app.database import get_db
from app.models.organization import Organization
from app.models.platform_audit import PlatformAuditLog
from app.models.user import User

logger = get_logger(__name__)


async def require_platform_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Gate every console route.

    Re-reads the flag rather than trusting the authenticated object, which may
    have been loaded from a cached session. Platform access is the highest
    privilege in the system; revocation must be immediate.

    404, not 403. A tenant admin probing for an operator console should not
    learn that one exists — 403 confirms the route is real and worth attacking,
    while 404 is indistinguishable from a typo.
    """
    fresh = db.query(User.is_platform_admin).filter(User.id == current_user.id).scalar()
    if not fresh:
        logger.warning(
            "Non-platform user %s (%s) attempted to reach the platform console",
            current_user.id, current_user.email,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return current_user


def client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def audit(db: Session, actor: User, request: Request, action: str,
          org: Optional[Organization] = None, **details) -> None:
    """Record an operator action. Added to the caller's transaction on purpose.

    Not committed here: the caller commits the change and its audit row
    together, so a mutation can never be persisted without its record. A
    separate commit would let one succeed while the other rolled back.
    """
    db.add(PlatformAuditLog(
        actor_user_id=actor.id,
        actor_email=actor.email,
        action=action,
        target_organization_id=org.id if org is not None else None,
        target_organization_domain=org.domain if org is not None else None,
        details=details or {},
        ip_address=client_ip(request),
    ))


def require_org(db: Session, organization_id: str) -> Organization:
    """Load a tenant or 404. Shared so every console route phrases it the same."""
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return org
