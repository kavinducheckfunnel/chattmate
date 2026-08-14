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

Operator console: the actions that change things.

Split from platform_admin.py, which had grown past the point where the tenant
read paths and the cross-tenant write paths could be reviewed as one file.
Everything here carries the same rules as that module — the flag re-read on
every request, an audit row in the same transaction as the change — imported
from app/core/platform_auth.py so the two cannot drift apart.

What is deliberately absent: nothing here can send a message as a tenant, read
a channel credential, or grant platform access. Operator accounts are still
created only by scripts/create_platform_admin.py, which needs shell access.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.logger import get_logger
from app.core.platform_auth import audit, require_org, require_platform_admin
from app.core.security import revoke_user_sessions, validate_password_strength
from app.database import get_db
from app.models.feature import FEATURE_CATALOG, FEATURE_KEYS, PlanFeature
from app.models.organization import Organization
from app.models.plan import Plan
from app.models.role import Role
from app.models.user import User
from app.services import features as feature_service
from app.services import tenant_provisioning

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------

class TenantCreate(BaseModel):
    name: str
    domain: str
    admin_name: str
    admin_email: EmailStr
    admin_password: str
    plan_code: Optional[str] = None
    timezone: str = "UTC"

    @field_validator("admin_password")
    @classmethod
    def _strength(cls, v: str) -> str:
        # The same policy as signup, invitations and self-service reset. An
        # operator-set password is the one most likely to be read aloud on a
        # call, so it is the last one that should get an exemption.
        return validate_password_strength(v)

    @field_validator("name", "admin_name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("This field is required")
        return v.strip()

    @field_validator("domain")
    @classmethod
    def _domain_shape(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v or "." not in v or " " in v:
            raise ValueError("Enter a domain such as acme.com")
        return v


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Create a customer workspace and its first admin.

    Goes through the same provisioning service as public signup, so an
    operator-created tenant is indistinguishable from a self-serve one — same
    roles, same permissions, same plan handling.

    The owner is marked verified. Public signup cannot do that because the
    address is an unproven claim by a stranger; here an operator has typed it
    and will hand the password over directly, so demanding a verification click
    would only lock out the customer they just onboarded.
    """
    organization, admin = tenant_provisioning.provision_tenant(
        db,
        name=payload.name,
        domain=payload.domain,
        timezone=payload.timezone,
        admin_name=payload.admin_name,
        admin_email=payload.admin_email,
        admin_password=payload.admin_password,
        plan_code=payload.plan_code,
        email_verified=True,
    )

    audit(
        db, actor, request, "tenant.create", organization,
        admin_email=admin.email, plan_code=organization.plan_code,
    )
    db.commit()

    logger.info(
        "Platform admin %s created tenant %s (owner %s)",
        actor.email, organization.domain, admin.email,
    )
    return {
        "message": f"Workspace {organization.domain} created",
        "tenant": {
            "id": str(organization.id),
            "name": organization.name,
            "domain": organization.domain,
            "plan_code": organization.plan_code,
        },
        "admin": {"id": str(admin.id), "email": admin.email},
    }


# ---------------------------------------------------------------------------
# Cross-tenant users
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_users(
    q: Optional[str] = Query(None, description="Match name or email"),
    organization_id: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Every user on the platform, filterable.

    This is the "a customer says they cannot sign in" screen, so it searches
    across tenants — the operator usually has an email address and nothing
    else, and asking which workspace it belongs to defeats the purpose.

    Operator accounts appear but are marked, so it is obvious why the row
    cannot be edited here before anyone tries.
    """
    query = (
        db.query(User)
        .options(joinedload(User.role), joinedload(User.organization))
    )

    if q:
        like = f"%{q.strip().lower()}%"
        query = query.filter(or_(
            func.lower(User.email).like(like),
            func.lower(User.full_name).like(like),
        ))
    if organization_id:
        query = query.filter(User.organization_id == organization_id)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if role:
        query = query.join(Role, User.role_id == Role.id).filter(Role.name == role)

    total = query.count()
    rows = (
        query.order_by(User.created_at.desc().nullslast())
        .limit(limit).offset(offset).all()
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "is_active": u.is_active,
                "is_email_verified": u.is_email_verified,
                "is_platform_admin": u.is_platform_admin,
                "role": u.role.name if u.role else None,
                "organization_id": str(u.organization_id) if u.organization_id else None,
                "organization_domain": u.organization.domain if u.organization else None,
                "organization_name": u.organization.name if u.organization else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in rows
        ],
    }


@router.get("/roles")
async def list_roles(
    organization_id: str = Query(...),
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """The roles available inside one tenant.

    Roles are per-organization, so the console has to ask which tenant before
    it can offer a role picker — there is no global list to choose from.
    """
    org = require_org(db, organization_id)
    roles = (
        db.query(Role).filter(Role.organization_id == org.id)
        .order_by(Role.name.asc()).all()
    )
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "is_default": r.is_default,
        }
        for r in roles
    ]


class TenantUserCreate(BaseModel):
    organization_id: str
    full_name: str
    email: EmailStr
    password: str
    role_id: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        return validate_password_strength(v)

    @field_validator("full_name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Name is required")
        return v.strip()


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: TenantUserCreate,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Add a user to a tenant.

    The role must belong to the same tenant. Without that check an operator
    could attach a role from another organization, and the permission system —
    which resolves permissions through the role — would silently grant access
    scoped to the wrong workspace.
    """
    org = require_org(db, payload.organization_id)

    normalized_email = payload.email.strip().lower()
    if db.query(User.id).filter(User.email == normalized_email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    if payload.role_id:
        role = (
            db.query(Role)
            .filter(Role.id == payload.role_id, Role.organization_id == org.id)
            .first()
        )
        if not role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That role does not belong to this workspace.",
            )
    else:
        role = (
            db.query(Role)
            .filter(Role.organization_id == org.id, Role.is_default == True)  # noqa: E712
            .first()
        )
        if not role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This workspace has no default role; pick one explicitly.",
            )

    user = User(
        email=normalized_email,
        full_name=payload.full_name,
        hashed_password=User.get_password_hash(payload.password),
        organization_id=org.id,
        role_id=role.id,
        is_active=True,
        # An operator typed this address and will pass on the password, so the
        # claim is already established — same reasoning as an invited teammate.
        is_email_verified=True,
    )
    db.add(user)
    db.flush()

    audit(
        db, actor, request, "user.create", org,
        target_user_id=str(user.id), target_user_email=user.email, role=role.name,
    )
    db.commit()

    logger.info(
        "Platform admin %s created user %s in %s", actor.email, user.email, org.domain,
    )
    return {
        "message": "User created",
        "user": {"id": str(user.id), "email": user.email, "role": role.name},
    }


class TenantUserRoleUpdate(BaseModel):
    role_id: str


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    payload: TenantUserRoleUpdate,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Move a tenant's user to a different role."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This is a platform operator account. Manage operators with "
                "grant_platform_admin.py on the server."
            ),
        )
    if not user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account belongs to no workspace, so it has no role to change.",
        )

    role = (
        db.query(Role)
        .filter(Role.id == payload.role_id, Role.organization_id == user.organization_id)
        .first()
    )
    if not role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That role does not belong to this user's workspace.",
        )

    before = user.role.name if user.role else None
    if role.id == user.role_id:
        return {"message": "No changes"}
    user.role_id = role.id

    org = db.query(Organization).filter(Organization.id == user.organization_id).first()
    audit(
        db, actor, request, "user.role", org,
        target_user_id=str(user.id), target_user_email=user.email,
        changes={"role": {"before": before, "after": role.name}},
    )
    db.commit()

    # A role change is a permission change, and cached session claims would
    # keep the old one alive until the token expired.
    try:
        revoke_user_sessions(user.email)
    except Exception as e:
        logger.error("Failed to revoke sessions for %s: %s", user.email, e)

    logger.warning(
        "Platform admin %s changed %s role: %s -> %s",
        actor.email, user.email, before, role.name,
    )
    return {"message": f"Role changed to {role.name}", "role": role.name}


class UserDelete(BaseModel):
    # Typing the address is the confirmation. Deleting a user detaches their
    # conversation history, and picking the wrong row from a cross-tenant list
    # is an easy mistake to make.
    confirm_email: str


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    payload: UserDelete,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Remove a user from the platform.

    Refuses to delete a tenant's last remaining member: that would leave an
    organization with data, billing and conversations but nobody who can sign
    in to it — recoverable only by hand on the server.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This is a platform operator account. Manage operators with "
                "grant_platform_admin.py on the server."
            ),
        )
    if payload.confirm_email.strip().lower() != (user.email or "").lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Type {user.email!r} exactly to confirm removal.",
        )

    org = (
        db.query(Organization).filter(Organization.id == user.organization_id).first()
        if user.organization_id else None
    )
    if org:
        remaining = db.scalar(
            select(func.count()).select_from(User)
            .where(User.organization_id == org.id, User.id != user.id)
        ) or 0
        if remaining == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{user.email} is the only member of {org.domain}. "
                    "Delete the whole workspace instead, or add another member first."
                ),
            )

    snapshot = {"email": user.email, "full_name": user.full_name,
                "role": user.role.name if user.role else None}
    audit(
        db, actor, request, "user.delete", org,
        target_user_id=str(user.id), target_user_email=user.email, deleted=snapshot,
    )
    email = user.email
    db.delete(user)
    db.commit()

    try:
        revoke_user_sessions(email)
    except Exception as e:
        logger.error("Failed to revoke sessions for %s: %s", email, e)

    logger.warning(
        "Platform admin %s DELETED user %s (%s)",
        actor.email, email, org.domain if org else "no workspace",
    )
    return {"message": f"{email} removed", "deleted": snapshot}


# ---------------------------------------------------------------------------
# Feature matrix
# ---------------------------------------------------------------------------

@router.get("/features")
async def feature_catalog(
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """The catalog, and which plans currently include each entry.

    `enforced_at` travels with every row so the console can show where a switch
    takes effect. A matrix of unexplained toggles invites an operator to guess,
    and the guess is usually that it does more than it does.
    """
    plans = db.query(Plan).order_by(Plan.sort_order.asc(), Plan.price_cents.asc()).all()

    rows = db.execute(
        select(PlanFeature.plan_code, PlanFeature.feature_key, PlanFeature.is_enabled)
    ).all()
    matrix: dict[str, dict[str, bool]] = {}
    for plan_code, key, enabled in rows:
        matrix.setdefault(plan_code, {})[key] = bool(enabled)

    return {
        "features": [f.to_dict() for f in FEATURE_CATALOG],
        "plans": [
            {
                "code": p.code,
                "name": p.name,
                "price_cents": p.price_cents,
                # A plan with no rows has never been configured, and is
                # therefore unrestricted rather than empty. The console has to
                # say which of the two it is looking at.
                "configured": p.code in matrix,
                "features": {
                    f.key: matrix.get(p.code, {}).get(f.key, False)
                    for f in FEATURE_CATALOG
                },
            }
            for p in plans
        ],
    }


class PlanFeatureUpdate(BaseModel):
    features: dict[str, bool]

    @field_validator("features")
    @classmethod
    def _known_keys(cls, v: dict[str, bool]) -> dict[str, bool]:
        unknown = sorted(set(v) - FEATURE_KEYS)
        if unknown:
            # Rejected rather than ignored: silently dropping a key would tell
            # the operator their change was saved when nothing was written.
            raise ValueError(f"Unknown feature keys: {', '.join(unknown)}")
        return v


@router.put("/plans/{plan_code}/features")
async def update_plan_features(
    plan_code: str,
    payload: PlanFeatureUpdate,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Set which capabilities a plan includes.

    Applies immediately to every tenant on the plan — the gate reads this table
    live rather than copying it onto the tenant at signup. Turning something
    off can therefore take it away from a customer mid-session, so the response
    reports how many tenants were affected.
    """
    plan = db.query(Plan).filter(Plan.code == plan_code).first()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

    current = feature_service.plan_features(db, plan.code) or {}
    changes = {
        key: {"before": current.get(key, False), "after": enabled}
        for key, enabled in payload.features.items()
        if current.get(key, False) != enabled
    }

    # Every catalog key is written, not only the changed ones. A plan must end
    # up "configured" for all of them, or an untouched key would keep falling
    # through to the unconfigured-means-unrestricted rule and quietly stay on.
    for feature in FEATURE_CATALOG:
        feature_service.set_plan_feature(
            db, plan.code, feature.key, payload.features.get(feature.key, False),
        )

    affected = db.scalar(
        select(func.count()).select_from(Organization)
        .where(Organization.plan_code == plan.code)
    ) or 0

    audit(
        db, actor, request, "plan.features", None,
        plan_code=plan.code, changes=changes, tenants_affected=affected,
    )
    db.commit()

    logger.info(
        "Platform admin %s set features on plan %s (%d tenants): %s",
        actor.email, plan.code, affected, changes,
    )
    return {
        "message": f"Plan features saved. {affected} tenant(s) are on this plan.",
        "changes": changes,
        "tenants_affected": affected,
    }


@router.get("/tenants/{organization_id}/features")
async def tenant_features(
    organization_id: str,
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """What one tenant can actually do, and why.

    Three columns rather than one answer: what the plan grants, what has been
    overridden for this tenant, and the result. An operator debugging "why
    can't my customer use workflows" needs to see which of the two layers said
    no.
    """
    org = require_org(db, organization_id)
    plan_map = feature_service.plan_features(db, org.plan_code)
    overrides = feature_service.org_overrides(db, org.id)
    effective = feature_service.effective_features(db, org)

    return {
        "organization_id": str(org.id),
        "plan_code": org.plan_code,
        "plan_configured": plan_map is not None,
        "features": [
            {
                **f.to_dict(),
                "plan_default": True if plan_map is None else plan_map.get(f.key, False),
                "override": overrides.get(f.key),
                "effective": effective[f.key],
            }
            for f in FEATURE_CATALOG
        ],
    }


class OrgFeatureOverride(BaseModel):
    feature_key: str
    # None clears the override, returning the tenant to their plan. That is
    # different from setting it to whatever the plan says today, because a
    # later plan change would then not reach them.
    is_enabled: Optional[bool] = None
    reason: Optional[str] = None

    @field_validator("feature_key")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in FEATURE_KEYS:
            raise ValueError(f"Unknown feature: {v}")
        return v


@router.put("/tenants/{organization_id}/features")
async def set_tenant_feature(
    organization_id: str,
    payload: OrgFeatureOverride,
    request: Request,
    actor: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Grant or withhold one capability for one tenant, against their plan."""
    org = require_org(db, organization_id)

    before = feature_service.org_overrides(db, org.id).get(payload.feature_key)
    feature_service.set_org_override(
        db, org.id, payload.feature_key, payload.is_enabled,
        payload.reason, actor.email,
    )

    audit(
        db, actor, request, "tenant.feature", org,
        feature=payload.feature_key,
        changes={"override": {"before": before, "after": payload.is_enabled}},
        reason=payload.reason,
    )
    db.commit()

    logger.info(
        "Platform admin %s set %s override on %s: %s",
        actor.email, payload.feature_key, org.domain, payload.is_enabled,
    )
    action = "cleared" if payload.is_enabled is None else (
        "enabled" if payload.is_enabled else "disabled"
    )
    return {"message": f"Override {action}", "feature": payload.feature_key}
