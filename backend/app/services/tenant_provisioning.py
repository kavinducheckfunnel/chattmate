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

Creating a tenant, once, for both ways in.

Two paths now produce an organization: public signup, and an operator adding a
customer from the console. They must produce identical tenants — same roles,
same permission set, same default plan. Written twice they would not stay
identical, and the failure would be silent: a tenant created by an operator
would work until someone hit the one permission the other path grants.

The uniqueness checks live here too. users.email and organizations.domain both
carry global unique indexes, and letting the insert fail instead turns a
correctable mistake into an opaque 500 with a constraint name in it.
"""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.models.organization import Organization
from app.models.permission import DEFAULT_AGENT_ROLE_PERMISSIONS, Permission
from app.models.plan import Plan
from app.models.role import Role
from app.models.user import User
from app.repositories.organization import OrganizationRepository

logger = get_logger(__name__)


def ensure_unique(db: Session, email: str, domain: str) -> tuple[str, str]:
    """Normalise and check the two globally unique fields.

    Returns the normalised pair so callers cannot check one form and insert
    another — the check and the insert must see the same string.
    """
    normalized_email = (email or "").strip().lower()
    normalized_domain = (domain or "").strip().lower()

    if db.query(User.id).filter(User.email == normalized_email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Try signing in instead.",
        )
    if db.query(Organization.id).filter(Organization.domain == normalized_domain).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This domain is already registered to another workspace.",
        )
    return normalized_email, normalized_domain


def ensure_permissions(db: Session) -> dict[str, Permission]:
    """Load the permission rows, creating any that this deployment lacks.

    Permissions are global, not per-tenant, so this is idempotent and cheap
    after the first tenant.
    """
    permissions: dict[str, Permission] = {}
    for name, description in Permission.default_permissions():
        perm = db.query(Permission).filter(Permission.name == name).first()
        if not perm:
            perm = Permission(name=name, description=description)
            db.add(perm)
            db.flush()
        permissions[name] = perm
    return permissions


def create_default_roles(db: Session, organization: Organization) -> Role:
    """Create Admin and Agent for a new tenant, and return Admin.

    Exactly one role must be is_default. Nothing in the schema enforces it and
    get_default_role() takes .first() with no ordering, so a second default
    would make an invited user's role depend on row order. Agent is the default
    because the tenant's creator is given Admin explicitly.
    """
    permissions = ensure_permissions(db)

    admin_role = Role(
        name="Admin",
        description="Full access to all features",
        organization_id=organization.id,
        is_default=False,
    )
    admin_role.permissions = list(permissions.values())
    db.add(admin_role)

    agent_role = Role(
        name="Agent",
        description="Access to assigned chats and the unclaimed AI queue",
        organization_id=organization.id,
        is_default=True,
    )
    agent_role.permissions = [
        permissions[name] for name in DEFAULT_AGENT_ROLE_PERMISSIONS if name in permissions
    ]
    db.add(agent_role)
    db.flush()
    return admin_role


def resolve_plan(db: Session, plan_code: Optional[str]) -> Optional[Plan]:
    """The plan to put a new tenant on.

    An explicit code is validated rather than trusted — the foreign key would
    reject an unknown one as a 500 with a constraint name in it. With no code,
    falls back to the catalog default.
    """
    if plan_code:
        plan = db.query(Plan).filter(Plan.code == plan_code).first()
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No such plan: {plan_code}",
            )
        return plan
    return (
        db.query(Plan)
        .filter(Plan.is_default == True, Plan.is_active == True)  # noqa: E712
        .first()
    )


def provision_tenant(
    db: Session,
    *,
    name: str,
    domain: str,
    timezone: str,
    admin_name: str,
    admin_email: str,
    admin_password: str,
    plan_code: Optional[str] = None,
    business_hours: Optional[dict] = None,
    email_verified: bool = False,
) -> tuple[Organization, User]:
    """Create an organization, its roles, and its first admin.

    Flushes but does not commit. The caller decides what else belongs in the
    same transaction — the signup path adds a verification token, the console
    adds an audit row, and neither should be able to persist without the tenant
    it describes.

    `email_verified` differs by caller and is passed explicitly rather than left
    to the column default, which is server-side `true` so a migration could
    backfill existing accounts. Public signup must start unverified; an
    operator who typed the address and will hand over the password has already
    established it by other means.
    """
    normalized_email, normalized_domain = ensure_unique(db, admin_email, domain)

    organization = OrganizationRepository(db).create_organization(
        name=name,
        domain=normalized_domain,
        timezone=timezone,
        business_hours=business_hours,
    )

    plan = resolve_plan(db, plan_code)
    if plan:
        organization.plan_code = plan.code
    else:
        logger.warning(
            "No plan resolved; organization %s created without one", organization.id,
        )

    admin_role = create_default_roles(db, organization)

    admin = User(
        email=normalized_email,
        full_name=admin_name,
        hashed_password=User.get_password_hash(admin_password),
        organization_id=organization.id,
        role_id=admin_role.id,
        is_active=True,
        is_email_verified=email_verified,
    )
    db.add(admin)
    db.flush()

    return organization, admin
