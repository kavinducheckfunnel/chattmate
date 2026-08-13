"""add plans catalog, org plan assignment and usage counters

Revision ID: add_plans_usage_001
Revises: add_auth_tokens_001
Create Date: 2026-08-13

Chains from the auth-tokens revision rather than opening yet another head;
deployment still runs `alembic upgrade heads` because upstream ships 17.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_plans_usage_001'
down_revision = 'add_auth_tokens_001'
branch_labels = None
depends_on = None


# Seeded here rather than in application startup so the catalog exists before
# the first request. NULL means unlimited; 0 would mean "none allowed", which
# is a different statement and not what any of these intend.
PLANS = [
    # code      name        desc                                    price  conv   msgs   agents seats  docs   storage sort default
    ('free',    'Free',     'Try it out with a single agent.',          0,   100,   500,     1,     2,     10,    100,  10, True),
    ('starter', 'Starter',  'For a small team running live support.', 4900,  2000, 10000,     3,     5,    100,   1000,  20, False),
    ('pro',     'Pro',      'Higher volume and a bigger team.',     14900, 10000, 50000,    10,    20,    500,   5000,  30, False),
    ('scale',   'Scale',    'Unmetered usage for larger businesses.',49900, None,  None,  None,  None,   None,   None,  40, False),
]


def upgrade() -> None:
    op.create_table(
        'plans',
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('price_cents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='USD'),
        sa.Column('max_conversations_per_month', sa.Integer(), nullable=True),
        sa.Column('max_ai_messages_per_month', sa.Integer(), nullable=True),
        sa.Column('max_agents', sa.Integer(), nullable=True),
        sa.Column('max_seats', sa.Integer(), nullable=True),
        sa.Column('max_knowledge_docs', sa.Integer(), nullable=True),
        sa.Column('max_storage_mb', sa.Integer(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('code'),
    )

    plans_table = sa.table(
        'plans',
        *[sa.column(c) for c in (
            'code', 'name', 'description', 'price_cents', 'currency',
            'max_conversations_per_month', 'max_ai_messages_per_month',
            'max_agents', 'max_seats', 'max_knowledge_docs', 'max_storage_mb',
            'sort_order', 'is_default',
        )]
    )
    op.bulk_insert(plans_table, [
        {
            'code': c, 'name': n, 'description': d, 'price_cents': p, 'currency': 'USD',
            'max_conversations_per_month': conv, 'max_ai_messages_per_month': msg,
            'max_agents': ag, 'max_seats': se, 'max_knowledge_docs': kd,
            'max_storage_mb': st, 'sort_order': so, 'is_default': df,
        }
        for (c, n, d, p, conv, msg, ag, se, kd, st, so, df) in PLANS
    ])

    # Exactly one default plan. Nothing in the ORM enforces this and
    # _resolve_plan() takes .first(), so two defaults would mean new tenants
    # land on whichever row Postgres happened to return.
    op.create_index(
        'uq_plans_single_default', 'plans', ['is_default'],
        unique=True, postgresql_where=sa.text('is_default'),
    )

    op.add_column(
        'organizations',
        sa.Column('plan_code', sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        'fk_organizations_plan_code', 'organizations', 'plans',
        ['plan_code'], ['code'], ondelete='RESTRICT',
    )
    op.create_index('ix_organizations_plan_code', 'organizations', ['plan_code'])

    # Existing tenants predate plans. Put them on the free tier explicitly
    # rather than leaving NULL: _resolve_plan falls back to the default anyway,
    # but an explicit value is what the operator console will show and edit.
    op.execute("UPDATE organizations SET plan_code = 'free' WHERE plan_code IS NULL")

    op.create_table(
        'usage_counters',
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('metric', sa.String(length=32), nullable=False),
        sa.Column('value', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        # The composite primary key is what makes ON CONFLICT DO UPDATE work,
        # which is how increments stay atomic under concurrent chat traffic.
        sa.PrimaryKeyConstraint('organization_id', 'period', 'metric'),
    )
    op.create_index(
        'ix_usage_counters_org_period', 'usage_counters',
        ['organization_id', 'period'],
    )


def downgrade() -> None:
    op.drop_index('ix_usage_counters_org_period', table_name='usage_counters')
    op.drop_table('usage_counters')
    op.drop_index('ix_organizations_plan_code', table_name='organizations')
    op.drop_constraint('fk_organizations_plan_code', 'organizations', type_='foreignkey')
    op.drop_column('organizations', 'plan_code')
    op.drop_index('uq_plans_single_default', table_name='plans')
    op.drop_table('plans')
