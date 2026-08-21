"""Platform backup settings and delivery history.

Revision ID: add_platform_backups_001
Revises: add_platform_ai_plan_terms_001
Create Date: 2026-08-21

Chains from add_platform_ai_plan_terms_001 rather than opening a fourth head.
This repo already carries three unmerged branches and deployment runs
`alembic upgrade heads` (plural) to cope; adding another would work, but every
extra head is one more thing that has to be reasoned about at deploy time.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_platform_backups_001'
down_revision = 'add_platform_ai_plan_terms_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'platform_backup_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=128), nullable=True),
        sa.Column('client_id', sa.String(length=128), nullable=True),
        sa.Column('encrypted_client_secret', sa.Text(), nullable=True),
        sa.Column('account_email', sa.String(length=320), nullable=True),
        sa.Column('folder', sa.String(length=512), nullable=False,
                  server_default='/ChatterMate Backups'),
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('schedule_enabled', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('frequency', sa.String(length=16), nullable=False,
                  server_default='daily'),
        sa.Column('weekday', sa.Integer(), nullable=False, server_default='6'),
        sa.Column('day_of_month', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('backup_time', sa.String(length=5), nullable=False,
                  server_default='02:00'),
        sa.Column('schedule_timezone', sa.String(length=64), nullable=False,
                  server_default='UTC'),
        sa.Column('contents', sa.String(length=32), nullable=False,
                  server_default='database_and_files'),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        # One platform, one destination. The check is what makes the singleton
        # real; without it a second row is a bug that only shows up as a
        # schedule that mysteriously stops matching what the console displays.
        sa.CheckConstraint('id = 1', name='ck_platform_backup_settings_singleton'),
    )

    op.create_table(
        'platform_backup_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('method', sa.String(length=16), nullable=False),
        sa.Column('contents', sa.String(length=32), nullable=False),
        sa.Column('destination', sa.String(length=512), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False,
                  server_default='running'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('filename', sa.String(length=512), nullable=True),
        sa.Column('remote_item_id', sa.String(length=256), nullable=True),
        sa.Column('remote_web_url', sa.Text(), nullable=True),
        sa.Column('local_path', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('actor_email', sa.String(length=320), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    # The console reads this table exactly one way: newest first.
    op.create_index('ix_platform_backup_runs_created_at', 'platform_backup_runs',
                    [sa.text('created_at DESC')])


def downgrade() -> None:
    op.drop_index('ix_platform_backup_runs_created_at', table_name='platform_backup_runs')
    op.drop_table('platform_backup_runs')
    op.drop_table('platform_backup_settings')
