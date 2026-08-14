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

  * Conversation transcripts ARE readable, at the platform owner's explicit
    instruction, so support staff can diagnose a customer's problem without
    asking them to paste screenshots. Because that is the most sensitive thing
    the console can do, every single transcript opened writes its own audit row
    naming the operator, the tenant and the conversation — the same pattern
    Intercom and Zendesk use for admin access. Reading is all it allows: there
    is no endpoint here that writes a message, and none that lets an operator
    appear to a customer as the tenant.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.platform_auth import (
    audit, client_ip, require_org, require_platform_admin,
)
from app.core.security import revoke_user_sessions, validate_password_strength
from app.core.logger import get_logger
from app.database import get_db
from app.models.agent import Agent
from app.models.channels.channel_account import ChannelAccount
from app.models.chat_history import ChatHistory
from app.models.customer import Customer
from app.models.knowledge import Knowledge
from app.models.organization import Organization
from app.models.session_to_agent import SessionToAgent
from app.models.widget import Widget
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
#
# The guard and the audit writer moved to app/core/platform_auth.py when the
# console grew past one module. Re-exported under the original private names so
# the rest of this file — and the CI guard that reads it — keep working.

_audit = audit
_require_org = require_org
_client_ip = client_ip


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


# ---------------------------------------------------------------------------
# Client operations: what a tenant has configured
# ---------------------------------------------------------------------------

@router.get("/tenants/{organization_id}/agents")
async def tenant_agents(
    organization_id: str,
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """The tenant's AI agents and how each is configured."""
    org = _require_org(db, organization_id)
    agents = (
        db.query(Agent).filter(Agent.organization_id == org.id)
        .order_by(Agent.created_at.desc().nullslast()).all()
    )
    return [
        {
            "id": str(a.id),
            "name": a.name,
            "display_name": a.display_name,
            "description": a.description,
            "agent_type": a.agent_type.value if a.agent_type else None,
            "is_active": a.is_active,
            "transfer_to_human": a.transfer_to_human,
            "use_workflow": a.use_workflow,
            # Instructions are the tenant's prompt engineering — their product,
            # effectively. Reported as a count so support can answer "is this
            # agent configured at all" without copying out their work.
            "instruction_count": len(a.instructions or []),
        }
        for a in agents
    ]


@router.get("/tenants/{organization_id}/knowledge")
async def tenant_knowledge(
    organization_id: str,
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """What the tenant has fed their agents.

    Sources and types only, not the indexed text. "Which documents did they
    add" answers the common support question — an agent that will not answer
    usually has an empty or failed knowledge base — while the contents remain
    the customer's.
    """
    org = _require_org(db, organization_id)
    rows = (
        db.query(Knowledge).filter(Knowledge.organization_id == org.id)
        .order_by(Knowledge.created_at.desc()).limit(limit).all()
    )
    return {
        "total": db.scalar(
            select(func.count()).select_from(Knowledge)
            .where(Knowledge.organization_id == org.id)
        ) or 0,
        "sources": [
            {
                "id": k.id,
                "source": k.source,
                "source_type": k.source_type.value if k.source_type else None,
                "created_at": k.created_at.isoformat() if k.created_at else None,
            }
            for k in rows
        ],
    }


@router.get("/tenants/{organization_id}/integrations")
async def tenant_integrations(
    organization_id: str,
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Connected channels and embedded widgets.

    Credentials are never returned — not the encrypted blob, not a masked
    version, not the webhook secret. Whether a channel is connected is a
    support question; the token itself never is, and an operator who could read
    it could impersonate the tenant on WhatsApp or Slack.
    """
    org = _require_org(db, organization_id)

    channels = (
        db.query(ChannelAccount)
        .filter(ChannelAccount.organization_id == org.id).all()
    )
    widgets = db.query(Widget).filter(Widget.organization_id == org.id).all()

    return {
        "channels": [
            {
                "id": str(c.id),
                "channel_type": c.channel_type,
                "display_name": c.display_name,
                "is_active": c.is_active,
                "created_at": c.created_at.isoformat() if getattr(c, "created_at", None) else None,
            }
            for c in channels
        ],
        "widgets": [
            {"id": str(w.id), "name": w.name, "agent_id": str(w.agent_id) if w.agent_id else None}
            for w in widgets
        ],
    }


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@router.get("/tenants/{organization_id}/conversations")
async def tenant_conversations(
    organization_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Conversation list for a tenant: metadata only, no message content.

    Not audited per call, deliberately. This is the index an operator scrolls
    to find the conversation a customer is asking about, and auditing every
    scroll would bury the entries that matter — opening an actual transcript —
    under thousands of routine ones. The transcript endpoint is where the
    record is written.
    """
    org = _require_org(db, organization_id)

    total = db.scalar(
        select(func.count()).select_from(SessionToAgent)
        .where(SessionToAgent.organization_id == org.id)
    ) or 0

    rows = (
        db.query(SessionToAgent, Customer, Agent)
        .outerjoin(Customer, Customer.id == SessionToAgent.customer_id)
        .outerjoin(Agent, Agent.id == SessionToAgent.agent_id)
        .filter(SessionToAgent.organization_id == org.id)
        .order_by(SessionToAgent.updated_at.desc().nullslast())
        .limit(limit).offset(offset).all()
    )

    # One grouped count rather than a query per row: at 50 conversations the
    # per-row version is 50 extra round trips on every page.
    session_ids = [r[0].session_id for r in rows]
    counts = {}
    if session_ids:
        counts = dict(db.execute(
            select(ChatHistory.session_id, func.count())
            .where(ChatHistory.session_id.in_(session_ids))
            .group_by(ChatHistory.session_id)
        ).all())

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "conversations": [
            {
                "session_id": str(s.session_id),
                "status": s.status.value if s.status else None,
                "channel": s.channel,
                "customer": {
                    "email": c.email if c else None,
                    "full_name": c.full_name if c else None,
                } if c else None,
                "agent_name": a.name if a else None,
                "message_count": counts.get(s.session_id, 0),
                "sentiment": s.sentiment_label,
                "assigned_at": s.assigned_at.isoformat() if s.assigned_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s, c, a in rows
        ],
    }


@router.get("/tenants/{organization_id}/conversations/{session_id}")
async def tenant_transcript(
    organization_id: str,
    session_id: str,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Read one conversation in full.

    The most sensitive read in the application: these are the tenant's
    customers' words, decrypted from EncryptedText. Two controls apply.

    First, the session must belong to the tenant named in the path. Without
    that check a valid session id from any tenant would be readable through any
    other tenant's URL, and the audit row would name the wrong customer —
    making the log actively misleading rather than merely incomplete.

    Second, every call writes an audit row before returning anything. It is
    committed even though this is a GET, which is unusual and deliberate: the
    record of who read a customer's conversation is worth more than the purity
    of the verb.
    """
    org = _require_org(db, organization_id)

    session = (
        db.query(SessionToAgent)
        .filter(
            SessionToAgent.session_id == session_id,
            SessionToAgent.organization_id == org.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )

    messages = (
        db.query(ChatHistory)
        .filter(ChatHistory.session_id == session.session_id)
        .order_by(ChatHistory.created_at.asc())
        .all()
    )
    customer = (
        db.query(Customer).filter(Customer.id == session.customer_id).first()
        if session.customer_id else None
    )

    _audit(
        db, actor, request, "conversation.read", org,
        session_id=str(session.session_id),
        customer_email=customer.email if customer else None,
        message_count=len(messages),
    )
    db.commit()

    logger.info(
        "Platform admin %s read conversation %s of tenant %s",
        actor.email, session.session_id, org.domain,
    )

    return {
        "session_id": str(session.session_id),
        "organization_domain": org.domain,
        "status": session.status.value if session.status else None,
        "channel": session.channel,
        "customer": {
            "email": customer.email if customer else None,
            "full_name": customer.full_name if customer else None,
        } if customer else None,
        "messages": [
            {
                "id": m.id,
                "message_type": m.message_type,
                "message": m.message,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "sentiment_label": m.sentiment_label,
            }
            for m in messages
        ],
    }


# ---------------------------------------------------------------------------
# Cross-tenant user management
# ---------------------------------------------------------------------------

class PlatformUserUpdate(BaseModel):
    is_active: Optional[bool] = None
    new_password: Optional[str] = None

    @field_validator("new_password")
    @classmethod
    def _strength(cls, v):
        if v is None:
            return v
        # Same policy as signup, invitations and self-service reset. An
        # operator-set password is the one most likely to be reused or shared,
        # so it is the last one that should get an exemption.
        return validate_password_strength(v)


@router.patch("/users/{user_id}")
async def update_tenant_user(
    user_id: str,
    payload: PlatformUserUpdate,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Deactivate, reactivate, or reset the password of any tenant's user.

    This is the "our customer is locked out" path. Setting a password is
    inherently an account takeover, so it is audited like one — and the new
    value is never written to the log.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Operators are not editable through the tenant-user endpoint. Otherwise
    # one operator could reset another's password and take over the platform
    # account, and the /platform surface would become its own escalation path.
    if user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This is a platform operator account. Manage operators with "
                "grant_platform_admin.py on the server."
            ),
        )

    org = (
        db.query(Organization).filter(Organization.id == user.organization_id).first()
        if user.organization_id else None
    )
    changes = {}

    if payload.is_active is not None and payload.is_active != user.is_active:
        changes["is_active"] = {"before": user.is_active, "after": payload.is_active}
        user.is_active = payload.is_active

    if payload.new_password:
        user.hashed_password = User.get_password_hash(payload.new_password)
        # Recorded as a fact, never a value. An audit log holding plaintext
        # passwords would be a worse leak than the one it exists to detect.
        changes["password"] = {"reset": True}

    if not changes:
        return {"message": "No changes"}

    _audit(
        db, actor, request, "user.update", org,
        target_user_id=str(user.id), target_user_email=user.email, changes=changes,
    )
    db.commit()

    if payload.new_password:
        # Every existing session dies with the old password — otherwise a
        # reset prompted by a compromise leaves the attacker signed in.
        try:
            revoke_user_sessions(user.email)
        except Exception as e:
            logger.error("Failed to revoke sessions for %s: %s", user.email, e)

    logger.warning(
        "Platform admin %s updated user %s (%s): %s",
        actor.email, user.email, org.domain if org else "no tenant", list(changes),
    )
    return {"message": "User updated", "changes": list(changes.keys())}


# ---------------------------------------------------------------------------
# Plan catalog
# ---------------------------------------------------------------------------

class PlanUpsert(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_cents: Optional[int] = None
    max_conversations_per_month: Optional[int] = None
    max_ai_messages_per_month: Optional[int] = None
    max_agents: Optional[int] = None
    max_seats: Optional[int] = None
    max_knowledge_docs: Optional[int] = None
    max_storage_mb: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("price_cents")
    @classmethod
    def _non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("Price cannot be negative")
        return v


# Sent as null to mean "unlimited", which is a real choice an operator makes —
# so these fields cannot use None as "leave unchanged" the way the others do.
_LIMIT_FIELDS = (
    "max_conversations_per_month", "max_ai_messages_per_month", "max_agents",
    "max_seats", "max_knowledge_docs", "max_storage_mb",
)


@router.get("/plans")
async def platform_list_plans(
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """The whole catalog, including retired plans.

    Differs from /usage/plans, which shows customers only what they can buy.
    An operator needs to see a deactivated tier to know why a grandfathered
    tenant is on it.
    """
    plans = db.query(Plan).order_by(Plan.sort_order.asc(), Plan.price_cents.asc()).all()
    counts = dict(db.execute(
        select(Organization.plan_code, func.count()).group_by(Organization.plan_code)
    ).all())
    return [{**p.to_dict(), "tenant_count": counts.get(p.code, 0)} for p in plans]


@router.patch("/plans/{plan_code}")
async def update_plan(
    plan_code: str,
    payload: PlanUpsert,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Change a plan's pricing or limits.

    Applies immediately to every tenant on the plan — quotas are read live, not
    copied onto the tenant — so lowering a limit can put existing customers
    instantly over quota. The response says how many tenants were affected so
    that is visible rather than discovered.

    is_default is not editable here. Exactly one plan may be the default, which
    a partial unique index enforces, and flipping it through this endpoint
    would surface as an opaque constraint error mid-request.
    """
    plan = db.query(Plan).filter(Plan.code == plan_code).first()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

    # exclude_unset distinguishes "not mentioned" from "explicitly null", which
    # is the whole difference between leaving a limit alone and making it
    # unlimited.
    supplied = payload.model_dump(exclude_unset=True)
    changes = {}
    for field, value in supplied.items():
        current = getattr(plan, field)
        if current != value:
            changes[field] = {"before": current, "after": value}
            setattr(plan, field, value)

    if not changes:
        return {"message": "No changes", "plan": plan.to_dict()}

    affected = db.scalar(
        select(func.count()).select_from(Organization)
        .where(Organization.plan_code == plan.code)
    ) or 0

    _audit(
        db, actor, request, "plan.update", None,
        plan_code=plan.code, changes=changes, tenants_affected=affected,
    )
    db.commit()

    logger.info(
        "Platform admin %s updated plan %s (%d tenants affected): %s",
        actor.email, plan.code, affected, changes,
    )
    return {
        "message": f"Plan updated. {affected} tenant(s) are on this plan.",
        "changes": changes,
        "tenants_affected": affected,
        "plan": plan.to_dict(),
    }


@router.get("/operators")
async def list_operators(
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Who else can do all this.

    Read-only on purpose. Granting and revoking stay in
    scripts/grant_platform_admin.py, which needs shell access — so an operator
    whose session is stolen cannot quietly add a second account for later.
    """
    operators = (
        db.query(User).filter(User.is_platform_admin == True)
        .order_by(User.created_at.asc()).all()
    )
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "is_active": u.is_active,
            # A standalone operator has no tenant; a promoted one still does.
            "tenant": u.organization.domain if u.organization_id and u.organization else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in operators
    ]
