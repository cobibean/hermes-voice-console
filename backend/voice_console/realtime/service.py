from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..auth import AuthContext
from ..config import TargetConfig, TargetsConfig
from ..session_manager import SessionManager
from .contracts import (
    RealtimeCompatibility,
    require_identifier,
    require_nonempty_string,
    validate_generation,
    validate_identifier,
    validate_sdp,
)
from .hermes_client import (
    AmbiguousRealtimeMutation,
    HermesRealtimeClient,
    RealtimeProxyError,
)
from .responses import (
    parse_approval,
    parse_closed,
    parse_command,
    parse_events,
    parse_job,
    parse_job_events,
    parse_job_list,
    parse_session,
    parse_snapshot,
)
from .store import RealtimeMappingStore


class RealtimeProxyService:
    """Owner-scoped facade over the authoritative Hermes Realtime API."""

    def __init__(
        self,
        *,
        targets: TargetsConfig,
        sessions: SessionManager,
        store: RealtimeMappingStore,
        request_timeout_seconds: float,
    ) -> None:
        self.targets = targets
        self.sessions = sessions
        self.store = store
        self.request_timeout_seconds = request_timeout_seconds

    def target(self, target_name: str) -> TargetConfig:
        target = self.targets.require(validate_identifier(target_name, "target"))
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
        target_name = require_identifier(body, "target")
        conversation_id = require_identifier(body, "conversation_id")
        request_id = require_identifier(body, "client_request_id")
        sdp_offer = validate_sdp(
            require_nonempty_string(body, "sdp_offer", maximum=262_144)
        )
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
        self.store.claim_request(
            owner_key=session.owner_key,
            target_name=target.name,
            scope_id=conversation_id,
            request_id=request_id,
            operation="create",
            payload={"sdp_offer": sdp_offer, "turn_mode": body.get("turn_mode")},
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
            raw = await client.create_session(forwarded)
        except AmbiguousRealtimeMutation:
            # Hermes contract major 1 makes create idempotent by client_request_id.
            # Repeating the same request is the only safe acceptance reconciliation.
            raw = await client.create_session(forwarded, timeout=max(5.0, self.request_timeout_seconds))
        result = parse_session(raw, conversation_id=conversation_id)
        result["client_request_id"] = request_id
        self.store.record_session(
            result, owner_key=session.owner_key, target_name=target.name, request_id=request_id
        )
        self.store.complete_request(
            owner_key=session.owner_key, target_name=target.name, scope_id=conversation_id,
            request_id=request_id,
        )
        return result

    async def get_session(
        self, session_id: str, *, target_name: str, auth_context: AuthContext
    ) -> dict[str, Any]:
        target, client, document = await self._owned_session(
            session_id, target_name=target_name, auth_context=auth_context
        )
        del target, client
        return parse_session(document, session_id=session_id, include_sdp=False)

    async def delete_session(
        self, session_id: str, *, target_name: str, auth_context: AuthContext,
        client_request_id: str,
    ) -> dict[str, Any]:
        validate_identifier(session_id, "realtime_session_id")
        target = self.target(validate_identifier(target_name, "target"))
        owner_key = self.sessions.owner_key(auth_context, target)
        mapping = self.store.require_session(
            session_id, owner_key=owner_key, target_name=target.name
        )
        self.require_conversation(
            mapping["conversation_id"], target=target, auth_context=auth_context
        )
        request_id = validate_identifier(client_request_id, "client_request_id")
        claim_state = self.store.claim_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=session_id,
            request_id=request_id, operation="delete", payload={},
        )
        if claim_state == "complete" and mapping["state"] == "closed":
            return {
                "realtime_session_id": session_id,
                "conversation_id": mapping["conversation_id"],
                "state": "closed",
                "client_request_id": request_id,
            }
        if claim_state == "pending":
            try:
                await self.client(target).get_session(session_id)
            except RealtimeProxyError as exc:
                if exc.code != "resource_not_found":
                    raise
                self.store.update_session(session_id, state="closed")
                self.store.complete_request(
                    owner_key=mapping["owner_key"], target_name=target_name,
                    scope_id=session_id, request_id=request_id,
                )
                return {
                    "realtime_session_id": session_id,
                    "conversation_id": mapping["conversation_id"],
                    "state": "closed",
                    "client_request_id": request_id,
                }
            raise AmbiguousRealtimeMutation("delete")
        client = self.client(target)
        try:
            raw = await client.delete_session(session_id)
            result = parse_closed(
                raw, conversation_id=mapping["conversation_id"], session_id=session_id
            )
        except AmbiguousRealtimeMutation:
            try:
                await client.get_session(session_id)
            except RealtimeProxyError as exc:
                if exc.code != "resource_not_found":
                    raise
                result = {"realtime_session_id": session_id,
                          "conversation_id": mapping["conversation_id"], "state": "closed"}
            else:
                raise
        self.store.update_session(session_id, state="closed")
        self.store.complete_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=session_id,
            request_id=request_id,
        )
        return {**result, "client_request_id": request_id}

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
        mapping = _document
        request_id = require_identifier(body, "client_request_id")
        generation = validate_generation(body.get("session_generation"))
        forwarded: dict[str, Any] = {
            "client_request_id": request_id,
            "session_generation": generation,
        }
        if action == "input":
            forwarded["text"] = require_nonempty_string(body, "text", maximum=32_000)
        claim_state = self.store.claim_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=session_id,
            request_id=request_id, operation=action, payload=forwarded,
        )
        if claim_state == "complete":
            if action == "activate":
                return parse_session(mapping, session_id=session_id, include_sdp=False)
            if action == "input":
                return {"client_request_id": request_id, "accepted": True}
            return {"realtime_session_id": session_id, "interrupted": True}
        if claim_state == "pending" and action != "input":
            if action == "activate" and mapping["state"] == "active":
                self.store.complete_request(
                    owner_key=mapping["owner_key"], target_name=target_name,
                    scope_id=session_id, request_id=request_id,
                )
                return parse_session(mapping, session_id=session_id, include_sdp=False)
            raise AmbiguousRealtimeMutation(action)
        try:
            raw = await client.session_action(session_id, action, forwarded)
        except AmbiguousRealtimeMutation:
            if action == "activate":
                observed = parse_session(
                    await client.get_session(session_id),
                    conversation_id=mapping["conversation_id"],
                    session_id=session_id,
                    include_sdp=False,
                )
                if observed["state"] != "active":
                    raise
                raw = observed
            else:
                raise
        if action == "activate":
            result = parse_session(
                raw,
                conversation_id=mapping["conversation_id"],
                session_id=session_id,
                include_sdp=False,
            )
            self.store.update_session(session_id, state=result["state"])
        else:
            allowed = {"client_request_id", "accepted"} if action == "input" else {
                "realtime_session_id", "interrupted"
            }
            result = {key: raw[key] for key in allowed if key in raw}
            if action == "input" and raw.get("client_request_id") != request_id:
                raise RealtimeProxyError("target_identity_mismatch", "Hermes returned a mismatched request")
            if action == "interrupt" and raw.get("realtime_session_id") != session_id:
                raise RealtimeProxyError("target_identity_mismatch", "Hermes returned a mismatched session")
        self.store.complete_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=session_id,
            request_id=request_id,
        )
        return result

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
        document = parse_events(
            await client.session_events(session_id, after),
            conversation_id=_document["conversation_id"], session_id=session_id,
        )
        if document["last_event_id"]:
            self.store.update_session(session_id, state=_document["state"],
                                      last_event_id=document["last_event_id"])
        return document

    async def resolve_approval(
        self,
        session_id: str,
        approval_id: str,
        body: Mapping[str, Any],
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        validate_identifier(approval_id, "approval_id")
        _target, client, _document = await self._owned_session(
            session_id, target_name=target_name, auth_context=auth_context
        )
        mapping = _document
        request_id = require_identifier(body, "client_request_id")
        choice = require_nonempty_string(body, "choice", maximum=32)
        if choice not in {"once", "session", "always", "deny"}:
            raise RealtimeProxyError("invalid_request", "Unsupported approval choice", status=400)
        forwarded = {"client_request_id": request_id,
                     "session_generation": validate_generation(body.get("session_generation")),
                     "choice": choice}
        claim_state = self.store.claim_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=approval_id,
            request_id=request_id, operation="approval", payload=forwarded,
        )
        if claim_state == "complete":
            return {"approval_id": approval_id, "state": "resolved", "accepted": choice}
        if claim_state == "pending":
            raise AmbiguousRealtimeMutation("approval")
        result = parse_approval(
            await client.resolve_approval(session_id, approval_id, forwarded),
            approval_id=approval_id,
        )
        self.store.complete_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=approval_id,
            request_id=request_id,
        )
        return result

    async def conversation(
        self,
        conversation_id: str,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        validate_identifier(conversation_id, "conversation_id")
        target = self.target(target_name)
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        return parse_snapshot(
            await self.client(target).conversation(conversation_id),
            conversation_id=conversation_id,
        )

    async def worker_jobs(
        self,
        conversation_id: str,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        validate_identifier(conversation_id, "conversation_id")
        target = self.target(target_name)
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        return parse_job_list(
            await self.client(target).list_worker_jobs(conversation_id),
            conversation_id=conversation_id,
        )

    async def worker_job(
        self,
        conversation_id: str,
        worker_job_id: str,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        validate_identifier(conversation_id, "conversation_id")
        target = self.target(target_name)
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        validate_identifier(worker_job_id, "worker_job_id")
        return parse_job(
            await self.client(target).worker_job(conversation_id, worker_job_id),
            conversation_id=conversation_id, worker_job_id=worker_job_id,
        )

    async def worker_events(
        self,
        conversation_id: str,
        worker_job_id: str,
        after: int,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        validate_identifier(conversation_id, "conversation_id")
        target = self.target(target_name)
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        validate_identifier(worker_job_id, "worker_job_id")
        if not isinstance(after, int) or isinstance(after, bool) or after < 0:
            raise RealtimeProxyError("invalid_event_cursor", "Invalid worker event cursor", status=400)
        return parse_job_events(
            await self.client(target).worker_events(conversation_id, worker_job_id, after),
            conversation_id=conversation_id, worker_job_id=worker_job_id,
        )

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
        validate_identifier(conversation_id, "conversation_id")
        target = self.target(target_name)
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        validate_identifier(worker_job_id, "worker_job_id")
        command_id = require_identifier(body, "command_id")
        revision = body.get("expected_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise RealtimeProxyError(
                "invalid_revision", "expected_revision must be an integer", status=400
            )
        payload = body.get("payload", {})
        if not isinstance(payload, Mapping):
            raise RealtimeProxyError("invalid_payload", "payload must be an object", status=400)
        allowed_payload = {"goal", "context"} if operation in {"refine", "redirect"} else set()
        unexpected = set(payload) - allowed_payload
        if unexpected:
            raise RealtimeProxyError("invalid_payload", "Worker command payload contains unsupported fields", status=400)
        for key, value in payload.items():
            if not isinstance(value, str) or len(value) > 32_000:
                raise RealtimeProxyError(
                    "invalid_payload", f"Worker command {key} must be bounded text", status=400
                )
        forwarded = {
            "command_id": command_id,
            "expected_revision": revision,
            "payload": dict(payload),
        }
        client = self.client(target)
        try:
            raw = await client.worker_command(
                conversation_id, worker_job_id, operation, forwarded
            )
        except AmbiguousRealtimeMutation:
            job = await client.worker_job(conversation_id, worker_job_id)
            reconciled = _find_command(job, command_id)
            if reconciled is None:
                raise
            raw = reconciled
        return parse_command(raw, command_id=command_id, worker_job_id=worker_job_id)

    async def _owned_session(
        self,
        session_id: str,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> tuple[TargetConfig, HermesRealtimeClient, dict[str, Any]]:
        validate_identifier(session_id, "realtime_session_id")
        target = self.target(validate_identifier(target_name, "target"))
        owner_key = self.sessions.owner_key(auth_context, target)
        mapping = self.store.require_session(session_id, owner_key=owner_key, target_name=target.name)
        client = self.client(target)
        raw = await client.get_session(session_id)
        document = parse_session(
            raw,
            conversation_id=mapping["conversation_id"],
            session_id=session_id,
            include_sdp=False,
        )
        self.require_conversation(mapping["conversation_id"], target=target, auth_context=auth_context)
        return target, client, {**mapping, **document}


def _find_command(job: Mapping[str, Any], command_id: str) -> dict[str, Any] | None:
    for key in ("commands", "command_history"):
        values = job.get(key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict) and item.get("command_id") == command_id:
                    return item
    return None
