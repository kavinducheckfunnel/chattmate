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

Billing, plan limits and subscription-state audit.

Covers the whole chain a paying customer moves along: what their tier allows,
what the product actually stops them doing, what happens on upgrade and
downgrade, and what the revenue figures say about it. The interesting cases are
the ones where a limit exists in the catalog but nothing consults it — a ceiling
nobody enforces reads as a working restriction on the operator console while the
tenant sails past it.
"""

import pytest
from fastapi import HTTPException

from app.models.feature import FEATURE_CATALOG, OrganizationFeatureOverride, PlanFeature
from app.models.plan import Plan
from app.models.plan_snapshot import OrganizationPlanSnapshot
from app.models.usage import UsageCounter, current_period
from app.services import features as feature_catalog
from app.services import usage as usage_service


# --- the real catalog, as deployed -----------------------------------------

TIERS = [
    # code,      price, ai_messages, conversations, agents, seats, docs
    ("free",         0,         500,           100,      1,     2,   10),
    ("starter",   4900,       10000,          2000,      3,     5,  100),
    ("pro",      14901,       50000,         10000,     10,    20,  500),
    ("scale",    49900,        None,          None,   None,  None, None),
]


@pytest.fixture
def catalog(db):
    """Seed the four tiers this deployment actually sells."""
    plans = []
    for i, (code, price, msgs, convs, agents, seats, docs) in enumerate(TIERS):
        plan = Plan(
            code=code,
            name=code.title(),
            price_cents=price,
            max_ai_messages_per_month=msgs,
            max_conversations_per_month=convs,
            max_agents=agents,
            max_seats=seats,
            max_knowledge_docs=docs,
            sort_order=i,
            is_active=True,
            is_default=(code == "free"),
        )
        db.add(plan)
        plans.append(plan)
    db.commit()
    return {p.code: p for p in plans}


@pytest.fixture
def org(db, test_organization, catalog):
    test_organization.plan_code = "free"
    db.commit()
    db.refresh(test_organization)
    return test_organization


def _use(db, org, metric, value):
    """Set a flow metric's consumption for the current period."""
    db.query(UsageCounter).filter(
        UsageCounter.organization_id == org.id,
        UsageCounter.metric == metric,
    ).delete()
    db.add(UsageCounter(
        organization_id=org.id, period=current_period(), metric=metric, value=value))
    db.commit()


# --- 1. limits are what the catalog says ------------------------------------

@pytest.mark.parametrize("code,price,msgs,convs,agents,seats,docs", TIERS)
def test_each_tier_reports_its_own_limits(
        db, catalog, code, price, msgs, convs, agents, seats, docs):
    """Every tier resolves the ceilings it was sold with."""
    plan = catalog[code]
    assert plan.price_cents == price
    assert plan.limit_for("ai_messages") == msgs
    assert plan.limit_for("conversations") == convs
    assert plan.limit_for("agents") == agents
    assert plan.limit_for("seats") == seats
    assert plan.limit_for("knowledge_docs") == docs


def test_tiers_increase_monotonically(catalog):
    """A more expensive tier must never allow less than a cheaper one.

    None means unlimited, so it sorts above every number rather than below it —
    the direction that would make Scale the most restrictive plan on offer.
    """
    paid_order = ["free", "starter", "pro", "scale"]
    for metric in ("ai_messages", "conversations", "agents", "seats", "knowledge_docs"):
        seen = [catalog[c].limit_for(metric) for c in paid_order]
        ranked = [float("inf") if v is None else v for v in seen]
        assert ranked == sorted(ranked), f"{metric} is not monotonic across tiers: {seen}"


def test_unlimited_is_distinct_from_zero(catalog):
    """None (no ceiling) and 0 (nothing allowed) must not collapse together."""
    assert catalog["scale"].limit_for("agents") is None
    assert catalog["free"].limit_for("agents") == 1


# --- 2. usage limits are actually enforced ----------------------------------

@pytest.mark.parametrize("metric", ["agents", "seats", "knowledge_docs"])
def test_stock_metrics_block_at_the_ceiling(db, org, catalog, metric):
    """Stock limits raise 402 once the tier's allowance is spent.

    402 rather than 403: the caller is authorised, the remedy is to upgrade.
    """
    limit = catalog["free"].limit_for(metric)
    with pytest.raises(HTTPException) as exc:
        usage_service.check(db, org, metric, amount=limit + 1)
    assert exc.value.status_code == 402
    assert exc.value.detail["metric"] == metric
    assert exc.value.detail["limit"] == limit


def test_stock_metric_allows_up_to_the_ceiling(db, org, catalog):
    """The limit is inclusive — spending the last unit is permitted."""
    usage_service.check(db, org, "agents", amount=catalog["free"].limit_for("agents"))


@pytest.mark.parametrize("metric", ["ai_messages", "conversations", "image_requests"])
def test_flow_metrics_are_enforced_when_exceeded(db, org, catalog, metric):
    """Monthly allowances must stop a tenant that has spent them.

    This is the check that decides whether `max_ai_messages_per_month` is a
    product rule or a decorative number on the pricing page.
    """
    limit = catalog["free"].limit_for(metric)
    if limit is None:
        pytest.skip(f"{metric} is unlimited on free")
    _use(db, org, metric, limit)

    with pytest.raises(HTTPException) as exc:
        usage_service.check(db, org, metric, amount=1)
    assert exc.value.status_code == 402


def test_unlimited_tier_never_blocks(db, org, catalog):
    """Scale has no ceilings, so no amount of usage may raise."""
    org.plan_code = "scale"
    db.commit()
    db.refresh(org)
    _use(db, org, "ai_messages", 10_000_000)
    usage_service.check(db, org, "ai_messages", amount=1_000_000)


def test_org_without_a_plan_falls_back_to_default_not_unlimited(db, org, catalog):
    """A tenant with no plan_code must land on the cheapest tier, not a free ride."""
    org.plan_code = None
    db.commit()
    db.refresh(org)
    resolved = usage_service._resolve_plan(db, org)
    assert resolved is not None
    assert resolved.code == "free"


# --- 3. features follow the plan --------------------------------------------

def test_unconfigured_plan_is_unrestricted_not_empty(db, org, catalog):
    """A plan with no feature rows means "nobody decided", so allow.

    The other direction would lock every tenant on a new or unseeded plan out of
    the whole product at once.
    """
    assert feature_catalog.plan_features(db, "free") is None


def test_configured_plan_grants_and_denies_per_row(db, org, catalog):
    key = next(iter(FEATURE_CATALOG)).key if hasattr(
        next(iter(FEATURE_CATALOG)), "key") else list(FEATURE_CATALOG)[0]
    db.add(PlanFeature(plan_code="free", feature_key=key, is_enabled=False))
    db.commit()

    resolved = feature_catalog.plan_features(db, "free")
    assert resolved is not None
    assert resolved[key] is False


def test_per_tenant_override_beats_the_plan(db, org, catalog):
    """Overrides are what let an operator grant an exception without a new tier."""
    key = list(FEATURE_CATALOG)[0]
    key = getattr(key, "key", key)
    db.add(PlanFeature(plan_code="free", feature_key=key, is_enabled=False))
    db.add(OrganizationFeatureOverride(
        organization_id=org.id, feature_key=key, is_enabled=True,
        reason="audit", created_by_email="ops@growmiq.io"))
    db.commit()

    assert feature_catalog.is_enabled(db, org.id, key) is True


# --- 4. upgrades, downgrades and held-back terms ----------------------------

def test_upgrade_raises_the_ceiling_immediately(db, org, catalog):
    """Moving up a tier must lift the limit on the same request."""
    _use(db, org, "ai_messages", 500)
    with pytest.raises(HTTPException):
        usage_service.check(db, org, "ai_messages", amount=1)

    org.plan_code = "starter"
    db.commit()
    db.refresh(org)
    usage_service.check(db, org, "ai_messages", amount=1)


def test_downgrade_applies_the_lower_ceiling(db, org, catalog):
    """And moving down must start enforcing the smaller allowance."""
    org.plan_code = "pro"
    db.commit()
    db.refresh(org)
    _use(db, org, "ai_messages", 600)
    usage_service.check(db, org, "ai_messages", amount=1)

    org.plan_code = "free"
    db.commit()
    db.refresh(org)
    with pytest.raises(HTTPException) as exc:
        usage_service.check(db, org, "ai_messages", amount=1)
    assert exc.value.detail["limit"] == 500


def test_snapshot_holds_a_tenant_to_the_terms_they_signed(db, org, catalog):
    """"New subscriptions only" has to survive a later plan edit."""
    db.add(OrganizationPlanSnapshot(
        organization_id=org.id, plan_code="free",
        limits={"ai_messages": 5000}, reason="grandfathered"))
    db.commit()

    catalog["free"].max_ai_messages_per_month = 50
    db.commit()

    assert usage_service._effective_limit(
        db, org, catalog["free"], "ai_messages") == 5000


def test_snapshot_does_not_survive_a_plan_change(db, org, catalog):
    """Terms from a plan they have left are not terms they agreed to."""
    db.add(OrganizationPlanSnapshot(
        organization_id=org.id, plan_code="free",
        limits={"ai_messages": 5000}, reason="grandfathered"))
    db.commit()

    org.plan_code = "starter"
    db.commit()
    db.refresh(org)

    assert usage_service._effective_limit(
        db, org, catalog["starter"], "ai_messages") == 10000


def test_usage_survives_a_plan_change(db, org, catalog):
    """Upgrading must not silently reset the month's meter.

    If it did, an upgrade-then-downgrade cycle would be a way to buy a fresh
    allowance for one month's fee.
    """
    _use(db, org, "ai_messages", 400)
    org.plan_code = "starter"
    db.commit()
    db.refresh(org)
    assert usage_service.get_usage(db, org.id, "ai_messages") == 400


# --- 5. billing figures -----------------------------------------------------

@pytest.mark.xfail(
    reason="production data: plans.pro is 14901 cents ($149.01). The runbook "
           "records an earlier console save as the cause. Fixing the row makes "
           "this pass; it is a data correction, not a code change.",
    strict=True,
)
def test_prices_are_whole_currency_units(db, catalog):
    """A price that is not a whole number of cents-per-dollar is a data entry slip.

    `pro` is 14901 on production — $149.01 — which the runbook already flags.
    """
    offenders = {c: catalog[c].price_cents for c in catalog
                 if catalog[c].price_cents % 100 != 0}
    assert not offenders, f"non-round prices: {offenders}"


def test_exactly_one_default_plan(db, catalog):
    """Two defaults makes tenant creation nondeterministic; none makes it fail."""
    defaults = [c for c in catalog if catalog[c].is_default]
    assert defaults == ["free"]
