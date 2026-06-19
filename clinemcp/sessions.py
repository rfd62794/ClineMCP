"""SQLite session persistence layer."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

# SQLite schema from SDD §4.4
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    task         TEXT NOT NULL,
    model        TEXT NOT NULL,
    cwd          TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    exit_code    INTEGER,
    output       TEXT,
    step_id      INTEGER,
    floor_result TEXT,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    completed_at TEXT,
    error        TEXT,
    iterations   INTEGER DEFAULT 0,
    answer       TEXT,
    duration_ms  INTEGER,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0
);
"""

# Valid state transitions and states
VALID_STATES = {"pending", "running", "complete", "failed", "cancelled", "completion_signaled"}


class SessionStore:
    """Async SQLite session store."""

    def __init__(self, db_path: str = "sessions.db") -> None:
        self.db_path = Path(db_path)

    async def init_db(self) -> None:
        """Initialize the database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(CREATE_TABLE_SQL)
            await db.commit()

    async def create_session(
        self,
        session_id: str,
        task: str,
        model: str,
        cwd: str,
    ) -> dict[str, Any]:
        """Create a new pending session."""
        created_at = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO sessions
                (session_id, task, model, cwd, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, task, model, cwd, "pending", created_at),
            )
            await db.commit()
        return {
            "session_id": session_id,
            "task": task,
            "model": model,
            "cwd": cwd,
            "status": "pending",
            "created_at": created_at,
        }

    async def update_session(
        self,
        session_id: str,
        status: str | None = None,
        exit_code: int | None = None,
        output: str | None = None,
        step_id: int | None = None,
        floor_result: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        error: str | None = None,
        iterations: int | None = None,
        answer: str | None = None,
        duration_ms: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> bool:
        """Update session fields. Returns True if session existed."""
        if status and status not in VALID_STATES:
            raise ValueError(f"Invalid status: {status}")

        fields = []
        values = []

        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if exit_code is not None:
            fields.append("exit_code = ?")
            values.append(exit_code)
        if output is not None:
            fields.append("output = ?")
            values.append(output)
        if step_id is not None:
            fields.append("step_id = ?")
            values.append(step_id)
        if floor_result is not None:
            fields.append("floor_result = ?")
            values.append(floor_result)
        if started_at is not None:
            fields.append("started_at = ?")
            values.append(started_at)
        if completed_at is not None:
            fields.append("completed_at = ?")
            values.append(completed_at)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if iterations is not None:
            fields.append("iterations = ?")
            values.append(iterations)
        if answer is not None:
            fields.append("answer = ?")
            values.append(answer)
        if duration_ms is not None:
            fields.append("duration_ms = ?")
            values.append(duration_ms)
        if input_tokens is not None:
            fields.append("input_tokens = ?")
            values.append(input_tokens)
        if output_tokens is not None:
            fields.append("output_tokens = ?")
            values.append(output_tokens)

        if not fields:
            return False

        values.append(session_id)
        sql = f"UPDATE sessions SET {', '.join(fields)} WHERE session_id = ?"

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(sql, values)
            await db.commit()
            return cursor.rowcount > 0

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session by ID. Returns None if not found."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                return dict(row)

    async def get_active_session(self) -> dict[str, Any] | None:
        """Get currently running session, if any."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM sessions WHERE status = ?", ("running",)
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                return dict(row)

    async def mark_running_as_failed_on_startup(self) -> int:
        """Mark any 'running' sessions as failed (ClineMCP restarted)."""
        failed_at = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """UPDATE sessions
                SET status = ?, error = ?, completed_at = ?
                WHERE status = ?""",
                ("failed", "ClineMCP restarted", failed_at, "running"),
            )
            await db.commit()
            return cursor.rowcount

    async def append_output(self, session_id: str, line: str) -> None:
        """Append a single line to the session's output column."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    UPDATE sessions
                    SET output = COALESCE(output, '') || ?
                    WHERE session_id = ?
                    """,
                    (line, session_id)
                )
                await db.commit()
        except Exception as e:
            # Never raise - log and continue to avoid breaking streaming loop
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"append_output failed for session {session_id}: {e}")
