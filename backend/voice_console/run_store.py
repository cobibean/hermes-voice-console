from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ConnectionRunStore:
    """Compatibility seam for the Phase 1 transport wrapper."""

    active_run_id: str | None = None

    def started(self, run_id: str) -> None:
        self.active_run_id = run_id

    def finished(self, run_id: str | None = None) -> None:
        if run_id is None or run_id == self.active_run_id:
            self.active_run_id = None


@dataclass(frozen=True)
class SessionRecord:
    conversation_id: str
    target_name: str
    hermes_session_id: str
    memory_session_key: str
    owner_key: str
    title: str
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class RunRecord:
    local_turn_id: str
    run_id: str | None
    target_name: str
    conversation_id: str
    hermes_session_id: str
    memory_session_key: str
    owner_key: str
    turn_id: str
    status: str
    last_sequence: int
    failure_category: str | None
    created_at: float
    updated_at: float
    terminal_at: float | None


class ConsoleStore:
    """Owner-only SQLite metadata store. Conversation content never enters this database."""

    def __init__(self, state_dir: str | Path) -> None:
        directory = Path(state_dir).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        self.path = directory / "voice-console.sqlite3"
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._initialize()
        os.chmod(self.path, 0o600)

    def _initialize(self) -> None:
        with self._lock, self._db:
            self._db.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS sessions (
                    conversation_id TEXT PRIMARY KEY,
                    target_name TEXT NOT NULL,
                    hermes_session_id TEXT NOT NULL,
                    memory_session_key TEXT NOT NULL,
                    owner_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(target_name, hermes_session_id)
                );
                CREATE INDEX IF NOT EXISTS sessions_owner_updated
                    ON sessions(owner_key, target_name, updated_at DESC);
                CREATE TABLE IF NOT EXISTS runs (
                    local_turn_id TEXT PRIMARY KEY,
                    run_id TEXT UNIQUE,
                    target_name TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    hermes_session_id TEXT NOT NULL,
                    memory_session_key TEXT NOT NULL,
                    owner_key TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_sequence INTEGER NOT NULL DEFAULT 0,
                    failure_category TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    terminal_at REAL,
                    FOREIGN KEY(conversation_id) REFERENCES sessions(conversation_id)
                );
                CREATE INDEX IF NOT EXISTS runs_owner_updated
                    ON runs(owner_key, target_name, updated_at DESC);
                CREATE INDEX IF NOT EXISTS runs_conversation_updated
                    ON runs(conversation_id, updated_at DESC);
                """
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def create_session(
        self,
        *,
        conversation_id: str,
        target_name: str,
        hermes_session_id: str,
        memory_session_key: str,
        owner_key: str,
        title: str,
    ) -> SessionRecord:
        now = time.time()
        with self._lock, self._db:
            self._db.execute(
                """
                INSERT INTO sessions (
                    conversation_id, target_name, hermes_session_id, memory_session_key,
                    owner_key, title, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    target_name,
                    hermes_session_id,
                    memory_session_key,
                    owner_key,
                    title,
                    now,
                    now,
                ),
            )
        return self.require_session(conversation_id, owner_key=owner_key, target_name=target_name)

    def list_sessions(
        self, *, owner_key: str, target_name: str | None = None
    ) -> list[SessionRecord]:
        query = "SELECT * FROM sessions WHERE owner_key = ?"
        values: list[Any] = [owner_key]
        if target_name:
            query += " AND target_name = ?"
            values.append(target_name)
        query += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._db.execute(query, values).fetchall()
        return [self._session(row) for row in rows]

    def require_session(
        self,
        conversation_id: str,
        *,
        owner_key: str,
        target_name: str | None = None,
    ) -> SessionRecord:
        query = "SELECT * FROM sessions WHERE conversation_id = ? AND owner_key = ?"
        values: list[Any] = [conversation_id, owner_key]
        if target_name:
            query += " AND target_name = ?"
            values.append(target_name)
        with self._lock:
            row = self._db.execute(query, values).fetchone()
        if row is None:
            raise KeyError("session not found")
        return self._session(row)

    def adopt_hermes_session(
        self,
        conversation_id: str,
        *,
        owner_key: str,
        hermes_session_id: str,
    ) -> SessionRecord:
        now = time.time()
        with self._lock, self._db:
            cursor = self._db.execute(
                """
                UPDATE sessions SET hermes_session_id = ?, updated_at = ?
                WHERE conversation_id = ? AND owner_key = ?
                """,
                (hermes_session_id, now, conversation_id, owner_key),
            )
            if cursor.rowcount != 1:
                raise KeyError("session not found")
        return self.require_session(conversation_id, owner_key=owner_key)

    def insert_run(
        self,
        *,
        local_turn_id: str,
        target_name: str,
        session: SessionRecord,
        turn_id: str,
        status: str = "submitting",
    ) -> RunRecord:
        now = time.time()
        with self._lock, self._db:
            self._db.execute(
                """
                INSERT INTO runs (
                    local_turn_id, target_name, conversation_id, hermes_session_id,
                    memory_session_key, owner_key, turn_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    local_turn_id,
                    target_name,
                    session.conversation_id,
                    session.hermes_session_id,
                    session.memory_session_key,
                    session.owner_key,
                    turn_id,
                    status,
                    now,
                    now,
                ),
            )
        return self.require_run(local_turn_id=local_turn_id, owner_key=session.owner_key)

    def update_run(
        self,
        local_turn_id: str,
        *,
        run_id: str | None = None,
        status: str | None = None,
        last_sequence: int | None = None,
        failure_category: str | None = None,
        terminal: bool = False,
    ) -> RunRecord:
        fields = ["updated_at = ?"]
        values: list[Any] = [time.time()]
        for name, value in (
            ("run_id", run_id),
            ("status", status),
            ("last_sequence", last_sequence),
            ("failure_category", failure_category),
        ):
            if value is not None:
                fields.append(f"{name} = ?")
                values.append(value)
        if terminal:
            fields.append("terminal_at = ?")
            values.append(time.time())
        values.append(local_turn_id)
        with self._lock, self._db:
            self._db.execute(
                f"UPDATE runs SET {', '.join(fields)} WHERE local_turn_id = ?",
                values,
            )
        return self.require_run(local_turn_id=local_turn_id)

    def require_run(
        self,
        *,
        local_turn_id: str | None = None,
        run_id: str | None = None,
        owner_key: str | None = None,
    ) -> RunRecord:
        if not local_turn_id and not run_id:
            raise ValueError("local_turn_id or run_id is required")
        column, value = ("local_turn_id", local_turn_id) if local_turn_id else ("run_id", run_id)
        query = f"SELECT * FROM runs WHERE {column} = ?"
        values: list[Any] = [value]
        if owner_key:
            query += " AND owner_key = ?"
            values.append(owner_key)
        with self._lock:
            row = self._db.execute(query, values).fetchone()
        if row is None:
            raise KeyError("run not found")
        return self._run(row)

    def active_run_for_conversation(
        self, conversation_id: str, *, owner_key: str
    ) -> RunRecord | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT * FROM runs
                WHERE conversation_id = ? AND owner_key = ?
                  AND status NOT IN ('completed', 'failed', 'cancelled', 'rejected')
                ORDER BY created_at DESC LIMIT 1
                """,
                (conversation_id, owner_key),
            ).fetchone()
        return self._run(row) if row else None

    def has_completed_run(self, conversation_id: str, *, owner_key: str) -> bool:
        with self._lock:
            row = self._db.execute(
                """
                SELECT 1 FROM runs
                WHERE conversation_id = ? AND owner_key = ? AND status = 'completed'
                LIMIT 1
                """,
                (conversation_id, owner_key),
            ).fetchone()
        return row is not None

    def acceptance_unknown_for_owner_target(
        self, *, owner_key: str, target_name: str
    ) -> RunRecord | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT * FROM runs
                WHERE owner_key = ? AND target_name = ? AND status = 'acceptance_unknown'
                ORDER BY created_at DESC LIMIT 1
                """,
                (owner_key, target_name),
            ).fetchone()
        return self._run(row) if row else None

    def list_recoverable_runs(self) -> list[RunRecord]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM runs
                WHERE status NOT IN ('completed', 'failed', 'cancelled', 'rejected')
                ORDER BY created_at
                """
            ).fetchall()
        return [self._run(row) for row in rows]

    def acknowledge_unknown(self, local_turn_id: str, *, owner_key: str) -> RunRecord:
        run = self.require_run(local_turn_id=local_turn_id, owner_key=owner_key)
        if run.status != "acceptance_unknown":
            raise ValueError("run is not acceptance_unknown")
        return self.update_run(
            local_turn_id, status="failed", failure_category="owner_acknowledged", terminal=True
        )

    def acknowledge_unrecoverable(self, run_id: str, *, owner_key: str) -> RunRecord:
        run = self.require_run(run_id=run_id, owner_key=owner_key)
        if run.status != "unrecoverable":
            raise ValueError("run is not unrecoverable")
        return self.update_run(
            run.local_turn_id,
            status="failed",
            failure_category="owner_acknowledged_unrecoverable",
            terminal=True,
        )

    def cleanup_terminal(self, older_than: float) -> int:
        with self._lock, self._db:
            cursor = self._db.execute(
                "DELETE FROM runs WHERE terminal_at IS NOT NULL AND terminal_at < ?",
                (older_than,),
            )
        return cursor.rowcount

    @staticmethod
    def _session(row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(**dict(row))

    @staticmethod
    def _run(row: sqlite3.Row) -> RunRecord:
        return RunRecord(**dict(row))
