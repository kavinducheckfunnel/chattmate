"""add auth_tokens table and user email verification columns

Revision ID: add_auth_tokens_001
Revises: 89a4f4898aa4
Create Date: 2026-08-12

Supports self-serve email verification and public password reset.

On the revision graph: this repository ships 17 unmerged alembic heads, so
`alembic upgrade head` (singular) aborts with "Multiple head revisions are
present". Deployment runs `alembic upgrade heads`. This revision chains from
one existing head rather than merging all of them — the table it adds depends
only on `users`, which every branch already has, so a merge revision would
assert ordering relationships that do not actually exist.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_auth_tokens_001'
down_revision = '89a4f4898aa4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default='true' backfills every pre-existing account as verified.
    # These users predate the feature; flipping them to unverified would nag
    # working accounts — including the four live workspaces — about proving an
    # address they have already been receiving mail at.
    op.add_column(
        'users',
        sa.Column('is_email_verified', sa.Boolean(), nullable=False,
                  server_default=sa.text('true')),
    )
    op.add_column(
        'users',
        sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    )

    token_purpose = postgresql.ENUM(
        'email_verification', 'password_reset',
        name='token_purpose',
        create_type=False,
    )
    # checkfirst matters on re-run: a failed deploy can leave the type behind
    # after the table create rolled back, and CREATE TYPE would then abort the
    # whole migration.
    token_purpose.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'auth_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('purpose', token_purpose, nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()')),
        # ON DELETE CASCADE at the database level, not only via the ORM
        # relationship: tenant offboarding and the token cleanup job both delete
        # without loading the User object, and an orphaned token row would keep
        # a stale credential alive past the account it belonged to.
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_auth_tokens_user_id', 'auth_tokens', ['user_id'])
    op.create_index('ix_auth_tokens_token_hash', 'auth_tokens', ['token_hash'])
    op.create_index(
        'ix_auth_tokens_purpose_hash', 'auth_tokens', ['purpose', 'token_hash']
    )


def downgrade() -> None:
    op.drop_index('ix_auth_tokens_purpose_hash', table_name='auth_tokens')
    op.drop_index('ix_auth_tokens_token_hash', table_name='auth_tokens')
    op.drop_index('ix_auth_tokens_user_id', table_name='auth_tokens')
    op.drop_table('auth_tokens')
    postgresql.ENUM(name='token_purpose').drop(op.get_bind(), checkfirst=True)
    op.drop_column('users', 'email_verified_at')
    op.drop_column('users', 'is_email_verified')
