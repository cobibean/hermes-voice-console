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
    app.state.run_status = {}
    app.state.run_payloads = []
    app.state.sessions = {}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "platform": "fake-hermes", "version": "test"}

    @app.get("/health/detailed")
    async def health_detailed(request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"status": "ready", "checks": {"fake": "ok"}}

    @app.get("/v1/toolsets")
    async def toolsets(request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"toolsets": [{"name": "fake"}]}

    @app.get("/v1/models")
    async def models(request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"models": [{"alias": "fake", "provider": "fake"}]}

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
                "sessions": {"method": "POST", "path": "/api/sessions"},
                "session_messages": {
                    "method": "GET",
                    "path": "/api/sessions/{session_id}/messages",
                },
            },
        }

    @app.post("/api/sessions")
    async def create_session(request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        body = await request.json()
        session_id = str(body.get("session_id") or f"session_{uuid.uuid4().hex}")
        app.state.sessions.setdefault(session_id, [])
        return {"session_id": session_id}

    @app.get("/api/sessions/{session_id}/messages")
    async def session_messages(session_id: str, request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        messages = app.state.sessions.get(session_id)
        if messages is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"session_id": session_id, "messages": messages}

    @app.post("/v1/runs")
    async def start_run(request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        body = await request.json()
        app.state.run_payloads.append(body)
        text = str(body.get("input") or "")
        if not text:
            raise HTTPException(status_code=400, detail="Missing input")
        run_id = f"run_{uuid.uuid4().hex}"
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        app.state.run_queues[run_id] = queue
        session_id = str(body.get("session_id") or "")
        app.state.sessions.setdefault(session_id, []).append({"role": "user", "content": text})
        app.state.run_status[run_id] = {
            "run_id": run_id,
            "status": "running",
            "session_id": session_id,
            "output": None,
        }
        approval_event = asyncio.Event()
        app.state.approvals[run_id] = approval_event

        async def produce() -> None:
            await queue.put(
                {
                    "event": "message.delta",
                    "run_id": run_id,
                    "timestamp": time.time(),
                    "delta": "Fake ",
                }
            )
            await queue.put(
                {
                    "event": "tool.started",
                    "run_id": run_id,
                    "timestamp": time.time(),
                    "tool": "fake_tool",
                    "preview": "deterministic fake target",
                }
            )
            await queue.put(
                {
                    "event": "tool.completed",
                    "run_id": run_id,
                    "timestamp": time.time(),
                    "tool": "fake_tool",
                    "duration": 0.001,
                    "error": False,
                }
            )
            if "approval" in text.lower():
                app.state.run_status[run_id]["status"] = "waiting_for_approval"
                await queue.put(
                    {
                        "event": "approval.request",
                        "run_id": run_id,
                        "timestamp": time.time(),
                        "message": "Approve fake action?",
                        "choices": ["once", "session", "always", "deny"],
                    }
                )
                await approval_event.wait()
                app.state.run_status[run_id]["status"] = "running"
            output = f"Fake response to: {text}"
            history = body.get("conversation_history") or []
            if "recall nonce" in text.lower() and history:
                prior_users = [
                    str(item.get("content") or "")
                    for item in history
                    if isinstance(item, dict) and item.get("role") == "user"
                ]
                output = f"Fake recalled context: {' | '.join(prior_users)}"
            await queue.put(
                {
                    "event": "message.delta",
                    "run_id": run_id,
                    "timestamp": time.time(),
                    "delta": "response",
                }
            )
            await queue.put(
                {
                    "event": "run.completed",
                    "run_id": run_id,
                    "timestamp": time.time(),
                    "output": output,
                    "usage": {"total_tokens": 3},
                }
            )
            app.state.sessions[session_id].append({"role": "assistant", "content": output})
            app.state.run_status[run_id].update({"status": "completed", "output": output})
            await queue.put(None)

        asyncio.create_task(produce())
        return {"run_id": run_id, "status": "started"}

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str, request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        status_document = app.state.run_status.get(run_id)
        if status_document is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return status_document

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
        return {
            "object": "hermes.run.approval_response",
            "run_id": run_id,
            "choice": body.get("choice", "once"),
            "resolved": 1,
        }

    @app.post("/v1/runs/{run_id}/stop")
    async def stop(run_id: str, request: Request) -> dict[str, Any]:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        queue = app.state.run_queues.get(run_id)
        if queue is None:
            raise HTTPException(status_code=404, detail="Run not found")
        await queue.put({"event": "run.cancelled", "run_id": run_id, "timestamp": time.time()})
        await queue.put(None)
        app.state.run_status[run_id]["status"] = "cancelled"
        return {"run_id": run_id, "status": "stopping"}

    return app
