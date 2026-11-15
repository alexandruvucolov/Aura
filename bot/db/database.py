"""SQLite schema and async CRUD helpers for Aura."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages (user_id, id);

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    last_interaction TEXT,
    checkin_cooldown_until TEXT,
    messages_since_extraction INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_user_id ON facts (user_id);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Async SQLite access layer holding a single :class:`aiosqlite.Connection`."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected. Call connect() first.")
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ── messages ────────────────────────────────────────────────────────
    async def add_message(
        self, user_id: int, role: str, content: str, created_at: str | None = None
    ) -> None:
        await self.conn.execute(
            "INSERT INTO messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (user_id, role, content, created_at or utc_now_iso()),
        )
        await self.conn.commit()

    async def record_user_message(
        self, user_id: int, content: str, created_at: str | None = None
    ) -> None:
        """Store an inbound message and bump the fact-extraction counter."""
        await self.add_message(user_id, "user", content, created_at)
        await self.conn.execute(
            "INSERT INTO users (user_id, messages_since_extraction) VALUES (?, 1) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "messages_since_extraction = messages_since_extraction + 1",
            (user_id,),
        )
        await self.conn.commit()

    async def get_recent_messages(self, user_id: int, limit: int = 30) -> list[dict]:
        cursor = await self.conn.execute(
            "SELECT id, user_id, role, content, created_at FROM messages "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(row) for row in reversed(rows)]

    async def clear_messages(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        await self.conn.commit()

    # ── user state ──────────────────────────────────────────────────────
    async def ensure_user(self, user_id: int) -> None:
        await self.conn.execute(
            "INSERT INTO users (user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING",
            (user_id,),
        )
        await self.conn.commit()

    async def get_user(self, user_id: int) -> dict | None:
        cursor = await self.conn.execute(
            "SELECT user_id, last_interaction, checkin_cooldown_until, "
            "messages_since_extraction FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row else None

    async def set_last_interaction(self, user_id: int, timestamp: str | None = None) -> None:
        timestamp = timestamp or utc_now_iso()
        await self.conn.execute(
            "INSERT INTO users (user_id, last_interaction) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_interaction = excluded.last_interaction",
            (user_id, timestamp),
        )
        await self.conn.commit()

    async def set_checkin_cooldown_until(self, user_id: int, timestamp: str) -> None:
        await self.conn.execute(
            "INSERT INTO users (user_id, checkin_cooldown_until) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "checkin_cooldown_until = excluded.checkin_cooldown_until",
            (user_id, timestamp),
        )
        await self.conn.commit()

    async def reset_extraction_counter(self, user_id: int) -> None:
        await self.conn.execute(
            "UPDATE users SET messages_since_extraction = 0 WHERE user_id = ?", (user_id,)
        )
        await self.conn.commit()

    async def get_all_user_ids(self) -> list[int]:
        cursor = await self.conn.execute("SELECT user_id FROM users")
        rows = await cursor.fetchall()
        await cursor.close()
        return [row["user_id"] for row in rows]

    # ── long-term facts ─────────────────────────────────────────────────
    async def add_fact(self, user_id: int, content: str, created_at: str | None = None) -> None:
        await self.conn.execute(
            "INSERT INTO facts (user_id, content, created_at) VALUES (?, ?, ?)",
            (user_id, content, created_at or utc_now_iso()),
        )
        await self.conn.commit()

    async def get_facts(self, user_id: int) -> list[dict]:
        cursor = await self.conn.execute(
            "SELECT id, user_id, content, created_at FROM facts "
            "WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(row) for row in rows]

    async def delete_fact(self, user_id: int, fact_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM facts WHERE user_id = ? AND id = ?", (user_id, fact_id)
        )
        await self.conn.commit()
