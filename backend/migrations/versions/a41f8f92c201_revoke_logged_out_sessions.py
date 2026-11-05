"""Persist logged-out session revocations across API restarts."""

from alembic import op
import sqlalchemy as sa

revision = "a41f8f92c201"
down_revision = "c47388911dd6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "revoked_sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        "ix_revoked_sessions_expires_at", "revoked_sessions", ["expires_at"]
    )


def downgrade():
    op.drop_index("ix_revoked_sessions_expires_at", table_name="revoked_sessions")
    op.drop_table("revoked_sessions")
