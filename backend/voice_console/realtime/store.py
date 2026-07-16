from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
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
                    response_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner_key, target_name, scope_id, request_id)
                );
                """
            )
            columns = {
                row["name"] for row in self._db.execute("PRAGMA table_info(realtime_requests)")
            }
            if "response_json" not in columns:
                self._db.execute("ALTER TABLE realtime_requests ADD COLUMN response_json TEXT")
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
        with self._immediate_transaction():
            reused = self._db.execute(
                """SELECT scope_id,operation,fingerprint,state FROM realtime_requests
                   WHERE owner_key=? AND target_name=? AND request_id=?""",
                (owner_key, target_name, request_id),
            ).fetchone()
            if reused is not None and reused["scope_id"] != scope_id:
                raise RealtimeProxyError(
                    "idempotency_conflict",
                    "The request ID was already used for another resource",
                    status=409,
                )
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
                         request_id: str, response: Mapping[str, Any] | None = None) -> None:
        self.set_request_state(
            owner_key=owner_key,
            target_name=target_name,
            scope_id=scope_id,
            request_id=request_id,
            state="complete",
            response=response,
        )

    def set_request_state(self, *, owner_key: str, target_name: str, scope_id: str,
                          request_id: str, state: str,
                          response: Mapping[str, Any] | None = None) -> None:
        if state not in {"pending", "in_progress", "outcome_unknown", "complete"}:
            raise ValueError("invalid Realtime request state")
        with self._immediate_transaction():
            self._db.execute(
                """UPDATE realtime_requests SET state=?,response_json=?,updated_at=?
                   WHERE owner_key=? AND target_name=? AND scope_id=? AND request_id=?""",
                (
                    state,
                    json.dumps(response, sort_keys=True, separators=(",", ":"))
                    if response is not None
                    else None,
                    time.time(),
                    owner_key,
                    target_name,
                    scope_id,
                    request_id,
                ),
            )

    @contextmanager
    def _immediate_transaction(self) -> Iterator[None]:
        """Serialize read-check-write decisions across independent SQLite connections."""
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                yield
                self._db.commit()
            except sqlite3.Error as exc:
                self._db.rollback()
                raise RealtimeProxyError(
                    "realtime_store_unavailable",
                    "Realtime durable state could not be updated",
                    status=503,
                ) from exc
            except BaseException:
                self._db.rollback()
                raise

    def request_response(self, *, owner_key: str, target_name: str, scope_id: str,
                         request_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                """SELECT response_json FROM realtime_requests
                   WHERE owner_key=? AND target_name=? AND scope_id=? AND request_id=?""",
                (owner_key, target_name, scope_id, request_id),
            ).fetchone()
        if row is None or not row["response_json"]:
            return None
        value = json.loads(row["response_json"])
        return value if isinstance(value, dict) else None

    def record_session(self, document: Mapping[str, Any], *, owner_key: str,
                       target_name: str, request_id: str) -> None:
        now = time.time()
        with self._immediate_transaction():
            existing_session = self._db.execute(
                "SELECT * FROM realtime_sessions WHERE realtime_session_id=?",
                (document["realtime_session_id"],),
            ).fetchone()
            expected = (
                document["conversation_id"], target_name, owner_key, request_id
            )
            if existing_session is not None and (
                existing_session["conversation_id"],
                existing_session["target_name"],
                existing_session["owner_key"],
                existing_session["create_request_id"],
            ) != expected:
                raise RealtimeProxyError(
                    "target_identity_mismatch",
                    "Hermes returned a session identifier owned by another request",
                )
            existing_request = self._db.execute(
                """SELECT realtime_session_id FROM realtime_sessions
                   WHERE owner_key=? AND target_name=? AND conversation_id=?
                     AND create_request_id=?""",
                (owner_key, target_name, document["conversation_id"], request_id),
            ).fetchone()
            if (
                existing_request is not None
                and existing_request["realtime_session_id"] != document["realtime_session_id"]
            ):
                raise RealtimeProxyError(
                    "target_identity_mismatch",
                    "Hermes returned a different session for the same request",
                )
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
