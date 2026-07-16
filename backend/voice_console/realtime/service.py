from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..auth import AuthContext
from ..config import TargetConfig, TargetsConfig
from ..session_manager import SessionManager
from .contracts import RealtimeCompatibility, require_nonempty_string
from .hermes_client import (
    AmbiguousRealtimeMutation,
    HermesRealtimeClient,
    RealtimeProxyError,
)


class RealtimeProxyService:
    """Owner-scoped facade over the authoritative Hermes Realtime API."""

    def __init__(
        self,
        *,
        targets: TargetsConfig,
        sessions: SessionManager,
        request_timeout_seconds: float,
    ) -> None:
        self.targets = targets
        self.sessions = sessions
        self.request_timeout_seconds = request_timeout_seconds

    def target(self, target_name: str) -> TargetConfig:
        target = self.targets.require(target_name)
        if not target.realtime_enabled:
            raise RealtimeProxyError(
                "realtime_disabled",
                "Realtime is disabled for this target",
                status=409,
            )
        return target

    def client(self, target: TargetConfig) -> HermesRealtimeClient:
        return HermesRealtimeClient(target, timeout=self.request_timeout_seconds)

    async def compatibility(self, target_name: str) -> RealtimeCompatibility:
        target = self.target(target_name)
        return await self.client(target).compatibility()

    def require_conversation(
        self,
        conversation_id: str,
        *,
        target: TargetConfig,
        auth_context: AuthContext,
    ):
        try:
            return self.sessions.require(
                conversation_id, auth_context=auth_context, target=target
            )
        except KeyError as exc:
            raise RealtimeProxyError(
                "conversation_not_found", "Conversation not found", status=404
            ) from exc

    async def create_session(
        self, body: Mapping[str, Any], *, auth_context: AuthContext
    ) -> dict[str, Any]:
        target_name = require_nonempty_string(body, "target")
        conversation_id = require_nonempty_string(body, "conversation_id")
        request_id = require_nonempty_string(body, "client_request_id")
        sdp_offer = require_nonempty_string(body, "sdp_offer", maximum=262_144)
        target = self.target(target_name)
        compatibility = await self.client(target).compatibility()
        if not compatibility.compatible:
            raise RealtimeProxyError(
                "realtime_contract_incompatible",
                "; ".join(compatibility.reasons),
                status=409,
            )
        session = self.require_conversation(
            conversation_id, target=target, auth_context=auth_context
        )
        forwarded: dict[str, Any] = {
            "conversation_id": conversation_id,
            "hermes_session_id": session.hermes_session_id,
            "client_request_id": request_id,
            "sdp_offer": sdp_offer,
            # The browser cannot choose or observe this stable pseudonymous identifier.
            "safety_identifier": f"hvc_{session.owner_key}",
        }
        turn_mode = body.get("turn_mode")
        if turn_mode is not None:
            if turn_mode not in {"server_vad", "manual"}:
                raise RealtimeProxyError("invalid_turn_mode", "Unsupported turn mode", status=400)
            forwarded["turn_mode"] = turn_mode
        client = self.client(target)
        try:
            result = await client.create_session(forwarded)
        except AmbiguousRealtimeMutation:
            result = await self._reconcile_create(client, conversation_id, request_id)
        self._assert_conversation(result, conversation_id)
        return result

    async def get_session(
        self, session_id: str, *, target_name: str, auth_context: AuthContext
    ) -> dict[str, Any]:
        target, client, document = await self._owned_session(
            session_id, target_name=target_name, auth_context=auth_context
        )
        del target, client
        return document

    async def delete_session(
        self, session_id: str, *, target_name: str, auth_context: AuthContext
    ) -> dict[str, Any]:
        _target, client, _document = await self._owned_session(
            session_id, target_name=target_name, auth_context=auth_context
        )
        return await client.delete_session(session_id)

    async def session_action(
        self,
        session_id: str,
        action: str,
        body: Mapping[str, Any],
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        _target, client, _document = await self._owned_session(
            session_id, target_name=target_name, auth_context=auth_context
        )
        forwarded = dict(body)
        forwarded.pop("target", None)
        forwarded.pop("conversation_id", None)
        if action in {"activate", "input", "interrupt"}:
            require_nonempty_string(forwarded, "client_request_id")
        if action == "input":
            require_nonempty_string(forwarded, "text", maximum=32_000)
        return await client.session_action(session_id, action, forwarded)

    async def events(
        self,
        session_id: str,
        *,
        target_name: str,
        auth_context: AuthContext,
        after: str | None,
    ) -> dict[str, Any]:
        _target, client, _document = await self._owned_session(
            session_id, target_name=target_name, auth_context=auth_context
        )
        if after is not None and len(after) > 128:
            raise RealtimeProxyError("invalid_event_cursor", "Event cursor is too long", status=400)
        return await client.session_events(session_id, after)

    async def resolve_approval(
        self,
        session_id: str,
        approval_id: str,
        body: Mapping[str, Any],
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        _target, client, _document = await self._owned_session(
            session_id, target_name=target_name, auth_context=auth_context
        )
        forwarded = dict(body)
        forwarded.pop("target", None)
        require_nonempty_string(forwarded, "client_request_id")
        require_nonempty_string(forwarded, "choice", maximum=32)
        return await client.resolve_approval(session_id, approval_id, forwarded)

    async def conversation(
        self,
        conversation_id: str,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        target = self.target(target_name)
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        document = await self.client(target).conversation(conversation_id)
        self._assert_conversation(document, conversation_id)
        return document

    async def worker_jobs(
        self,
        conversation_id: str,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        target = self.target(target_name)
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        return await self.client(target).list_worker_jobs(conversation_id)

    async def worker_job(
        self,
        conversation_id: str,
        worker_job_id: str,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        target = self.target(target_name)
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        return await self.client(target).worker_job(conversation_id, worker_job_id)

    async def worker_events(
        self,
        conversation_id: str,
        worker_job_id: str,
        after: int,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        target = self.target(target_name)
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        return await self.client(target).worker_events(conversation_id, worker_job_id, after)

    async def worker_command(
        self,
        conversation_id: str,
        worker_job_id: str,
        operation: str,
        body: Mapping[str, Any],
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        target = self.target(target_name)
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        command_id = require_nonempty_string(body, "command_id")
        revision = body.get("expected_revision")
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise RealtimeProxyError(
                "invalid_revision", "expected_revision must be an integer", status=400
            )
        payload = body.get("payload", {})
        if not isinstance(payload, Mapping):
            raise RealtimeProxyError("invalid_payload", "payload must be an object", status=400)
        forwarded = {
            "command_id": command_id,
            "expected_revision": revision,
            "payload": dict(payload),
        }
        client = self.client(target)
        try:
            return await client.worker_command(
                conversation_id, worker_job_id, operation, forwarded
            )
        except AmbiguousRealtimeMutation:
            job = await client.worker_job(conversation_id, worker_job_id)
            reconciled = _find_command(job, command_id)
            if reconciled is None:
                raise
            return reconciled

    async def _owned_session(
        self,
        session_id: str,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> tuple[TargetConfig, HermesRealtimeClient, dict[str, Any]]:
        target = self.target(target_name)
        client = self.client(target)
        document = await client.get_session(session_id)
        conversation_id = document.get("conversation_id")
        if not isinstance(conversation_id, str):
            raise RealtimeProxyError(
                "invalid_target_response", "Hermes session omitted conversation ownership"
            )
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        return target, client, document

    async def _reconcile_create(
        self,
        client: HermesRealtimeClient,
        conversation_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        snapshot = await client.conversation(conversation_id)
        session = snapshot.get("session")
        if isinstance(session, dict) and session.get("answer_sdp"):
            return session
        raise AmbiguousRealtimeMutation(f"create request {request_id}")

    @staticmethod
    def _assert_conversation(document: Mapping[str, Any], expected: str) -> None:
        if document.get("conversation_id") != expected:
            raise RealtimeProxyError(
                "target_ownership_mismatch", "Hermes returned a mismatched conversation", status=502
            )


def _find_command(job: Mapping[str, Any], command_id: str) -> dict[str, Any] | None:
    for key in ("commands", "command_history"):
        values = job.get(key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict) and item.get("command_id") == command_id:
                    return item
    return None
