from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from .config import TargetConfig


class HermesApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class Capabilities:
    raw: dict[str, Any]

    def supports_runs(self) -> bool:
        """Return True only when the API server exposes the full V1 run contract."""
        features = self.raw.get("features") or self.raw.get("capabilities") or {}
        endpoints = self.raw.get("endpoints") or {}
        if not isinstance(features, dict):
            features = {}
        if not isinstance(endpoints, dict):
            endpoints = {}
        required_features = {
            "run_submission",
            "run_events_sse",
            "run_stop",
            "run_approval_response",
            "approval_events",
        }
        required_endpoints = {"runs", "run_events", "run_approval", "run_stop"}
        return all(features.get(name) is True for name in required_features) and required_endpoints.issubset(endpoints)

    def public_dict(self) -> dict[str, Any]:
        return self.raw


class HermesApiClient:
    def __init__(self, target: TargetConfig, *, timeout: float = 120.0) -> None:
        self.target = target
        self.timeout = timeout
        key = target.resolve_api_key()
        if not key:
            raise HermesApiError(f"API key env var is not configured for target {target.name}: {target.api_key_env}")
        self.api_key = key

    def _headers(self, *, session_key: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if session_key:
            headers["X-Hermes-Session-Key"] = session_key
        return headers

    async def capabilities(self) -> Capabilities:
        async with httpx.AsyncClient(base_url=self.target.base_url, timeout=15) as client:
            resp = await client.get("/v1/capabilities", headers=self._headers())
        if resp.status_code >= 400:
            raise HermesApiError(f"capabilities probe failed for {self.target.name}: HTTP {resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict):
            raise HermesApiError("capabilities response was not an object")
        return Capabilities(data)

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.target.base_url, timeout=15) as client:
            resp = await client.get("/health")
        if resp.status_code >= 400:
            raise HermesApiError(f"health probe failed for {self.target.name}: HTTP {resp.status_code}")
        data = resp.json()
        return data if isinstance(data, dict) else {"status": "unknown"}

    async def start_run(self, *, text: str, session_id: str, session_key: str | None = None) -> str:
        payload = {"input": text, "session_id": session_id}
        async with httpx.AsyncClient(base_url=self.target.base_url, timeout=self.timeout) as client:
            resp = await client.post("/v1/runs", headers=self._headers(session_key=session_key), json=payload)
        if resp.status_code >= 400:
            raise HermesApiError(f"run start failed: HTTP {resp.status_code}: {resp.text[:400]}")
        data = resp.json()
        run_id = data.get("run_id")
        if not run_id:
            raise HermesApiError("run start response missing run_id")
        return str(run_id)

    async def stream_run_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self.target.base_url, timeout=None) as client:
            async with client.stream("GET", f"/v1/runs/{run_id}/events", headers=self._headers()) as resp:
                if resp.status_code >= 400:
                    text = await resp.aread()
                    raise HermesApiError(f"run event stream failed: HTTP {resp.status_code}: {text[:400]!r}")
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        try:
                            event = json.loads(raw)
                        except ValueError:
                            continue
                        if isinstance(event, dict):
                            yield event

    async def approve(self, run_id: str, decision: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.target.base_url, timeout=30) as client:
            resp = await client.post(f"/v1/runs/{run_id}/approval", headers=self._headers(), json={"choice": decision})
        if resp.status_code >= 400:
            raise HermesApiError(f"approval failed: HTTP {resp.status_code}: {resp.text[:400]}")
        data = resp.json()
        return data if isinstance(data, dict) else {"ok": True}

    async def stop(self, run_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.target.base_url, timeout=30) as client:
            resp = await client.post(f"/v1/runs/{run_id}/stop", headers=self._headers(), json={})
        if resp.status_code >= 400:
            raise HermesApiError(f"stop failed: HTTP {resp.status_code}: {resp.text[:400]}")
        data = resp.json()
        return data if isinstance(data, dict) else {"ok": True}


def normalize_run_event(raw: dict[str, Any]) -> dict[str, Any]:
    event = raw.get("event") or raw.get("type") or "event"
    run_id = raw.get("run_id")
    if event == "message.delta":
        return {"type": "agent.delta", "run_id": run_id, "delta": raw.get("delta", "")}
    if event == "tool.started":
        return {"type": "agent.tool.started", "run_id": run_id, "tool": raw.get("tool"), "preview": raw.get("preview")}
    if event == "tool.completed":
        return {"type": "agent.tool.completed", "run_id": run_id, "tool": raw.get("tool"), "error": raw.get("error", False), "duration": raw.get("duration")}
    if event == "approval.request":
        return {"type": "agent.approval.request", "run_id": run_id, "approval": raw}
    if event == "approval.responded":
        return {"type": "agent.approval.responded", "run_id": run_id, "choice": raw.get("choice"), "resolved": raw.get("resolved")}
    if event == "run.completed":
        return {"type": "agent.completed", "run_id": run_id, "text": raw.get("output", ""), "usage": raw.get("usage") or {}}
    if event in {"run.failed", "error"}:
        return {"type": "agent.failed", "run_id": run_id, "error": raw.get("error") or raw.get("message") or "run failed"}
    if event in {"run.cancelled", "run.stopped"}:
        return {"type": "agent.stopped", "run_id": run_id}
    return {"type": "agent.event", "run_id": run_id, "event": raw}


class ApiRunsTransport:
    def __init__(self, client: HermesApiClient) -> None:
        self.client = client

    async def health(self) -> dict[str, Any]:
        return await self.client.health()

    async def capabilities(self) -> Capabilities:
        return await self.client.capabilities()

    async def send_turn(self, *, session_id: str, session_key: str, text: str) -> AsyncIterator[dict[str, Any]]:
        caps = await self.capabilities()
        if not caps.supports_runs():
            raise HermesApiError("target lacks required /v1/runs + run events capabilities")
        run_id = await self.client.start_run(text=text, session_id=session_id, session_key=session_key)
        yield {"type": "agent.run.started", "run_id": run_id, "session_id": session_id}
        async for raw in self.client.stream_run_events(run_id):
            yield normalize_run_event(raw)

    async def approve(self, run_id: str, decision: str) -> dict[str, Any]:
        return await self.client.approve(run_id, decision)

    async def stop(self, run_id: str) -> dict[str, Any]:
        return await self.client.stop(run_id)
