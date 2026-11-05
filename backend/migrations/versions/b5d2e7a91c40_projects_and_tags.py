"""Add projects and document tags."""

from alembic import op
import sqlalchemy as sa

revision = "b5d2e7a91c40"
down_revision = "a41f8f92c201"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(40), nullable=False, unique=True),
    )
    op.create_table(
        "document_tags",
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_documents_project_id",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_documents_project_id", ["project_id"])
    op.create_index("ix_audit_history_action", "audit_history", ["action"])


def downgrade():
    op.drop_index("ix_audit_history_action", table_name="audit_history")
    with op.batch_alter_table("documents") as batch:
        batch.drop_index("ix_documents_project_id")
        batch.drop_constraint("fk_documents_project_id", type_="foreignkey")
        batch.drop_column("project_id")
    op.drop_table("document_tags")
    op.drop_table("tags")
    op.drop_table("projects")
