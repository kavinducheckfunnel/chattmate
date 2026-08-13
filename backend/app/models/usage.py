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

from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, BigInteger, DateTime, ForeignKey, func, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


def current_period(at: datetime | None = None) -> str:
    """Billing period key for a moment in time, as 'YYYY-MM'.

    UTC, always. Deriving the period from server local time would move the
    reset boundary if the host timezone were ever changed, and would put
    tenants in different timezones onto different month boundaries for a
    quota that is billed globally.
    """
    moment = at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m")


class UsageCounter(Base):
    """Accumulated consumption of one metric by one tenant in one period.

    Only *flow* metrics live here — things that happen and accumulate, like
    conversations started or AI replies generated. Stock metrics (how many
    agents exist, how many seats are filled) are deliberately NOT stored: they
    are counted from their own tables at read time.

    That split is the important design decision. A stored stock counter drifts
    the moment a row is removed by any path that forgot to decrement it — a
    cascade delete, a direct SQL fix, tenant offboarding — and the tenant is
    then billed for agents they no longer have, or blocked from creating one
    they are entitled to. A COUNT(*) cannot drift.
    """

    __tablename__ = "usage_counters"

    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # 'YYYY-MM'. A string, not a date: it is a bucket label, and storing a date
    # invites someone to compare it with a range and silently split a month.
    period = Column(String(7), primary_key=True)
    metric = Column(String(32), primary_key=True)

    # BigInteger: token counts on a busy tenant pass 2^31 within a year, and an
    # overflow here would be a silent wrap to a negative balance.
    value = Column(BigInteger, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())

    __table_args__ = (
        # Serves the dashboard read ("everything for this tenant this period")
        # without touching the metric component of the primary key.
        Index("ix_usage_counters_org_period", "organization_id", "period"),
    )

    def __repr__(self) -> str:
        return (
            f"<UsageCounter org={self.organization_id} {self.period} "
            f"{self.metric}={self.value}>"
        )
