from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .audio import OwnedAudioStore
from .auth import AuthGate
from .config import (
    ConfigError,
    ConsoleConfig,
    TargetsConfig,
    load_console_config,
    load_env_file,
    load_targets_config,
)
from .hermes_client import ApiRunsTransport, HermesApiClient, HermesApiError
from .protocol import (
    ALLOWED_APPROVAL_DECISIONS,
    VoiceProtocolError,
    error_frame,
    parse_json_frame,
    sanitize_provider_error,
    validate_hello,
    validate_session_key,
    validate_turn_id,
)
from .providers import ProviderUnavailable, SttProvider, TtsProvider, make_stt_provider, make_tts_provider
from .voice_session import RecordingSession

log = logging.getLogger(__name__)


@dataclass
class ConsoleState:
    config: ConsoleConfig
    targets: TargetsConfig
    auth: AuthGate
    audio_store: OwnedAudioStore
    stt: SttProvider
    tts: TtsProvider


async def _send_json(ws: WebSocket, lock: asyncio.Lock, payload: dict[str, Any]) -> None:
    async with lock:
        await ws.send_json(payload)


async def _send_bytes(ws: WebSocket, lock: asyncio.Lock, payload: bytes) -> None:
    async with lock:
        await ws.send_bytes(payload)


def _app_state(request_or_ws: Request | WebSocket) -> ConsoleState:
    return request_or_ws.app.state.console_state


def create_app(
    *,
    config_path: str | Path = "config/voice.yaml",
    targets_path: str | Path = "config/targets.yaml",
    env_path: str | Path | None = ".env",
    static_dir: str | Path | None = "frontend/dist",
) -> FastAPI:
    load_env_file(env_path)
    config = load_console_config(config_path)
    targets = load_targets_config(targets_path)
    state = ConsoleState(
        config=config,
        targets=targets,
        auth=AuthGate(required=config.server.auth_required),
        audio_store=OwnedAudioStore(config.voice.temp_dir),
        stt=make_stt_provider(config.voice.stt_provider),
        tts=make_tts_provider(config.voice.tts_provider),
    )

    app = FastAPI(title="Hermes Voice Console", version="0.1.0")
    app.state.console_state = state

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "hermes-voice-console",
            "auth_required": state.config.server.auth_required,
            "warnings": state.auth.startup_warnings(),
        }

    @app.get("/api/bootstrap")
    async def bootstrap(request: Request) -> dict[str, Any]:
        state.auth.require_http(request)
        return {
            "server": {
                "public_base_url": state.config.server.public_base_url,
                "auth_required": state.config.server.auth_required,
            },
            "voice": {
                "stt_provider": state.stt.name,
                "tts_provider": state.tts.name,
                "sample_rate": state.config.voice.sample_rate,
                "max_recording_seconds": state.config.voice.max_recording_seconds,
                "speak_replies_default": state.config.voice.speak_replies_default,
            },
            "targets": state.targets.public_list(),
        }

    @app.get("/api/targets")
    async def list_targets(request: Request) -> dict[str, Any]:
        state.auth.require_http(request)
        return {"targets": state.targets.public_list()}

    @app.get("/api/targets/{target_name}/health")
    async def target_health(target_name: str, request: Request) -> dict[str, Any]:
        state.auth.require_http(request)
        try:
            target = state.targets.require(target_name)
            client = HermesApiClient(target, timeout=state.config.server.request_timeout_seconds)
            caps = await client.capabilities()
            health_doc = await client.health()
            return {"target": target.public_dict(), "health": health_doc, "capabilities": caps.public_dict(), "ok": True}
        except ConfigError as exc:
            return {"target": {"name": target_name}, "ok": False, "error": str(exc)}
        except Exception as exc:
            target_doc = target.public_dict() if "target" in locals() else {"name": target_name}
            return {"target": target_doc, "ok": False, "error": sanitize_provider_error(str(exc))}

    @app.websocket("/ws/voice")
    async def voice_ws(ws: WebSocket) -> None:
        state = _app_state(ws)
        if not await state.auth.require_ws(ws):
            return
        await ws.accept()
        send_lock = asyncio.Lock()
        session = RecordingSession(state.config.voice)
        hello_received = False
        target_name = ws.query_params.get("target") or state.targets.first_name()
        target = None
        session_id = ws.query_params.get("session_id") or "voice-console"
        session_key = ws.query_params.get("session_key") or session_id
        transport: ApiRunsTransport | None = None
        active_run_id: str | None = None
        agent_task: asyncio.Task | None = None
        tts_task: asyncio.Task | None = None
        recording_timeout_task: asyncio.Task | None = None
        speak_replies = state.config.voice.speak_replies_default

        async def send_error(exc: VoiceProtocolError) -> None:
            await _send_json(ws, send_lock, error_frame(exc))

        async def synthesize_and_send(turn_id: str, text: str) -> None:
            if not text.strip() or session.is_cancelled(turn_id):
                return
            if len(text) > state.config.voice.max_tts_text_chars:
                await send_error(VoiceProtocolError("text_too_long", f"TTS text exceeds {state.config.voice.max_tts_text_chars} chars"))
                return
            audio_path = None
            try:
                audio = await state.tts.synthesize(text, config=state.config.voice, store=state.audio_store)
                audio_path = audio.path
                path = state.audio_store.validate_for_stream(audio.path, max_bytes=state.config.voice.max_tts_audio_bytes)
                if session.is_cancelled(turn_id):
                    return
                await _send_json(ws, send_lock, {"type": "tts.start", "turn_id": turn_id, "mime": audio.mime, "provider": audio.provider})
                with path.open("rb") as fh:
                    while True:
                        if session.is_cancelled(turn_id):
                            break
                        chunk = fh.read(32 * 1024)
                        if not chunk:
                            break
                        await _send_bytes(ws, send_lock, chunk)
                if not session.is_cancelled(turn_id):
                    await _send_json(ws, send_lock, {"type": "tts.end", "turn_id": turn_id})
            except asyncio.CancelledError:
                session.cancel(turn_id)
                raise
            except ProviderUnavailable as exc:
                await send_error(VoiceProtocolError("tts_unavailable", sanitize_provider_error(str(exc))))
            except VoiceProtocolError as exc:
                await send_error(exc)
            except Exception:
                log.exception("unexpected TTS failure")
                await send_error(VoiceProtocolError("internal_error", "internal voice error"))
            finally:
                if audio_path:
                    state.audio_store.cleanup(audio_path, retain=state.config.voice.retain_audio_debug)
                session.forget_cancel(turn_id)

        async def run_agent_turn(turn_id: str, text: str) -> None:
            nonlocal active_run_id, tts_task
            assert transport is not None
            final_text = ""
            try:
                async for event in transport.send_turn(session_id=session_id, session_key=session_key, text=text):
                    if event.get("type") == "agent.run.started":
                        active_run_id = str(event.get("run_id") or "")
                    if event.get("type") == "agent.completed":
                        final_text = str(event.get("text") or "")
                    await _send_json(ws, send_lock, event)
                if speak_replies and final_text.strip() and not session.is_cancelled(turn_id):
                    tts_task = asyncio.create_task(synthesize_and_send(turn_id, final_text))
            except HermesApiError as exc:
                await send_error(VoiceProtocolError("target_error", sanitize_provider_error(str(exc))))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("unexpected Hermes target failure")
                await send_error(VoiceProtocolError("internal_error", "internal target error"))

        async def recording_timeout(turn_id: str) -> None:
            await asyncio.sleep(state.config.voice.max_recording_wall_seconds)
            if session.expire_if_active(turn_id):
                await send_error(VoiceProtocolError("recording_timeout", "recording exceeded max wall-clock duration"))

        async def finish_recording(turn_id: str) -> None:
            nonlocal agent_task, recording_timeout_task
            if recording_timeout_task and not recording_timeout_task.done():
                recording_timeout_task.cancel()
            active_turn, pcm = session.stop_recording(turn_id)
            await _send_json(ws, send_lock, {"type": "recording.stopped", "turn_id": active_turn})
            try:
                transcript = await state.stt.transcribe(pcm, config=state.config.voice, store=state.audio_store)
            except ProviderUnavailable as exc:
                await send_error(VoiceProtocolError("stt_unavailable", sanitize_provider_error(str(exc))))
                return
            except VoiceProtocolError as exc:
                await send_error(exc)
                return
            except Exception:
                log.exception("unexpected STT failure")
                await send_error(VoiceProtocolError("internal_error", "internal voice error"))
                return
            await _send_json(
                ws,
                send_lock,
                {"type": "transcript.final", "turn_id": active_turn, "text": transcript.text, "provider": transcript.provider},
            )
            if transcript.text.strip():
                if agent_task and not agent_task.done():
                    await send_error(VoiceProtocolError("agent_busy", "A Hermes run is already active; stop it before starting another turn"))
                    return
                agent_task = asyncio.create_task(run_agent_turn(active_turn, transcript.text))

        try:
            while True:
                frame = await ws.receive()
                if frame.get("type") == "websocket.disconnect":
                    break
                if "bytes" in frame and frame["bytes"] is not None:
                    if not hello_received:
                        await send_error(VoiceProtocolError("no_hello", "send hello before audio frames"))
                        continue
                    try:
                        session.add_audio(frame["bytes"])
                    except VoiceProtocolError as exc:
                        await send_error(exc)
                    continue
                text = frame.get("text")
                if text is None:
                    continue
                try:
                    msg = parse_json_frame(text)
                    mtype = msg.get("type")
                    if mtype == "ping":
                        await _send_json(ws, send_lock, {"type": "pong"})
                        continue
                    if mtype == "hello":
                        if hello_received:
                            raise VoiceProtocolError("duplicate_hello", "hello is only allowed once per connection", recoverable=False)
                        validate_hello(msg)
                        requested_target = str(msg.get("target") or target_name or "")
                        if not requested_target:
                            raise VoiceProtocolError("target_required", "hello.target is required")
                        target = state.targets.require(requested_target)
                        session_id = validate_session_key(msg.get("session_id") or target.default_session_key, field="session_id")
                        session_key = validate_session_key(msg.get("session_key") or target.default_session_key, field="session_key")
                        speak_replies = bool(msg.get("speak_replies", state.config.voice.speak_replies_default))
                        client = HermesApiClient(target, timeout=state.config.server.request_timeout_seconds)
                        transport = ApiRunsTransport(client)
                        caps = await transport.capabilities()
                        if not caps.supports_runs():
                            raise VoiceProtocolError("target_capability_missing", "target lacks required runs/event capabilities", recoverable=False)
                        hello_received = True
                        await _send_json(
                            ws,
                            send_lock,
                            {
                                "type": "ready",
                                "target": target.name,
                                "session_id": session_id,
                                "capabilities": caps.public_dict(),
                                "stt_provider": state.stt.name,
                                "tts_provider": state.tts.name,
                                "speak_replies": speak_replies,
                            },
                        )
                        continue
                    if not hello_received:
                        raise VoiceProtocolError("no_hello", "send hello before other messages")
                    if mtype == "recording.start":
                        if agent_task and not agent_task.done():
                            raise VoiceProtocolError("agent_busy", "A Hermes run is already active; stop it before recording again")
                        tid = validate_turn_id(msg.get("turn_id"), required=True)
                        session.start_recording(tid)
                        if recording_timeout_task and not recording_timeout_task.done():
                            recording_timeout_task.cancel()
                        recording_timeout_task = asyncio.create_task(recording_timeout(tid))
                        await _send_json(ws, send_lock, {"type": "recording.started", "turn_id": tid})
                    elif mtype == "recording.stop":
                        tid = validate_turn_id(msg.get("turn_id"), required=True)
                        await finish_recording(tid)
                    elif mtype == "approval.resolve":
                        if transport is None:
                            raise VoiceProtocolError("bad_state", "target is not ready")
                        run_id = str(msg.get("run_id") or active_run_id or "")
                        decision = str(msg.get("decision") or "").strip().lower()
                        if not run_id:
                            raise VoiceProtocolError("bad_run_id", "run_id is required")
                        if decision not in ALLOWED_APPROVAL_DECISIONS:
                            raise VoiceProtocolError("bad_approval_decision", "decision must be once, session, always, or deny")
                        result = await transport.approve(run_id, decision)
                        await _send_json(ws, send_lock, {"type": "agent.approval.resolved", "run_id": run_id, "result": result})
                    elif mtype == "agent.stop":
                        if transport is None:
                            raise VoiceProtocolError("bad_state", "target is not ready")
                        run_id = str(msg.get("run_id") or active_run_id or "")
                        if not run_id:
                            raise VoiceProtocolError("bad_run_id", "run_id is required")
                        result = await transport.stop(run_id)
                        if agent_task and not agent_task.done():
                            agent_task.cancel()
                        await _send_json(ws, send_lock, {"type": "agent.stop.requested", "run_id": run_id, "result": result})
                    elif mtype == "tts.cancel":
                        tid = validate_turn_id(msg.get("turn_id"), required=False)
                        session.cancel(tid)
                        if tts_task and not tts_task.done():
                            tts_task.cancel()
                        await _send_json(ws, send_lock, {"type": "tts.cancelled", "turn_id": tid})
                    else:
                        raise VoiceProtocolError("unknown_type", f"unknown message type: {mtype!r}")
                except ConfigError as exc:
                    await send_error(VoiceProtocolError("bad_target", str(exc), recoverable=False))
                except HermesApiError as exc:
                    await send_error(VoiceProtocolError("target_error", sanitize_provider_error(str(exc))))
                except VoiceProtocolError as exc:
                    await send_error(exc)
                except Exception:
                    log.exception("unexpected websocket error")
                    await send_error(VoiceProtocolError("internal_error", "internal voice error"))
        except WebSocketDisconnect:
            pass
        finally:
            for task in (agent_task, tts_task, recording_timeout_task):
                if task and not task.done():
                    task.cancel()

    static_path = Path(static_dir) if static_dir else None
    if static_path and static_path.exists():
        app.mount("/assets", StaticFiles(directory=static_path / "assets"), name="assets")
        voice_public = static_path / "voice"
        if voice_public.exists():
            app.mount("/voice", StaticFiles(directory=voice_public), name="voice")

        @app.get("/{path:path}")
        async def spa(path: str) -> FileResponse:  # noqa: ARG001
            return FileResponse(static_path / "index.html")

    return app
