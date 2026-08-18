"""add plan features, per-tenant overrides, and platform metric snapshots

Revision ID: add_plan_features_001
Revises: add_platform_admin_001
Create Date: 2026-08-14

Seeds the feature matrix from the plans that already exist rather than leaving
it empty. An empty matrix reads as "no plan includes anything", and the gate
would lock every tenant out of everything the moment this deploys. The seed
mirrors the tiering the plan limits already imply: the cheapest plan gets the
core set, and each step up adds the tier above it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_plan_features_001'
down_revision = 'add_platform_admin_001'
branch_labels = None
depends_on = None


# Feature -> minimum tier that includes it, where tier is the plan's rank when
# plans are ordered by price. Kept here rather than imported from the model so
# a later edit to the catalog cannot silently rewrite what this migration did.
TIERS = {
    # Everything a tenant needs for the product to work at all. Chat, agents
    # and the widget are not listed because they are not gated — a plan that
    # could switch off chat would not be a plan, it would be a suspension.
    # custom_models is base-tier, not premium. There is no shared platform
    # model here, so a plan without it cannot configure any AI at all and its
    # agents can never answer — that is a broken plan, not a cheap one.
    0: ['knowledge_base', 'custom_models'],
    1: ['analytics', 'roles_permissions', 'user_groups', 'help_center'],
    2: [
        'workflow', 'lead_capture', 'mcp_tools',
        'ai_ticketing', 'crm_sync', 'jira',
    ],
}


def upgrade() -> None:
    op.create_table(
        'plan_features',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('plan_code', sa.String(length=32), nullable=False),
        sa.Column('feature_key', sa.String(length=64), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['plan_code'], ['plans.code'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plan_code', 'feature_key', name='uq_plan_feature'),
    )
    op.create_index('ix_plan_features_plan_code', 'plan_features', ['plan_code'])
    op.create_index('ix_plan_features_feature_key', 'plan_features', ['feature_key'])

    op.create_table(
        'organization_feature_overrides',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('feature_key', sa.String(length=64), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('created_by_email', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'feature_key', name='uq_org_feature_override'),
    )
    op.create_index(
        'ix_org_feature_overrides_org', 'organization_feature_overrides', ['organization_id'],
    )
    op.create_index(
        'ix_org_feature_overrides_key', 'organization_feature_overrides', ['feature_key'],
    )

    op.create_table(
        'platform_metrics',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('metric', sa.String(length=32), nullable=False),
        sa.Column('value', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('period', 'metric', name='uq_platform_metric_period'),
    )
    op.create_index('ix_platform_metrics_period', 'platform_metrics', ['period'])
    op.create_index('ix_platform_metrics_metric', 'platform_metrics', ['metric'])

    _seed_features()


def _seed_features() -> None:
    """Give every existing plan the features its price implies.

    Ranking by price rather than by a hard-coded list of codes: this repository
    is deployed by others who will have renamed or replaced the seeded plans,
    and a migration that keys off 'free'/'starter'/'pro' would seed nothing for
    them and leave their customers with no features at all.
    """
    conn = op.get_bind()
    plans = conn.execute(
        sa.text("SELECT code FROM plans ORDER BY price_cents ASC, sort_order ASC")
    ).fetchall()
    if not plans:
        return

    for index, (code,) in enumerate(plans):
        # The top plan gets everything, even if there are more tiers than plans.
        rank = min(index, max(TIERS)) if index < len(plans) - 1 else max(TIERS)
        granted = [key for tier, keys in TIERS.items() if tier <= rank for key in keys]
        for key in granted:
            conn.execute(
                sa.text(
                    "INSERT INTO plan_features (id, plan_code, feature_key, is_enabled) "
                    "VALUES (gen_random_uuid(), :code, :key, true) "
                    "ON CONFLICT (plan_code, feature_key) DO NOTHING"
                ),
                {"code": code, "key": key},
            )


def downgrade() -> None:
    op.drop_index('ix_platform_metrics_metric', table_name='platform_metrics')
    op.drop_index('ix_platform_metrics_period', table_name='platform_metrics')
    op.drop_table('platform_metrics')
    op.drop_index('ix_org_feature_overrides_key', table_name='organization_feature_overrides')
    op.drop_index('ix_org_feature_overrides_org', table_name='organization_feature_overrides')
    op.drop_table('organization_feature_overrides')
    op.drop_index('ix_plan_features_feature_key', table_name='plan_features')
    op.drop_index('ix_plan_features_plan_code', table_name='plan_features')
    op.drop_table('plan_features')
