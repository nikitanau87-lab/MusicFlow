"""Initial schema for projects and their task checklists."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("musical_key", sa.String(40), nullable=True),
        sa.Column("genre", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("folder_path", sa.Text(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('idea','working','mixing','mastering','done')"),
        sa.CheckConstraint("bpm IS NULL OR bpm > 0"),
    )
    op.create_table("tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0"),
    )
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])


def downgrade():
    op.drop_table("tasks")
    op.drop_table("projects")
