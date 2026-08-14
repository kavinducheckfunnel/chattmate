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

Month-end snapshots of platform-wide figures.

Revenue history cannot be recomputed from live data. Recurring revenue is
plan price x tenants on that plan, and both sides move: a tenant upgrades, a
plan is repriced, an account is deleted. Recomputing last March from today's
table gives March's revenue at today's prices, which is not what happened.

So the current month is written down as it is observed. Each console read
upserts the running figure for the current period; when the month rolls over
that last value stays put and becomes history. Months before the platform
started recording have no row, and the API reports them as absent rather than
inventing a number — an honest gap in a chart is worth more than a smooth line
that never happened.
"""

from sqlalchemy import BigInteger, Column, DateTime, String, UniqueConstraint, func

from app.database import Base


class PlatformMetric(Base):
    """One recorded value for one metric in one period.

    Integers only, and money in minor units, so a stored figure never carries
    floating-point drift into a revenue chart.
    """

    __tablename__ = "platform_metrics"
    __table_args__ = (UniqueConstraint("period", "metric", name="uq_platform_metric_period"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # "YYYY-MM", matching UsageCounter.period so the two can be joined.
    period = Column(String(7), nullable=False, index=True)
    metric = Column(String(32), nullable=False, index=True)
    value = Column(BigInteger, nullable=False, default=0)

    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# Metric keys. Named constants because these strings appear in the snapshot
# writer and the chart reader, and a typo in either would silently produce an
# empty series rather than an error.
MRR_CENTS = "mrr_cents"
ACTIVE_TENANTS = "active_tenants"
PAYING_TENANTS = "paying_tenants"

SNAPSHOT_METRICS = (MRR_CENTS, ACTIVE_TENANTS, PAYING_TENANTS)
