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
    parse_activate_result,
    parse_approval_result,
    parse_command,
    parse_delete_result,
    parse_events,
    parse_input_result,
    parse_interrupt_result,
    parse_job,
    parse_job_events,
    parse_job_list,
    parse_request_state,
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
            raw = await self._lookup_request(client, conversation_id, request_id, "create")
        pending = parse_request_state(
            raw, client_request_id=request_id, operation="create"
        )
        if pending is not None:
            self.store.set_request_state(
                owner_key=session.owner_key, target_name=target.name,
                scope_id=conversation_id, request_id=request_id, state=pending["state"],
            )
            return pending
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
        client_request_id: Any,
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
        request_id = require_identifier(
            {"client_request_id": client_request_id}, "client_request_id"
        )
        claim_state = self.store.claim_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=session_id,
            request_id=request_id, operation="delete", payload={},
        )
        client = self.client(target)
        if claim_state == "complete":
            cached = self.store.request_response(
                owner_key=mapping["owner_key"], target_name=target_name,
                scope_id=session_id, request_id=request_id,
            )
            if cached is not None:
                return cached
        if claim_state != "new":
            raw = await self._lookup_request(
                client, mapping["conversation_id"], request_id, "delete"
            )
        else:
            try:
                raw = await client.delete_session(
                    session_id,
                    {
                        "client_request_id": request_id,
                        "conversation_id": mapping["conversation_id"],
                    },
                )
            except AmbiguousRealtimeMutation:
                raw = await self._lookup_request(
                    client, mapping["conversation_id"], request_id, "delete"
                )
        pending = parse_request_state(
            raw, client_request_id=request_id, operation="delete"
        )
        if pending is not None:
            self.store.set_request_state(
                owner_key=mapping["owner_key"], target_name=target_name,
                scope_id=session_id, request_id=request_id, state=pending["state"],
                response=pending,
            )
            return pending
        result = parse_delete_result(
            raw,
            conversation_id=mapping["conversation_id"],
            session_id=session_id,
            client_request_id=request_id,
        )
        self.store.update_session(session_id, state="closed")
        self.store.complete_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=session_id,
            request_id=request_id, response=result,
        )
        return result

    async def session_action(
        self,
        session_id: str,
        action: str,
        body: Mapping[str, Any],
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        _target, client, mapping = self._owned_mapping(
            session_id, target_name=target_name, auth_context=auth_context
        )
        request_id = require_identifier(body, "client_request_id")
        generation = validate_generation(body.get("session_generation"))
        forwarded: dict[str, Any] = {
            "client_request_id": request_id,
            "conversation_id": mapping["conversation_id"],
            "session_generation": generation,
        }
        if action == "input":
            forwarded["text"] = require_nonempty_string(body, "text", maximum=32_000)
        claim_state = self.store.claim_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=session_id,
            request_id=request_id, operation=action, payload=forwarded,
        )
        if claim_state == "complete":
            cached = self.store.request_response(
                owner_key=mapping["owner_key"],
                target_name=target_name,
                scope_id=session_id,
                request_id=request_id,
            )
            if cached is not None:
                return cached
        if claim_state != "new":
            raw = await self._lookup_request(
                client, mapping["conversation_id"], request_id, action
            )
        else:
            try:
                raw = await client.session_action(session_id, action, forwarded)
            except AmbiguousRealtimeMutation:
                raw = await self._lookup_request(
                    client, mapping["conversation_id"], request_id, action
                )
        pending = parse_request_state(
            raw, client_request_id=request_id, operation=action
        )
        if pending is not None:
            self.store.set_request_state(
                owner_key=mapping["owner_key"],
                target_name=target_name,
                scope_id=session_id,
                request_id=request_id,
                state=pending["state"],
                response=pending,
            )
            return pending
        if action == "activate":
            result = parse_activate_result(
                raw,
                conversation_id=mapping["conversation_id"],
                session_id=session_id,
                client_request_id=request_id,
            )
            self.store.update_session(session_id, state=result["state"])
        elif action == "input":
            result = parse_input_result(raw, client_request_id=request_id)
        else:
            result = parse_interrupt_result(
                raw, session_id=session_id, client_request_id=request_id
            )
        self.store.complete_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=session_id,
            request_id=request_id, response=result,
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
        _target, client, mapping = self._owned_mapping(
            session_id, target_name=target_name, auth_context=auth_context
        )
        request_id = require_identifier(body, "client_request_id")
        choice = require_nonempty_string(body, "choice", maximum=32)
        if choice not in {"once", "session", "always", "deny"}:
            raise RealtimeProxyError("invalid_request", "Unsupported approval choice", status=400)
        forwarded = {
            "client_request_id": request_id,
            "conversation_id": mapping["conversation_id"],
            "session_generation": validate_generation(body.get("session_generation")),
            "choice": choice,
        }
        claim_state = self.store.claim_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=approval_id,
            request_id=request_id, operation="approval", payload=forwarded,
        )
        if claim_state == "complete":
            cached = self.store.request_response(
                owner_key=mapping["owner_key"],
                target_name=target_name,
                scope_id=approval_id,
                request_id=request_id,
            )
            if cached is not None:
                return cached
        if claim_state != "new":
            raw = await self._lookup_request(
                client, mapping["conversation_id"], request_id, "approval"
            )
        else:
            try:
                raw = await client.resolve_approval(session_id, approval_id, forwarded)
            except AmbiguousRealtimeMutation:
                raw = await self._lookup_request(
                    client, mapping["conversation_id"], request_id, "approval"
                )
        pending = parse_request_state(
            raw, client_request_id=request_id, operation="approval"
        )
        if pending is not None:
            self.store.set_request_state(
                owner_key=mapping["owner_key"],
                target_name=target_name,
                scope_id=approval_id,
                request_id=request_id,
                state=pending["state"],
                response=pending,
            )
            return pending
        result = parse_approval_result(
            raw, approval_id=approval_id, client_request_id=request_id
        )
        self.store.complete_request(
            owner_key=mapping["owner_key"], target_name=target_name, scope_id=approval_id,
            request_id=request_id, response=result,
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

    async def request_result(
        self,
        conversation_id: str,
        client_request_id: str,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> dict[str, Any]:
        validate_identifier(conversation_id, "conversation_id")
        request_id = validate_identifier(client_request_id, "client_request_id")
        target = self.target(target_name)
        self.require_conversation(conversation_id, target=target, auth_context=auth_context)
        raw = await self.client(target).request_result(conversation_id, request_id)
        pending = parse_request_state(raw, client_request_id=request_id)
        if pending is not None:
            return pending
        result = self._parse_completed_request(raw, conversation_id, request_id)
        if raw.get("answer_sdp") is not None:
            session = self.require_conversation(
                conversation_id, target=target, auth_context=auth_context
            )
            self.store.record_session(
                result,
                owner_key=session.owner_key,
                target_name=target.name,
                request_id=request_id,
            )
            self.store.complete_request(
                owner_key=session.owner_key,
                target_name=target.name,
                scope_id=conversation_id,
                request_id=request_id,
            )
        return result

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
        target, client, mapping = self._owned_mapping(
            session_id, target_name=target_name, auth_context=auth_context
        )
        raw = await client.get_session(session_id)
        document = parse_session(
            raw,
            conversation_id=mapping["conversation_id"],
            session_id=session_id,
            include_sdp=False,
        )
        self.require_conversation(mapping["conversation_id"], target=target, auth_context=auth_context)
        return target, client, {**mapping, **document}

    def _owned_mapping(
        self,
        session_id: str,
        *,
        target_name: str,
        auth_context: AuthContext,
    ) -> tuple[TargetConfig, HermesRealtimeClient, dict[str, Any]]:
        validate_identifier(session_id, "realtime_session_id")
        target = self.target(validate_identifier(target_name, "target"))
        owner_key = self.sessions.owner_key(auth_context, target)
        mapping = self.store.require_session(
            session_id, owner_key=owner_key, target_name=target.name
        )
        self.require_conversation(
            mapping["conversation_id"], target=target, auth_context=auth_context
        )
        return target, self.client(target), mapping

    async def _lookup_request(
        self,
        client: HermesRealtimeClient,
        conversation_id: str,
        request_id: str,
        operation: str,
    ) -> dict[str, Any]:
        try:
            return await client.request_result(conversation_id, request_id)
        except RealtimeProxyError as exc:
            if exc.code == "resource_not_found":
                raise AmbiguousRealtimeMutation(operation) from exc
            raise

    @staticmethod
    def _parse_completed_request(
        raw: Mapping[str, Any], conversation_id: str, request_id: str
    ) -> dict[str, Any]:
        parse_request_state(raw, client_request_id=request_id)
        if raw.get("answer_sdp") is not None:
            result = parse_session(raw, conversation_id=conversation_id)
        elif raw.get("state") == "closed" and raw.get("realtime_session_id"):
            session_id = validate_identifier(
                str(raw["realtime_session_id"]), "realtime_session_id"
            )
            result = parse_delete_result(
                raw,
                conversation_id=conversation_id,
                session_id=session_id,
                client_request_id=request_id,
            )
        elif raw.get("approval_id") is not None:
            result = parse_approval_result(
                raw,
                approval_id=validate_identifier(str(raw["approval_id"]), "approval_id"),
                client_request_id=request_id,
            )
        elif raw.get("interrupted") is True:
            session_id = validate_identifier(
                str(raw.get("realtime_session_id") or ""), "realtime_session_id"
            )
            result = parse_interrupt_result(
                raw, session_id=session_id, client_request_id=request_id
            )
        elif raw.get("accepted") is True:
            result = parse_input_result(raw, client_request_id=request_id)
        elif raw.get("realtime_session_id") and raw.get("session_generation"):
            session_id = validate_identifier(
                str(raw["realtime_session_id"]), "realtime_session_id"
            )
            result = parse_activate_result(
                raw,
                conversation_id=conversation_id,
                session_id=session_id,
                client_request_id=request_id,
            )
        else:
            raise RealtimeProxyError(
                "invalid_target_response", "Hermes returned an unknown request result"
            )
        result["client_request_id"] = request_id
        return result


def _find_command(job: Mapping[str, Any], command_id: str) -> dict[str, Any] | None:
    for key in ("commands", "command_history"):
        values = job.get(key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict) and item.get("command_id") == command_id:
                    return item
    return None
