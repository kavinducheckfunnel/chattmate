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

from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, func, Index
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class PlatformAuditLog(Base):
    """An action taken by a platform operator across the tenant boundary.

    Every endpoint under /platform writes here. That boundary is the one thing
    the whole isolation model exists to prevent being crossed casually, so when
    it *is* crossed legitimately there has to be a record of who, what and when
    — both to investigate an incident and to answer a customer asking whether
    anyone at the provider looked at their data.

    Deliberately append-only in practice: no update or delete path exists in the
    application. An audit trail an operator can edit is not an audit trail.
    """

    __tablename__ = "platform_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ondelete SET NULL, not CASCADE: removing an operator's account must not
    # erase the history of what they did. The denormalised email below is what
    # keeps the record readable afterwards.
    actor_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Copied at write time rather than joined at read time. The join would
    # return NULL for a deleted operator, which is precisely the case where
    # knowing who acted matters most.
    actor_email = Column(String(255), nullable=False)

    action = Column(String(64), nullable=False)

    # The tenant acted upon. Also SET NULL — the most consequential action here
    # is deleting an organization, and a CASCADE would delete the evidence of it
    # along with the tenant.
    target_organization_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_organization_domain = Column(String(100), nullable=True)

    # What changed, as {"before": ..., "after": ...}, plus any free-form context.
    details = Column(JSON, nullable=False, default=dict)

    ip_address = Column(String(45), nullable=True)  # 45 chars fits IPv6
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_platform_audit_target_created", "target_organization_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "actor_email": self.actor_email,
            "action": self.action,
            "target_organization_id": (
                str(self.target_organization_id) if self.target_organization_id else None
            ),
            "target_organization_domain": self.target_organization_domain,
            "details": self.details or {},
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
