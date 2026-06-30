from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
SAMPLE_RATE = 16_000
MAX_TURN_ID_LEN = 128
TURN_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
ALLOWED_APPROVAL_DECISIONS = {"once", "session", "always", "deny"}


@dataclass
class VoiceProtocolError(Exception):
    code: str
    message: str
    recoverable: bool = True

    def __str__(self) -> str:  # pragma: no cover - dataclass repr is noisy
        return f"{self.code}: {self.message}"


def validate_turn_id(turn_id: Any, *, required: bool = True) -> str:
    tid = "" if turn_id is None else str(turn_id).strip()
    if not tid:
        if required:
            raise VoiceProtocolError("bad_turn_id", "turn_id is required")
        return ""
    if len(tid) > MAX_TURN_ID_LEN:
        raise VoiceProtocolError("bad_turn_id", f"turn_id exceeds {MAX_TURN_ID_LEN} chars")
    if not TURN_ID_RE.match(tid):
        raise VoiceProtocolError(
            "bad_turn_id", "turn_id has invalid characters (allowed: A-Za-z0-9_.:-)"
        )
    return tid



def validate_session_key(value: Any, *, field: str = "session_key") -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise VoiceProtocolError("bad_session", f"{field} is required")
    if len(text) > 256:
        raise VoiceProtocolError("bad_session", f"{field} exceeds 256 chars")
    if any(ch in text for ch in ("\r", "\n", "\x00")):
        raise VoiceProtocolError("bad_session", f"{field} contains control characters")
    return text


def parse_json_frame(text: str) -> dict[str, Any]:
    try:
        msg = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise VoiceProtocolError("bad_json", "message was not valid JSON") from exc
    if not isinstance(msg, dict):
        raise VoiceProtocolError("bad_json", "message must be a JSON object")
    return msg


def validate_hello(msg: dict[str, Any]) -> dict[str, Any]:
    version = msg.get("version", PROTOCOL_VERSION)
    if version != PROTOCOL_VERSION:
        raise VoiceProtocolError(
            "unsupported_version",
            f"unsupported protocol version {version!r}; server speaks {PROTOCOL_VERSION}",
            recoverable=False,
        )
    mode = msg.get("mode", "push_to_talk")
    if mode not in {"push_to_talk", "half_duplex"}:
        raise VoiceProtocolError("unsupported_mode", f"unsupported mode {mode!r}")
    fmt = msg.get("input_format", "pcm16")
    if fmt != "pcm16":
        raise VoiceProtocolError("unsupported_format", f"unsupported input_format {fmt!r}")
    sample_rate = msg.get("input_sample_rate", SAMPLE_RATE)
    if sample_rate != SAMPLE_RATE:
        raise VoiceProtocolError(
            "unsupported_sample_rate",
            f"unsupported input_sample_rate {sample_rate!r}; server expects {SAMPLE_RATE}",
        )
    return msg


def error_frame(exc: VoiceProtocolError) -> dict[str, Any]:
    return {"type": "error", "code": exc.code, "message": exc.message, "recoverable": exc.recoverable}


def sanitize_provider_error(message: str) -> str:
    # Keep the browser message useful without echoing stack traces or likely secrets.
    text = " ".join(str(message).split())
    for marker in ("sk-", "Bearer ", "api_key", "API_KEY", "Authorization"):
        if marker in text:
            return "provider failed; check server logs and credentials"
    return text[:400] or "provider failed"
