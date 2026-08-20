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

Plan snapshots are what make the operator's "who does this apply to?" answer
real. If enforcement ignored them, all three options in the dialog would behave
identically and the console would be quietly lying about what it just did.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.plan import Plan
from app.models.plan_snapshot import OrganizationPlanSnapshot
from app.services import usage as usage_service


@pytest.fixture
def plan(db) -> Plan:
    plan = Plan(
        code="test-tier",
        name="Test Tier",
        price_cents=2500,
        max_ai_messages_per_month=300,
        max_agents=1,
        sort_order=1,
        is_active=True,
    )
    db.add(plan)
    db.commit()
    return plan


@pytest.fixture
def org_on_plan(db, test_organization, plan):
    test_organization.plan_code = plan.code
    db.commit()
    db.refresh(test_organization)
    return test_organization


def _snapshot(db, org, plan, limits, expires_at=None, reason="test"):
    snapshot = OrganizationPlanSnapshot(
        organization_id=org.id,
        plan_code=plan.code,
        limits=limits,
        expires_at=expires_at,
        reason=reason,
    )
    db.add(snapshot)
    db.commit()
    return snapshot


def test_without_a_snapshot_the_plan_applies(db, org_on_plan, plan):
    """The ordinary case: no hold-back, so the live plan is what is enforced."""
    assert usage_service._effective_limit(db, org_on_plan, plan, "ai_messages") == 300


def test_snapshot_holds_the_tenant_to_the_old_allowance(db, org_on_plan, plan):
    """"New subscriptions only" must actually protect existing customers.

    The plan is lowered to 50 after the snapshot recorded 300. Reading the plan
    directly would apply the cut to everyone, making the operator's choice
    cosmetic — which is the whole failure this table exists to prevent.
    """
    _snapshot(db, org_on_plan, plan, {"ai_messages": 300})
    plan.max_ai_messages_per_month = 50
    db.commit()

    assert usage_service._effective_limit(db, org_on_plan, plan, "ai_messages") == 300


def test_expired_snapshot_lets_the_new_terms_through(db, org_on_plan, plan):
    """"Apply at next renewal" stops holding once the renewal has passed."""
    _snapshot(
        db, org_on_plan, plan, {"ai_messages": 300},
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    plan.max_ai_messages_per_month = 50
    db.commit()

    assert usage_service._effective_limit(db, org_on_plan, plan, "ai_messages") == 50


def test_future_expiry_still_holds(db, org_on_plan, plan):
    _snapshot(
        db, org_on_plan, plan, {"ai_messages": 300},
        expires_at=datetime.now(timezone.utc) + timedelta(days=5),
    )
    plan.max_ai_messages_per_month = 50
    db.commit()

    assert usage_service._effective_limit(db, org_on_plan, plan, "ai_messages") == 300


def test_metric_absent_from_the_snapshot_falls_through_to_the_plan(db, org_on_plan, plan):
    """A snapshot speaks only for what it recorded.

    Otherwise adding a brand-new metric later would leave every held-back tenant
    unlimited on it, which is the expensive direction to get wrong.
    """
    _snapshot(db, org_on_plan, plan, {"ai_messages": 300})
    plan.max_agents = 4
    db.commit()

    assert usage_service._effective_limit(db, org_on_plan, plan, "agents") == 4


def test_snapshot_for_a_different_plan_is_ignored(db, org_on_plan, plan):
    """Terms carried over from a plan the tenant has left are not their terms."""
    _snapshot(db, org_on_plan, plan, {"ai_messages": 9999})
    snapshot = db.query(OrganizationPlanSnapshot).first()
    snapshot.plan_code = "some-other-tier"
    plan.max_ai_messages_per_month = 50
    db.commit()

    assert usage_service._effective_limit(db, org_on_plan, plan, "ai_messages") == 50


def test_snapshot_null_means_unlimited_not_missing(db, org_on_plan, plan):
    """None inside a snapshot is a recorded "unlimited", not an absent key.

    Collapsing the two would silently re-impose a ceiling on a tenant who was
    explicitly sold none.
    """
    _snapshot(db, org_on_plan, plan, {"ai_messages": None})
    plan.max_ai_messages_per_month = 50
    db.commit()

    assert usage_service._effective_limit(db, org_on_plan, plan, "ai_messages") is None


def test_check_enforces_the_snapshot_not_the_plan(db, org_on_plan, plan):
    """End to end: the quota gate itself must respect the hold-back."""
    _snapshot(db, org_on_plan, plan, {"ai_messages": 300})
    plan.max_ai_messages_per_month = 1
    db.commit()

    usage_service.record(db, org_on_plan.id, "ai_messages", amount=10)
    db.commit()

    # Over the plan's new ceiling of 1, but well inside the 300 they keep.
    usage_service.check(db, org_on_plan, "ai_messages", amount=1)
