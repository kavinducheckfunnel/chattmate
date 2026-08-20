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

Operator console: the platform's own AI credentials, and the plan terms tenants
are held to. Both are guarded by require_platform_admin, which 404s rather than
403s so the console's existence is not disclosed to tenant accounts.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.model_catalog import list_providers
from app.core.platform_auth import audit, require_platform_admin
from app.database import get_db
from app.models.ai_config import AIConfig
from app.models.organization import Organization
from app.models.plan import Plan
from app.models.plan_snapshot import OrganizationPlanSnapshot
from app.models.user import User
from app.services import platform_ai
from app.services.platform_ai import PlatformAIError

router = APIRouter()
logger = get_logger(__name__)


# ---------------------------------------------------------------- AI config


class ModelSection(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    # Absent means "leave the stored key alone". The console is never sent the
    # existing key, so it cannot echo one back, and treating absent as "clear"
    # would destroy working credentials on any save that only changed a model.
    api_key: Optional[str] = None


class FallbackSection(BaseModel):
    enabled: bool = False
    provider: Optional[str] = None
    model: Optional[str] = None


class PlatformAIUpdate(BaseModel):
    text: ModelSection
    image: ModelSection = Field(default_factory=ModelSection)
    fallback: FallbackSection = Field(default_factory=FallbackSection)


@router.get("/ai-config")
async def get_platform_ai_config(
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Current platform credentials, the provider catalog, and who is using them."""
    config = platform_ai.get_config(db)
    tenants_on_platform = (
        db.query(AIConfig).filter(AIConfig.is_platform_managed.is_(True)).count()
    )
    return {
        "config": config.to_dict(),
        "providers": list_providers(),
        "tenants_using_platform_model": tenants_on_platform,
    }


@router.put("/ai-config")
async def update_platform_ai_config(
    payload: PlatformAIUpdate,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Save the platform's provider accounts.

    Every tenant already on the platform model is re-pointed in the same
    transaction. Saving new credentials while hosted tenants keep authenticating
    with the retired ones would look like a successful rotation and break chat
    for all of them.
    """
    try:
        config = platform_ai.save_config(db, payload.model_dump())
    except PlatformAIError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    synced = platform_ai.sync_tenant_configs(db)

    audit(
        db, actor, request, "platform_ai.update", None,
        text_provider=config.text_provider,
        text_model=config.text_model,
        image_provider=config.image_provider,
        fallback_enabled=config.fallback_enabled,
        tenants_resynced=synced,
    )
    db.commit()

    logger.info(
        "Platform admin %s saved platform AI config (%s/%s); %d tenant(s) resynced",
        actor.email, config.text_provider, config.text_model, synced,
    )
    return {
        "config": config.to_dict(),
        "tenants_resynced": synced,
        "message": (
            f"Platform AI configuration saved. {synced} tenant(s) using the "
            "platform model were updated."
            if synced
            else "Platform AI configuration saved."
        ),
    }


# ------------------------------------------------------------------- billing


@router.get("/billing")
async def platform_billing(
    period: Optional[str] = None,
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Sales, subscriptions, usage and projected AI cost for one billing period."""
    from app.services import platform_billing as billing_service

    return billing_service.overview(db, period)


# ------------------------------------------------------------- plan limits


# What "apply" means, and what each answer does to tenants already on the plan.
APPLY_NEW_ONLY = "new_subscriptions_only"
APPLY_AT_RENEWAL = "at_next_renewal"
APPLY_IMMEDIATELY = "immediately"
APPLY_POLICIES = (APPLY_NEW_ONLY, APPLY_AT_RENEWAL, APPLY_IMMEDIATELY)


class PlanTermsUpdate(BaseModel):
    """One plan's sellable terms. Every field is optional so the console can
    submit only what changed, but a field that *is* sent replaces the stored
    value — including with null, which means unlimited."""

    price_cents: Optional[int] = None
    limits: dict[str, Optional[int]] = Field(default_factory=dict)
    policies: dict[str, Optional[int]] = Field(default_factory=dict)

    @field_validator("limits")
    @classmethod
    def known_limits(cls, value: dict) -> dict:
        unknown = set(value) - set(Plan.LIMIT_COLUMNS)
        if unknown:
            # Silently dropping an unknown metric would report success while
            # changing nothing, and the operator would believe a cap was set.
            raise ValueError(f"Unknown limit(s): {', '.join(sorted(unknown))}")
        return value

    @field_validator("policies")
    @classmethod
    def known_policies(cls, value: dict) -> dict:
        unknown = set(value) - set(Plan.POLICY_COLUMNS)
        if unknown:
            raise ValueError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
        return value


class PlanLimitsUpdate(BaseModel):
    apply_policy: str
    plans: dict[str, PlanTermsUpdate]

    @field_validator("apply_policy")
    @classmethod
    def known_policy(cls, value: str) -> str:
        if value not in APPLY_POLICIES:
            raise ValueError(f"apply_policy must be one of: {', '.join(APPLY_POLICIES)}")
        return value


def _current_limits(plan: Plan) -> dict:
    return {metric: getattr(plan, column) for metric, column in Plan.LIMIT_COLUMNS.items()}


def _renewal_cutoff() -> datetime:
    """When "at next renewal" takes effect.

    Billing periods here are calendar months (see usage.current_period), so the
    next renewal is the first day of next month. Derived rather than stored:
    a per-tenant renewal date would have to be kept in step with a billing
    system this deployment does not have yet, and inventing one would make the
    console promise a date nothing enforces.
    """
    now = datetime.now(timezone.utc)
    first_of_next = (now.replace(day=1) + timedelta(days=32)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    return first_of_next


def _preserve_existing_terms(db: Session, plan: Plan, policy: str) -> int:
    """Record the terms existing tenants keep, before the plan row moves.

    Called *before* the update so the snapshot captures what those tenants were
    actually sold. Returns how many tenants were held back.
    """
    if policy == APPLY_IMMEDIATELY:
        # Nobody is held back, so any earlier hold is released too — otherwise
        # "apply to everyone" would quietly skip tenants pinned by a previous
        # edit, which is the one thing this option promises not to do.
        return (
            db.query(OrganizationPlanSnapshot)
            .filter(OrganizationPlanSnapshot.plan_code == plan.code)
            .delete(synchronize_session=False)
        )

    expires_at = _renewal_cutoff() if policy == APPLY_AT_RENEWAL else None
    frozen = _current_limits(plan)

    organizations = db.query(Organization).filter(Organization.plan_code == plan.code).all()
    for org in organizations:
        snapshot = (
            db.query(OrganizationPlanSnapshot)
            .filter(OrganizationPlanSnapshot.organization_id == org.id)
            .first()
        )
        if snapshot is None:
            snapshot = OrganizationPlanSnapshot(organization_id=org.id)
            db.add(snapshot)
        elif snapshot.plan_code == plan.code and snapshot.is_active():
            # Already holding older terms for this plan. Overwriting would drag
            # them forward to terms they were also never sold, so the earlier
            # snapshot wins and only its expiry is extended if needed.
            if expires_at and snapshot.expires_at and snapshot.expires_at < expires_at:
                snapshot.expires_at = expires_at
            continue

        snapshot.plan_code = plan.code
        snapshot.limits = frozen
        snapshot.expires_at = expires_at
        snapshot.reason = policy

    return len(organizations)


@router.put("/plans/limits")
async def update_plan_limits(
    payload: PlanLimitsUpdate,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Edit the price, allowances and policies of one or more plans.

    `apply_policy` decides what happens to tenants already on each plan, and is
    required rather than defaulted: silently re-pricing live customers is not a
    reasonable thing to do by omission.
    """
    codes = list(payload.plans)
    plans = {p.code: p for p in db.query(Plan).filter(Plan.code.in_(codes)).all()}

    missing = [code for code in codes if code not in plans]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown plan(s): {', '.join(sorted(missing))}",
        )

    affected = 0
    changed: dict[str, dict] = {}

    for code, terms in payload.plans.items():
        plan = plans[code]
        before = {"price_cents": plan.price_cents, **_current_limits(plan)}

        affected += _preserve_existing_terms(db, plan, payload.apply_policy)

        if terms.price_cents is not None:
            plan.price_cents = terms.price_cents
        for metric, value in terms.limits.items():
            setattr(plan, Plan.LIMIT_COLUMNS[metric], value)
        for column, value in terms.policies.items():
            setattr(plan, column, value)

        after = {"price_cents": plan.price_cents, **_current_limits(plan)}
        delta = {k: [before[k], after[k]] for k in after if before.get(k) != after[k]}
        if delta:
            changed[code] = delta

    audit(
        db, actor, request, "plan.limits", None,
        apply_policy=payload.apply_policy,
        plans=codes,
        changes=changed,
        tenants_affected=affected,
    )
    db.commit()

    logger.info(
        "Platform admin %s updated plan limits %s (policy=%s, %d tenants)",
        actor.email, codes, payload.apply_policy, affected,
    )

    messages = {
        APPLY_IMMEDIATELY: f"Saved. {affected} organization(s) move to the new terms now.",
        APPLY_AT_RENEWAL: (
            f"Saved. New customers get these terms now; {affected} existing "
            f"organization(s) move on {_renewal_cutoff().date().isoformat()}."
        ),
        APPLY_NEW_ONLY: (
            f"Saved for new subscriptions. {affected} existing organization(s) "
            "keep their current terms."
        ),
    }
    return {
        "message": messages[payload.apply_policy],
        "apply_policy": payload.apply_policy,
        "tenants_affected": affected,
        "changes": changed,
        "plans": [plans[c].to_dict() for c in codes],
    }
