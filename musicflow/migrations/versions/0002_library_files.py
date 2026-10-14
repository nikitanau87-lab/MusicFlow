"""DAW links, automatic demo previews, file information and collections."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("daw_path", sa.Text(), nullable=True),
        sa.Column("preview_path", sa.Text(), nullable=True),
        sa.Column("preview_auto", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("folder_size_bytes", sa.Integer(), nullable=True),
        sa.Column("folder_file_count", sa.Integer(), nullable=True),
        sa.Column("folder_scanned_at", sa.DateTime(), nullable=True),
        sa.Column("folder_scan_partial", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("folder_unavailable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_worked_at", sa.DateTime(), nullable=True),
    ):
        op.add_column("projects", column)
    op.create_table("collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("normalized_name", sa.String(80), nullable=False, unique=True),
    )
    op.create_table("project_collections",
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade():
    op.drop_table("project_collections")
    op.drop_table("collections")
    with op.batch_alter_table("projects") as batch:
        for name in ("daw_path", "preview_path", "preview_auto", "tags", "folder_size_bytes", "folder_file_count", "folder_scanned_at", "folder_scan_partial", "folder_unavailable", "last_worked_at"):
            batch.drop_column(name)
