from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from ..config import TargetConfig
from .contracts import RealtimeCompatibility, check_realtime_compatibility

MAX_JSON_RESPONSE_BYTES = 2 * 1024 * 1024


class RealtimeProxyError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def public_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


class AmbiguousRealtimeMutation(RealtimeProxyError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            "ambiguous_acceptance",
            f"Hermes may have accepted the {operation}; reconcile before retrying",
            status=502,
        )


class HermesRealtimeClient:
    def __init__(self, target: TargetConfig, *, timeout: float = 30.0) -> None:
        self.target = target
        self.timeout = timeout
        api_key = target.resolve_api_key()
        if not api_key:
            raise RealtimeProxyError("target_credentials_missing", "Target credentials are missing")
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def compatibility(self) -> RealtimeCompatibility:
        document = await self._request("GET", "/v1/capabilities", timeout=15.0)
        return check_realtime_compatibility(document)

    async def create_session(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/v1/realtime/sessions", json_body=body, mutation="create")

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/realtime/sessions/{_segment(session_id)}")

    async def delete_session(self, session_id: str) -> dict[str, Any]:
        return await self._request(
            "DELETE", f"/v1/realtime/sessions/{_segment(session_id)}", mutation="delete"
        )

    async def session_action(
        self, session_id: str, action: str, body: Mapping[str, Any]
    ) -> dict[str, Any]:
        if action not in {"activate", "input", "interrupt"}:
            raise ValueError("unsupported Realtime session action")
        return await self._request(
            "POST",
            f"/v1/realtime/sessions/{_segment(session_id)}/{action}",
            json_body=body,
            mutation=action,
        )

    async def session_events(self, session_id: str, after: str | None) -> dict[str, Any]:
        params = {"after": after} if after else None
        return await self._request(
            "GET", f"/v1/realtime/sessions/{_segment(session_id)}/events", params=params
        )

    async def resolve_approval(
        self, session_id: str, approval_id: str, body: Mapping[str, Any]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/realtime/sessions/{_segment(session_id)}/approvals/{_segment(approval_id)}",
            json_body=body,
            mutation="approval",
        )

    async def conversation(self, conversation_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/v1/realtime/conversations/{_segment(conversation_id)}"
        )

    async def list_worker_jobs(self, conversation_id: str) -> dict[str, Any]:
        return await self._request("GET", _worker_base(conversation_id))

    async def worker_job(self, conversation_id: str, worker_job_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"{_worker_base(conversation_id)}/{_segment(worker_job_id)}"
        )

    async def worker_events(
        self, conversation_id: str, worker_job_id: str, after: int
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"{_worker_base(conversation_id)}/{_segment(worker_job_id)}/events",
            params={"after": str(after)},
        )

    async def worker_command(
        self,
        conversation_id: str,
        worker_job_id: str,
        operation: str,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        if operation not in {"refine", "redirect", "cancel"}:
            raise ValueError("unsupported worker command")
        return await self._request(
            "POST",
            f"{_worker_base(conversation_id)}/{_segment(worker_job_id)}/{operation}",
            json_body=body,
            mutation=f"worker {operation}",
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
        timeout: float | None = None,
        mutation: str | None = None,
    ) -> dict[str, Any]:
        try:
            async with (
                httpx.AsyncClient(
                    base_url=self.target.base_url,
                    timeout=timeout or self.timeout,
                    follow_redirects=False,
                ) as client,
                client.stream(
                    method, path, headers=self._headers(), json=json_body, params=params
                ) as response,
            ):
                status_code = response.status_code
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_JSON_RESPONSE_BYTES:
                        raise RealtimeProxyError(
                            "target_response_too_large",
                            "Hermes response exceeded the limit",
                        )
        except httpx.ConnectError as exc:
            raise RealtimeProxyError(
                "target_unavailable", "Could not connect to the Hermes target", status=503
            ) from exc
        except httpx.RequestError as exc:
            if mutation:
                raise AmbiguousRealtimeMutation(mutation) from exc
            raise RealtimeProxyError(
                "target_transport_failed", "Hermes target request failed", status=502
            ) from exc

        document = _json_object(bytes(raw))
        if status_code >= 400:
            code, message = _public_upstream_error(document, status_code)
            raise RealtimeProxyError(code, message, status=_safe_status(status_code))
        return document


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RealtimeProxyError("invalid_target_response", "Hermes returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise RealtimeProxyError("invalid_target_response", "Hermes response was not an object")
    return data


def _public_upstream_error(document: Mapping[str, Any], status: int) -> tuple[str, str]:
    error = document.get("error")
    if isinstance(error, Mapping):
        code = str(error.get("code") or "hermes_request_failed")[:80]
        message = str(error.get("message") or "Hermes rejected the request")[:400]
        return code, message
    return "hermes_request_failed", f"Hermes rejected the request (HTTP {status})"


def _safe_status(status: int) -> int:
    return status if status in {400, 401, 403, 404, 409, 413, 422, 429, 503} else 502


def _segment(value: str) -> str:
    return quote(value, safe="")


def _worker_base(conversation_id: str) -> str:
    return f"/v1/realtime/conversations/{_segment(conversation_id)}/worker-jobs"
