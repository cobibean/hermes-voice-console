from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SUPPORTED_CONTRACT_MAJOR = 1
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

REQUIRED_FEATURES = frozenset(
    {
        "realtime_voice",
        "realtime_sideband_tools",
        "realtime_conversation_snapshot",
        "realtime_durable_event_replay",
        "realtime_worker_jobs",
        "realtime_worker_job_commands",
        "realtime_exactly_once_worker_projection",
    }
)

REQUIRED_ENDPOINTS = {
    "/v1/realtime/sessions": "POST",
    "/v1/realtime/sessions/{session_id}": "GET|DELETE",
    "/v1/realtime/sessions/{session_id}/activate": "POST",
    "/v1/realtime/sessions/{session_id}/input": "POST",
    "/v1/realtime/sessions/{session_id}/commit": "POST",
    "/v1/realtime/sessions/{session_id}/discard": "POST",
    "/v1/realtime/sessions/{session_id}/turn-mode": "POST",
    "/v1/realtime/sessions/{session_id}/interrupt": "POST",
    "/v1/realtime/sessions/{session_id}/events": "GET",
    "/v1/realtime/sessions/{session_id}/approvals/{approval_id}": "POST",
    "/v1/realtime/conversations/{conversation_id}": "GET",
    "/v1/realtime/conversations/{conversation_id}/requests/{client_request_id}": "GET",
    "/v1/realtime/conversations/{conversation_id}/worker-jobs": "GET",
    "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}": "GET",
    "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/events": "GET",
    "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/commands/{command_id}": "GET",
    "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/refine": "POST",
    "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/redirect": "POST",
    "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/cancel": "POST",
}


@dataclass(frozen=True)
class RealtimeCompatibility:
    compatible: bool
    version: str | None
    reasons: tuple[str, ...]
    contract: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "version": self.version,
            "reasons": list(self.reasons),
            "contract": self.contract,
        }


def check_realtime_compatibility(capabilities: Mapping[str, Any]) -> RealtimeCompatibility:
    contracts = capabilities.get("contracts")
    raw = contracts.get("realtime") if isinstance(contracts, Mapping) else None
    if not isinstance(raw, Mapping):
        return RealtimeCompatibility(False, None, ("missing contracts.realtime",), {})

    contract = _safe_contract(raw)
    version = raw.get("version")
    version_text = str(version) if isinstance(version, (str, int, float)) else None
    reasons: list[str] = []
    try:
        major = int((version_text or "").split(".", 1)[0])
    except ValueError:
        major = -1
    if major != SUPPORTED_CONTRACT_MAJOR:
        reasons.append(
            f"unsupported contracts.realtime major {version_text or 'missing'}; expected 1.x"
        )
    if raw.get("sideband_authority") != "server":
        reasons.append("top-level server sideband authority is missing")
    models = raw.get("models")
    if not isinstance(models, list) or "gpt-realtime-2.1" not in models:
        reasons.append("top-level Realtime model availability is missing")

    features_value = capabilities.get("features")
    features = {
        str(name) for name, enabled in features_value.items() if enabled is True
    } if isinstance(features_value, Mapping) else set()
    missing_features = sorted(REQUIRED_FEATURES - features)
    if missing_features:
        reasons.append("missing Realtime features: " + ", ".join(missing_features))

    endpoints = capabilities.get("endpoints")
    advertised: dict[str, set[str]] = {}
    if isinstance(endpoints, Mapping):
        for item in endpoints.values():
            if isinstance(item, Mapping) and item.get("path") and item.get("method"):
                advertised.setdefault(str(item["path"]), set()).add(str(item["method"]).upper())
    contract_endpoints = raw.get("endpoints")
    if isinstance(contract_endpoints, Mapping):
        for item in contract_endpoints.values():
            if isinstance(item, Mapping) and item.get("path") and item.get("method"):
                advertised.setdefault(str(item["path"]), set()).add(str(item["method"]).upper())
    missing_endpoints = []
    for path, methods in REQUIRED_ENDPOINTS.items():
        expected = set(methods.split("|"))
        if not expected.issubset(advertised.get(path, set())):
            missing_endpoints.append(f"{methods} {path}")
    if missing_endpoints:
        reasons.append("missing Realtime endpoints: " + ", ".join(missing_endpoints))

    provider = raw.get("provider")
    if (
        not isinstance(provider, Mapping)
        or provider.get("id") != "openai"
        or provider.get("model") != "gpt-realtime-2.1"
    ):
        reasons.append("gpt-realtime-2.1 is not advertised")
    media = raw.get("media")
    if not isinstance(media, Mapping) or any(
        media.get(key) != expected
        for key, expected in {
            "transport": "webrtc",
            "bootstrap": "unified_sdp",
            "sideband_authority": "server",
            "create_readiness": "controller_ready_before_sdp",
        }.items()
    ):
        reasons.append("required server-controlled WebRTC bootstrap is missing")

    sessions = raw.get("sessions")
    if not isinstance(sessions, Mapping) or not all(
        sessions.get(name) is True
        for name in (
            "rotation",
            "conversation_snapshot",
            "text_input",
            "manual_audio_commit",
            "manual_audio_discard",
            "speech_interrupt",
            "turn_mode_update",
        )
    ):
        reasons.append("required Realtime session recovery and control behavior is missing")
    elif not {"server_vad", "manual"}.issubset(set(sessions.get("turn_modes") or [])):
        reasons.append("required Realtime turn modes are missing")
    events = raw.get("events")
    if not isinstance(events, Mapping) or not all(
        events.get(name) is True for name in ("replay", "durable")
    ):
        reasons.append("durable event replay is missing")
    elif events.get("cursor") != "event_id" or events.get("gap_error") != "event_replay_gap":
        reasons.append("required event cursor or replay-gap behavior is missing")
    tools = raw.get("tools")
    if (
        not isinstance(tools, Mapping)
        or tools.get("execution") != "server"
        or not isinstance(tools.get("direct_allowlist"), list)
        or tools.get("delegation_tool") != "delegate_work"
        or tools.get("raw_delegate_task_exposed") is not False
    ):
        reasons.append("required server tool authority or delegation boundary is missing")
    workers = raw.get("workers")
    commands = workers.get("commands") if isinstance(workers, Mapping) else None
    delivery = workers.get("delivery") if isinstance(workers, Mapping) else None
    if (
        not isinstance(workers, Mapping)
        or workers.get("lead_model") != "gpt-5.6-sol"
        or not isinstance(workers.get("max_concurrency"), int)
        or int(workers.get("max_concurrency", 0)) < 1
        or not isinstance(workers.get("max_fanout"), int)
        or int(workers.get("max_fanout", 0)) < 1
        or workers.get("queue") != "fifo_per_conversation"
        or workers.get("ownership") != "conversation_path"
        or workers.get("optimistic_revision") is not True
        or not isinstance(commands, list)
        or not {"refine", "redirect", "cancel"}.issubset(commands)
        or workers.get("command_result_lookup") is not True
        or not isinstance(delivery, Mapping)
        or delivery.get("realtime_projection") != "exactly_once_durable_inbox"
    ):
        reasons.append("durable conversation-owned worker controls are missing")
    approvals = raw.get("approvals")
    pending_fields = approvals.get("pending_snapshot_fields") if isinstance(approvals, Mapping) else None
    if (
        not isinstance(approvals, Mapping)
        or approvals.get("server_authoritative") is not True
        or not {"once", "deny"}.issubset(set(approvals.get("choices") or []))
        or pending_fields
        != ["approval_id", "state", "tool_call_id", "tool_name", "expires_at"]
    ):
        reasons.append("server-authoritative approvals are missing")
    routing = raw.get("routing_policy")
    if not isinstance(routing, Mapping) or any(
        routing.get(key) != expected
        for key, expected in {
            "persona_model": "gpt-realtime-2.1",
            "substantial_work": "delegate",
            "default_fanout": 1,
            "confirmation": "announce_without_prompting",
        }.items()
    ):
        reasons.append("required persona dispatch routing policy is missing")
    retention = raw.get("retention")
    if not isinstance(retention, Mapping) or not all(
        isinstance(retention.get(key), (int, float)) and retention.get(key) > 0
        for key in ("event_count", "event_bytes", "context_bytes", "completed_item_days")
    ):
        reasons.append("bounded Realtime retention policy is missing")
    timeouts = raw.get("timeouts")
    if not isinstance(timeouts, Mapping) or not all(
        isinstance(timeouts.get(key), (int, float)) and timeouts.get(key) > 0
        for key in (
            "provider_request_seconds",
            "controller_ready_seconds",
            "tool_seconds",
            "worker_seconds",
            "approval_seconds",
        )
    ):
        reasons.append("bounded Realtime timeout policy is missing")

    return RealtimeCompatibility(not reasons, version_text, tuple(reasons), contract)


def _safe_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    allowed: dict[str, tuple[str, ...]] = {
        "media": ("transport", "bootstrap", "sideband_authority", "create_readiness"),
        "provider": ("id", "model", "voice", "reasoning_effort"),
        "sessions": (
            "rotation", "conversation_snapshot", "text_input", "manual_audio_commit",
            "manual_audio_discard", "speech_interrupt", "turn_modes", "turn_mode_update",
        ),
        "events": ("replay", "durable", "cursor", "gap_error"),
        "tools": ("execution", "direct_allowlist", "delegation_tool", "raw_delegate_task_exposed"),
        "workers": ("lead_model", "max_concurrency", "max_fanout", "queue", "commands", "command_result_lookup", "ownership", "optimistic_revision", "delivery"),
        "approvals": ("server_authoritative", "choices", "pending_snapshot_fields"),
        "routing_policy": ("persona_model", "substantial_work", "default_fanout", "confirmation"),
        "retention": ("event_count", "event_bytes", "context_bytes", "completed_item_days"),
        "timeouts": ("provider_request_seconds", "controller_ready_seconds", "tool_seconds", "worker_seconds", "approval_seconds"),
    }

    def primitive(value: Any) -> Any:
        if isinstance(value, str):
            lowered = value.lower()
            if any(marker in lowered for marker in ("sk-", "bearer ", "api_key", "token=", "http://", "https://")):
                return "[redacted]"
            return value[:200]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return [primitive(item) for item in value[:100] if isinstance(item, (str, int, float, bool))]
        if isinstance(value, Mapping):
            return {
                str(key): primitive(item)
                for key, item in value.items()
                if isinstance(key, str)
                and key in {"realtime_projection", "external_claims"}
            }
        return None

    result: dict[str, Any] = {
        "version": primitive(raw.get("version")),
        "sideband_authority": primitive(raw.get("sideband_authority")),
        "models": primitive(raw.get("models")),
    }
    for section, keys in allowed.items():
        value = raw.get(section)
        if isinstance(value, Mapping):
            result[section] = {key: primitive(value.get(key)) for key in keys if key in value}
    return result


def require_nonempty_string(
    body: Mapping[str, Any], key: str, *, maximum: int = 128
) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{key} exceeds the {maximum}-character limit")
    return value


def require_identifier(body: Mapping[str, Any], key: str) -> str:
    value = require_nonempty_string(body, key)
    return validate_identifier(value, key)


def validate_identifier(value: str, field: str = "identifier") -> str:
    if value in {".", ".."} or not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field} contains invalid characters")
    return value


def validate_generation(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("session_generation must be a positive integer")
    return value


def validate_sdp(value: str) -> str:
    if not value.startswith("v=0") or "\x00" in value:
        raise ValueError("sdp_offer is not a valid SDP offer")
    return value
