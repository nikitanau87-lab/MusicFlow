"""Project activity journal and persisted file observation baseline."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("file_history_state", sa.JSON(), nullable=True))
    op.create_table("activity_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.CheckConstraint("duration_minutes IS NULL OR (duration_minutes > 0 AND duration_minutes <= 1440)"),
    )
    op.create_index("ix_activity_events_project_id", "activity_events", ["project_id"])
    op.create_index("ix_activity_events_occurred_at", "activity_events", ["occurred_at"])


def downgrade():
    op.drop_table("activity_events")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("file_history_state")
