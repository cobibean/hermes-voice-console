from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

try:  # python-dotenv is a runtime dependency, but keep a tiny fallback for tests.
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]


PLACEHOLDER_VALUES = {"", "replace_me", "replace_me_with_a_random_value", "changeme", "todo"}


class ConfigError(ValueError):
    """Raised when console configuration is invalid or unsafe."""


class AuthMode(StrEnum):
    CLERK = "clerk"
    SERVICE = "service"
    DEVELOPMENT = "development"


def load_env_file(path: str | Path | None) -> None:
    if not path:
        return
    p = Path(path)
    if not p.exists():
        return
    if load_dotenv is not None:
        load_dotenv(p, override=False)
        return
    for raw in p.read_text().splitlines():  # pragma: no cover - fallback only
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _read_yaml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"configuration file not found: {p}")
    data = yaml.safe_load(p.read_text()) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"configuration file must contain a mapping: {p}")
    return data


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int(value: Any, default: int, *, minimum: int | None = None) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        out = default
    if minimum is not None:
        out = max(minimum, out)
    return out


def _float(value: Any, default: float, *, minimum: float | None = None) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        out = default
    if minimum is not None:
        out = max(minimum, out)
    return out


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8787
    public_base_url: str = "http://localhost:8787"
    request_timeout_seconds: int = 120
    allowed_hosts: tuple[str, ...] = ()
    max_ws_text_chars: int = 65_536
    state_dir: str = "~/.local/state/hermes-voice-console"
    terminal_retention_seconds: int = 7_200
    max_run_events: int = 250


@dataclass(frozen=True)
class AuthConfig:
    mode: AuthMode = AuthMode.DEVELOPMENT
    clerk_publishable_key: str | None = None
    clerk_issuer: str | None = None
    clerk_jwks_url: str | None = None
    allowed_user_ids: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()
    service_token_env: str = "VOICE_CONSOLE_SERVICE_TOKEN"
    scope_secret_env: str = "VOICE_CONSOLE_SCOPE_SECRET"
    auth_timeout_seconds: int = 5
    preauth_max_chars: int = 8_192
    clock_skew_seconds: int = 5
    refresh_notice_seconds: int = 15
    allow_persistent_approvals: bool = False


@dataclass(frozen=True)
class VoiceConfig:
    stt_provider: str = "fake"
    tts_provider: str = "fake"
    sample_rate: int = 16_000
    max_recording_seconds: int = 120
    max_recording_wall_seconds: int = 180
    max_buffer_mb: int = 25
    max_tts_text_chars: int = 8_000
    max_input_text_chars: int = 16_000
    max_tts_audio_mb: int = 50
    speak_replies_default: bool = False
    retain_audio_debug: bool = False
    temp_dir: str | None = None
    fake_transcript: str = "hello hermes"
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    openai_stt_language: str = ""
    groq_stt_model: str = "whisper-large-v3-turbo"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    edge_tts_voice: str = "en-US-AriaNeural"
    elevenlabs_voice_id: str = ""
    min_recording_seconds: float = 0.25
    min_recording_rms: int = 90
    tts_sentence_max_chars: int = 420
    tts_chunk_timeout_seconds: int = 45

    @property
    def max_buffer_bytes(self) -> int:
        return self.max_buffer_mb * 1024 * 1024

    @property
    def max_tts_audio_bytes(self) -> int:
        return self.max_tts_audio_mb * 1024 * 1024

    @property
    def duration_cap_bytes(self) -> int:
        return self.max_recording_seconds * self.sample_rate * 2

    @property
    def max_recording_bytes(self) -> int:
        return min(self.max_buffer_bytes, self.duration_cap_bytes)


@dataclass(frozen=True)
class ConsoleConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)


@dataclass(frozen=True)
class TargetVoiceConfig:
    tts_voice: str = "default"


@dataclass(frozen=True)
class TargetConfig:
    name: str
    label: str
    base_url: str
    api_key_env: str
    default_session_key: str
    preferred_transport: str = "runs"
    configured_provider_label: str | None = None
    configured_model_label: str | None = None
    memory_scope_prefix: str = "voice-console"
    fixed_memory_session_key: str | None = None
    voice: TargetVoiceConfig = field(default_factory=TargetVoiceConfig)

    @property
    def api_key_present(self) -> bool:
        return bool(self.resolve_api_key())

    def resolve_api_key(self) -> str | None:
        value = os.environ.get(self.api_key_env, "").strip()
        return value or None

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "preferred_transport": self.preferred_transport,
            "api_key_configured": self.api_key_present,
            "configured_provider_label": self.configured_provider_label,
            "configured_model_label": self.configured_model_label,
            "voice": {"tts_voice": self.voice.tts_voice},
        }


@dataclass(frozen=True)
class TargetsConfig:
    targets: dict[str, TargetConfig]

    def first_name(self) -> str | None:
        return next(iter(self.targets), None)

    def require(self, name: str) -> TargetConfig:
        try:
            return self.targets[name]
        except KeyError as exc:
            raise ConfigError(f"unknown target: {name}") from exc

    def public_list(self) -> list[dict[str, Any]]:
        return [target.public_dict() for target in self.targets.values()]


def load_console_config(path: str | Path) -> ConsoleConfig:
    raw = _read_yaml(path)
    sraw = raw.get("server") or {}
    araw = raw.get("auth") or {}
    vraw = raw.get("voice") or {}
    if not isinstance(sraw, dict) or not isinstance(araw, dict) or not isinstance(vraw, dict):
        raise ConfigError("server, auth, and voice config sections must be mappings")
    public_base_url = str(sraw.get("public_base_url", "http://localhost:8787")).rstrip("/")
    parsed_public_url = urlparse(public_base_url)
    if parsed_public_url.scheme not in {"http", "https"} or not parsed_public_url.hostname:
        raise ConfigError("server.public_base_url must be an absolute http(s) URL")
    raw_allowed_hosts = sraw.get("allowed_hosts") or []
    if not isinstance(raw_allowed_hosts, list):
        raise ConfigError("server.allowed_hosts must be a list")
    allowed_hosts = tuple(
        dict.fromkeys(
            [
                parsed_public_url.hostname,
                *[str(value).strip().lower() for value in raw_allowed_hosts if str(value).strip()],
            ]
        )
    )
    server = ServerConfig(
        host=str(sraw.get("host", "127.0.0.1")),
        port=_int(sraw.get("port"), 8787, minimum=1),
        public_base_url=public_base_url,
        request_timeout_seconds=_int(sraw.get("request_timeout_seconds"), 120, minimum=5),
        allowed_hosts=allowed_hosts,
        max_ws_text_chars=_int(sraw.get("max_ws_text_chars"), 65_536, minimum=1_024),
        state_dir=str(
            os.environ.get("VOICE_CONSOLE_STATE_DIR")
            or sraw.get("state_dir")
            or "~/.local/state/hermes-voice-console"
        ),
        terminal_retention_seconds=_int(sraw.get("terminal_retention_seconds"), 7_200, minimum=60),
        max_run_events=_int(sraw.get("max_run_events"), 250, minimum=10),
    )
    legacy_auth_required = sraw.get("auth_required")
    default_mode = "service" if _bool(legacy_auth_required, False) else "development"
    try:
        auth_mode = AuthMode(str(araw.get("mode", default_mode)).strip().lower())
    except ValueError as exc:
        raise ConfigError("auth.mode must be clerk, service, or development") from exc
    raw_origins = araw.get("allowed_origins") or []
    raw_user_ids = araw.get("allowed_user_ids") or []
    if not isinstance(raw_origins, list) or not isinstance(raw_user_ids, list):
        raise ConfigError("auth.allowed_origins and auth.allowed_user_ids must be lists")
    auth = AuthConfig(
        mode=auth_mode,
        clerk_publishable_key=(
            str(araw.get("clerk_publishable_key")).strip()
            if araw.get("clerk_publishable_key")
            else None
        ),
        clerk_issuer=(
            str(araw.get("clerk_issuer")).strip().rstrip("/") if araw.get("clerk_issuer") else None
        ),
        clerk_jwks_url=(
            str(araw.get("clerk_jwks_url")).strip() if araw.get("clerk_jwks_url") else None
        ),
        allowed_user_ids=tuple(str(value).strip() for value in raw_user_ids if str(value).strip()),
        allowed_origins=tuple(
            str(value).strip().rstrip("/") for value in raw_origins if str(value).strip()
        ),
        service_token_env=str(araw.get("service_token_env", "VOICE_CONSOLE_SERVICE_TOKEN")).strip(),
        scope_secret_env=str(araw.get("scope_secret_env", "VOICE_CONSOLE_SCOPE_SECRET")).strip(),
        auth_timeout_seconds=_int(araw.get("auth_timeout_seconds"), 5, minimum=1),
        preauth_max_chars=_int(araw.get("preauth_max_chars"), 8_192, minimum=512),
        clock_skew_seconds=_int(araw.get("clock_skew_seconds"), 5, minimum=0),
        refresh_notice_seconds=_int(araw.get("refresh_notice_seconds"), 15, minimum=1),
        allow_persistent_approvals=_bool(araw.get("allow_persistent_approvals"), False),
    )
    _validate_exposure(server, auth)
    voice = VoiceConfig(
        stt_provider=str(vraw.get("stt_provider", "fake")).strip().lower(),
        tts_provider=str(vraw.get("tts_provider", "fake")).strip().lower(),
        sample_rate=_int(vraw.get("sample_rate"), 16_000, minimum=8_000),
        max_recording_seconds=_int(vraw.get("max_recording_seconds"), 120, minimum=1),
        max_recording_wall_seconds=_int(vraw.get("max_recording_wall_seconds"), 180, minimum=1),
        max_buffer_mb=_int(vraw.get("max_buffer_mb"), 25, minimum=1),
        max_tts_text_chars=_int(vraw.get("max_tts_text_chars"), 8_000, minimum=1),
        max_input_text_chars=_int(vraw.get("max_input_text_chars"), 16_000, minimum=1),
        max_tts_audio_mb=_int(vraw.get("max_tts_audio_mb"), 50, minimum=1),
        speak_replies_default=_bool(vraw.get("speak_replies_default"), False),
        retain_audio_debug=_bool(vraw.get("retain_audio_debug"), False),
        temp_dir=(str(vraw.get("temp_dir")).strip() if vraw.get("temp_dir") else None),
        fake_transcript=str(vraw.get("fake_transcript", "hello hermes")),
        openai_stt_model=str(vraw.get("openai_stt_model", "gpt-4o-mini-transcribe")),
        openai_stt_language=str(vraw.get("openai_stt_language", "")).strip(),
        groq_stt_model=str(vraw.get("groq_stt_model", "whisper-large-v3-turbo")),
        openai_tts_model=str(vraw.get("openai_tts_model", "gpt-4o-mini-tts")),
        openai_tts_voice=str(vraw.get("openai_tts_voice", "alloy")),
        edge_tts_voice=str(vraw.get("edge_tts_voice", "en-US-AriaNeural")),
        elevenlabs_voice_id=str(vraw.get("elevenlabs_voice_id", "")),
        min_recording_seconds=_float(vraw.get("min_recording_seconds"), 0.25, minimum=0.05),
        min_recording_rms=_int(vraw.get("min_recording_rms"), 90, minimum=0),
        tts_sentence_max_chars=_int(vraw.get("tts_sentence_max_chars"), 420, minimum=80),
        tts_chunk_timeout_seconds=_int(vraw.get("tts_chunk_timeout_seconds"), 45, minimum=5),
    )
    if voice.sample_rate != 16_000:
        raise ConfigError("V1 voice protocol requires sample_rate: 16000")
    return ConsoleConfig(server=server, auth=auth, voice=voice)


def _is_loopback(host: str | None) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"}


def _validate_exposure(server: ServerConfig, auth: AuthConfig) -> None:
    public_url = urlparse(server.public_base_url)
    if not _is_loopback(public_url.hostname) and public_url.scheme != "https":
        raise ConfigError("non-loopback public_base_url must use HTTPS")
    if auth.mode is AuthMode.DEVELOPMENT and (
        not _is_loopback(server.host) or not _is_loopback(public_url.hostname)
    ):
        raise ConfigError("development auth requires loopback bind and public_base_url")
    if auth.mode is AuthMode.CLERK:
        if not auth.clerk_publishable_key or not auth.clerk_issuer:
            raise ConfigError("Clerk mode requires clerk_publishable_key and clerk_issuer")
        issuer = urlparse(auth.clerk_issuer)
        if issuer.scheme != "https" or not issuer.hostname:
            raise ConfigError("auth.clerk_issuer must be an exact HTTPS URL")
        if not auth.allowed_origins:
            raise ConfigError("Clerk mode requires a non-empty exact allowed_origins list")


def load_targets_config(path: str | Path) -> TargetsConfig:
    raw = _read_yaml(path)
    targets_raw = raw.get("targets") or {}
    if not isinstance(targets_raw, dict) or not targets_raw:
        raise ConfigError("targets config must contain at least one target")
    targets: dict[str, TargetConfig] = {}
    for name, item in targets_raw.items():
        if not isinstance(item, dict):
            raise ConfigError(f"target {name!r} must be a mapping")
        label = str(item.get("label") or name)
        base_url = str(item.get("base_url") or "").rstrip("/")
        api_key_env = str(item.get("api_key_env") or "").strip()
        default_session_key = str(item.get("default_session_key") or f"voice-console:{name}")
        if not base_url:
            raise ConfigError(f"target {name!r} missing base_url")
        if not api_key_env:
            raise ConfigError(f"target {name!r} missing api_key_env")
        voice_raw = item.get("voice") or {}
        if not isinstance(voice_raw, dict):
            raise ConfigError(f"target {name!r} voice section must be a mapping")
        targets[str(name)] = TargetConfig(
            name=str(name),
            label=label,
            base_url=base_url,
            api_key_env=api_key_env,
            default_session_key=default_session_key,
            preferred_transport=str(item.get("preferred_transport") or "runs"),
            configured_provider_label=(
                str(item.get("configured_provider_label")).strip()
                if item.get("configured_provider_label")
                else None
            ),
            configured_model_label=(
                str(item.get("configured_model_label")).strip()
                if item.get("configured_model_label")
                else None
            ),
            memory_scope_prefix=str(item.get("memory_scope_prefix") or "voice-console"),
            fixed_memory_session_key=(
                str(item.get("fixed_memory_session_key")).strip()
                if item.get("fixed_memory_session_key")
                else None
            ),
            voice=TargetVoiceConfig(tts_voice=str(voice_raw.get("tts_voice") or "default")),
        )
    return TargetsConfig(targets=targets)


def secret_is_usable(value: str | None, *, min_length: int = 16) -> bool:
    if not value:
        return False
    v = value.strip()
    if v.lower() in PLACEHOLDER_VALUES:
        return False
    return len(v) >= min_length


def redacted_env_status(env_name: str) -> dict[str, Any]:
    value = os.environ.get(env_name, "")
    return {
        "env": env_name,
        "configured": bool(value.strip()),
        "redacted": f"{value[:4]}…{value[-4:]}" if len(value) >= 12 else None,
    }
