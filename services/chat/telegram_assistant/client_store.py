from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ClientStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    chat_id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    consent_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS case_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    message_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS handoffs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id INTEGER NOT NULL,
                    chat_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id INTEGER,
                    chat_id TEXT NOT NULL,
                    stored_path TEXT,
                    original_name TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def ensure_user(self, chat_id: str, actor_id: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users(chat_id, actor_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET actor_id=excluded.actor_id, updated_at=excluded.updated_at
                """,
                (chat_id, actor_id, now, now),
            )

    def accept_consent(self, chat_id: str, actor_id: str) -> None:
        self.ensure_user(chat_id, actor_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET consent_at=?, updated_at=? WHERE chat_id=?",
                (utc_now(), utc_now(), chat_id),
            )

    def has_consent(self, chat_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT consent_at FROM users WHERE chat_id=?", (chat_id,)).fetchone()
        return bool(row and row["consent_at"])

    def create_case(self, chat_id: str, text: str) -> int:
        now = utc_now()
        title = " ".join(text.split())[:80] or "Новое обращение"
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO cases(chat_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (chat_id, title, now, now),
            )
            return int(cursor.lastrowid)

    def current_case(self, chat_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM cases WHERE chat_id=? AND status='active' ORDER BY updated_at DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_cases(self, chat_id: str, limit: int = 10) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM cases WHERE chat_id=? ORDER BY updated_at DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def append_message(self, case_id: int, role: str, content: str, message_id: str = "") -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO case_messages(case_id, role, content, message_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (case_id, role, content[:12000], message_id, utc_now()),
            )
            connection.execute("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(), case_id))

    def case_messages(self, case_id: int, limit: int = 20) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, created_at FROM case_messages
                WHERE case_id=? ORDER BY id DESC LIMIT ?
                """,
                (case_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def create_handoff(self, chat_id: str, case_id: int, summary: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO handoffs(case_id, chat_id, summary, created_at) VALUES (?, ?, ?, ?)",
                (case_id, chat_id, summary[:12000], utc_now()),
            )
            return int(cursor.lastrowid)

    def latest_handoff(self, chat_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM handoffs WHERE chat_id=? ORDER BY id DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_handoff_status(self, handoff_id: int, status: str) -> None:
        allowed = {"approved_internal", "rejected", "revision_requested"}
        if status not in allowed:
            raise ValueError(f"Unsupported handoff status: {status}")
        with self._connect() as connection:
            connection.execute("UPDATE handoffs SET status=? WHERE id=?", (status, handoff_id))

    def add_document(
        self,
        chat_id: str,
        case_id: int | None,
        status: str,
        stored_path: str = "",
        original_name: str = "",
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO documents(case_id, chat_id, stored_path, original_name, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (case_id, chat_id, stored_path, original_name, status, utc_now()),
            )
            return int(cursor.lastrowid)

    def profile(self, chat_id: str) -> dict:
        with self._connect() as connection:
            cases = connection.execute("SELECT COUNT(*) FROM cases WHERE chat_id=?", (chat_id,)).fetchone()[0]
            handoffs = connection.execute("SELECT COUNT(*) FROM handoffs WHERE chat_id=?", (chat_id,)).fetchone()[0]
            documents = connection.execute("SELECT COUNT(*) FROM documents WHERE chat_id=?", (chat_id,)).fetchone()[0]
        return {"cases": cases, "handoffs": handoffs, "documents": documents}
