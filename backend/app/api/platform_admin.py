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

The platform operator console: the one part of the application that crosses the
tenant boundary on purpose.

Everything else in this codebase is built to make cross-tenant access
impossible. These endpoints are the deliberate exception, so they carry rules
the rest of the API does not need:

  * Access comes from users.is_platform_admin, a column no API can write. The
    existing "super_admin" permission is organization-scoped and self-grantable
    — a tenant admin can add it to their own role — so building on it would
    have handed every customer the keys to every other customer.

  * The flag is re-read from the database on every request rather than trusted
    from the session. Revoking an operator has to take effect immediately, not
    whenever their week-old refresh token expires.

  * Every mutation writes a PlatformAuditLog row in the same transaction. If
    the audit write fails, the action fails with it.

  * Nothing here returns customer conversation content. The console answers
    "how much is this tenant using, and is their account healthy" — support
    questions — not "what did their customers say". Reading transcripts would
    need a separate, individually-audited impersonation flow with the
    customer's consent, which is deliberately not built.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.logger import get_logger
from app.database import get_db
from app.models.agent import Agent
from app.models.organization import Organization
from app.models.plan import Plan
from app.models.platform_audit import PlatformAuditLog
from app.models.usage import UsageCounter, current_period
from app.models.user import User
from app.services import usage as usage_service

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

async def require_platform_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Gate every route in this module.

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
            "Non-platform user %s (%s) attempted to reach %s",
            current_user.id, current_user.email, "platform console",
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return current_user


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _audit(db: Session, actor: User, request: Request, action: str,
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
        ip_address=_client_ip(request),
    ))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TenantUpdate(BaseModel):
    is_active: Optional[bool] = None
    plan_code: Optional[str] = None


class TenantDelete(BaseModel):
    # Typing the domain is the confirmation step. This deletes every agent,
    # conversation and document the tenant owns, and the operator should have
    # to look at which tenant they picked rather than click through a dialog.
    confirm_domain: str

    @field_validator("confirm_domain")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Type the tenant's domain to confirm")
        return v.strip().lower()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@router.get("/stats")
async def platform_stats(
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Headline numbers for the console."""
    period = current_period()
    total = db.scalar(select(func.count()).select_from(Organization)) or 0
    active = db.scalar(
        select(func.count()).select_from(Organization).where(Organization.is_active == True)
    ) or 0
    users = db.scalar(select(func.count()).select_from(User)) or 0

    # Platform-wide totals for the period, summed across tenants.
    rows = db.execute(
        select(UsageCounter.metric, func.sum(UsageCounter.value))
        .where(UsageCounter.period == period)
        .group_by(UsageCounter.metric)
    ).all()
    totals = {metric: int(value or 0) for metric, value in rows}

    by_plan = db.execute(
        select(Organization.plan_code, func.count())
        .group_by(Organization.plan_code)
    ).all()

    return {
        "period": period,
        "organizations": {"total": total, "active": active, "suspended": total - active},
        "users": users,
        "usage": {
            "conversations": totals.get("conversations", 0),
            "ai_messages": totals.get("ai_messages", 0),
        },
        "by_plan": {(code or "none"): count for code, count in by_plan},
    }


@router.get("/tenants")
async def list_tenants(
    q: Optional[str] = Query(None, description="Match name or domain"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Every tenant, with the counts an operator needs to triage.

    Usage is read in two grouped queries rather than per-tenant calls to the
    usage service: at 50 rows that would be 250 round trips, and the page would
    get slower with every customer signed.
    """
    query = db.query(Organization)
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.filter(or_(
            func.lower(Organization.name).like(like),
            func.lower(Organization.domain).like(like),
        ))

    total = query.count()
    orgs = (
        query.order_by(Organization.created_at.desc())
        .limit(limit).offset(offset).all()
    )
    org_ids = [o.id for o in orgs]

    seats, agents, flow = {}, {}, {}
    if org_ids:
        seats = dict(db.execute(
            select(User.organization_id, func.count())
            .where(User.organization_id.in_(org_ids))
            .group_by(User.organization_id)
        ).all())
        agents = dict(db.execute(
            select(Agent.organization_id, func.count())
            .where(Agent.organization_id.in_(org_ids))
            .group_by(Agent.organization_id)
        ).all())
        for org_id, metric, value in db.execute(
            select(UsageCounter.organization_id, UsageCounter.metric, UsageCounter.value)
            .where(
                UsageCounter.organization_id.in_(org_ids),
                UsageCounter.period == current_period(),
            )
        ).all():
            flow.setdefault(org_id, {})[metric] = value

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "period": current_period(),
        "tenants": [
            {
                "id": str(o.id),
                "name": o.name,
                "domain": o.domain,
                "plan_code": o.plan_code,
                "is_active": o.is_active,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "seats": seats.get(o.id, 0),
                "agents": agents.get(o.id, 0),
                "conversations": flow.get(o.id, {}).get("conversations", 0),
                "ai_messages": flow.get(o.id, {}).get("ai_messages", 0),
            }
            for o in orgs
        ],
    }


@router.get("/tenants/{organization_id}")
async def get_tenant(
    organization_id: str,
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """One tenant in detail: plan, usage against limits, and its owners.

    Owner emails are included because the commonest support task is "who do I
    contact about this account". Conversation content is not, and no endpoint
    here exposes it.
    """
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    admins = (
        db.query(User)
        .filter(User.organization_id == org.id)
        .order_by(User.created_at.asc())
        .limit(25).all()
    )

    return {
        "id": str(org.id),
        "name": org.name,
        "domain": org.domain,
        "timezone": org.timezone,
        "is_active": org.is_active,
        "plan_code": org.plan_code,
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "usage": usage_service.summary(db, org),
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "is_active": u.is_active,
                "is_email_verified": u.is_email_verified,
                "role": u.role.name if u.role else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in admins
        ],
    }


@router.get("/audit")
async def list_audit(
    organization_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """The operator action trail, newest first."""
    query = db.query(PlatformAuditLog)
    if organization_id:
        query = query.filter(PlatformAuditLog.target_organization_id == organization_id)
    rows = query.order_by(PlatformAuditLog.created_at.desc()).limit(limit).all()
    return [r.to_dict() for r in rows]


# ---------------------------------------------------------------------------
# Mutate
# ---------------------------------------------------------------------------

@router.patch("/tenants/{organization_id}")
async def update_tenant(
    organization_id: str,
    payload: TenantUpdate,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Suspend, reactivate, or move a tenant between plans."""
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    changes = {}

    if payload.plan_code is not None and payload.plan_code != org.plan_code:
        plan = db.query(Plan).filter(Plan.code == payload.plan_code).first()
        if not plan:
            # Explicit check rather than letting the foreign key reject it: the
            # FK error is a 500 with a constraint name in it.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No such plan: {payload.plan_code}",
            )
        changes["plan_code"] = {"before": org.plan_code, "after": plan.code}
        org.plan_code = plan.code

    if payload.is_active is not None and payload.is_active != org.is_active:
        changes["is_active"] = {"before": org.is_active, "after": payload.is_active}
        org.is_active = payload.is_active

    if not changes:
        return {"message": "No changes", "tenant": {"id": str(org.id), "domain": org.domain}}

    _audit(db, actor, request, "tenant.update", org, changes=changes)
    db.commit()

    logger.info(
        "Platform admin %s updated tenant %s: %s", actor.email, org.domain, changes
    )
    return {
        "message": "Tenant updated",
        "changes": changes,
        "tenant": {
            "id": str(org.id), "domain": org.domain,
            "is_active": org.is_active, "plan_code": org.plan_code,
        },
    }


@router.delete("/tenants/{organization_id}")
async def delete_tenant(
    organization_id: str,
    payload: TenantDelete,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Delete a tenant and everything it owns. Irreversible.

    The cascade reaches agents, widgets, workflows, knowledge, customers,
    sessions and conversation transcripts. That completeness is the point —
    offboarding should leave nothing behind — and it is also why the domain has
    to be typed to confirm.
    """
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    if payload.confirm_domain != (org.domain or "").lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Confirmation does not match this tenant's domain. "
                f"Type {org.domain!r} exactly to confirm deletion."
            ),
        )

    # Snapshot before deleting: once the row is gone the FK nulls itself, and
    # this is the record of what was destroyed.
    snapshot = {
        "name": org.name,
        "domain": org.domain,
        "plan_code": org.plan_code,
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "users": db.scalar(
            select(func.count()).select_from(User).where(User.organization_id == org.id)
        ) or 0,
        "agents": db.scalar(
            select(func.count()).select_from(Agent).where(Agent.organization_id == org.id)
        ) or 0,
    }
    _audit(db, actor, request, "tenant.delete", org, deleted=snapshot)

    db.delete(org)
    db.commit()

    logger.warning(
        "Platform admin %s DELETED tenant %s (%s)", actor.email, org.domain, snapshot
    )
    return {"message": f"Tenant {snapshot['domain']} deleted", "deleted": snapshot}
