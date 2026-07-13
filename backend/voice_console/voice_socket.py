from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, WebSocketDisconnect

from .auth import AuthFailure
from .config import ConfigError, TargetConfig
from .diagnostics import diagnostic
from .hermes_client import ApiRunsTransport, HermesApiClient, HermesApiError
from .protocol import (
    ALLOWED_APPROVAL_DECISIONS,
    VoiceProtocolError,
    error_frame,
    parse_json_frame,
    sanitize_provider_error,
    validate_hello,
    validate_input_text,
    validate_turn_id,
)
from .providers import ProviderUnavailable
from .run_coordinator import AcceptanceUnknown
from .run_store import SessionRecord
from .tts_session import TtsSession
from .voice_filters import filter_transcript, validate_spoken_audio
from .voice_session import RecordingSession

if TYPE_CHECKING:
    from .app import ConsoleState

log = logging.getLogger(__name__)


def _safe_approval_event(event: dict[str, Any], *, persistent_enabled: bool) -> dict[str, Any]:
    if event.get("type") != "agent.approval.request":
        return event
    approval = event.get("approval")
    if not isinstance(approval, dict):
        return event
    choices = approval.get("choices")
    allow_permanent = approval.get("allow_permanent") is True and persistent_enabled
    if isinstance(choices, list):
        choices = [choice for choice in choices if choice != "always" or allow_permanent]
    return {
        **event,
        "approval": {**approval, "choices": choices, "allow_permanent": allow_permanent},
    }


async def handle_voice_socket(ws: WebSocket, state: ConsoleState) -> None:
    """Run one authenticated browser subscription over backend-owned Hermes runs."""

    auth_context = await state.auth.authenticate_ws(ws)
    if auth_context is None:
        return
    socket_started_at = time.monotonic()
    audio_chunks = 0
    audio_bytes = 0
    diagnostic(log, "socket.authenticated", principal=auth_context.audit_subject)

    send_lock = asyncio.Lock()
    recording_session = RecordingSession(state.config.voice)
    hello_received = False
    target: TargetConfig | None = None
    session: SessionRecord | None = None
    subscription_task: asyncio.Task[None] | None = None
    subscription_queue: asyncio.Queue[dict[str, Any] | None] | None = None
    subscribed_run_id: str | None = None
    recording_timeout_task: asyncio.Task[None] | None = None
    speak_replies = state.config.voice.speak_replies_default
    auth_watchdog_task: asyncio.Task[None] | None = None

    async def send_json(payload: dict[str, Any]) -> None:
        async with send_lock:
            await ws.send_json(payload)

    async def send_bytes(payload: bytes) -> None:
        async with send_lock:
            await ws.send_bytes(payload)

    async def send_error(exc: VoiceProtocolError) -> None:
        await send_json(error_frame(exc))

    async def auth_watchdog() -> None:
        nonlocal auth_context
        while auth_context.expires_at:
            observed_expiry = auth_context.expires_at
            notice_at = observed_expiry - state.config.auth.refresh_notice_seconds
            await asyncio.sleep(max(0, notice_at - time.time()))
            if auth_context.expires_at != observed_expiry:
                continue
            await send_json({"type": "auth.expiring", "expires_at": observed_expiry})
            close_at = observed_expiry + state.config.auth.clock_skew_seconds
            await asyncio.sleep(max(0, close_at - time.time()))
            if auth_context.expires_at == observed_expiry:
                await ws.close(code=4401, reason="Authentication expired")
                return

    if auth_context.expires_at:
        auth_watchdog_task = asyncio.create_task(auth_watchdog())

    tts_session = TtsSession(
        config=state.config.voice,
        provider=state.tts,
        audio_store=state.audio_store,
        recording_session=recording_session,
        send_json=send_json,
        send_bytes=send_bytes,
        send_error=send_error,
    )

    async def stream_subscription(
        run_id: str,
        turn_id: str,
        queue: asyncio.Queue[dict[str, Any] | None],
        *,
        allow_tts: bool,
    ) -> None:
        final_text = ""
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                event = _safe_approval_event(
                    event,
                    persistent_enabled=state.config.auth.allow_persistent_approvals,
                )
                if event.get("type") == "agent.completed":
                    final_text = str(event.get("text") or "")
                await send_json(event)
            if (
                allow_tts
                and speak_replies
                and final_text.strip()
                and not recording_session.is_cancelled(turn_id)
            ):
                tts_session.start(turn_id, final_text)
        finally:
            state.runs.unsubscribe(run_id, queue)

    async def begin_run(turn_id: str, text: str) -> None:
        nonlocal subscription_task, subscription_queue, subscribed_run_id
        assert target is not None and session is not None
        diagnostic(
            log,
            "run.submit.requested",
            turn_id=turn_id,
            conversation_id=session.conversation_id,
            target=target.name,
            input_chars=len(text),
        )
        try:
            record, queue = await state.runs.start(
                target=target,
                session=session,
                turn_id=turn_id,
                text=text,
            )
            assert record.run_id
            diagnostic(log, "run.submit.accepted", turn_id=turn_id, run_id=record.run_id)
            subscription_queue = queue
            subscribed_run_id = record.run_id
            subscription_task = asyncio.create_task(
                stream_subscription(record.run_id, turn_id, queue, allow_tts=True)
            )
        except AcceptanceUnknown as exc:
            await send_json(
                {
                    "type": "run.acceptance_unknown",
                    "turn_id": turn_id,
                    "local_turn_id": exc.local_turn_id,
                    "message": "Hermes may have accepted this turn. The conversation remains locked and the turn will not be retried automatically.",
                }
            )
        except RuntimeError as exc:
            await send_error(VoiceProtocolError("conversation_locked", str(exc)))
        except HermesApiError as exc:
            await send_error(VoiceProtocolError("target_error", sanitize_provider_error(str(exc))))
        except Exception:
            log.exception("unexpected Hermes run submission failure")
            await send_error(VoiceProtocolError("internal_error", "internal target error"))

    async def recording_timeout(turn_id: str) -> None:
        await asyncio.sleep(state.config.voice.max_recording_wall_seconds)
        if recording_session.expire_if_active(turn_id):
            diagnostic(log, "recording.timeout", level=logging.WARNING, turn_id=turn_id)
            await send_error(
                VoiceProtocolError(
                    "recording_timeout",
                    "recording exceeded max wall-clock duration",
                )
            )

    async def finish_recording(turn_id: str) -> None:
        nonlocal recording_timeout_task
        if recording_timeout_task and not recording_timeout_task.done():
            recording_timeout_task.cancel()
        active_turn, pcm = recording_session.stop_recording(turn_id)
        diagnostic(
            log,
            "recording.stopped",
            turn_id=active_turn,
            pcm_bytes=len(pcm),
            audio_chunks=audio_chunks,
            duration_ms=round(len(pcm) / (state.config.voice.sample_rate * 2) * 1000),
        )
        await send_json({"type": "recording.stopped", "turn_id": active_turn})
        stt_started_at = time.monotonic()
        try:
            validate_spoken_audio(pcm, state.config.voice)
            transcript = await state.stt.transcribe(
                pcm,
                config=state.config.voice,
                store=state.audio_store,
            )
        except ProviderUnavailable as exc:
            await send_error(
                VoiceProtocolError("stt_unavailable", sanitize_provider_error(str(exc)))
            )
            return
        except VoiceProtocolError as exc:
            await send_error(exc)
            return
        except Exception:
            log.exception("unexpected STT failure")
            await send_error(VoiceProtocolError("internal_error", "internal voice error"))
            return

        text = validate_input_text(
            filter_transcript(transcript.text),
            max_chars=state.config.voice.max_input_text_chars,
        )
        diagnostic(
            log,
            "stt.completed",
            turn_id=active_turn,
            provider=transcript.provider,
            model=state.config.voice.openai_stt_model if transcript.provider == "openai" else None,
            latency_ms=round((time.monotonic() - stt_started_at) * 1000),
            transcript_chars=len(text),
        )
        await send_json(
            {
                "type": "transcript.final",
                "turn_id": active_turn,
                "text": text,
                "provider": transcript.provider,
            }
        )
        asyncio.create_task(begin_run(active_turn, text))

    try:
        while True:
            frame = await ws.receive()
            if frame.get("type") == "websocket.disconnect":
                break
            if frame.get("bytes") is not None:
                if not hello_received:
                    await send_error(
                        VoiceProtocolError("no_hello", "send hello before audio frames")
                    )
                    continue
                try:
                    audio_chunks += 1
                    audio_bytes += len(frame["bytes"])
                    if audio_chunks % 25 == 0:
                        diagnostic(
                            log,
                            "recording.audio.progress",
                            level=logging.DEBUG,
                            turn_id=recording_session.turn_id,
                            audio_chunks=audio_chunks,
                            pcm_bytes=audio_bytes,
                        )
                    recording_session.add_audio(frame["bytes"])
                except VoiceProtocolError as exc:
                    await send_error(exc)
                continue

            text = frame.get("text")
            if text is None:
                continue
            try:
                if len(text) > state.config.server.max_ws_text_chars:
                    raise VoiceProtocolError(
                        "frame_too_large",
                        "WebSocket text frame exceeds the configured limit",
                        recoverable=False,
                    )
                message = parse_json_frame(text)
                message_type = message.get("type")
                if message_type == "auth.refresh":
                    try:
                        auth_context = state.auth.refresh(message.get("token"), auth_context)
                    except AuthFailure as exc:
                        await ws.close(code=exc.ws_code, reason=exc.message)
                        break
                    await send_json(
                        {"type": "auth.refreshed", "expires_at": auth_context.expires_at}
                    )
                    continue
                if message_type == "ping":
                    await send_json({"type": "pong"})
                    continue
                if message_type == "hello":
                    if hello_received:
                        raise VoiceProtocolError(
                            "duplicate_hello",
                            "hello is only allowed once per connection",
                            recoverable=False,
                        )
                    validate_hello(message)
                    requested_target = str(message.get("target") or "")
                    conversation_id = str(message.get("conversation_id") or "")
                    if not requested_target or not conversation_id:
                        raise VoiceProtocolError(
                            "session_required",
                            "hello.target and hello.conversation_id are required",
                        )
                    target = state.targets.require(requested_target)
                    try:
                        session = state.sessions.require(
                            conversation_id,
                            auth_context=auth_context,
                            target=target,
                        )
                    except KeyError as exc:
                        raise VoiceProtocolError(
                            "session_not_found", "owned conversation was not found"
                        ) from exc
                    speak_replies = bool(
                        message.get("speak_replies", state.config.voice.speak_replies_default)
                    )
                    transport = ApiRunsTransport(
                        HermesApiClient(
                            target,
                            timeout=state.config.server.request_timeout_seconds,
                        )
                    )
                    capabilities = await transport.capabilities()
                    if not capabilities.supports_runs():
                        raise VoiceProtocolError(
                            "target_capability_missing",
                            "target lacks required runs/event capabilities",
                            recoverable=False,
                        )
                    hello_received = True
                    await send_json(
                        {
                            "type": "ready",
                            "target": target.name,
                            "conversation_id": session.conversation_id,
                            "capabilities": capabilities.public_dict(),
                            "stt_provider": state.stt.name,
                            "tts_provider": state.tts.name,
                            "speak_replies": speak_replies,
                        }
                    )
                    resume_run_id = str(message.get("resume_run_id") or "")
                    locked_run = state.store.active_run_for_conversation(
                        session.conversation_id,
                        owner_key=state.sessions.owner_key(auth_context, target),
                    )
                    if locked_run and locked_run.status == "acceptance_unknown":
                        await send_json(
                            {
                                "type": "run.acceptance_unknown",
                                "turn_id": locked_run.turn_id,
                                "local_turn_id": locked_run.local_turn_id,
                                "message": "Hermes may have accepted this turn. The conversation remains locked and the turn will not be retried automatically.",
                            }
                        )
                    elif locked_run and locked_run.status == "unrecoverable":
                        await send_json(
                            {
                                "type": "run.unrecoverable",
                                "run_id": locked_run.run_id,
                                "turn_id": locked_run.turn_id,
                                "error": "Hermes no longer exposes this run; acknowledgement is required",
                            }
                        )
                    elif not resume_run_id and locked_run and locked_run.run_id:
                        resume_run_id = locked_run.run_id
                    if resume_run_id:
                        owner_key = state.sessions.owner_key(auth_context, target)
                        queue = state.runs.subscribe(
                            run_id=resume_run_id,
                            owner_key=owner_key,
                            last_sequence=int(message.get("last_sequence") or 0),
                        )
                        subscribed_run_id = resume_run_id
                        subscription_queue = queue
                        subscription_task = asyncio.create_task(
                            stream_subscription(
                                resume_run_id,
                                "recovered",
                                queue,
                                allow_tts=False,
                            )
                        )
                    diagnostic(
                        log,
                        "socket.ready",
                        target=target.name,
                        conversation_id=session.conversation_id,
                        stt_provider=state.stt.name,
                        tts_provider=state.tts.name,
                        speak_replies=speak_replies,
                        resumed=bool(resume_run_id),
                    )
                    continue

                if not hello_received or target is None or session is None:
                    raise VoiceProtocolError("no_hello", "send hello before other messages")
                owner_key = state.sessions.owner_key(auth_context, target)
                if message_type == "recording.start":
                    active = state.store.active_run_for_conversation(
                        session.conversation_id, owner_key=owner_key
                    )
                    if active:
                        raise VoiceProtocolError(
                            "conversation_locked",
                            f"conversation is locked by {active.status}",
                        )
                    turn_id = validate_turn_id(message.get("turn_id"), required=True)
                    audio_chunks = 0
                    audio_bytes = 0
                    recording_session.start_recording(turn_id)
                    if recording_timeout_task and not recording_timeout_task.done():
                        recording_timeout_task.cancel()
                    recording_timeout_task = asyncio.create_task(recording_timeout(turn_id))
                    await send_json({"type": "recording.started", "turn_id": turn_id})
                    diagnostic(log, "recording.started", turn_id=turn_id)
                elif message_type == "recording.stop":
                    turn_id = validate_turn_id(message.get("turn_id"), required=True)
                    await finish_recording(turn_id)
                elif message_type == "recording.cancel":
                    turn_id = validate_turn_id(message.get("turn_id"), required=True)
                    if recording_timeout_task and not recording_timeout_task.done():
                        recording_timeout_task.cancel()
                    discarded = recording_session.discard_recording(turn_id)
                    await send_json({"type": "recording.discarded", "turn_id": turn_id})
                    diagnostic(
                        log,
                        "recording.discarded",
                        turn_id=turn_id,
                        discarded=discarded,
                        pcm_bytes=audio_bytes,
                    )
                elif message_type == "text.submit":
                    active = state.store.active_run_for_conversation(
                        session.conversation_id, owner_key=owner_key
                    )
                    if active:
                        raise VoiceProtocolError(
                            "conversation_locked",
                            f"conversation is locked by {active.status}",
                        )
                    turn_id = validate_turn_id(message.get("turn_id"), required=True)
                    input_text = validate_input_text(
                        message.get("text"),
                        max_chars=state.config.voice.max_input_text_chars,
                    )
                    await send_json({"type": "text.accepted", "turn_id": turn_id})
                    asyncio.create_task(begin_run(turn_id, input_text))
                elif message_type == "approval.resolve":
                    run_id = str(message.get("run_id") or subscribed_run_id or "")
                    decision = str(message.get("decision") or "").strip().lower()
                    if not run_id:
                        raise VoiceProtocolError("bad_run_id", "run_id is required")
                    if decision not in ALLOWED_APPROVAL_DECISIONS:
                        raise VoiceProtocolError(
                            "bad_approval_decision",
                            "decision must be once, session, always, or deny",
                        )
                    if decision == "always" and not state.config.auth.allow_persistent_approvals:
                        raise VoiceProtocolError(
                            "persistent_approval_disabled",
                            "persistent approvals are disabled by deployment policy",
                        )
                    try:
                        await state.runs.approve(run_id, decision, owner_key=owner_key)
                    except RuntimeError as exc:
                        raise VoiceProtocolError("approval_unavailable", str(exc)) from exc
                elif message_type == "agent.stop":
                    run_id = str(message.get("run_id") or subscribed_run_id or "")
                    if not run_id:
                        raise VoiceProtocolError("bad_run_id", "run_id is required")
                    await state.runs.stop(run_id, owner_key=owner_key)
                elif message_type == "run.acceptance_unknown.acknowledge":
                    local_turn_id = str(message.get("local_turn_id") or "")
                    if not local_turn_id:
                        raise VoiceProtocolError("bad_run_id", "local_turn_id is required")
                    state.runs.acknowledge_unknown(local_turn_id, owner_key=owner_key)
                    await send_json(
                        {
                            "type": "run.acceptance_unknown.acknowledged",
                            "local_turn_id": local_turn_id,
                        }
                    )
                elif message_type == "run.unrecoverable.acknowledge":
                    run_id = str(message.get("run_id") or "")
                    if not run_id:
                        raise VoiceProtocolError("bad_run_id", "run_id is required")
                    state.runs.acknowledge_unrecoverable(run_id, owner_key=owner_key)
                    await send_json({"type": "run.unrecoverable.acknowledged", "run_id": run_id})
                elif message_type == "tts.cancel":
                    turn_id = validate_turn_id(message.get("turn_id"), required=False)
                    await tts_session.cancel(turn_id)
                else:
                    raise VoiceProtocolError(
                        "unknown_type", f"unknown message type: {message_type!r}"
                    )
            except ConfigError as exc:
                await send_error(VoiceProtocolError("bad_target", str(exc), recoverable=False))
            except HermesApiError as exc:
                await send_error(
                    VoiceProtocolError("target_error", sanitize_provider_error(str(exc)))
                )
            except VoiceProtocolError as exc:
                await send_error(exc)
            except Exception:
                log.exception("unexpected websocket error")
                await send_error(VoiceProtocolError("internal_error", "internal voice error"))
    except WebSocketDisconnect:
        pass
    finally:
        if subscription_task and not subscription_task.done():
            subscription_task.cancel()
        if subscribed_run_id and subscription_queue:
            state.runs.unsubscribe(subscribed_run_id, subscription_queue)
        for task in (recording_timeout_task, auth_watchdog_task):
            if task and not task.done():
                task.cancel()
        tts_session.close()
        diagnostic(
            log,
            "socket.closed",
            principal=auth_context.audit_subject,
            lifetime_ms=round((time.monotonic() - socket_started_at) * 1000),
            subscribed_run_id=subscribed_run_id,
        )
