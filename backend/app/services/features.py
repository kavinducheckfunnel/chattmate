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

Resolving what a tenant may actually do.

Three layers, most specific wins:

    per-tenant override  >  plan entitlement  >  unconfigured default

The last layer is the one worth explaining. A plan with no `plan_features` rows
means nobody has decided what it includes — not that it includes nothing. If an
absent row denied access, then creating a plan, or deploying before the seed
ran, would lock every tenant on it out of the entire product at once. So an
unconfigured plan is unrestricted, and the matrix only starts constraining a
plan once someone has actually configured it. The console shows this state
plainly rather than letting an operator mistake "not set up" for "denied".

Deleting the last feature row from a plan therefore reopens everything, which
is why the console disables rather than deletes.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.models.feature import (
    FEATURE_CATALOG, FEATURE_KEYS, OrganizationFeatureOverride, PlanFeature,
)
from app.models.organization import Organization

logger = get_logger(__name__)


def plan_features(db: Session, plan_code: Optional[str]) -> Optional[dict[str, bool]]:
    """What a plan includes, or None if the plan has never been configured.

    None and {} are different answers and must not be collapsed: None means "no
    policy exists" (allow everything), {} would mean "a policy exists and grants
    nothing". Returning None lets the caller tell them apart.
    """
    if not plan_code:
        return None
    rows = db.execute(
        select(PlanFeature.feature_key, PlanFeature.is_enabled)
        .where(PlanFeature.plan_code == plan_code)
    ).all()
    if not rows:
        return None
    return {key: bool(enabled) for key, enabled in rows}


def org_overrides(db: Session, organization_id: UUID) -> dict[str, bool]:
    """The exceptions recorded for one tenant."""
    rows = db.execute(
        select(OrganizationFeatureOverride.feature_key, OrganizationFeatureOverride.is_enabled)
        .where(OrganizationFeatureOverride.organization_id == organization_id)
    ).all()
    return {key: bool(enabled) for key, enabled in rows}


def effective_features(db: Session, organization) -> dict[str, bool]:
    """The final answer for every catalog key, for one tenant.

    Returns the whole catalog rather than only what is enabled, so a caller can
    render a matrix without having to know which keys exist.
    """
    base = plan_features(db, getattr(organization, "plan_code", None))
    # No configured plan policy — everything is available, as it was before
    # feature gating existed.
    resolved = {f.key: True for f in FEATURE_CATALOG} if base is None else {
        f.key: base.get(f.key, False) for f in FEATURE_CATALOG
    }
    for key, enabled in org_overrides(db, organization.id).items():
        if key in resolved:
            resolved[key] = enabled
    return resolved


def is_enabled(db: Session, organization_id: UUID, feature: str) -> bool:
    """Whether one tenant may use one capability.

    Unknown keys return True. A typo at a call site must not silently disable a
    working feature in production — the console's catalog is the list of keys
    that mean anything, and anything outside it was never gated.
    """
    if feature not in FEATURE_KEYS:
        logger.warning("Feature check for unknown key %r — allowing", feature)
        return True

    override = db.scalar(
        select(OrganizationFeatureOverride.is_enabled).where(
            OrganizationFeatureOverride.organization_id == organization_id,
            OrganizationFeatureOverride.feature_key == feature,
        )
    )
    if override is not None:
        return bool(override)

    plan_code = db.scalar(
        select(Organization.plan_code).where(Organization.id == organization_id)
    )
    base = plan_features(db, plan_code)
    if base is None:
        return True
    return base.get(feature, False)


def set_plan_feature(db: Session, plan_code: str, feature: str, enabled: bool) -> None:
    """Turn a capability on or off for a plan. Caller commits."""
    row = (
        db.query(PlanFeature)
        .filter(PlanFeature.plan_code == plan_code, PlanFeature.feature_key == feature)
        .first()
    )
    if row:
        row.is_enabled = enabled
    else:
        db.add(PlanFeature(plan_code=plan_code, feature_key=feature, is_enabled=enabled))


def set_org_override(db: Session, organization_id: UUID, feature: str,
                     enabled: Optional[bool], reason: Optional[str],
                     actor_email: Optional[str]) -> None:
    """Record, change, or clear one tenant's exception. Caller commits.

    `enabled=None` deletes the override, returning the tenant to whatever their
    plan says — which is different from setting it to the same value the plan
    happens to have today, because a later plan change would then not reach them.
    """
    row = (
        db.query(OrganizationFeatureOverride)
        .filter(
            OrganizationFeatureOverride.organization_id == organization_id,
            OrganizationFeatureOverride.feature_key == feature,
        )
        .first()
    )
    if enabled is None:
        if row:
            db.delete(row)
        return
    if row:
        row.is_enabled = enabled
        row.reason = reason
        row.created_by_email = actor_email
    else:
        db.add(OrganizationFeatureOverride(
            organization_id=organization_id,
            feature_key=feature,
            is_enabled=enabled,
            reason=reason,
            created_by_email=actor_email,
        ))
