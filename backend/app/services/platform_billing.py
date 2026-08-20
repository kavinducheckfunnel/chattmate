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

Sales and billing figures for the operator console.

Everything here is derived from the tables we already keep — plans,
organizations and usage counters — rather than from a payment provider. That
makes the page honest on a deployment with no Stripe account, which is the
current one, and it keeps the revenue figures consistent with the same plan
prices the quota service enforces.

The one thing it cannot know is whether money actually arrived. Payment status
is reported as "unbilled" rather than guessed at, so nothing here claims a
customer has paid when no payment processor has ever been asked.
"""

from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.models.organization import Organization
from app.models.plan import Plan
from app.models.usage import UsageCounter, current_period

logger = get_logger(__name__)

# Estimated provider cost per unit, in cents, used to project spend from the
# message counts we do have. Rough by nature: real invoices are per-token and
# arrive a month late, so these are for reserving funds, not for reconciling
# them. Both are overridable in settings once real invoices exist.
TEXT_COST_CENTS_PER_MESSAGE = 0.0526
IMAGE_COST_CENTS_PER_REQUEST = 0.75

# Multiplier on projected spend for the recommended reserve. Provider bills
# arrive after the usage that caused them, so holding exactly the estimate is
# holding too little.
RESERVE_SAFETY_MULTIPLIER = 1.25

MONTHS_OF_HISTORY = 6


def _period_months(count: int) -> list[str]:
    """The last `count` billing periods as 'YYYY-MM', oldest first."""
    today = date.today()
    months = []
    year, month = today.year, today.month
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(months))


def _usage_by_period(db: Session, metric: str) -> dict[str, int]:
    rows = db.execute(
        select(UsageCounter.period, func.sum(UsageCounter.value))
        .where(UsageCounter.metric == metric)
        .group_by(UsageCounter.period)
    ).all()
    return {period: int(total or 0) for period, total in rows}


def _usage_by_org(db: Session, metric: str, period: str) -> dict:
    rows = db.execute(
        select(UsageCounter.organization_id, UsageCounter.value)
        .where(UsageCounter.metric == metric, UsageCounter.period == period)
    ).all()
    return {org_id: int(value or 0) for org_id, value in rows}


def _ai_cost_cents(messages: int, images: int) -> float:
    return messages * TEXT_COST_CENTS_PER_MESSAGE + images * IMAGE_COST_CENTS_PER_REQUEST


def overview(db: Session, period: Optional[str] = None) -> dict:
    """Everything the billing page needs, in one call.

    One call rather than several because every figure on that page is a share
    of the same totals — splitting them across endpoints would let the cards
    and the table disagree while both were individually correct.
    """
    period = period or current_period()

    plans = db.query(Plan).order_by(Plan.sort_order.asc(), Plan.price_cents.asc()).all()
    organizations = db.query(Organization).all()

    messages_by_org = _usage_by_org(db, "ai_messages", period)
    images_by_org = _usage_by_org(db, "image_requests", period)

    by_plan: dict[str, dict] = {
        p.code: {
            "plan": p.name,
            "code": p.code,
            "price_cents": p.price_cents,
            "customers": 0,
            "paid": 0,
            "revenue_cents": 0,
            # None stays None all the way to the UI: a plan with no ceiling is
            # not a plan at 0% of its allowance.
            "allowance": None if p.max_ai_messages_per_month is None else 0,
            "used": 0,
            "images": 0,
            "ai_cost_cents": 0.0,
        }
        for p in plans
    }

    subscriptions = []
    for org in organizations:
        row = by_plan.get(org.plan_code)
        if row is None:
            continue
        plan = next(p for p in plans if p.code == org.plan_code)

        used = messages_by_org.get(org.id, 0)
        images = images_by_org.get(org.id, 0)
        cost = _ai_cost_cents(used, images)

        row["customers"] += 1
        row["used"] += used
        row["images"] += images
        row["ai_cost_cents"] += cost
        if row["allowance"] is not None:
            row["allowance"] += plan.max_ai_messages_per_month
        if plan.price_cents > 0:
            row["paid"] += 1
            row["revenue_cents"] += plan.price_cents

        subscriptions.append({
            "organization_id": str(org.id),
            "organization": org.name,
            "domain": org.domain,
            "plan": plan.name,
            "plan_code": plan.code,
            "revenue_cents": plan.price_cents,
            "used": used,
            "allowance": plan.max_ai_messages_per_month,
            "ai_cost_cents": round(cost, 2),
            # No payment processor is connected, so this is what is actually
            # known. Reporting "Paid" would be inventing a fact.
            "status": "Unbilled" if plan.price_cents else "Free",
        })

    # Paying customers first, then by revenue: the rows an operator opens this
    # page to look at.
    subscriptions.sort(key=lambda s: (-s["revenue_cents"], s["organization"].lower()))

    plan_rows = list(by_plan.values())
    total_customers = sum(r["customers"] for r in plan_rows)
    paid_customers = sum(r["paid"] for r in plan_rows)
    total_revenue = sum(r["revenue_cents"] for r in plan_rows)
    used_messages = sum(r["used"] for r in plan_rows)
    total_images = sum(r["images"] for r in plan_rows)
    estimated_ai_cost = sum(r["ai_cost_cents"] for r in plan_rows)
    allocated = sum(r["allowance"] for r in plan_rows if r["allowance"] is not None)
    unlimited_plans = any(r["allowance"] is None and r["customers"] for r in plan_rows)

    api_reserve = round(estimated_ai_cost * RESERVE_SAFETY_MULTIPLIER, 2)

    # Six months of revenue history. Revenue is reconstructed from today's plan
    # prices and the tenants that existed then is not something we store, so the
    # series reports message volume and its projected cost — which we do have —
    # and carries current MRR forward only for the present period.
    monthly = []
    messages_by_period = _usage_by_period(db, "ai_messages")
    images_by_period = _usage_by_period(db, "image_requests")
    for month in _period_months(MONTHS_OF_HISTORY):
        msgs = messages_by_period.get(month, 0)
        imgs = images_by_period.get(month, 0)
        monthly.append({
            "period": month,
            "messages": msgs,
            "ai_cost_cents": round(_ai_cost_cents(msgs, imgs), 2),
            # Only the current period has a revenue figure we can stand behind.
            "revenue_cents": total_revenue if month == period else None,
        })

    for row in plan_rows:
        row["ai_cost_cents"] = round(row["ai_cost_cents"], 2)

    return {
        "period": period,
        "currency": plans[0].currency if plans else "USD",
        "totals": {
            "customers": total_customers,
            "paid_customers": paid_customers,
            "revenue_cents": total_revenue,
            "average_revenue_cents": round(total_revenue / paid_customers, 2) if paid_customers else 0,
            "used_messages": used_messages,
            "image_requests": total_images,
            "allocated_messages": allocated,
            "has_unlimited_plans": unlimited_plans,
            "usage_rate": round(used_messages / allocated * 100, 1) if allocated else None,
            "estimated_ai_cost_cents": round(estimated_ai_cost, 2),
            "api_reserve_cents": api_reserve,
            "reserve_remaining_cents": round(api_reserve - estimated_ai_cost, 2),
            "reserve_usage_rate": round(estimated_ai_cost / api_reserve * 100, 1) if api_reserve else 0,
            "net_after_reserve_cents": round(total_revenue - api_reserve, 2),
            "margin_after_reserve": round((total_revenue - api_reserve) / total_revenue * 100, 1) if total_revenue else None,
            "ai_spend_share": round(estimated_ai_cost / total_revenue * 100, 1) if total_revenue else None,
            "ai_cost_per_paying_customer_cents": round(estimated_ai_cost / paid_customers, 2) if paid_customers else 0,
            "paid_conversion": round(paid_customers / total_customers * 100, 1) if total_customers else 0,
        },
        "providers": {
            "text_cost_cents": round(used_messages * TEXT_COST_CENTS_PER_MESSAGE, 2),
            "image_cost_cents": round(total_images * IMAGE_COST_CENTS_PER_REQUEST, 2),
        },
        "by_plan": plan_rows,
        "monthly": monthly,
        "subscriptions": subscriptions,
        # Said plainly rather than implied by empty payment columns.
        "payments_connected": False,
    }
