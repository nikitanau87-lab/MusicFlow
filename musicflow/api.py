import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError

from .database import Database
from .models import ActivityEvent, Collection, Project, Task, now
from .history import FIELD_LABELS, STAGE_LABELS, record, utc_naive
from .files import AUDIO_TYPES, DAW_EXTENSIONS, FolderScanner

Stage = Literal["idea", "working", "mixing", "mastering", "done"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class ProjectCreate(Input):
    title: str = Field(min_length=1, max_length=200)
    bpm: float | None = Field(default=None, gt=0)
    musical_key: str | None = Field(default=None, max_length=40)
    genre: str | None = Field(default=None, max_length=100)
    status: Stage = "idea"
    notes: str = Field(default="", max_length=100000)
    folder_path: str | None = Field(default=None, max_length=4096)
    daw_path: str | None = Field(default=None, max_length=4096)
    preview_path: str | None = Field(default=None, max_length=4096)
    preview_auto: bool = True
    tags: list[str] = Field(default_factory=list, max_length=30)
    collection_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("musical_key", "genre", "folder_path", "daw_path", "preview_path")
    @classmethod
    def empty_to_none(cls, value):
        return value or None

    @field_validator("folder_path", "daw_path", "preview_path")
    @classmethod
    def absolute_path(cls, value):
        if value and (not Path(value).is_absolute() or "\x00" in value):
            raise ValueError("Путь к папке должен быть абсолютным.")
        return value

    @field_validator("daw_path")
    @classmethod
    def daw_extension(cls, value):
        if value and Path(value).suffix.lower() not in DAW_EXTENSIONS:
            raise ValueError("Выберите файл проекта DAW.")
        return value

    @field_validator("preview_path")
    @classmethod
    def audio_extension(cls, value):
        if value and Path(value).suffix.lower() not in AUDIO_TYPES:
            raise ValueError("Выберите аудиофайл WAV, MP3, M4A, AIFF, FLAC или AAC.")
        return value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values):
        result, existing = [], set()
        for value in values:
            tag = " ".join(value.lstrip("#").split())
            if not tag or len(tag) > 48:
                raise ValueError("Длина тега — от 1 до 48 символов.")
            if tag.casefold() not in existing:
                existing.add(tag.casefold())
                result.append(tag)
        return result


class CollectionInput(Input):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        return " ".join(value.split())


class ProjectPatch(ProjectCreate):
    title: str = Field(default="", min_length=1, max_length=200)
    archived: bool = False


class TaskCreate(Input):
    title: str = Field(min_length=1, max_length=300)


class TaskPatch(TaskCreate):
    title: str = Field(default="", min_length=1, max_length=300)
    completed: bool = False


class TaskOrder(Input):
    ids: list[int]


class WorkEntry(Input):
    summary: str = Field(min_length=1, max_length=5000)
    occurred_at: datetime
    duration_minutes: int | None = Field(default=None, gt=0, le=1440, strict=True)

    @field_validator("occurred_at")
    @classmethod
    def actual_date(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Укажите дату с часовым поясом.")
        if value > now():
            raise ValueError("Запись о работе не может относиться к будущему.")
        return utc_naive(value)


def date(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z") + ("Z" if value.tzinfo is None else "")


def serialize(project):
    tasks = [{"id": task.id, "title": task.title, "completed": task.completed, "position": task.position} for task in sorted(project.tasks, key=lambda t: t.position)]
    completed = sum(task["completed"] for task in tasks)
    return {
        "id": project.id, "title": project.title, "bpm": project.bpm,
        "musical_key": project.musical_key, "genre": project.genre,
        "status": project.status, "notes": project.notes, "folder_path": project.folder_path,
        "archived": project.archived, "created_at": date(project.created_at), "updated_at": date(project.updated_at),
        "tasks": tasks, "task_count": len(tasks), "completed_tasks": completed,
        "progress": round(completed / len(tasks) * 100) if tasks else None,
        "daw_path": project.daw_path, "preview_path": project.preview_path, "preview_auto": project.preview_auto,
        "tags": project.tags, "collection_ids": [item.id for item in project.collections],
        "collections": [{"id": item.id, "name": item.name} for item in project.collections],
        "folder_size_bytes": project.folder_size_bytes, "folder_file_count": project.folder_file_count,
        "folder_scanned_at": date(project.folder_scanned_at) if project.folder_scanned_at else None,
        "folder_scan_partial": project.folder_scan_partial, "folder_unavailable": project.folder_unavailable,
        "last_worked_at": date(project.last_worked_at) if project.last_worked_at else None,
    }


def serialize_event(item):
    return {"id": item.id, "kind": item.kind, "summary": item.summary, "details": item.details,
            "occurred_at": date(item.occurred_at), "recorded_at": date(item.recorded_at), "duration_minutes": item.duration_minutes}


def create_app(database: Database, token: str, assets: Path | None = None):
    scanner = FolderScanner(database)
    media_token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(_):
        yield
        scanner.close()

    app = FastAPI(title="MusicFlow", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.scanner = scanner

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, error):
        messages = [str(item.get("ctx", {}).get("error", "")) for item in error.errors()]
        specific = next((message for message in messages if message), None)
        return JSONResponse(status_code=422, content={"detail": specific or "Проверьте поля: название и описание обязательны, BPM и длительность должны быть положительными числами, поля не должны превышать допустимую длину."})

    @app.exception_handler(Exception)
    async def unexpected_error(_, error):
        logging.getLogger("musicflow").exception("API failure", exc_info=error)
        return JSONResponse(status_code=500, content={"detail": "Не удалось сохранить изменения. Повторите попытку."})

    def authorize(request: Request):
        if not secrets.compare_digest(request.headers.get("X-MusicFlow-Token", "").encode(), token.encode()):
            raise HTTPException(403, "Доступ к MusicFlow разрешён только из приложения.")

    def session():
        with database.lock, database.session() as current:
            yield current

    DB = Annotated[Session, Depends(session)]
    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    def get_project(db, identifier):
        project = db.get(Project, identifier)
        if project is None:
            raise HTTPException(404, "Проект не найден.")
        return project

    def get_task(project, identifier):
        for task in project.tasks:
            if task.id == identifier:
                return task
        raise HTTPException(404, "Задача не найдена.")

    def collections_for(db, identifiers):
        unique = list(dict.fromkeys(identifiers))
        items = list(db.scalars(select(Collection).where(Collection.id.in_(unique))))
        if len(items) != len(unique):
            raise HTTPException(422, "Одна из подборок не найдена. Обновите список подборок.")
        return items

    @router.post("/media-session")
    def media_session():
        response = JSONResponse({"ready": True})
        response.set_cookie("musicflow_media", media_token, httponly=True, samesite="strict", path="/api/projects")
        return response

    @app.get("/api/projects/{identifier}/audio", include_in_schema=False)
    def stream_audio(identifier: int, request: Request):
        cookie = request.cookies.get("musicflow_media", "")
        header = request.headers.get("X-MusicFlow-Token", "")
        if not (secrets.compare_digest(cookie.encode(), media_token.encode()) or secrets.compare_digest(header.encode(), token.encode())):
            raise HTTPException(403, "Откройте аудиопревью из MusicFlow.")
        with database.lock, database.session() as db:
            project = get_project(db, identifier)
            path = Path(project.preview_path) if project.preview_path else None
        if path is None or path.suffix.lower() not in AUDIO_TYPES or not path.is_file():
            raise HTTPException(404, "Аудиофайл недоступен. Обновите поиск демки или выберите другой файл.")
        return FileResponse(path, media_type=AUDIO_TYPES[path.suffix.lower()], headers={"Cache-Control": "private, no-store"})

    @router.post("/files/refresh")
    def refresh_files():
        return {"pending": scanner.refresh_all()}

    @router.get("/files/status")
    def files_status():
        return {"pending": scanner.pending()}

    @router.get("/projects/{identifier}/folder-info")
    def folder_info(identifier: int, refresh: bool = False):
        try:
            info = scanner.get(identifier, refresh)
        except KeyError:
            raise HTTPException(404, "Проект не найден.")
        with database.lock, database.session() as db:
            info["project"] = serialize(get_project(db, identifier))
        return info

    @router.get("/projects")
    def list_projects(db: DB, archived: bool = False, search: str = "", status: Stage | None = None, genre: str | None = None, tag: str | None = None, collection_id: int | None = None, sort: Literal["updated", "created", "title", "size", "worked"] = "updated"):
        projects = db.scalars(select(Project).where(Project.archived == archived).options(selectinload(Project.tasks), selectinload(Project.collections))).all()
        projects = [project for project in projects if search.casefold().strip() in project.title.casefold() and (not status or project.status == status) and (not genre or project.genre == genre) and (not tag or tag.casefold() in {item.casefold() for item in project.tags}) and (collection_id is None or any(item.id == collection_id for item in project.collections))]
        key = {"updated": lambda p: (p.updated_at, p.id), "created": lambda p: (p.created_at, p.id), "title": lambda p: (p.title.casefold(), p.id), "size": lambda p: (p.folder_size_bytes if p.folder_size_bytes is not None else -1, p.id), "worked": lambda p: (p.last_worked_at or datetime.min, p.id)}[sort]
        return [serialize(project) for project in sorted(projects, key=key, reverse=sort != "title")]

    @router.get("/overview")
    def overview(db: DB):
        projects = db.scalars(select(Project)).all()
        tags = {}
        for project in projects:
            for tag in project.tags:
                tags.setdefault(tag.casefold(), tag)
        return {"active": sum(not p.archived for p in projects), "archived": sum(p.archived for p in projects), "done": sum(p.status == "done" and not p.archived for p in projects), "genres": sorted({p.genre for p in projects if p.genre}, key=str.casefold), "tags": sorted(tags.values(), key=str.casefold)}

    @router.get("/collections")
    def list_collections(db: DB):
        items = db.scalars(select(Collection).options(selectinload(Collection.projects))).all()
        return [{"id": item.id, "name": item.name, "project_count": sum(not p.archived for p in item.projects)} for item in sorted(items, key=lambda item: item.name.casefold())]

    @router.post("/collections", status_code=201)
    def add_collection(payload: CollectionInput, db: DB):
        item = Collection(name=payload.name, normalized_name=payload.name.casefold())
        db.add(item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Подборка с таким названием уже существует.")
        return {"id": item.id, "name": item.name, "project_count": 0}

    @router.patch("/collections/{identifier}")
    def rename_collection(identifier: int, payload: CollectionInput, db: DB):
        item = db.get(Collection, identifier)
        if item is None:
            raise HTTPException(404, "Подборка не найдена.")
        item.name, item.normalized_name = payload.name, payload.name.casefold()
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Подборка с таким названием уже существует.")
        return {"id": item.id, "name": item.name, "project_count": sum(not p.archived for p in item.projects)}

    @router.delete("/collections/{identifier}", status_code=204)
    def delete_collection(identifier: int, db: DB):
        item = db.get(Collection, identifier)
        if item is None:
            raise HTTPException(404, "Подборка не найдена.")
        db.delete(item)
        db.commit()

    @router.post("/projects", status_code=201)
    def add_project(payload: ProjectCreate, db: DB):
        fields = payload.model_dump()
        identifiers = fields.pop("collection_ids")
        project = Project(**fields, collections=collections_for(db, identifiers))
        db.add(project)
        record(project, "project_created", "Создан проект")
        db.commit()
        return serialize(project)

    @router.get("/projects/{identifier}")
    def read_project(identifier: int, db: DB):
        return serialize(get_project(db, identifier))

    @router.patch("/projects/{identifier}")
    def edit_project(identifier: int, payload: ProjectPatch, db: DB):
        project = get_project(db, identifier)
        fields = payload.model_dump(exclude_unset=True)
        changes = {}
        if "collection_ids" in fields:
            groups = collections_for(db, fields.pop("collection_ids"))
            before = sorted(item.name for item in project.collections)
            after = sorted(item.name for item in groups)
            if before != after:
                changes["collections"] = {"before": before, "after": after}
                project.collections = groups
        fields = {key: value for key, value in fields.items() if getattr(project, key) != value}
        if "folder_path" in fields or "daw_path" in fields:
            project.folder_size_bytes = None
            project.folder_scanned_at = None
            project.last_worked_at = None
            project.folder_unavailable = False
            project.file_history_state = None
        elif "preview_path" in fields or "preview_auto" in fields:
            project.file_history_state = None
        for field, value in fields.items():
            old = getattr(project, field)
            if field == "status":
                record(project, "status_changed", f"Стадия: {STAGE_LABELS[old]} → {STAGE_LABELS[value]}", {"before": old, "after": value})
            elif field == "archived":
                record(project, "archived" if value else "restored", "Проект отправлен в архив" if value else "Проект возвращён из архива")
            else:
                changes[field] = {"before": old[:1000] if isinstance(old, str) else old, "after": value[:1000] if isinstance(value, str) else value}
            setattr(project, field, value)
        if changes:
            record(project, "project_updated", "Изменены: " + ", ".join(FIELD_LABELS[key] for key in changes), {"changes": changes})
        if fields or changes:
            project.updated_at = now()
        db.commit()
        return serialize(project)

    @router.delete("/projects/{identifier}", status_code=204)
    def delete_project(identifier: int, db: DB):
        db.delete(get_project(db, identifier))
        db.commit()

    @router.get("/projects/{identifier}/history")
    def history(identifier: int, since: datetime, until: datetime, db: DB):
        get_project(db, identifier)
        if since.tzinfo is None or until.tzinfo is None:
            raise HTTPException(422, "Укажите часовой пояс периода.")
        start, end = utc_naive(since), utc_naive(until)
        if not 0 < (end - start).total_seconds() <= 32 * 86400:
            raise HTTPException(422, "Выберите период не более 32 дней.")
        items = list(db.scalars(select(ActivityEvent).where(ActivityEvent.project_id == identifier, ActivityEvent.occurred_at >= start, ActivityEvent.occurred_at < end).order_by(ActivityEvent.occurred_at.desc(), ActivityEvent.id.desc()).limit(5001)))
        return {"events": [serialize_event(item) for item in items[:5000]], "truncated": len(items) > 5000}

    @router.post("/projects/{identifier}/history", status_code=201)
    def add_work(identifier: int, payload: WorkEntry, db: DB):
        project = get_project(db, identifier)
        item = record(project, "manual", payload.summary, occurred_at=payload.occurred_at, duration=payload.duration_minutes)
        project.updated_at = now()
        db.commit()
        return serialize_event(item)

    def manual_event(db, identifier, event_id):
        get_project(db, identifier)
        item = db.get(ActivityEvent, event_id)
        if item is None or item.project_id != identifier:
            raise HTTPException(404, "Запись не найдена.")
        if item.kind != "manual":
            raise HTTPException(403, "Автоматические события нельзя редактировать.")
        return item

    @router.put("/projects/{identifier}/history/{event_id}")
    def edit_work(identifier: int, event_id: int, payload: WorkEntry, db: DB):
        item = manual_event(db, identifier, event_id)
        item.summary, item.occurred_at, item.duration_minutes = payload.summary, payload.occurred_at, payload.duration_minutes
        item.project.updated_at = now()
        db.commit()
        return serialize_event(item)

    @router.delete("/projects/{identifier}/history/{event_id}", status_code=204)
    def delete_work(identifier: int, event_id: int, db: DB):
        item = manual_event(db, identifier, event_id)
        item.project.updated_at = now()
        db.delete(item)
        db.commit()

    @router.get("/projects/{identifier}/tasks")
    def list_tasks(identifier: int, db: DB):
        return serialize(get_project(db, identifier))["tasks"]

    @router.post("/projects/{identifier}/tasks", status_code=201)
    def add_task(identifier: int, payload: TaskCreate, db: DB):
        project = get_project(db, identifier)
        project.tasks.append(Task(title=payload.title, position=len(project.tasks)))
        record(project, "task_added", f"Добавлена задача «{payload.title}»")
        project.updated_at = now()
        db.commit()
        return serialize(project)

    @router.post("/projects/{identifier}/tasks/template")
    def template(identifier: int, db: DB):
        project = get_project(db, identifier)
        existing = {task.title.casefold() for task in project.tasks}
        for title in ("Написать бит", "Записать вокал", "Свести трек", "Сделать мастеринг"):
            if title.casefold() not in existing:
                project.tasks.append(Task(title=title, position=len(project.tasks)))
                record(project, "task_added", f"Добавлена задача «{title}»")
        project.updated_at = now()
        db.commit()
        return serialize(project)

    @router.put("/projects/{identifier}/tasks/order")
    def reorder(identifier: int, payload: TaskOrder, db: DB):
        project = get_project(db, identifier)
        if len(payload.ids) != len(project.tasks) or set(payload.ids) != {task.id for task in project.tasks}:
            raise HTTPException(422, "Новый порядок должен содержать каждую задачу ровно один раз.")
        positions = {task_id: position for position, task_id in enumerate(payload.ids)}
        if any(task.position != positions[task.id] for task in project.tasks):
            record(project, "tasks_reordered", "Изменён порядок задач")
        for task in project.tasks:
            task.position = positions[task.id]
        project.updated_at = now()
        db.commit()
        return serialize(project)

    @router.patch("/projects/{identifier}/tasks/{task_id}")
    def edit_task(identifier: int, task_id: int, payload: TaskPatch, db: DB):
        project = get_project(db, identifier)
        task = get_task(project, task_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            if getattr(task, field) == value:
                continue
            if field == "completed":
                record(project, "task_completed" if value else "task_reopened", f"{'Выполнена задача' if value else 'Возвращена в работу задача'} «{task.title}»")
            else:
                record(project, "task_updated", f"Переименована задача «{task.title}» → «{value}»")
            setattr(task, field, value)
        project.updated_at = now()
        db.commit()
        return serialize(project)

    @router.delete("/projects/{identifier}/tasks/{task_id}")
    def delete_task(identifier: int, task_id: int, db: DB):
        project = get_project(db, identifier)
        task = get_task(project, task_id)
        record(project, "task_deleted", f"Удалена задача «{task.title}»")
        project.tasks.remove(task)
        for position, task in enumerate(sorted(project.tasks, key=lambda t: t.position)):
            task.position = position
        project.updated_at = now()
        db.commit()
        return serialize(project)

    app.include_router(router)
    if assets is not None:
        app.mount("/", StaticFiles(directory=assets, html=True), name="ui")
    return app
