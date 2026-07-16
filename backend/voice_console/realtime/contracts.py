from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SUPPORTED_CONTRACT_MAJOR = 1

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

REQUIRED_ENDPOINT_PATHS = frozenset(
    {
        "/v1/realtime/sessions",
        "/v1/realtime/sessions/{session_id}",
        "/v1/realtime/sessions/{session_id}/activate",
        "/v1/realtime/sessions/{session_id}/input",
        "/v1/realtime/sessions/{session_id}/interrupt",
        "/v1/realtime/sessions/{session_id}/events",
        "/v1/realtime/sessions/{session_id}/approvals/{approval_id}",
        "/v1/realtime/conversations/{conversation_id}",
        "/v1/realtime/conversations/{conversation_id}/worker-jobs",
        "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}",
        "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/events",
        "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/refine",
        "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/redirect",
        "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/cancel",
    }
)


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

    features_value = capabilities.get("features")
    features = {
        str(name) for name, enabled in features_value.items() if enabled is True
    } if isinstance(features_value, Mapping) else set()
    missing_features = sorted(REQUIRED_FEATURES - features)
    if missing_features:
        reasons.append("missing Realtime features: " + ", ".join(missing_features))

    endpoints = capabilities.get("endpoints")
    paths = {
        str(item.get("path"))
        for item in endpoints.values()
        if isinstance(endpoints, Mapping) and isinstance(item, Mapping) and item.get("path")
    } if isinstance(endpoints, Mapping) else set()
    contract_endpoints = raw.get("endpoints")
    if isinstance(contract_endpoints, Mapping):
        paths.update(
            str(item.get("path"))
            for item in contract_endpoints.values()
            if isinstance(item, Mapping) and item.get("path")
        )
    missing_paths = sorted(REQUIRED_ENDPOINT_PATHS - paths)
    if missing_paths:
        reasons.append("missing Realtime endpoints: " + ", ".join(missing_paths))

    provider = raw.get("provider")
    if not isinstance(provider, Mapping) or provider.get("model") != "gpt-realtime-2.1":
        reasons.append("gpt-realtime-2.1 is not advertised")
    media = raw.get("media")
    if not isinstance(media, Mapping) or media.get("sideband_authority") != "server":
        reasons.append("server sideband authority is not advertised")

    sessions = raw.get("sessions")
    if not isinstance(sessions, Mapping) or not all(
        sessions.get(name) is True
        for name in ("rotation", "conversation_snapshot", "text_input", "speech_interrupt")
    ):
        reasons.append("required Realtime session recovery and control behavior is missing")
    events = raw.get("events")
    if not isinstance(events, Mapping) or not all(
        events.get(name) is True for name in ("replay", "durable")
    ):
        reasons.append("durable event replay is missing")
    workers = raw.get("workers")
    commands = workers.get("commands") if isinstance(workers, Mapping) else None
    delivery = workers.get("delivery") if isinstance(workers, Mapping) else None
    if (
        not isinstance(workers, Mapping)
        or workers.get("ownership") != "conversation_path"
        or workers.get("optimistic_revision") is not True
        or not isinstance(commands, list)
        or not {"refine", "redirect", "cancel"}.issubset(commands)
        or not isinstance(delivery, Mapping)
        or delivery.get("realtime_projection") != "exactly_once_durable_inbox"
    ):
        reasons.append("durable conversation-owned worker controls are missing")
    approvals = raw.get("approvals")
    if not isinstance(approvals, Mapping) or approvals.get("server_authoritative") is not True:
        reasons.append("server-authoritative approvals are missing")

    return RealtimeCompatibility(not reasons, version_text, tuple(reasons), contract)


def _safe_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    def safe(value: Any, depth: int = 0) -> Any:
        if depth > 6:
            return None
        if isinstance(value, Mapping):
            return {
                str(key): safe(item, depth + 1)
                for key, item in value.items()
                if isinstance(key, str)
                and not any(word in key.lower() for word in ("secret", "token", "credential", "key"))
            }
        if isinstance(value, list):
            return [safe(item, depth + 1) for item in value[:100]]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)[:200]

    return safe(raw)


def require_nonempty_string(
    body: Mapping[str, Any], key: str, *, maximum: int = 128
) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{key} exceeds the {maximum}-character limit")
    return value
