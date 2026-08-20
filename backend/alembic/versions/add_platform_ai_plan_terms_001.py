"""Platform-owned AI credentials, the plan terms the console edits, and the
snapshots that let an operator change a plan without re-pricing existing tenants.

Revision ID: add_platform_ai_plan_terms_001
Revises: add_user_delete_cascades_001
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_platform_ai_plan_terms_001'
down_revision = 'add_user_delete_cascades_001'
branch_labels = None
depends_on = None


# Seeded so the three tiers in the console are not blank on first load. These
# mirror the published pricing table; the operator can edit every one of them.
PLAN_TERMS = {
    'free': {
        # 0, not NULL. NULL means unlimited everywhere else in this schema, so
        # leaving it null would have given the free tier unlimited image analysis
        # — the opposite of the "No image analysis" the pricing page advertises.
        'max_image_requests_per_month': 0,
        'max_subpages_per_source': 10,
        'overage_price_cents_per_message': None,   # not offered: blocked at limit
        'data_retention_days': 30,
    },
    # Both names are seeded because the tier between free and pro is called
    # `base` in some deployments and `starter` in others; the UPDATE simply
    # matches nothing for whichever is absent.
    'base': {
        'max_image_requests_per_month': 200,
        'max_subpages_per_source': 30,
        'overage_price_cents_per_message': 1,
        'data_retention_days': 60,
    },
    'starter': {
        'max_image_requests_per_month': 200,
        'max_subpages_per_source': 30,
        'overage_price_cents_per_message': 1,
        'data_retention_days': 60,
    },
    'pro': {
        'max_image_requests_per_month': 400,
        'max_subpages_per_source': 50,
        'overage_price_cents_per_message': 1,
        'data_retention_days': 90,
    },
    # The top tier sells unlimited messages, so an image ceiling is left null to
    # match rather than inventing a number the pricing page never mentions.
    'scale': {
        'max_image_requests_per_month': None,
        'max_subpages_per_source': 100,
        'overage_price_cents_per_message': 1,
        'data_retention_days': 365,
    },
}


def upgrade() -> None:
    op.add_column('plans', sa.Column('max_image_requests_per_month', sa.Integer(), nullable=True))
    op.add_column('plans', sa.Column('max_subpages_per_source', sa.Integer(), nullable=True))
    op.add_column('plans', sa.Column('overage_price_cents_per_message', sa.Integer(), nullable=True))
    op.add_column('plans', sa.Column('data_retention_days', sa.Integer(), nullable=True))

    # Seed by plan code, and only where the row exists. A deployment may have
    # renamed or removed a tier, and an UPDATE that matches nothing is correct
    # here — unlike an INSERT, which would resurrect a tier the operator deleted.
    for code, terms in PLAN_TERMS.items():
        op.execute(
            sa.text(
                "UPDATE plans SET "
                "max_image_requests_per_month = :img, "
                "max_subpages_per_source = :sub, "
                "overage_price_cents_per_message = :over, "
                "data_retention_days = :ret "
                "WHERE code = :code"
            ).bindparams(
                img=terms['max_image_requests_per_month'],
                sub=terms['max_subpages_per_source'],
                over=terms['overage_price_cents_per_message'],
                ret=terms['data_retention_days'],
                code=code,
            )
        )

    # Marks a tenant config as running on platform credentials. Kept separate
    # from model_type so that column can stay the real provider.
    op.add_column('ai_configs', sa.Column(
        'is_platform_managed', sa.Boolean(), nullable=False,
        server_default=sa.text('false')))

    op.create_table(
        'platform_ai_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('text_provider', sa.String(length=32), nullable=True),
        sa.Column('text_model', sa.String(length=128), nullable=True),
        sa.Column('text_encrypted_api_key', sa.String(), nullable=True),
        sa.Column('image_provider', sa.String(length=32), nullable=True),
        sa.Column('image_model', sa.String(length=128), nullable=True),
        sa.Column('image_encrypted_api_key', sa.String(), nullable=True),
        sa.Column('fallback_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('fallback_provider', sa.String(length=32), nullable=True),
        sa.Column('fallback_model', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'organization_plan_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('plan_code', sa.String(length=32), nullable=False),
        sa.Column('limits', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reason', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        # CASCADE: a snapshot describes terms for an organization and is
        # meaningless once that organization is gone. Deleting a tenant already
        # had to learn this lesson across seven other tables.
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    )
    op.create_index(
        'ix_organization_plan_snapshots_organization_id',
        'organization_plan_snapshots', ['organization_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_organization_plan_snapshots_organization_id',
                  table_name='organization_plan_snapshots')
    op.drop_table('organization_plan_snapshots')
    op.drop_table('platform_ai_config')
    op.drop_column('ai_configs', 'is_platform_managed')
    op.drop_column('plans', 'data_retention_days')
    op.drop_column('plans', 'overage_price_cents_per_message')
    op.drop_column('plans', 'max_subpages_per_source')
    op.drop_column('plans', 'max_image_requests_per_month')
