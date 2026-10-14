from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Table, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

STAGES = ("idea", "working", "mixing", "mastering", "done")


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


project_collections = Table(
    "project_collections", Base.metadata,
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("collection_id", ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
)


class Collection(Base):
    __tablename__ = "collections"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    normalized_name: Mapped[str] = mapped_column(String(80), unique=True)
    projects: Mapped[list["Project"]] = relationship(secondary=project_collections, back_populates="collections")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('idea','working','mixing','mastering','done')"),
        CheckConstraint("bpm IS NULL OR bpm > 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    musical_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idea")
    notes: Mapped[str] = mapped_column(Text, default="")
    folder_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    daw_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_auto: Mapped[bool] = mapped_column(Boolean, default=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    folder_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    folder_file_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    folder_scanned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    folder_scan_partial: Mapped[bool] = mapped_column(Boolean, default=False)
    folder_unavailable: Mapped[bool] = mapped_column(Boolean, default=False)
    last_worked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    file_history_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Task.position")
    collections: Mapped[list[Collection]] = relationship(secondary=project_collections, back_populates="projects", order_by="Collection.name")
    events: Mapped[list["ActivityEvent"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (CheckConstraint("position >= 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer)
    project: Mapped[Project] = relationship(back_populates="tasks")


EVENT_KINDS = ("project_created", "project_updated", "status_changed", "archived", "restored", "task_added", "task_completed", "task_reopened", "task_updated", "task_deleted", "tasks_reordered", "daw_saved", "demo_updated", "manual")


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (CheckConstraint("duration_minutes IS NULL OR (duration_minutes > 0 AND duration_minutes <= 1440)"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    kind: Mapped[str] = mapped_column(String(30))
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project: Mapped[Project] = relationship(back_populates="events")
