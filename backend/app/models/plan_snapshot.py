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

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class OrganizationPlanSnapshot(Base):
    """The plan terms one tenant keeps while the catalog moves on beneath them.

    Editing a plan is not the same act as re-pricing everyone already on it. An
    operator lowering the Free message allowance is usually writing next month's
    offer, not cutting off tenants mid-period — so the console asks, and this
    table is what makes the two gentler answers real rather than cosmetic.

    A row here means: this organization is still on the terms recorded in
    ``limits``, whatever the plan row now says.

      expires_at IS NULL   the tenant keeps these terms until they change plan
                           ("new subscriptions only" — the edit describes a new
                           offer, and existing customers were never sold it)

      expires_at set       the tenant keeps these terms until their period rolls
                           over ("apply at next renewal")

    "Apply immediately to everyone" writes no row at all, and deletes any that
    exist: the whole point is that nobody is held back.

    Storing the old values rather than a pointer to a plan version matters — a
    version pointer would have to survive every later edit of that version, and
    the tenant's terms would silently change again the next time somebody
    touched history.
    """

    __tablename__ = "organization_plan_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # One live snapshot per organization. A second row would leave the effective
    # limit depending on row order, which is not a decision anyone made.
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Recorded so a snapshot can be discarded when the tenant moves to a
    # different plan — terms carried over from a plan they have left are not
    # terms anyone agreed to.
    plan_code = Column(String(32), nullable=False)

    # Metric -> ceiling, mirroring Plan.LIMIT_COLUMNS keys. NULL values inside
    # mean unlimited, exactly as they do on the plan itself.
    limits = Column(JSON, nullable=False, default=dict)

    # NULL means "until they change plan"; see the class docstring.
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Kept for the audit trail: which change these terms were preserved against.
    reason = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def is_active(self, now: datetime = None) -> bool:
        """Whether these terms still apply.

        An expired snapshot is left in place rather than deleted so the audit
        log keeps its subject; it simply stops being consulted.

        The stored value is normalised to UTC before comparing because not every
        backend hands it back with a timezone — SQLite drops it entirely — and an
        offset-naive/aware comparison raises TypeError. That would surface inside
        the quota check, turning a plan edit into an error on the tenant's next
        message rather than a limit decision.
        """
        if self.expires_at is None:
            return True

        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        return (now or datetime.now(timezone.utc)) < expires_at

    def to_dict(self) -> dict:
        return {
            "organization_id": str(self.organization_id),
            "plan_code": self.plan_code,
            "limits": self.limits or {},
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "reason": self.reason,
            "active": self.is_active(),
        }
