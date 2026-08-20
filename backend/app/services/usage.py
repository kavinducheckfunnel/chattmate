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

Usage metering and quota enforcement.

Two kinds of metric, handled differently on purpose:

  FLOW   conversations, ai_messages, image_requests — events that accumulate
         within a billing period. Stored in usage_counters and reset by moving
         to a new period.

  STOCK  agents, seats, knowledge_docs — how many currently exist. Counted from
         the owning table on demand, never stored. A stored stock counter drifts
         the moment anything deletes a row without decrementing it, and the
         tenant is then wrongly billed or wrongly blocked.
"""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.models.plan import Plan
from app.models.plan_snapshot import OrganizationPlanSnapshot
from app.models.usage import UsageCounter, current_period

logger = get_logger(__name__)

FLOW_METRICS = ("conversations", "ai_messages", "image_requests")
STOCK_METRICS = ("agents", "seats", "knowledge_docs")
ALL_METRICS = FLOW_METRICS + STOCK_METRICS


def _effective_limit(db: Session, organization, plan: Optional[Plan], metric: str):
    """The ceiling this tenant is actually held to, which is not always the plan's.

    When an operator edits a plan they choose whether existing customers move
    with it. If they chose not to, the terms this tenant keeps are recorded in a
    snapshot, and that is what must be enforced — reading the plan directly would
    apply the new limits to everyone regardless of what was chosen, making the
    choice cosmetic.

    A snapshot only speaks for the metrics it recorded; anything absent falls
    through to the plan, so a later edit adding a brand-new metric still reaches
    held-back tenants rather than leaving them unlimited.
    """
    snapshot = (
        db.query(OrganizationPlanSnapshot)
        .filter(OrganizationPlanSnapshot.organization_id == organization.id)
        .first()
    )
    if (
        snapshot is not None
        and snapshot.is_active()
        # Terms from a plan they have since left are not terms they agreed to.
        and plan is not None
        and snapshot.plan_code == plan.code
        and metric in (snapshot.limits or {})
    ):
        return (snapshot.limits or {})[metric]

    return plan.limit_for(metric) if plan else None


def _resolve_plan(db: Session, organization) -> Optional[Plan]:
    """The organization's plan, falling back to the catalog default.

    A tenant with no plan_code (created before plans existed, or by a path that
    did not set one) must not be treated as unlimited. Falling back to the
    default plan means the safe outcome is the cheapest tier, not a free ride.
    """
    if organization is None:
        return None
    if getattr(organization, "plan", None) is not None:
        return organization.plan
    return db.query(Plan).filter(Plan.is_default == True, Plan.is_active == True).first()


def record(db: Session, organization_id, metric: str, amount: int = 1,
           period: Optional[str] = None) -> None:
    """Add `amount` to a flow metric. Caller commits.

    The write is a single INSERT ... ON CONFLICT DO UPDATE that increments in
    the database. Read-modify-write in Python would lose increments whenever two
    chat messages for the same tenant are handled concurrently — which, for the
    busiest tenant on the platform, is the normal case rather than the edge one.
    """
    if metric not in FLOW_METRICS:
        # Incrementing a stock metric would create a counter row that nothing
        # reads, and the caller would believe usage was being tracked.
        raise ValueError(
            f"{metric!r} is a stock metric (or unknown); it is counted from its "
            f"own table, not incremented. Flow metrics: {FLOW_METRICS}"
        )
    if amount == 0:
        return

    stmt = pg_insert(UsageCounter).values(
        organization_id=organization_id,
        period=period or current_period(),
        metric=metric,
        value=amount,
    ).on_conflict_do_update(
        index_elements=["organization_id", "period", "metric"],
        set_={
            "value": UsageCounter.__table__.c.value + amount,
            "updated_at": func.now(),
        },
    )
    db.execute(stmt)


def _stock_count(db: Session, organization_id, metric: str) -> int:
    """Count a stock metric from its owning table."""
    # Imported here rather than at module scope: app.models imports services in
    # places, and hoisting these would close an import cycle.
    if metric == "agents":
        from app.models.agent import Agent
        model = Agent
    elif metric == "seats":
        from app.models.user import User
        model = User
    elif metric == "knowledge_docs":
        from app.models.knowledge import Knowledge
        model = Knowledge
    else:
        raise ValueError(f"Unknown stock metric: {metric!r}")

    return db.scalar(
        select(func.count()).select_from(model)
        .where(model.organization_id == organization_id)
    ) or 0


def get_usage(db: Session, organization_id, metric: str,
              period: Optional[str] = None) -> int:
    """Current consumption of one metric."""
    if metric in STOCK_METRICS:
        return _stock_count(db, organization_id, metric)
    if metric not in FLOW_METRICS:
        raise ValueError(f"Unknown usage metric: {metric!r}")
    return db.scalar(
        select(UsageCounter.value).where(
            UsageCounter.organization_id == organization_id,
            UsageCounter.period == (period or current_period()),
            UsageCounter.metric == metric,
        )
    ) or 0


def summary(db: Session, organization) -> dict:
    """Everything the usage dashboard needs, in one call."""
    plan = _resolve_plan(db, organization)
    period = current_period()
    metrics = {}
    for metric in ALL_METRICS:
        used = get_usage(db, organization.id, metric, period)
        limit = _effective_limit(db, organization, plan, metric)
        metrics[metric] = {
            "used": used,
            "limit": limit,
            # Percent is computed here so the dashboard and the enforcement
            # path cannot disagree about what "90% used" means. None where
            # unlimited — a progress bar has nothing to fill against no ceiling.
            "percent": None if not limit else min(100, round(used / limit * 100)),
            "exceeded": limit is not None and used >= limit,
        }
    return {
        "period": period,
        "plan": plan.to_dict() if plan else None,
        "metrics": metrics,
    }


def check(db: Session, organization, metric: str, amount: int = 1) -> None:
    """Raise 402 if consuming `amount` more would break the plan's limit.

    402 Payment Required, not 403: the caller is authenticated and authorised,
    and the remedy is upgrading rather than obtaining a permission. The
    frontend distinguishes the two to decide whether to show an upgrade prompt
    or an access error.
    """
    plan = _resolve_plan(db, organization)
    if plan is None:
        # No catalog at all — a fresh install, or plans not yet seeded. Refusing
        # here would break every tenant on the platform to enforce a limit that
        # was never configured, so allow and say so loudly.
        logger.warning(
            "No plan resolved for organization %s; quota check skipped",
            getattr(organization, "id", "?"),
        )
        return

    limit = _effective_limit(db, organization, plan, metric)
    if limit is None:
        return

    used = get_usage(db, organization.id, metric)
    if used + amount > limit:
        logger.info(
            "Quota exceeded: org=%s metric=%s used=%s requested=%s limit=%s plan=%s",
            organization.id, metric, used, amount, limit, plan.code,
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": QUOTA_MESSAGES.get(
                    metric, f"You've reached your plan's {metric} limit."
                ),
                "metric": metric,
                "used": used,
                "limit": limit,
                "plan": plan.code,
            },
        )


# Written for the person who hits the wall, not for the developer reading logs:
# each says what ran out and what to do about it.
QUOTA_MESSAGES = {
    "conversations": (
        "You've used all the conversations included in your plan this month. "
        "Upgrade to keep chatting, or wait for the monthly reset."
    ),
    "ai_messages": (
        "You've used all the AI replies included in your plan this month. "
        "Upgrade for more, or wait for the monthly reset."
    ),
    "agents": (
        "You've reached the number of AI agents your plan allows. "
        "Upgrade to add more, or delete an agent you're not using."
    ),
    "seats": (
        "You've reached the number of team members your plan allows. "
        "Upgrade to invite more, or remove someone who no longer needs access."
    ),
    "knowledge_docs": (
        "You've reached the number of knowledge sources your plan allows. "
        "Upgrade to add more, or remove a source you no longer need."
    ),
}
