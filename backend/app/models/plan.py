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

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Numeric, func
from sqlalchemy.orm import relationship

from app.database import Base


class Plan(Base):
    """A sellable tier: what a tenant may consume before being asked to upgrade.

    Limits are explicit columns rather than a JSON blob. A blob is more flexible,
    but the quota service would then look limits up by string key, and a typo or
    a renamed key would read as "no limit configured" — silently unlimited. A
    missing column is a loud error; a missing dict key is an open door.

    Naming avoids `subscription`: the enterprise submodule attaches its own
    Subscription relationship to Organization at mapper-configuration time, and
    reusing that name would collide the moment the module is present.
    """

    __tablename__ = "plans"

    # Stable identifier used in code and stored on the organization. Not the
    # display name, which is marketing copy and will change.
    code = Column(String(32), primary_key=True)
    name = Column(String(64), nullable=False)
    description = Column(String(255), nullable=True)

    # Minor units (cents) rather than a float. Currency arithmetic in binary
    # floating point accumulates error, and this value feeds invoices.
    price_cents = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="USD")

    # NULL means unlimited throughout. Zero means "none allowed" and is a
    # genuinely different statement — a plan with max_agents=0 is a plan that
    # cannot create agents, which is not the same as one with no ceiling.
    max_conversations_per_month = Column(Integer, nullable=True)
    max_ai_messages_per_month = Column(Integer, nullable=True)
    max_agents = Column(Integer, nullable=True)
    max_seats = Column(Integer, nullable=True)
    max_knowledge_docs = Column(Integer, nullable=True)
    max_storage_mb = Column(Integer, nullable=True)

    # Display order in the pricing table; keeps presentation out of the code.
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    is_default = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organizations = relationship("Organization", back_populates="plan")

    # Metric key -> limit column. The single place the two vocabularies meet, so
    # a new metric cannot be metered without also declaring how it is capped.
    LIMIT_COLUMNS = {
        "conversations": "max_conversations_per_month",
        "ai_messages": "max_ai_messages_per_month",
        "agents": "max_agents",
        "seats": "max_seats",
        "knowledge_docs": "max_knowledge_docs",
        "storage_mb": "max_storage_mb",
    }

    def limit_for(self, metric: str):
        """The ceiling for `metric`, or None for unlimited.

        Raises on an unknown metric rather than returning None: "unknown metric"
        and "no limit" must not collapse into the same answer, or a typo at a
        call site turns into an unmetered resource.
        """
        try:
            return getattr(self, self.LIMIT_COLUMNS[metric])
        except KeyError:
            raise ValueError(f"Unknown usage metric: {metric!r}")

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "price_cents": self.price_cents,
            "currency": self.currency,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "is_default": self.is_default,
            "limits": {
                metric: getattr(self, column)
                for metric, column in self.LIMIT_COLUMNS.items()
            },
        }
