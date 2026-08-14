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

Which capabilities a plan includes, and the per-tenant exceptions to that.

Two tables rather than a JSON column on `plans`:

  * `plan_features` is one row per (plan, feature), so "which plans include
    workflows" is an index scan rather than a table scan with a JSON predicate,
    and a feature can be added to a plan without rewriting a document.

  * `organization_feature_overrides` records only the differences from the
    plan. Copying the whole matrix onto each tenant would freeze them at
    signup: raising a plan's entitlements later would reach nobody. Storing
    just the exceptions means a plan change flows to every tenant that has not
    been deliberately excepted.

The catalog below is the closed set of gateable capabilities. It is
deliberately short: a toggle that no code consults is worse than no toggle,
because it tells an operator they have changed something when they have not.
Every key here is checked by a real call site — `enforced_at` names it, and the
console shows that text so the entry cannot quietly become decorative.
"""

import enum
import uuid

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class FeatureCategory(str, enum.Enum):
    CORE = "Core"
    CHANNELS = "Channels"
    INSIGHTS = "Insights"
    WORKSPACE = "Workspace"
    AUTOMATION = "AI & automation"
    SUPPORT = "Support"


class FeatureDef:
    """One capability. Static metadata — not a table.

    The catalog is code, not data, because each entry is only meaningful
    alongside the call site that enforces it. A row an operator could insert
    would have no enforcement behind it.
    """

    __slots__ = ("key", "label", "category", "description", "enforced_at")

    def __init__(self, key: str, label: str, category: FeatureCategory,
                 description: str, enforced_at: str):
        self.key = key
        self.label = label
        self.category = category
        self.description = description
        self.enforced_at = enforced_at

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category.value,
            "description": self.description,
            "enforced_at": self.enforced_at,
        }


FEATURE_CATALOG: tuple[FeatureDef, ...] = (
    FeatureDef(
        "knowledge_base", "Knowledge base", FeatureCategory.CORE,
        "Upload documents and crawl sites for the agent to answer from.",
        "POST /knowledge/upload, /knowledge/crawl",
    ),
    FeatureDef(
        "analytics", "Analytics", FeatureCategory.INSIGHTS,
        "Conversation volume, resolution rate and agent performance reports.",
        "GET /analytics/*",
    ),
    FeatureDef(
        "roles_permissions", "Roles & permissions", FeatureCategory.WORKSPACE,
        "Create custom roles instead of using the built-in ones.",
        "POST /roles",
    ),
    FeatureDef(
        "user_groups", "Team groups", FeatureCategory.WORKSPACE,
        "Group agents for routing and reporting.",
        "POST /user-groups",
    ),
    FeatureDef(
        "workflow", "Workflow builder", FeatureCategory.AUTOMATION,
        "Design branching conversation flows instead of a single prompt.",
        "POST /workflow",
    ),
    FeatureDef(
        "custom_models", "Bring your own model", FeatureCategory.AUTOMATION,
        "Use the customer's own AI provider and API key instead of the platform's.",
        "POST /ai/setup",
    ),
    FeatureDef(
        "lead_capture", "Lead capture", FeatureCategory.AUTOMATION,
        "Collect contact details mid-conversation and push them onward.",
        "POST /lead-capture/*",
    ),
    FeatureDef(
        "mcp_tools", "MCP tools", FeatureCategory.AUTOMATION,
        "Let the agent call external tools over the Model Context Protocol.",
        "POST /mcp-tools",
    ),
    FeatureDef(
        "ai_ticketing", "AI ticketing", FeatureCategory.SUPPORT,
        "Turn unresolved conversations into tracked tickets.",
        "app/services/ticket_access.py",
    ),
    FeatureDef(
        "help_center", "Help centre", FeatureCategory.SUPPORT,
        "Public, searchable article site generated from the knowledge base.",
        "app/services/help_center_access.py",
    ),
    FeatureDef(
        "crm_sync", "CRM sync", FeatureCategory.AUTOMATION,
        "Push captured contacts to HubSpot, Pipedrive or Shopify.",
        "app/services/crm_sync.py",
    ),
    FeatureDef(
        "jira", "Jira integration", FeatureCategory.SUPPORT,
        "Raise and link Jira issues from a conversation.",
        "POST /jira/*",
    ),
)

FEATURE_KEYS = frozenset(f.key for f in FEATURE_CATALOG)
FEATURES_BY_KEY = {f.key: f for f in FEATURE_CATALOG}


class PlanFeature(Base):
    """A capability included in a plan.

    Presence alone is not enough — `is_enabled` exists so an operator can turn
    something off without losing the row, which keeps the console's matrix
    stable instead of making rows appear and vanish as they are toggled.
    """

    __tablename__ = "plan_features"
    __table_args__ = (UniqueConstraint("plan_code", "feature_key", name="uq_plan_feature"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # CASCADE: a deleted plan's entitlements are meaningless, and leaving them
    # behind would silently re-apply if the code were ever reused.
    plan_code = Column(
        String(32), ForeignKey("plans.code", ondelete="CASCADE"), nullable=False, index=True,
    )
    feature_key = Column(String(64), nullable=False, index=True)
    is_enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class OrganizationFeatureOverride(Base):
    """One tenant's deviation from their plan.

    Exists for the two support realities a pure plan model cannot express: a
    customer promised something outside their tier during a sale, and a
    customer who must lose one capability without being moved off their plan.
    """

    __tablename__ = "organization_feature_overrides"
    __table_args__ = (
        UniqueConstraint("organization_id", "feature_key", name="uq_org_feature_override"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    feature_key = Column(String(64), nullable=False, index=True)
    is_enabled = Column(Boolean, nullable=False)

    # Why the exception was made. An override with no reason becomes folklore
    # within a month — nobody remembers whether it can be removed.
    reason = Column(String(255), nullable=True)
    created_by_email = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "feature_key": self.feature_key,
            "is_enabled": self.is_enabled,
            "reason": self.reason,
            "created_by_email": self.created_by_email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
