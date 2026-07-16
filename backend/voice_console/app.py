from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .audio import OwnedAudioStore
from .auth import AuthContext, AuthGate
from .config import (
    ConfigError,
    ConsoleConfig,
    TargetsConfig,
    load_console_config,
    load_env_file,
    load_targets_config,
)
from .hermes_client import HermesApiClient
from .protocol import sanitize_provider_error
from .providers import (
    SttProvider,
    TtsProvider,
    make_stt_provider,
    make_tts_provider,
)
from .realtime import RealtimeProxyService, create_realtime_router
from .run_coordinator import RunCoordinator
from .run_store import ConsoleStore
from .session_manager import SessionManager
from .voice_socket import handle_voice_socket


@dataclass
class ConsoleState:
    config: ConsoleConfig
    targets: TargetsConfig
    auth: AuthGate
    audio_store: OwnedAudioStore
    stt: SttProvider
    tts: TtsProvider
    store: ConsoleStore
    sessions: SessionManager
    runs: RunCoordinator
    realtime: RealtimeProxyService


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
    if config.auth.mode.value == "clerk" and len(config.auth.allowed_user_ids) != 1:
        fixed_scope_targets = [
            target.name for target in targets.targets.values() if target.fixed_memory_session_key
        ]
        if fixed_scope_targets:
            raise ConfigError(
                "fixed_memory_session_key requires exactly one allowed Clerk user; unsafe targets: "
                + ", ".join(fixed_scope_targets)
            )
    auth = AuthGate(
        config.auth,
        public_base_url=config.server.public_base_url,
        allowed_hosts=config.server.allowed_hosts,
    )
    store = ConsoleStore(config.server.state_dir)
    sessions = SessionManager(store, auth)
    runs = RunCoordinator(
        store=store,
        sessions=sessions,
        targets=targets,
        max_events=config.server.max_run_events,
        terminal_retention_seconds=config.server.terminal_retention_seconds,
    )
    realtime = RealtimeProxyService(
        targets=targets,
        sessions=sessions,
        request_timeout_seconds=config.server.request_timeout_seconds,
    )
    state = ConsoleState(
        config=config,
        targets=targets,
        auth=auth,
        audio_store=OwnedAudioStore(config.voice.temp_dir),
        stt=make_stt_provider(config.voice.stt_provider),
        tts=make_tts_provider(config.voice.tts_provider),
        store=store,
        sessions=sessions,
        runs=runs,
        realtime=realtime,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await state.runs.recover()
        try:
            yield
        finally:
            await state.runs.close()
            state.store.close()

    app = FastAPI(title="Hermes Voice Console", version="0.1.0", lifespan=lifespan)
    app.state.console_state = state
    app.include_router(create_realtime_router(state.realtime, state.auth))

    @app.middleware("http")
    async def exposure_guard(request: Request, call_next):
        if not state.auth.validate_host(request.headers.get("host")):
            return JSONResponse({"detail": "Host is not allowed"}, status_code=400)
        origin = request.headers.get("origin")
        if origin and not state.auth.validate_origin(origin, required=False):
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "hermes-voice-console",
            "auth_mode": state.auth.mode.value,
        }

    @app.get("/api/public-config")
    async def public_config() -> dict[str, Any]:
        return state.auth.public_config()

    @app.get("/api/bootstrap")
    async def bootstrap(request: Request) -> dict[str, Any]:
        auth_context: AuthContext = state.auth.authenticate_http(request)
        return {
            "server": {
                "public_base_url": state.config.server.public_base_url,
                "auth_mode": state.auth.mode.value,
            },
            "principal": {
                "kind": auth_context.principal_kind,
                "owner_key": auth_context.owner_key[:10],
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
        state.auth.authenticate_http(request)
        return {"targets": state.targets.public_list()}

    @app.get("/api/targets/{target_name}/health")
    async def target_health(target_name: str, request: Request) -> dict[str, Any]:
        state.auth.authenticate_http(request)
        try:
            target = state.targets.require(target_name)
            client = HermesApiClient(
                target,
                timeout=state.config.server.request_timeout_seconds,
            )
            capabilities = await client.capabilities()
            health_document = await client.health()
            return {
                "target": target.public_dict(),
                "health": health_document,
                "capabilities": capabilities.public_dict(),
                "ok": True,
            }
        except ConfigError as exc:
            return {"target": {"name": target_name}, "ok": False, "error": str(exc)}
        except Exception as exc:
            target_document = (
                target.public_dict() if "target" in locals() else {"name": target_name}
            )
            return {
                "target": target_document,
                "ok": False,
                "error": sanitize_provider_error(str(exc)),
            }

    @app.get("/api/sessions")
    async def list_sessions(target: str, request: Request) -> dict[str, Any]:
        auth_context = state.auth.authenticate_http(request)
        target_config = state.targets.require(target)
        sessions = state.sessions.list(auth_context=auth_context, target=target_config)
        return {"sessions": [state.sessions.public(session) for session in sessions]}

    @app.post("/api/sessions", status_code=201)
    async def create_session(request: Request) -> dict[str, Any]:
        auth_context = state.auth.authenticate_http(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise ConfigError("session request must be an object")
        target_config = state.targets.require(str(body.get("target") or ""))
        session = await state.sessions.create(
            auth_context=auth_context,
            target=target_config,
            title=str(body.get("title") or "New conversation"),
        )
        return state.sessions.public(session)

    @app.get("/api/sessions/{conversation_id}/messages")
    async def session_messages(
        conversation_id: str,
        target: str,
        request: Request,
    ) -> dict[str, Any]:
        auth_context = state.auth.authenticate_http(request)
        target_config = state.targets.require(target)
        session = state.sessions.require(
            conversation_id,
            auth_context=auth_context,
            target=target_config,
        )
        resolved, messages = await state.sessions.history(session, target=target_config)
        return {
            "conversation_id": resolved.conversation_id,
            "messages": messages,
        }

    @app.websocket("/ws/voice")
    async def voice_ws(ws: WebSocket) -> None:
        if not state.auth.validate_websocket_scheme(ws.url.scheme):
            await ws.close(code=4403, reason="Secure WebSocket transport is required")
            return
        if not state.auth.validate_host(ws.headers.get("host")):
            await ws.close(code=4403, reason="Host is not allowed")
            return
        if not state.auth.validate_origin(
            ws.headers.get("origin"),
            required=False,
        ):
            await ws.close(code=4403, reason="Origin is not allowed")
            return
        await handle_voice_socket(ws, state)

    if static_dir == "auto":
        source_static = Path("frontend/dist")
        packaged_static = Path(__file__).parent / "static"
        static_path = source_static if source_static.exists() else packaged_static
    else:
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
