from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:  # python-dotenv is a runtime dependency, but keep a tiny fallback for tests.
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]


PLACEHOLDER_VALUES = {"", "replace_me", "replace_me_with_a_random_value", "changeme", "todo"}


class ConfigError(ValueError):
    """Raised when console configuration is invalid or unsafe."""


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


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8787
    public_base_url: str = "http://localhost:8787"
    auth_required: bool = True
    request_timeout_seconds: int = 120


@dataclass(frozen=True)
class VoiceConfig:
    stt_provider: str = "fake"
    tts_provider: str = "fake"
    sample_rate: int = 16_000
    max_recording_seconds: int = 120
    max_recording_wall_seconds: int = 180
    max_buffer_mb: int = 25
    max_tts_text_chars: int = 8_000
    max_tts_audio_mb: int = 50
    speak_replies_default: bool = False
    retain_audio_debug: bool = False
    temp_dir: str | None = None
    fake_transcript: str = "hello hermes"
    openai_stt_model: str = "whisper-1"
    groq_stt_model: str = "whisper-large-v3-turbo"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    edge_tts_voice: str = "en-US-AriaNeural"
    elevenlabs_voice_id: str = ""

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
            "base_url": self.base_url,
            "default_session_key": self.default_session_key,
            "preferred_transport": self.preferred_transport,
            "api_key_configured": self.api_key_present,
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
    vraw = raw.get("voice") or {}
    if not isinstance(sraw, dict) or not isinstance(vraw, dict):
        raise ConfigError("server and voice config sections must be mappings")
    server = ServerConfig(
        host=str(sraw.get("host", "127.0.0.1")),
        port=_int(sraw.get("port"), 8787, minimum=1),
        public_base_url=str(sraw.get("public_base_url", "http://localhost:8787")),
        auth_required=_bool(sraw.get("auth_required"), True),
        request_timeout_seconds=_int(sraw.get("request_timeout_seconds"), 120, minimum=5),
    )
    voice = VoiceConfig(
        stt_provider=str(vraw.get("stt_provider", "fake")).strip().lower(),
        tts_provider=str(vraw.get("tts_provider", "fake")).strip().lower(),
        sample_rate=_int(vraw.get("sample_rate"), 16_000, minimum=8_000),
        max_recording_seconds=_int(vraw.get("max_recording_seconds"), 120, minimum=1),
        max_recording_wall_seconds=_int(vraw.get("max_recording_wall_seconds"), 180, minimum=1),
        max_buffer_mb=_int(vraw.get("max_buffer_mb"), 25, minimum=1),
        max_tts_text_chars=_int(vraw.get("max_tts_text_chars"), 8_000, minimum=1),
        max_tts_audio_mb=_int(vraw.get("max_tts_audio_mb"), 50, minimum=1),
        speak_replies_default=_bool(vraw.get("speak_replies_default"), False),
        retain_audio_debug=_bool(vraw.get("retain_audio_debug"), False),
        temp_dir=(str(vraw.get("temp_dir")).strip() if vraw.get("temp_dir") else None),
        fake_transcript=str(vraw.get("fake_transcript", "hello hermes")),
        openai_stt_model=str(vraw.get("openai_stt_model", "whisper-1")),
        groq_stt_model=str(vraw.get("groq_stt_model", "whisper-large-v3-turbo")),
        openai_tts_model=str(vraw.get("openai_tts_model", "gpt-4o-mini-tts")),
        openai_tts_voice=str(vraw.get("openai_tts_voice", "alloy")),
        edge_tts_voice=str(vraw.get("edge_tts_voice", "en-US-AriaNeural")),
        elevenlabs_voice_id=str(vraw.get("elevenlabs_voice_id", "")),
    )
    if voice.sample_rate != 16_000:
        raise ConfigError("V1 voice protocol requires sample_rate: 16000")
    return ConsoleConfig(server=server, voice=voice)


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
