from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from typing import Any

from .auth import AuthContext, AuthGate
from .config import TargetConfig
from .hermes_client import HermesApiClient
from .protocol import validate_session_key
from .run_store import ConsoleStore, SessionRecord


@dataclass(frozen=True)
class SessionSelection:
    session_id: str
    session_key: str


class SessionManager:
    """Own console-to-Hermes session authorization and stable memory scopes."""

    def __init__(self, store: ConsoleStore, auth: AuthGate) -> None:
        self.store = store
        self.auth = auth

    @staticmethod
    def from_hello(message: dict[str, Any], target: TargetConfig) -> SessionSelection:
        """Legacy normalization retained for old transport-focused unit tests."""
        session_id = validate_session_key(
            message.get("session_id") or target.default_session_key,
            field="session_id",
        )
        session_key = validate_session_key(
            message.get("session_key") or target.default_session_key,
            field="session_key",
        )
        return SessionSelection(session_id=session_id, session_key=session_key)

    def owner_key(self, auth_context: AuthContext, target: TargetConfig) -> str:
        material = (
            f"{target.name}\x00{auth_context.principal_kind}\x00{auth_context.principal_subject}"
        ).encode()
        return hmac.new(self.auth.scope_secret.encode(), material, hashlib.sha256).hexdigest()[:32]

    def memory_session_key(self, auth_context: AuthContext, target: TargetConfig) -> str:
        if target.fixed_memory_session_key:
            return validate_session_key(target.fixed_memory_session_key)
        return f"{target.memory_scope_prefix}:{self.owner_key(auth_context, target)}"

    async def create(
        self,
        *,
        auth_context: AuthContext,
        target: TargetConfig,
        title: str = "New conversation",
    ) -> SessionRecord:
        conversation_id = f"hvc_{uuid.uuid4().hex}"
        client = HermesApiClient(target)
        hermes_session_id = await client.create_session(conversation_id)
        return self.store.create_session(
            conversation_id=conversation_id,
            target_name=target.name,
            hermes_session_id=hermes_session_id,
            memory_session_key=self.memory_session_key(auth_context, target),
            owner_key=self.owner_key(auth_context, target),
            title=title.strip()[:120] or "New conversation",
        )

    def list(
        self,
        *,
        auth_context: AuthContext,
        target: TargetConfig,
    ) -> list[SessionRecord]:
        return self.store.list_sessions(
            owner_key=self.owner_key(auth_context, target),
            target_name=target.name,
        )

    def require(
        self,
        conversation_id: str,
        *,
        auth_context: AuthContext,
        target: TargetConfig,
    ) -> SessionRecord:
        return self.store.require_session(
            conversation_id,
            owner_key=self.owner_key(auth_context, target),
            target_name=target.name,
        )

    async def history(
        self,
        session: SessionRecord,
        *,
        target: TargetConfig,
    ) -> tuple[SessionRecord, list[dict[str, str]]]:
        client = HermesApiClient(target)
        document = await client.session_messages(session.hermes_session_id)
        resolved_id = str(document.get("session_id") or session.hermes_session_id)
        if resolved_id != session.hermes_session_id:
            session = self.store.adopt_hermes_session(
                session.conversation_id,
                owner_key=session.owner_key,
                hermes_session_id=resolved_id,
            )
        messages = document.get("messages") or []
        history: list[dict[str, str]] = []
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role") or "")
                content = str(message.get("content") or "").strip()
                if role in {"user", "assistant"} and content:
                    history.append({"role": role, "content": content})
        return session, history

    @staticmethod
    def public(record: SessionRecord) -> dict[str, Any]:
        return {
            "conversation_id": record.conversation_id,
            "target": record.target_name,
            "title": record.title,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
