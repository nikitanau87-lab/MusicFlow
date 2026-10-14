"""Activity is recorded in the same transaction as the change it describes."""
from datetime import timezone
from sqlalchemy.orm import object_session
from .models import ActivityEvent, now

STAGE_LABELS = {"idea": "Идея", "working": "В работе", "mixing": "Сведение", "mastering": "Мастеринг", "done": "Завершён"}
FIELD_LABELS = {"title": "Название", "bpm": "BPM", "musical_key": "Тональность", "genre": "Жанр", "notes": "Заметки", "folder_path": "Папка", "daw_path": "Файл DAW", "preview_path": "Демка", "preview_auto": "Автопоиск демки", "tags": "Теги", "collections": "Подборки"}


def utc_naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def record(project, kind, summary, details=None, occurred_at=None, duration=None):
    event = ActivityEvent(project=project, kind=kind, summary=summary, details=details or {}, occurred_at=occurred_at or now(), duration_minutes=duration)
    session = object_session(project)
    if session is not None:
        # Adding an event must not load the project's entire existing journal.
        session.add(event)
    return event
