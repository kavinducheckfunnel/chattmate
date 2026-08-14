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

Read-only reporting for the operator console: the overview, cross-tenant
analytics, and system health.

Every figure here is computed from the database or measured from a live
service. Where a number cannot honestly be produced — revenue for a month that
predates recording, uptime with no history to average — the response says so
with a null and a flag rather than filling the gap. A dashboard that quietly
invents a plausible number is worse than one with a hole in it: the hole
prompts a question, the invention ends one.
"""

import os
import shutil
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logger import get_logger
from app.core.platform_auth import require_platform_admin
from app.database import get_db
from app.models.agent import Agent
from app.models.ai_config import AIConfig
from app.models.channels.channel_account import ChannelAccount
from app.models.chat_history import ChatHistory
from app.models.knowledge import Knowledge
from app.models.organization import Organization
from app.models.rating import Rating
from app.models.session_to_agent import SessionToAgent
from app.models.usage import UsageCounter, current_period
from app.models.user import User
from app.services import platform_metrics
from app.services import transactional_email

logger = get_logger(__name__)
router = APIRouter()

# When the process started, so the health page can report its own uptime
# without inventing a service-level history it does not keep.
_STARTED_AT = time.time()


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@router.get("/overview")
async def overview(
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Everything the landing dashboard needs, in one round trip.

    One endpoint rather than six: the overview draws all of these at once, and
    six parallel requests would each re-authenticate, re-read the operator flag
    and open their own transaction for numbers that should agree with each
    other.
    """
    period = current_period()

    total_orgs = db.scalar(select(func.count()).select_from(Organization)) or 0
    active_orgs = db.scalar(
        select(func.count()).select_from(Organization)
        .where(Organization.is_active == True)  # noqa: E712
    ) or 0
    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    total_agents = db.scalar(select(func.count()).select_from(Agent)) or 0

    revenue = platform_metrics.current_revenue(db)
    # Reading the dashboard is what keeps the history alive. See
    # app/services/platform_metrics.py — this is a deliberate write on a GET.
    platform_metrics.record_snapshot(db, revenue)

    usage_rows = db.execute(
        select(UsageCounter.metric, func.sum(UsageCounter.value))
        .where(UsageCounter.period == period)
        .group_by(UsageCounter.metric)
    ).all()
    usage = {metric: int(value or 0) for metric, value in usage_rows}

    # Signups this month, so growth is a measured number rather than a guess.
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )
    new_this_month = db.scalar(
        select(func.count()).select_from(Organization)
        .where(Organization.created_at >= month_start)
    ) or 0

    recent = (
        db.query(Organization)
        .order_by(Organization.created_at.desc().nullslast())
        .limit(5).all()
    )

    return {
        "period": period,
        "organizations": {
            "total": total_orgs,
            "active": active_orgs,
            "suspended": total_orgs - active_orgs,
            "new_this_month": new_this_month,
        },
        "users": total_users,
        "agents": total_agents,
        "usage": {
            "conversations": usage.get("conversations", 0),
            "ai_messages": usage.get("ai_messages", 0),
        },
        "revenue": revenue,
        "revenue_history": platform_metrics.revenue_history(db),
        "usage_history": platform_metrics.usage_history(db),
        "recent_organizations": [
            {
                "id": str(o.id),
                "name": o.name,
                "domain": o.domain,
                "plan_code": o.plan_code,
                "is_active": o.is_active,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in recent
        ],
    }


# ---------------------------------------------------------------------------
# Cross-tenant analytics
# ---------------------------------------------------------------------------

_RANGES = {"7d": 7, "30d": 30, "90d": 90}


@router.get("/analytics")
async def analytics(
    range: str = Query("30d", pattern="^(7d|30d|90d)$"),
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Conversation performance across every tenant.

    The tenant-facing analytics module answers the same questions inside one
    organization. This deliberately does not reuse it: those queries all take
    an organization_id and filter by it, and calling them in a loop over
    tenants would be both slow and a strange way to express "no filter".
    """
    days = _RANGES[range]
    since = datetime.now(timezone.utc) - timedelta(days=days)

    total = db.scalar(
        select(func.count()).select_from(SessionToAgent)
        .where(SessionToAgent.assigned_at >= since)
    ) or 0

    # Outcome is read from the session status rather than inferred from who
    # sent the last message: a conversation can end with a bot message and
    # still have been handed over.
    status_rows = db.execute(
        select(SessionToAgent.status, func.count())
        .where(SessionToAgent.assigned_at >= since)
        .group_by(SessionToAgent.status)
    ).all()
    by_status = {
        (s.value if hasattr(s, "value") else str(s) if s else "unknown"): c
        for s, c in status_rows
    }

    # A human took over when a human agent is assigned. user_id is set at
    # handover and stays null for a conversation the AI handled alone.
    handovers = db.scalar(
        select(func.count()).select_from(SessionToAgent)
        .where(SessionToAgent.assigned_at >= since, SessionToAgent.user_id.isnot(None))
    ) or 0

    channel_rows = db.execute(
        select(SessionToAgent.channel, func.count())
        .where(SessionToAgent.assigned_at >= since)
        .group_by(SessionToAgent.channel)
    ).all()

    messages = db.scalar(
        select(func.count()).select_from(ChatHistory)
        .where(ChatHistory.created_at >= since)
    ) or 0

    # Daily volume, bucketed in the database. Pulling rows and grouping in
    # Python would move the whole conversation table across the wire.
    daily = db.execute(
        select(
            func.date_trunc("day", SessionToAgent.assigned_at).label("day"),
            func.count(),
        )
        .where(SessionToAgent.assigned_at >= since)
        .group_by(text("day"))
        .order_by(text("day"))
    ).all()

    rating_stats = db.execute(
        select(func.avg(Rating.rating), func.count())
        .where(Rating.created_at >= since)
    ).first()
    avg_rating = float(rating_stats[0]) if rating_stats and rating_stats[0] is not None else None
    rating_count = int(rating_stats[1] or 0) if rating_stats else 0

    # Busiest tenants, by conversations started in the window.
    top_rows = db.execute(
        select(
            Organization.id, Organization.name, Organization.domain,
            Organization.plan_code, func.count(SessionToAgent.session_id),
        )
        .join(SessionToAgent, SessionToAgent.organization_id == Organization.id)
        .where(SessionToAgent.assigned_at >= since)
        .group_by(Organization.id, Organization.name, Organization.domain, Organization.plan_code)
        .order_by(func.count(SessionToAgent.session_id).desc())
        .limit(8)
    ).all()

    knowledge_total = db.scalar(select(func.count()).select_from(Knowledge)) or 0

    return {
        "range": range,
        "since": since.isoformat(),
        "conversations": {
            "total": total,
            "messages": messages,
            "handovers": handovers,
            "ai_only": max(0, total - handovers),
            "by_status": by_status,
            "daily": [
                {"date": day.date().isoformat(), "count": count} for day, count in daily
            ],
        },
        "channels": [
            {"channel": channel or "web", "count": count}
            for channel, count in sorted(channel_rows, key=lambda r: -r[1])
        ],
        "satisfaction": {
            # Null, not 0. No ratings yet is not the same as everyone scoring zero.
            "average": round(avg_rating, 2) if avg_rating is not None else None,
            "responses": rating_count,
        },
        "knowledge": {"sources": knowledge_total},
        "top_organizations": [
            {
                "id": str(org_id),
                "name": name,
                "domain": domain,
                "plan_code": plan_code,
                "conversations": count,
            }
            for org_id, name, domain, plan_code, count in top_rows
        ],
    }


# ---------------------------------------------------------------------------
# System health
# ---------------------------------------------------------------------------

def _probe(name: str, fn) -> dict:
    """Run one check and time it.

    Latency comes from the measurement itself rather than a stored average.
    A single sample is honest about what it is; a fabricated "99.98% uptime"
    would not be, because nothing in this deployment records uptime.
    """
    started = time.perf_counter()
    try:
        detail = fn()
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "name": name,
            "status": "operational",
            "latency_ms": round(elapsed, 1),
            "detail": detail,
        }
    except Exception as e:
        elapsed = (time.perf_counter() - started) * 1000
        logger.error("Health probe %s failed: %s", name, e)
        return {
            "name": name,
            "status": "down",
            "latency_ms": round(elapsed, 1),
            "detail": str(e)[:200],
        }


@router.get("/health")
async def health(
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Live status of the services this deployment depends on.

    Each entry is measured now. Nothing is cached, because a health page that
    shows a cached "operational" during an outage is the one moment it had a
    job to do.
    """
    services = []

    def check_db():
        db.execute(text("SELECT 1"))
        version = db.execute(text("SHOW server_version")).scalar()
        return f"PostgreSQL {version}"

    services.append(_probe("PostgreSQL", check_db))

    def check_vector():
        installed = db.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        if not installed:
            raise RuntimeError("pgvector extension is not installed")
        return f"pgvector {installed}"

    services.append(_probe("Vector search", check_vector))

    def check_redis():
        from app.core.redis import get_redis
        client = get_redis()
        if client is None:
            raise RuntimeError("Redis is disabled or unreachable")
        client.ping()
        info = client.info("server")
        return f"Redis {info.get('redis_version', 'unknown')}"

    services.append(_probe("Redis", check_redis))

    def check_email():
        if not transactional_email.is_configured():
            raise RuntimeError("SMTP credentials are not configured")
        return f"SMTP via {settings.SMTP_SERVER}"

    services.append(_probe("Email delivery", check_email))

    def check_storage():
        usage = shutil.disk_usage(os.getenv("UPLOAD_DIR", "/app/uploads"))
        used_pct = round(usage.used / usage.total * 100, 1)
        if used_pct >= 95:
            raise RuntimeError(f"Disk {used_pct}% full")
        return f"{used_pct}% of {usage.total // (1024 ** 3)} GB used"

    services.append(_probe("File storage", check_storage))

    # Degraded rather than down: the platform still answers, but something in
    # it does not. Distinguishing the two is the difference between "look now"
    # and "look today".
    down = [s for s in services if s["status"] == "down"]
    overall = "operational" if not down else ("degraded" if len(down) < len(services) else "down")

    uptime_seconds = int(time.time() - _STARTED_AT)

    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "api_uptime_seconds": uptime_seconds,
        "services": services,
        "counts": {
            "organizations": db.scalar(select(func.count()).select_from(Organization)) or 0,
            "users": db.scalar(select(func.count()).select_from(User)) or 0,
            "agents": db.scalar(select(func.count()).select_from(Agent)) or 0,
            "channels": db.scalar(select(func.count()).select_from(ChannelAccount)) or 0,
            "conversations": db.scalar(select(func.count()).select_from(SessionToAgent)) or 0,
            "knowledge_sources": db.scalar(select(func.count()).select_from(Knowledge)) or 0,
        },
    }


# ---------------------------------------------------------------------------
# AI configuration
# ---------------------------------------------------------------------------

@router.get("/ai")
async def ai_configuration(
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Which AI provider and model each workspace is running on.

    API keys are never returned — not decrypted, not masked, not their length.
    A masked key still confirms which provider account a customer is paying
    for, and an operator who could read one could spend the customer's credit.

    "Which model is this customer on" is the question support actually asks,
    usually as a prelude to "why are their answers poor" or "why is their bill
    high", and that is answerable without the secret.
    """
    rows = (
        db.query(AIConfig, Organization)
        .join(Organization, Organization.id == AIConfig.organization_id)
        .order_by(Organization.name.asc())
        .all()
    )

    configured_ids = {c.organization_id for c, _ in rows}
    unconfigured = (
        db.query(Organization)
        .filter(~Organization.id.in_(configured_ids) if configured_ids else True)
        .order_by(Organization.name.asc())
        .all()
    )

    by_model: dict[str, int] = {}
    for config, _org in rows:
        key = f"{config.model_type.value if config.model_type else 'unknown'} · {config.model_name}"
        by_model[key] = by_model.get(key, 0) + 1

    return {
        # The platform's own fallback, read from the environment rather than a
        # table: it is deployment configuration, changed by editing .env and
        # restarting, and pretending it were editable here would be a lie.
        "platform_default": {
            "model_name": os.getenv("CHATTERMATE_MODEL_NAME") or None,
            "configured": bool(os.getenv("CHATTERMATE_API_KEY")),
            "note": (
                "Set with CHATTERMATE_API_KEY and CHATTERMATE_MODEL_NAME in the "
                "server's .env. Only used by the hosted enterprise module, which "
                "is not installed on this deployment — here every workspace "
                "brings its own provider key."
            ),
        },
        "by_model": [
            {"model": model, "workspaces": count}
            for model, count in sorted(by_model.items(), key=lambda r: -r[1])
        ],
        "workspaces": [
            {
                "organization_id": str(org.id),
                "organization_name": org.name,
                "domain": org.domain,
                "plan_code": org.plan_code,
                "model_type": config.model_type.value if config.model_type else None,
                "model_name": config.model_name,
                "is_active": config.is_active,
                "updated_at": config.updated_at.isoformat() if config.updated_at else None,
            }
            for config, org in rows
        ],
        "unconfigured": [
            {
                "organization_id": str(o.id),
                "organization_name": o.name,
                "domain": o.domain,
                "plan_code": o.plan_code,
            }
            for o in unconfigured
        ],
    }
