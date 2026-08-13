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
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.logger import get_logger
from app.database import get_db
from app.models.plan import Plan
from app.models.organization import Organization
from app.models.user import User
from app.services import usage as usage_service

logger = get_logger(__name__)
router = APIRouter()


@router.get("")
async def get_usage_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """This tenant's consumption and limits for the current period.

    Scoped to the caller's own organization, taken from the session rather than
    a parameter — there is deliberately no way to ask for another tenant's
    usage here. Cross-tenant visibility belongs to the operator console, behind
    a separate permission.

    Readable by any authenticated member, not gated on manage_organization: an
    agent who hits a quota wall needs to see why, and hiding the number turns
    a clear limit into an unexplained failure.
    """
    organization = (
        db.query(Organization)
        .filter(Organization.id == current_user.organization_id)
        .first()
    )
    return usage_service.summary(db, organization)


@router.get("/plans")
async def list_plans(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The sellable catalog, cheapest first.

    Inactive plans are withheld: a tenant grandfathered onto a retired tier
    keeps it, but nobody should be shown a plan they cannot buy.
    """
    plans = (
        db.query(Plan)
        .filter(Plan.is_active == True)
        .order_by(Plan.sort_order.asc(), Plan.price_cents.asc())
        .all()
    )
    return [p.to_dict() for p in plans]
