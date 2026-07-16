from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, WebSocketDisconnect

from .contracts import require_identifier, validate_identifier
from .hermes_client import RealtimeProxyError

if TYPE_CHECKING:
    from ..app import ConsoleState

MAX_FRAME_CHARS = 96 * 1024
FIRST_FRAME_TIMEOUT = 10.0
FRAME_IDLE_TIMEOUT = 30.0
SEND_TIMEOUT = 5.0
POLL_SECONDS = 0.5


async def handle_realtime_socket(ws: WebSocket, state: ConsoleState) -> None:
    """Dedicated owner-scoped control and replay channel; it never carries media."""
    auth_context = await state.auth.authenticate_ws(ws)
    if auth_context is None:
        return
    send_lock = asyncio.Lock()
    closed = False

    async def send(payload: dict[str, Any]) -> None:
        nonlocal closed
        if closed:
            return
        try:
            async with send_lock, asyncio.timeout(SEND_TIMEOUT):
                await ws.send_json(payload)
        except (TimeoutError, RuntimeError, WebSocketDisconnect):
            closed = True
            with suppress(RuntimeError):
                await ws.close(code=4410, reason="Realtime control consumer is too slow")

    try:
        first = await _receive(ws, timeout=FIRST_FRAME_TIMEOUT)
        if first.get("type") != "subscribe":
            raise RealtimeProxyError("subscribe_required", "First control frame must subscribe", status=400)
        target = require_identifier(first, "target")
        conversation_id = require_identifier(first, "conversation_id")
        session_id = require_identifier(first, "realtime_session_id")
        after = first.get("after")
        if after is not None:
            validate_identifier(str(after), "after")
            after = str(after)
        session = await state.realtime.get_session(
            session_id, target_name=target, auth_context=auth_context
        )
        if session["conversation_id"] != conversation_id:
            raise RealtimeProxyError("resource_not_found", "The requested resource was not found", status=404)
        snapshot = await state.realtime.conversation(
            conversation_id, target_name=target, auth_context=auth_context
        )
        await send({"type": "snapshot", "snapshot": snapshot})
        cursor = snapshot.get("last_event_id")
        await send(
            {
                "type": "subscribed",
                "realtime_session_id": session_id,
                "after": cursor,
                "client_after": after,
                "cursor_rebased": after is not None and after != cursor,
            }
        )

        stop = asyncio.Event()

        async def replay_loop() -> None:
            nonlocal cursor
            while not stop.is_set() and not closed:
                try:
                    document = await state.realtime.events(
                        session_id,
                        target_name=target,
                        auth_context=auth_context,
                        after=cursor,
                    )
                    for event in document["events"]:
                        await send({"type": "event", "event": event})
                    cursor = document.get("last_event_id") or cursor
                except RealtimeProxyError as exc:
                    if exc.code == "event_replay_gap":
                        recovered = await state.realtime.conversation(
                            conversation_id, target_name=target, auth_context=auth_context
                        )
                        cursor = recovered.get("last_event_id")
                        await send({"type": "replay.gap", "snapshot": recovered, "after": cursor})
                    else:
                        await send(_error_frame(exc))
                        stop.set()
                        return
                await asyncio.sleep(POLL_SECONDS)

        replay_task = asyncio.create_task(replay_loop())
        idle_misses = 0
        try:
            while not closed:
                try:
                    frame = await _receive(ws, timeout=FRAME_IDLE_TIMEOUT)
                    idle_misses = 0
                except TimeoutError:
                    idle_misses += 1
                    if idle_misses >= 2:
                        await ws.close(code=4408, reason="Realtime control heartbeat timed out")
                        break
                    await send({"type": "heartbeat", "after": cursor})
                    continue
                kind = frame.get("type")
                if kind in {"ping", "heartbeat.ack"}:
                    await send({"type": "pong", "after": cursor})
                    continue
                request_id = require_identifier(frame, "client_request_id")
                if kind in {"input", "interrupt"}:
                    body = {
                        "client_request_id": request_id,
                        "session_generation": frame.get("session_generation"),
                    }
                    if kind == "input":
                        body["text"] = frame.get("text")
                    result = await state.realtime.session_action(
                        session_id, kind, body, target_name=target, auth_context=auth_context
                    )
                elif kind in {"manual_audio_commit", "turn_mode_update"}:
                    body = {
                        "client_request_id": request_id,
                        "session_generation": frame.get("session_generation"),
                    }
                    if kind == "turn_mode_update":
                        body["turn_mode"] = frame.get("turn_mode")
                    result = await state.realtime.manual_control(
                        session_id,
                        kind,
                        body,
                        target_name=target,
                        auth_context=auth_context,
                    )
                elif kind == "approval":
                    approval_id = require_identifier(frame, "approval_id")
                    result = await state.realtime.resolve_approval(
                        session_id,
                        approval_id,
                        {
                            "client_request_id": request_id,
                            "session_generation": frame.get("session_generation"),
                            "choice": frame.get("choice"),
                        },
                        target_name=target,
                        auth_context=auth_context,
                    )
                elif kind == "worker.command":
                    worker_job_id = require_identifier(frame, "worker_job_id")
                    operation = frame.get("operation")
                    if operation not in {"refine", "redirect", "cancel"}:
                        raise RealtimeProxyError("invalid_request", "Unsupported worker operation", status=400)
                    result = await state.realtime.worker_command(
                        conversation_id,
                        worker_job_id,
                        operation,
                        {
                            "command_id": request_id,
                            "expected_revision": frame.get("expected_revision"),
                            "payload": frame.get("payload", {}),
                        },
                        target_name=target,
                        auth_context=auth_context,
                    )
                else:
                    raise RealtimeProxyError("invalid_frame", "Unsupported control frame", status=400)
                await send({"type": "ack", "client_request_id": request_id, "result": result})
        finally:
            stop.set()
            replay_task.cancel()
            await asyncio.gather(replay_task, return_exceptions=True)
    except WebSocketDisconnect:
        return
    except (RealtimeProxyError, ValueError) as exc:
        error = exc if isinstance(exc, RealtimeProxyError) else RealtimeProxyError(
            "invalid_frame", str(exc), status=400
        )
        await send(_error_frame(error))
        if not closed:
            await ws.close(code=4400, reason="Invalid Realtime control request")
    except TimeoutError:
        await ws.close(code=4408, reason="Realtime control frame timed out")


async def _receive(ws: WebSocket, *, timeout: float) -> dict[str, Any]:
    async with asyncio.timeout(timeout):
        message = await ws.receive()
    if message.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    raw = message.get("text")
    if not isinstance(raw, str):
        raise RealtimeProxyError("invalid_frame", "Realtime control frames must be text", status=400)
    if len(raw) > MAX_FRAME_CHARS:
        raise RealtimeProxyError("frame_too_large", "Realtime control frame exceeded the limit", status=413)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RealtimeProxyError("invalid_frame", "Realtime control frame must be JSON", status=400) from exc
    if not isinstance(value, dict):
        raise RealtimeProxyError("invalid_frame", "Realtime control frame must be an object", status=400)
    return value


def _error_frame(exc: RealtimeProxyError) -> dict[str, Any]:
    return {"type": "error", **exc.public_dict()["error"]}
