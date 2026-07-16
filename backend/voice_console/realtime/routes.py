from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..auth import AuthContext, AuthGate
from ..config import ConfigError
from .hermes_client import RealtimeProxyError
from .service import RealtimeProxyService

MAX_CONTROL_BODY_BYTES = 96 * 1024
MAX_SDP_BODY_BYTES = 384 * 1024


def create_realtime_router(service: RealtimeProxyService, auth: AuthGate) -> APIRouter:
    router = APIRouter(prefix="/api/realtime", tags=["realtime"])

    def context(request: Request) -> AuthContext:
        return auth.authenticate_http(request)

    @router.get("/targets/{target_name}/compatibility")
    async def compatibility(target_name: str, request: Request):
        context(request)
        return await _respond(
            lambda: _compatibility_document(service, target_name)
        )

    @router.post("/sessions", status_code=201)
    async def create_session(request: Request):
        auth_context = context(request)
        return await _respond(
            lambda: _with_body(
                request,
                lambda body: service.create_session(body, auth_context=auth_context),
                maximum=MAX_SDP_BODY_BYTES,
            ),
            status=201,
        )

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str, target: str, request: Request):
        auth_context = context(request)
        return await _respond(
            lambda: service.get_session(
                session_id, target_name=target, auth_context=auth_context
            )
        )

    @router.delete("/sessions/{session_id}")
    async def delete_session(session_id: str, target: str, request: Request):
        auth_context = context(request)
        return await _respond(
            lambda: _with_body(
                request,
                lambda body: service.delete_session(
                    session_id,
                    target_name=target,
                    auth_context=auth_context,
                    client_request_id=body.get("client_request_id"),
                ),
            )
        )

    for action in ("activate", "input", "interrupt"):
        router.add_api_route(
            f"/sessions/{{session_id}}/{action}",
            _session_action(service, auth, action),
            methods=["POST"],
            name=f"realtime_session_{action}",
        )

    @router.post("/sessions/{session_id}/commit")
    async def manual_audio_commit(session_id: str, target: str, request: Request):
        auth_context = context(request)
        return await _respond(
            lambda: _with_body(
                request,
                lambda body: service.manual_control(
                    session_id,
                    "manual_audio_commit",
                    body,
                    target_name=target,
                    auth_context=auth_context,
                ),
            )
        )

    @router.post("/sessions/{session_id}/turn-mode")
    async def turn_mode_update(session_id: str, target: str, request: Request):
        auth_context = context(request)
        return await _respond(
            lambda: _with_body(
                request,
                lambda body: service.manual_control(
                    session_id,
                    "turn_mode_update",
                    body,
                    target_name=target,
                    auth_context=auth_context,
                ),
            )
        )

    @router.get("/sessions/{session_id}/events")
    async def events(
        session_id: str,
        target: str,
        request: Request,
        after: str | None = None,
    ):
        auth_context = context(request)
        return await _respond(
            lambda: service.events(
                session_id,
                target_name=target,
                auth_context=auth_context,
                after=after,
            )
        )

    @router.post("/sessions/{session_id}/approvals/{approval_id}")
    async def approval(session_id: str, approval_id: str, target: str, request: Request):
        auth_context = context(request)
        return await _respond(
            lambda: _with_body(
                request,
                lambda body: service.resolve_approval(
                    session_id,
                    approval_id,
                    body,
                    target_name=target,
                    auth_context=auth_context,
                ),
            )
        )

    @router.get("/conversations/{conversation_id}")
    async def conversation(conversation_id: str, target: str, request: Request):
        auth_context = context(request)
        return await _respond(
            lambda: service.conversation(
                conversation_id, target_name=target, auth_context=auth_context
            )
        )

    @router.get("/conversations/{conversation_id}/requests/{client_request_id}")
    async def request_result(
        conversation_id: str,
        client_request_id: str,
        target: str,
        request: Request,
    ):
        auth_context = context(request)
        return await _respond(
            lambda: service.request_result(
                conversation_id,
                client_request_id,
                target_name=target,
                auth_context=auth_context,
            ),
            outcome_unknown_status=200,
            rejected_status=200,
        )

    worker_base = "/conversations/{conversation_id}/worker-jobs"

    @router.get(worker_base)
    async def worker_jobs(conversation_id: str, target: str, request: Request):
        auth_context = context(request)
        return await _respond(
            lambda: service.worker_jobs(
                conversation_id, target_name=target, auth_context=auth_context
            )
        )

    @router.get(worker_base + "/{worker_job_id}")
    async def worker_job(
        conversation_id: str, worker_job_id: str, target: str, request: Request
    ):
        auth_context = context(request)
        return await _respond(
            lambda: service.worker_job(
                conversation_id,
                worker_job_id,
                target_name=target,
                auth_context=auth_context,
            )
        )

    @router.get(worker_base + "/{worker_job_id}/events")
    async def worker_events(
        conversation_id: str,
        worker_job_id: str,
        target: str,
        request: Request,
        after: int = 0,
    ):
        auth_context = context(request)
        return await _respond(
            lambda: service.worker_events(
                conversation_id,
                worker_job_id,
                after,
                target_name=target,
                auth_context=auth_context,
            )
        )

    for operation in ("refine", "redirect", "cancel"):
        router.add_api_route(
            worker_base + f"/{{worker_job_id}}/{operation}",
            _worker_command(service, auth, operation),
            methods=["POST"],
            name=f"realtime_worker_{operation}",
        )

    return router


def _session_action(service: RealtimeProxyService, auth: AuthGate, action: str):
    async def handler(session_id: str, target: str, request: Request):
        auth_context = auth.authenticate_http(request)
        return await _respond(
            lambda: _with_body(
                request,
                lambda body: service.session_action(
                    session_id,
                    action,
                    body,
                    target_name=target,
                    auth_context=auth_context,
                ),
            )
        )

    return handler


def _worker_command(service: RealtimeProxyService, auth: AuthGate, operation: str):
    async def handler(
        conversation_id: str,
        worker_job_id: str,
        target: str,
        request: Request,
    ):
        auth_context = auth.authenticate_http(request)
        return await _respond(
            lambda: _with_body(
                request,
                lambda body: service.worker_command(
                    conversation_id,
                    worker_job_id,
                    operation,
                    body,
                    target_name=target,
                    auth_context=auth_context,
                ),
            )
        )

    return handler


async def _read_json(request: Request, *, maximum: int = MAX_CONTROL_BODY_BYTES) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json" and not content_type.endswith("+json"):
        raise RealtimeProxyError(
            "unsupported_media_type", "Content-Type must be application/json", status=415
        )
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > maximum:
        raise RealtimeProxyError("request_too_large", "Request body exceeded the limit", status=413)
    try:
        async with asyncio.timeout(5):
            raw = await request.body()
    except TimeoutError as exc:
        raise RealtimeProxyError("request_timeout", "Request body timed out", status=408) from exc
    if len(raw) > maximum:
        raise RealtimeProxyError("request_too_large", "Request body exceeded the limit", status=413)
    try:
        document = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RealtimeProxyError("invalid_json", "Request body must be valid JSON", status=400) from exc
    if not isinstance(document, dict):
        raise RealtimeProxyError("invalid_request", "Request body must be an object", status=400)
    return document


async def _with_body(
    request: Request,
    operation: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    maximum: int = MAX_CONTROL_BODY_BYTES,
) -> dict[str, Any]:
    return await operation(await _read_json(request, maximum=maximum))


async def _compatibility_document(
    service: RealtimeProxyService, target_name: str
) -> dict[str, Any]:
    result = await service.compatibility(target_name)
    return result.public_dict()


async def _respond(
    operation: Callable[[], Awaitable[dict[str, Any]]],
    *,
    status: int = 200,
    outcome_unknown_status: int = 202,
    rejected_status: int = 409,
):
    try:
        document = await operation()
        resolved_status = (
            rejected_status
            if document.get("state") == "rejected"
            else outcome_unknown_status
            if document.get("state") == "outcome_unknown"
            else status
        )
        return JSONResponse(document, status_code=resolved_status)
    except RealtimeProxyError as exc:
        return JSONResponse(exc.public_dict(), status_code=exc.status)
    except ConfigError:
        error = RealtimeProxyError("target_not_found", "Target not found", status=404)
        return JSONResponse(error.public_dict(), status_code=error.status)
    except ValueError as exc:
        error = RealtimeProxyError("invalid_request", str(exc), status=400)
        return JSONResponse(error.public_dict(), status_code=error.status)
