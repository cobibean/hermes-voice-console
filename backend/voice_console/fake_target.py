from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

API_KEY = "fake"


def _auth_ok(request: Request) -> bool:
    return request.headers.get("authorization") == f"Bearer {API_KEY}"


def create_fake_hermes_app() -> FastAPI:
    app = FastAPI(title="Fake Hermes API Server")
    app.state.run_queues = {}
    app.state.approvals = {}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "platform": "fake-hermes", "version": "test"}

    @app.get("/v1/capabilities")
    async def capabilities(request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {
            "platform": "hermes-agent",
            "features": {
                "run_submission": True,
                "run_events_sse": True,
                "run_stop": True,
                "run_approval_response": True,
                "approval_events": True,
                "session_resources": True,
                "session_chat": True,
                "session_chat_streaming": True,
            },
            "endpoints": {
                "runs": {"method": "POST", "path": "/v1/runs"},
                "run_events": {"method": "GET", "path": "/v1/runs/{run_id}/events"},
                "run_approval": {"method": "POST", "path": "/v1/runs/{run_id}/approval"},
                "run_stop": {"method": "POST", "path": "/v1/runs/{run_id}/stop"},
            },
        }

    @app.post("/v1/runs")
    async def start_run(request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        body = await request.json()
        text = str(body.get("input") or "")
        if not text:
            raise HTTPException(status_code=400, detail="Missing input")
        run_id = f"run_{uuid.uuid4().hex}"
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        app.state.run_queues[run_id] = queue
        approval_event = asyncio.Event()
        app.state.approvals[run_id] = approval_event

        async def produce() -> None:
            await queue.put({"event": "message.delta", "run_id": run_id, "timestamp": time.time(), "delta": "Fake "})
            await queue.put({"event": "tool.started", "run_id": run_id, "timestamp": time.time(), "tool": "fake_tool", "preview": "deterministic fake target"})
            await queue.put({"event": "tool.completed", "run_id": run_id, "timestamp": time.time(), "tool": "fake_tool", "duration": 0.001, "error": False})
            if "approval" in text.lower():
                await queue.put({
                    "event": "approval.request",
                    "run_id": run_id,
                    "timestamp": time.time(),
                    "message": "Approve fake action?",
                    "choices": ["once", "session", "always", "deny"],
                })
                await approval_event.wait()
            output = f"Fake response to: {text}"
            await queue.put({"event": "message.delta", "run_id": run_id, "timestamp": time.time(), "delta": "response"})
            await queue.put({"event": "run.completed", "run_id": run_id, "timestamp": time.time(), "output": output, "usage": {"total_tokens": 3}})
            await queue.put(None)

        asyncio.create_task(produce())
        return {"run_id": run_id, "status": "started"}

    @app.get("/v1/runs/{run_id}/events")
    async def events(run_id: str, request: Request) -> StreamingResponse:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        queue = app.state.run_queues.get(run_id)
        if queue is None:
            raise HTTPException(status_code=404, detail="Run not found")

        async def stream():
            while True:
                item = await queue.get()
                if item is None:
                    yield ": stream closed\n\n"
                    break
                yield f"data: {json.dumps(item)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/v1/runs/{run_id}/approval")
    async def approval(run_id: str, request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        body = await request.json()
        ev = app.state.approvals.get(run_id)
        if ev is None:
            raise HTTPException(status_code=404, detail="Run not found")
        ev.set()
        return {"object": "hermes.run.approval_response", "run_id": run_id, "choice": body.get("choice", "once"), "resolved": 1}

    @app.post("/v1/runs/{run_id}/stop")
    async def stop(run_id: str, request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        queue = app.state.run_queues.get(run_id)
        if queue is None:
            raise HTTPException(status_code=404, detail="Run not found")
        await queue.put({"event": "run.cancelled", "run_id": run_id, "timestamp": time.time()})
        await queue.put(None)
        return {"run_id": run_id, "status": "stopping"}

    return app
