from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import validate_identifier
from .hermes_client import RealtimeProxyError

SESSION_STATES = {
    "provisioning", "controller_ready", "client_authorized", "active",
    "degraded", "closed", "failed",
}
SAFE_PAYLOAD_KEYS = {
    "type", "event_type", "event_id", "conversation_id", "realtime_session_id",
    "worker_job_id", "worker_attempt_id", "attempt_id", "approval_id", "artifact_id",
    "tool_call_id", "tool_name", "name", "role", "text", "delta", "status", "state",
    "message", "choice", "choices", "accepted", "resolved", "operation", "revision",
    "resulting_revision", "attempt_number", "model", "progress", "summary", "verification",
    "result", "output", "error", "code", "reason", "created_at", "updated_at",
    "completed_at", "expires_at", "duration", "usage", "metadata", "payload", "content",
    "task", "goal", "context", "path", "uri", "filename", "mime_type", "size",
    "queue_position", "delivery_state", "delivery_id", "fanout_count", "fanout_rationale",
    "acknowledgement", "requires_interrupt", "supersedes_attempt_id", "delegation_id",
    "command_id",
}


def parse_session(document: Mapping[str, Any], *, conversation_id: str | None = None,
                  session_id: str | None = None, include_sdp: bool = True) -> dict[str, Any]:
    _object(document)
    sid = _id(document, "realtime_session_id")
    cid = _id(document, "conversation_id")
    if session_id is not None and sid != session_id:
        _mismatch("session")
    if conversation_id is not None and cid != conversation_id:
        _mismatch("conversation")
    generation = document.get("session_generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        _invalid("session generation")
    state = document.get("state")
    if state not in SESSION_STATES:
        _invalid("session state")
    result = {
        "contract_version": str(document.get("contract_version") or "1.0")[:16],
        "realtime_session_id": sid,
        "conversation_id": cid,
        "session_generation": generation,
        "state": state,
    }
    if include_sdp:
        sdp = document.get("answer_sdp")
        if not isinstance(sdp, str) or not sdp.startswith("v=0") or len(sdp) > 262_144:
            _invalid("SDP answer")
        result["answer_sdp"] = sdp
    return result


def parse_closed(document: Mapping[str, Any], *, conversation_id: str,
                 session_id: str) -> dict[str, Any]:
    if _id(document, "realtime_session_id") != session_id:
        _mismatch("session")
    if _id(document, "conversation_id") != conversation_id:
        _mismatch("conversation")
    if document.get("state") != "closed":
        _invalid("closed session state")
    return {"realtime_session_id": session_id, "conversation_id": conversation_id, "state": "closed"}


def parse_events(document: Mapping[str, Any], *, conversation_id: str,
                 session_id: str) -> dict[str, Any]:
    if _id(document, "conversation_id") != conversation_id:
        _mismatch("conversation")
    raw_events = document.get("events")
    if not isinstance(raw_events, list) or len(raw_events) > 500:
        _invalid("event list")
    events: list[dict[str, Any]] = []
    for raw in raw_events:
        if not isinstance(raw, Mapping):
            _invalid("event")
        event_id = _id(raw, "event_id")
        if raw.get("conversation_id") != conversation_id:
            _mismatch("event conversation")
        if raw.get("realtime_session_id") not in {None, session_id}:
            _mismatch("event session")
        event_type = raw.get("type")
        if not isinstance(event_type, str) or not event_type or len(event_type) > 128:
            _invalid("event type")
        event = {"event_id": event_id, "type": event_type, "conversation_id": conversation_id}
        for key in ("realtime_session_id", "generation", "created_at"):
            if key in raw:
                event[key] = _safe(raw[key])
        payload = _safe(raw.get("payload") or {})
        if isinstance(payload, dict):
            if payload.get("conversation_id") not in {None, conversation_id}:
                _mismatch("event payload conversation")
            for id_key in ("worker_job_id", "worker_attempt_id", "approval_id", "tool_call_id"):
                if payload.get(id_key) is not None:
                    validate_identifier(str(payload[id_key]), id_key)
        event["payload"] = payload
        events.append(event)
    cursor = document.get("last_event_id")
    if "last_event_id" not in document or (events and cursor != events[-1]["event_id"]):
        _invalid("event cursor")
    if cursor is not None:
        validate_identifier(str(cursor), "last_event_id")
    return {"conversation_id": conversation_id, "events": events, "last_event_id": cursor}


def parse_approval(document: Mapping[str, Any], *, approval_id: str) -> dict[str, Any]:
    if _id(document, "approval_id") != approval_id:
        _mismatch("approval")
    state = document.get("state")
    if state not in {"pending", "resolving", "resolved", "denied", "expired"}:
        _invalid("approval state")
    return {"approval_id": approval_id, "state": state, "accepted": _safe(document.get("accepted"))}


def parse_job(document: Mapping[str, Any], *, conversation_id: str,
              worker_job_id: str | None = None) -> dict[str, Any]:
    jid = _id(document, "worker_job_id")
    if worker_job_id is not None and jid != worker_job_id:
        _mismatch("worker job")
    if document.get("conversation_key") != conversation_id:
        _mismatch("worker conversation")
    allowed = {
        "worker_job_id", "conversation_key", "status", "revision", "task", "lead_model",
        "fanout_count", "fanout_rationale", "created_at", "updated_at", "completed_at",
        "completion", "delivery_state", "delivery_id", "queue_position", "attempts", "artifacts",
        "events", "approvals", "commands", "command_history",
    }
    result = {key: _safe(value) for key, value in document.items() if key in allowed}
    result["worker_job_id"] = jid
    result["conversation_key"] = conversation_id
    if not isinstance(result.get("revision"), int):
        _invalid("worker revision")
    for attempt in result.get("attempts") or []:
        if not isinstance(attempt, dict):
            _invalid("worker attempt")
        aid = attempt.get("worker_attempt_id")
        if aid is not None:
            validate_identifier(str(aid), "worker_attempt_id")
    attempt_ids = {
        item.get("worker_attempt_id")
        for item in result.get("attempts") or []
        if isinstance(item, dict) and item.get("worker_attempt_id")
    }
    for collection in ("events", "artifacts", "approvals"):
        for item in result.get(collection) or []:
            if not isinstance(item, dict):
                _invalid(f"worker {collection}")
            item_attempt = item.get("worker_attempt_id")
            if item_attempt is not None and item_attempt not in attempt_ids:
                _mismatch(f"worker {collection} attempt")
    return result


def parse_job_list(document: Mapping[str, Any], *, conversation_id: str) -> dict[str, Any]:
    data = document.get("data")
    if document.get("object") != "list" or not isinstance(data, list) or len(data) > 200:
        _invalid("worker job list")
    return {"object": "list", "data": [parse_job(job, conversation_id=conversation_id) for job in data]}


def parse_job_events(document: Mapping[str, Any], *, conversation_id: str,
                     worker_job_id: str) -> dict[str, Any]:
    if _id(document, "worker_job_id") != worker_job_id:
        _mismatch("worker job")
    events = document.get("events")
    if not isinstance(events, list) or len(events) > 500:
        _invalid("worker event list")
    safe_events = []
    for event in events:
        safe_event = _safe(event)
        if not isinstance(safe_event, dict):
            _invalid("worker event")
        if safe_event.get("worker_job_id") not in {None, worker_job_id}:
            _mismatch("worker event job")
        if safe_event.get("conversation_id") not in {None, conversation_id}:
            _mismatch("worker event conversation")
        safe_events.append(safe_event)
    cursor = document.get("last_event_id")
    if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
        _invalid("worker event cursor")
    return {"worker_job_id": worker_job_id, "events": safe_events, "last_event_id": cursor}


def parse_command(document: Mapping[str, Any], *, command_id: str,
                  worker_job_id: str) -> dict[str, Any]:
    if _id(document, "command_id") != command_id:
        _mismatch("command")
    if document.get("worker_job_id") not in {None, worker_job_id}:
        _mismatch("command worker job")
    allowed = {"command_id", "worker_job_id", "operation", "acknowledgement", "accepted",
               "revision", "resulting_revision", "requires_interrupt"}
    return {key: _safe(value) for key, value in document.items() if key in allowed}


def parse_snapshot(document: Mapping[str, Any], *, conversation_id: str) -> dict[str, Any]:
    if _id(document, "conversation_id") != conversation_id:
        _mismatch("conversation")
    result: dict[str, Any] = {"contract_version": str(document.get("contract_version") or "1.0")[:16], "conversation_id": conversation_id}
    session = document.get("session")
    result["session"] = (
        parse_session(session, conversation_id=conversation_id, include_sdp=False)
        if isinstance(session, Mapping)
        else None
    )
    for key in ("pending_approvals", "transcript", "work_summary"):
        value = document.get(key, [])
        if not isinstance(value, list):
            _invalid(key)
        result[key] = [_safe(item) for item in value[:500]]
    for approval in result["pending_approvals"]:
        if not isinstance(approval, dict) or not approval.get("approval_id"):
            _invalid("pending approval")
        validate_identifier(str(approval["approval_id"]), "approval_id")
        if approval.get("conversation_id") not in {None, conversation_id}:
            _mismatch("approval conversation")
    jobs = document.get("worker_jobs", [])
    if not isinstance(jobs, list):
        _invalid("worker jobs")
    result["worker_jobs"] = [parse_job(job, conversation_id=conversation_id) for job in jobs[:200]]
    cursor = document.get("last_event_id")
    if cursor is not None:
        validate_identifier(str(cursor), "last_event_id")
    result["last_event_id"] = cursor
    return result


def _safe(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return None
    if isinstance(value, Mapping):
        return {str(key): _safe(item, depth + 1) for key, item in value.items() if key in SAFE_PAYLOAD_KEYS}
    if isinstance(value, list):
        return [_safe(item, depth + 1) for item in value[:200]]
    if isinstance(value, str):
        return value[:32_000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _id(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str):
        _invalid(key)
    return validate_identifier(value, key)


def _object(document: Any) -> None:
    if not isinstance(document, Mapping):
        _invalid("response object")


def _invalid(subject: str):
    raise RealtimeProxyError("invalid_target_response", f"Hermes returned an invalid {subject}")


def _mismatch(subject: str):
    raise RealtimeProxyError("target_identity_mismatch", f"Hermes returned a mismatched {subject}")
