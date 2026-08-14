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

Platform-wide revenue and volume figures.

Recurring revenue here is derived, not invoiced: it is the sum of plan prices
across active tenants. That is a real number and the right one for "what are we
billing per month", but it is not the same as cash received — nothing has
charged a card yet. Both the API and the console say so rather than letting a
figure labelled "revenue" imply money in the bank.

History is recorded, not recomputed. See app/models/platform_metric.py for why
recomputing it would produce a number that never happened.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.models.organization import Organization
from app.models.plan import Plan
from app.models.platform_metric import (
    ACTIVE_TENANTS, MRR_CENTS, PAYING_TENANTS, PlatformMetric,
)
from app.models.usage import UsageCounter, current_period

logger = get_logger(__name__)


def _period_of(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def recent_periods(count: int = 6) -> list[str]:
    """The last `count` periods ending with the current one, oldest first."""
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    out = []
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(out))


def current_revenue(db: Session) -> dict:
    """Recurring revenue as the plan catalog stands right now.

    Counts only active tenants: a suspended account is not billable, and
    including it would overstate the figure exactly when an operator is looking
    at the console to understand a drop.
    """
    rows = db.execute(
        select(Organization.plan_code, func.count())
        .where(Organization.is_active == True)  # noqa: E712 — SQL boolean, not Python
        .group_by(Organization.plan_code)
    ).all()

    plans = {p.code: p for p in db.query(Plan).all()}
    mrr_cents = 0
    paying = 0
    by_plan = []

    for code, count in rows:
        plan = plans.get(code) if code else None
        price = plan.price_cents if plan else 0
        mrr_cents += price * count
        if price > 0:
            paying += count
        by_plan.append({
            "code": code or "none",
            "name": plan.name if plan else "No plan",
            "tenants": count,
            "price_cents": price,
            "mrr_cents": price * count,
        })

    by_plan.sort(key=lambda r: (-r["mrr_cents"], r["code"]))
    total_active = sum(r["tenants"] for r in by_plan)

    return {
        "mrr_cents": mrr_cents,
        "currency": (next(iter(plans.values())).currency if plans else "USD"),
        "active_tenants": total_active,
        "paying_tenants": paying,
        "arpa_cents": round(mrr_cents / paying) if paying else 0,
        "by_plan": by_plan,
    }


def record_snapshot(db: Session, revenue: dict) -> None:
    """Write this month's figures so next month can read them back as history.

    Upsert, because this runs on every console read: the row is overwritten all
    month and then simply stops changing when the month ends. Failures are
    swallowed — an operator opening a dashboard must not get a 500 because a
    bookkeeping write lost a race with a concurrent one.
    """
    period = current_period()
    values = {
        MRR_CENTS: revenue["mrr_cents"],
        ACTIVE_TENANTS: revenue["active_tenants"],
        PAYING_TENANTS: revenue["paying_tenants"],
    }
    try:
        for metric, value in values.items():
            stmt = pg_insert(PlatformMetric).values(
                period=period, metric=metric, value=value,
            ).on_conflict_do_update(
                index_elements=["period", "metric"],
                set_={"value": value, "recorded_at": func.now()},
            )
            db.execute(stmt)
        db.commit()
    except Exception as e:
        logger.error("Could not record platform snapshot for %s: %s", period, e)
        db.rollback()


def revenue_history(db: Session, months: int = 6) -> list[dict]:
    """Recorded MRR per period.

    Periods with no snapshot come back with `recorded=False` and a null value
    rather than a zero. Zero would draw as a real collapse in revenue on the
    chart; null draws as a gap, which is what actually happened — nobody was
    writing the number down yet.
    """
    periods = recent_periods(months)
    rows = db.execute(
        select(PlatformMetric.period, PlatformMetric.metric, PlatformMetric.value)
        .where(PlatformMetric.period.in_(periods))
    ).all()

    recorded: dict[str, dict[str, int]] = {}
    for period, metric, value in rows:
        recorded.setdefault(period, {})[metric] = value

    return [
        {
            "period": period,
            "mrr_cents": recorded.get(period, {}).get(MRR_CENTS),
            "active_tenants": recorded.get(period, {}).get(ACTIVE_TENANTS),
            "paying_tenants": recorded.get(period, {}).get(PAYING_TENANTS),
            "recorded": period in recorded,
        }
        for period in periods
    ]


def usage_history(db: Session, months: int = 6) -> list[dict]:
    """Platform-wide metered volume per period.

    Unlike revenue this genuinely can be read back, because UsageCounter rows
    are written per period as the usage happens and are never rewritten.
    """
    periods = recent_periods(months)
    rows = db.execute(
        select(UsageCounter.period, UsageCounter.metric, func.sum(UsageCounter.value))
        .where(UsageCounter.period.in_(periods))
        .group_by(UsageCounter.period, UsageCounter.metric)
    ).all()

    totals: dict[str, dict[str, int]] = {}
    for period, metric, value in rows:
        totals.setdefault(period, {})[metric] = int(value or 0)

    return [
        {
            "period": period,
            "conversations": totals.get(period, {}).get("conversations", 0),
            "ai_messages": totals.get(period, {}).get("ai_messages", 0),
        }
        for period in periods
    ]
