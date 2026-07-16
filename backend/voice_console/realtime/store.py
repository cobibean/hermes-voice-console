from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .hermes_client import RealtimeProxyError


class RealtimeMappingStore:
    """Content-free ownership and idempotency metadata for the proxy boundary."""

    def __init__(self, state_dir: str | Path) -> None:
        directory = Path(state_dir).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "voice-console-realtime.sqlite3"
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS realtime_sessions (
                    realtime_session_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    owner_key TEXT NOT NULL,
                    create_request_id TEXT NOT NULL,
                    session_generation INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    last_event_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(owner_key, target_name, conversation_id, create_request_id)
                );
                CREATE TABLE IF NOT EXISTS realtime_requests (
                    owner_key TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner_key, target_name, scope_id, request_id)
                );
                """
            )
            cutoff = time.time() - 30 * 86400
            self._db.execute(
                "DELETE FROM realtime_requests WHERE updated_at < ?", (cutoff,)
            )
            self._db.execute(
                "DELETE FROM realtime_sessions WHERE state='closed' AND updated_at < ?",
                (cutoff,),
            )
        os.chmod(self.path, 0o600)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def claim_request(self, *, owner_key: str, target_name: str, scope_id: str,
                      request_id: str, operation: str, payload: Mapping[str, Any]) -> str:
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        now = time.time()
        with self._lock, self._db:
            row = self._db.execute(
                """SELECT operation,fingerprint,state FROM realtime_requests
                   WHERE owner_key=? AND target_name=? AND scope_id=? AND request_id=?""",
                (owner_key, target_name, scope_id, request_id),
            ).fetchone()
            if row is not None:
                if row["operation"] != operation or row["fingerprint"] != fingerprint:
                    raise RealtimeProxyError(
                        "idempotency_conflict",
                        "The request ID was already used for different input",
                        status=409,
                    )
                return str(row["state"])
            self._db.execute(
                """INSERT INTO realtime_requests
                   (owner_key,target_name,scope_id,request_id,operation,fingerprint,state,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,'pending',?,?)""",
                (owner_key, target_name, scope_id, request_id, operation, fingerprint, now, now),
            )
        return "new"

    def complete_request(self, *, owner_key: str, target_name: str, scope_id: str,
                         request_id: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                """UPDATE realtime_requests SET state='complete',updated_at=?
                   WHERE owner_key=? AND target_name=? AND scope_id=? AND request_id=?""",
                (time.time(), owner_key, target_name, scope_id, request_id),
            )

    def record_session(self, document: Mapping[str, Any], *, owner_key: str,
                       target_name: str, request_id: str) -> None:
        now = time.time()
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO realtime_sessions
                   (realtime_session_id,conversation_id,target_name,owner_key,create_request_id,
                    session_generation,state,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(realtime_session_id) DO UPDATE SET
                    state=excluded.state,session_generation=excluded.session_generation,
                    updated_at=excluded.updated_at""",
                (
                    document["realtime_session_id"], document["conversation_id"], target_name,
                    owner_key, request_id, document["session_generation"], document["state"], now, now,
                ),
            )

    def require_session(self, session_id: str, *, owner_key: str,
                        target_name: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute(
                """SELECT * FROM realtime_sessions
                   WHERE realtime_session_id=? AND owner_key=? AND target_name=?""",
                (session_id, owner_key, target_name),
            ).fetchone()
        if row is None:
            raise RealtimeProxyError("resource_not_found", "The requested resource was not found", status=404)
        return dict(row)

    def update_session(self, session_id: str, *, state: str,
                       last_event_id: str | None = None) -> None:
        fields = "state=?,updated_at=?"
        values: list[Any] = [state, time.time()]
        if last_event_id is not None:
            fields += ",last_event_id=?"
            values.append(last_event_id)
        values.append(session_id)
        with self._lock, self._db:
            self._db.execute(f"UPDATE realtime_sessions SET {fields} WHERE realtime_session_id=?", values)
