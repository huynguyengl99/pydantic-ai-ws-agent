from datetime import UTC, datetime

import aiosqlite
from pydantic import BaseModel, TypeAdapter

from app.config import settings

DB_PATH = settings.db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    history TEXT NOT NULL,
    title TEXT,
    suggestions TEXT,
    updated_at TEXT NOT NULL
);
"""

_SUGGESTIONS = TypeAdapter(list[str])


class TaskItem(BaseModel):
    id: int
    title: str
    done: bool


class ConversationItem(BaseModel):
    id: str
    title: str
    updated_at: str


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript(SCHEMA)
        # CREATE TABLE IF NOT EXISTS never alters an existing table: add nullable
        # columns introduced after a database was created. (Breaking changes like
        # NOT NULL columns still require deleting the dev database — see README.)
        rows = await conn.execute_fetchall("PRAGMA table_info(conversations)")
        existing = {row[1] for row in rows}
        for column in ("title", "suggestions"):
            if column not in existing:
                await conn.execute(
                    f"ALTER TABLE conversations ADD COLUMN {column} TEXT"
                )
        await conn.commit()


async def list_tasks(conversation_id: str) -> list[TaskItem]:
    async with aiosqlite.connect(DB_PATH) as conn:
        rows = await conn.execute_fetchall(
            "SELECT id, title, done FROM tasks WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        )
    return [TaskItem(id=r[0], title=r[1], done=bool(r[2])) for r in rows]


async def add_task(conversation_id: str, title: str) -> TaskItem:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "INSERT INTO tasks (conversation_id, title) VALUES (?, ?)",
            (conversation_id, title),
        )
        await conn.commit()
        assert cursor.lastrowid is not None
        return TaskItem(id=cursor.lastrowid, title=title, done=False)


async def complete_task(conversation_id: str, task_id: int) -> TaskItem | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE tasks SET done = 1 WHERE id = ? AND conversation_id = ?",
            (task_id, conversation_id),
        )
        await conn.commit()
        rows = await conn.execute_fetchall(
            "SELECT id, title, done FROM tasks WHERE id = ? AND conversation_id = ?",
            (task_id, conversation_id),
        )
    row = next(iter(rows), None)
    return TaskItem(id=row[0], title=row[1], done=bool(row[2])) if row else None


async def delete_task(conversation_id: str, task_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "DELETE FROM tasks WHERE id = ? AND conversation_id = ?",
            (task_id, conversation_id),
        )
        await conn.commit()
        return cursor.rowcount > 0


async def clear_tasks(conversation_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "DELETE FROM tasks WHERE conversation_id = ?", (conversation_id,)
        )
        await conn.commit()
        return cursor.rowcount


async def load_history(conversation_id: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        rows = await conn.execute_fetchall(
            "SELECT history FROM conversations WHERE id = ?", (conversation_id,)
        )
    row = next(iter(rows), None)
    return row[0] if row else None


async def save_history(
    conversation_id: str, history_json: str, title: str | None = None
) -> None:
    updated_at = datetime.now(UTC).isoformat()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO conversations (id, history, title, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "history = excluded.history, "
            "updated_at = excluded.updated_at, "
            "title = COALESCE(conversations.title, excluded.title)",
            (conversation_id, history_json, title, updated_at),
        )
        await conn.commit()


async def set_title(conversation_id: str, title: str | None) -> None:
    """Name a conversation from its first prompt, once."""
    if not title:
        return
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ? AND title IS NULL",
            (title, conversation_id),
        )
        await conn.commit()


async def load_suggestions(conversation_id: str) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as conn:
        rows = await conn.execute_fetchall(
            "SELECT suggestions FROM conversations WHERE id = ?", (conversation_id,)
        )
    row = next(iter(rows), None)
    return _SUGGESTIONS.validate_json(row[0]) if row and row[0] else []


async def save_suggestions(conversation_id: str, follow_ups: list[str]) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE conversations SET suggestions = ? WHERE id = ?",
            (_SUGGESTIONS.dump_json(follow_ups).decode(), conversation_id),
        )
        await conn.commit()


async def list_conversations() -> list[ConversationItem]:
    async with aiosqlite.connect(DB_PATH) as conn:
        rows = await conn.execute_fetchall(
            "SELECT id, COALESCE(title, ''), updated_at FROM conversations "
            "ORDER BY updated_at DESC"
        )
    return [ConversationItem(id=r[0], title=r[1], updated_at=r[2]) for r in rows]


async def delete_conversation(conversation_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "DELETE FROM tasks WHERE conversation_id = ?", (conversation_id,)
        )
        cursor = await conn.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
        await conn.commit()
        return cursor.rowcount > 0
