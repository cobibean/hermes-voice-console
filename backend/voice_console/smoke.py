from __future__ import annotations

import time
from typing import Any

import httpx

from .config import TargetConfig
from .hermes_client import ApiRunsTransport, HermesApiClient


async def run_smoke(
    target: TargetConfig,
    *,
    read_only: bool,
    allow_run: bool = False,
    text: str | None = None,
) -> dict[str, Any]:
    if not read_only and (not allow_run or not text or not text.strip()):
        raise ValueError("write smoke requires both --allow-run and explicit --text")
    client = HermesApiClient(target, timeout=120)
    checks: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=target.base_url, timeout=20) as http:
        for name, path, authenticated in (
            ("health", "/health", False),
            ("health_detailed", "/health/detailed", True),
            ("capabilities", "/v1/capabilities", True),
            ("toolsets", "/v1/toolsets", True),
            ("models", "/v1/models", True),
        ):
            started = time.perf_counter()
            response = await http.get(path, headers=client._headers() if authenticated else None)
            document = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            status_value = document.get("status") if isinstance(document, dict) else None
            checks.append(
                {
                    "name": name,
                    "http_status": response.status_code,
                    "status": status_value,
                    "ok": response.status_code == 200
                    and (name != "health_detailed" or status_value in {"ok", "ready", "healthy"}),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            )
    result: dict[str, Any] = {
        "target": target.name,
        "mode": "read-only" if read_only else "write",
        "checks": checks,
        "ok": all(check["ok"] for check in checks),
    }
    if not read_only:
        events: list[str] = []
        started = time.perf_counter()
        transport = ApiRunsTransport(client)
        async for event in transport.send_turn(
            session_id="voice-console-smoke",
            session_key="voice-console:service-smoke",
            text=text or "",
        ):
            events.append(str(event.get("type") or "unknown"))
        result["run"] = {
            "events": events,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    return result
