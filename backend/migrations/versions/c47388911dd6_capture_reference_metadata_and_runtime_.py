"""Capture reference metadata and runtime configuration."""

from alembic import op
import sqlalchemy as sa

revision = "c47388911dd6"
down_revision = "88c28e3d3768"
branch_labels = None
depends_on = None


def upgrade():
    # Batch mode supports populated SQLite catalogs and PostgreSQL.
    with op.batch_alter_table("materials") as batch:
        batch.add_column(
            sa.Column("description", sa.Text(), server_default="", nullable=False)
        )
        batch.add_column(
            sa.Column("manufacturer", sa.String(255), server_default="", nullable=False)
        )
        batch.add_column(
            sa.Column(
                "last_updated",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            )
        )
    op.add_column(
        "processing_jobs",
        sa.Column("runtime_config", sa.Text(), server_default="{}", nullable=False),
    )


def downgrade():
    op.drop_column("processing_jobs", "runtime_config")
    with op.batch_alter_table("materials") as batch:
        batch.drop_column("last_updated")
        batch.drop_column("manufacturer")
        batch.drop_column("description")
