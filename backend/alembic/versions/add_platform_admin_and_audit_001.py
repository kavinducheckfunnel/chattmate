"""add platform admin flag and platform audit log

Revision ID: add_platform_admin_001
Revises: add_plans_usage_001
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_platform_admin_001'
down_revision = 'add_plans_usage_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defaults to false for everyone, including every existing admin. Platform
    # access is granted deliberately, one account at a time, by someone with
    # shell access to the server — never by a migration and never over HTTP.
    op.add_column(
        'users',
        sa.Column('is_platform_admin', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
    )
    # Partial index: the console's "who are the operators" query hits the tiny
    # true-set, and Postgres never scans the millions of ordinary users.
    op.create_index(
        'ix_users_platform_admin', 'users', ['is_platform_admin'],
        postgresql_where=sa.text('is_platform_admin'),
    )

    op.create_table(
        'platform_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('actor_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('actor_email', sa.String(length=255), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('target_organization_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('target_organization_domain', sa.String(length=100), nullable=True),
        sa.Column('details', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        # Both SET NULL rather than CASCADE. Deleting a tenant is the single
        # most consequential action an operator can take, and CASCADE would
        # delete the record of it together with the tenant.
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['target_organization_id'], ['organizations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_platform_audit_log_created_at', 'platform_audit_log', ['created_at'])
    op.create_index(
        'ix_platform_audit_target_created', 'platform_audit_log',
        ['target_organization_id', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_platform_audit_target_created', table_name='platform_audit_log')
    op.drop_index('ix_platform_audit_log_created_at', table_name='platform_audit_log')
    op.drop_table('platform_audit_log')
    op.drop_index('ix_users_platform_admin', table_name='users')
    op.drop_column('users', 'is_platform_admin')
