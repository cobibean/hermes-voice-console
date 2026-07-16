from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

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
    app.state.stopped_runs = set()
    app.state.realtime_sessions = {}
    app.state.realtime_by_conversation = {}
    app.state.realtime_requests = {}
    app.state.realtime_events = {}
    app.state.worker_jobs = {}
    app.state.realtime_overrides = {}
    app.state.realtime_create_payloads = []
    app.state.realtime_control_calls = {}
    app.state.realtime_audio_buffers = {}
    app.state.realtime_committed_audio = {}
    app.state.worker_command_calls = {}

    def overridden(name: str, document: dict[str, Any]) -> dict[str, Any]:
        return {**document, **(app.state.realtime_overrides.get(name) or {})}

    def unknown_result(
        conversation_id: str, request_id: str, operation: str
    ) -> dict[str, Any] | None:
        if not request_id.startswith("unknown_"):
            return None
        result = {
            "client_request_id": request_id,
            "operation": operation,
            "state": "outcome_unknown",
            "accepted": False,
        }
        app.state.realtime_requests[(conversation_id, request_id)] = result
        return result

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

    @app.get("/test/state")
    async def test_state(request: Request) -> dict[str, Any]:
        """Expose non-secret counters for deterministic browser acceptance tests."""
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {
            "run_count": len(app.state.run_payloads),
            "runs": list(app.state.run_status.values()),
        }

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
                "realtime_voice": True,
                "realtime_sideband_tools": True,
                "realtime_conversation_snapshot": True,
                "realtime_durable_event_replay": True,
                "realtime_worker_jobs": True,
                "realtime_worker_job_commands": True,
                "realtime_exactly_once_worker_projection": True,
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
                "realtime_session_create": {"method": "POST", "path": "/v1/realtime/sessions"},
                "realtime_session": {"method": "GET", "path": "/v1/realtime/sessions/{session_id}"},
                "realtime_session_delete": {"method": "DELETE", "path": "/v1/realtime/sessions/{session_id}"},
                "realtime_session_activate": {"method": "POST", "path": "/v1/realtime/sessions/{session_id}/activate"},
                "realtime_session_input": {"method": "POST", "path": "/v1/realtime/sessions/{session_id}/input"},
                "realtime_session_manual_audio_commit": {"method": "POST", "path": "/v1/realtime/sessions/{session_id}/commit"},
                "realtime_session_manual_audio_discard": {"method": "POST", "path": "/v1/realtime/sessions/{session_id}/discard"},
                "realtime_session_turn_mode_update": {"method": "POST", "path": "/v1/realtime/sessions/{session_id}/turn-mode"},
                "realtime_session_interrupt": {"method": "POST", "path": "/v1/realtime/sessions/{session_id}/interrupt"},
                "realtime_session_events": {"method": "GET", "path": "/v1/realtime/sessions/{session_id}/events"},
                "realtime_approval": {"method": "POST", "path": "/v1/realtime/sessions/{session_id}/approvals/{approval_id}"},
                "realtime_conversation": {"method": "GET", "path": "/v1/realtime/conversations/{conversation_id}"},
                "realtime_request_result": {"method": "GET", "path": "/v1/realtime/conversations/{conversation_id}/requests/{client_request_id}"},
                "realtime_worker_jobs": {"method": "GET", "path": "/v1/realtime/conversations/{conversation_id}/worker-jobs"},
                "realtime_worker_job": {"method": "GET", "path": "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}"},
                "realtime_worker_job_events": {"method": "GET", "path": "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/events"},
                "realtime_worker_job_command_result": {"method": "GET", "path": "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/commands/{command_id}"},
                "realtime_worker_job_refine": {"method": "POST", "path": "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/refine"},
                "realtime_worker_job_redirect": {"method": "POST", "path": "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/redirect"},
                "realtime_worker_job_cancel": {"method": "POST", "path": "/v1/realtime/conversations/{conversation_id}/worker-jobs/{worker_job_id}/cancel"},
            },
            "contracts": {
                "realtime": {
                    "version": "1.0",
                    "media": {
                        "transport": "webrtc",
                        "bootstrap": "unified_sdp",
                        "sideband_authority": "server",
                        "create_readiness": "controller_ready_before_sdp",
                    },
                    "provider": {"id": "openai", "model": "gpt-realtime-2.1", "voice": "marin", "reasoning_effort": None},
                    "models": ["gpt-realtime-2.1"],
                    "sideband_authority": "server",
                    "sessions": {"rotation": True, "conversation_snapshot": True, "text_input": True, "manual_audio_commit": True, "manual_audio_discard": True, "speech_interrupt": True, "turn_modes": ["server_vad", "manual"], "turn_mode_update": True},
                    "events": {"replay": True, "durable": True, "cursor": "event_id", "gap_error": "event_replay_gap"},
                    "tools": {"execution": "server", "direct_allowlist": ["get_status"], "delegation_tool": "delegate_work", "raw_delegate_task_exposed": False},
                    "workers": {"lead_model": "gpt-5.6-sol", "max_concurrency": 1, "max_fanout": 1, "queue": "fifo_per_conversation", "commands": ["refine", "redirect", "cancel"], "command_result_lookup": True, "ownership": "conversation_path", "optimistic_revision": True, "delivery": {"realtime_projection": "exactly_once_durable_inbox", "external_claims": "at_least_once_lease_ack"}},
                    "approvals": {"server_authoritative": True, "choices": ["once", "deny"], "pending_snapshot_fields": ["approval_id", "state", "tool_call_id", "tool_name", "expires_at"]},
                    "routing_policy": {"persona_model": "gpt-realtime-2.1", "substantial_work": "delegate", "default_fanout": 1, "confirmation": "announce_without_prompting"},
                    "retention": {"event_count": 2048, "event_bytes": 4194304, "context_bytes": 65536, "completed_item_days": 30},
                    "timeouts": {"provider_request_seconds": 30, "controller_ready_seconds": 10, "tool_seconds": 120, "worker_seconds": 3600, "approval_seconds": 300},
                }
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
                    "error": "failed tool" in text.lower(),
                }
            )
            if "drop sse" in text.lower():
                await queue.put(None)
                await asyncio.sleep(0.25)
                output = f"Fake response to: {text}"
                app.state.sessions[session_id].append({"role": "assistant", "content": output})
                app.state.run_status[run_id].update({"status": "completed", "output": output})
                return
            if "approval" in text.lower():
                app.state.run_status[run_id]["status"] = "waiting_for_approval"
                await queue.put(
                    {
                        "event": "approval.request",
                        "run_id": run_id,
                        "timestamp": time.time(),
                        "message": "Approve fake action?",
                        "tool": "fake_tool",
                        "operation": "write test artifact",
                        "path": "/tmp/browser-acceptance/" + "nested/" * 24 + "artifact.txt",
                        "reason": "Exercise long approval details without changing external state.",
                        "choices": ["once", "session", "always", "deny"],
                    }
                )
                await approval_event.wait()
                app.state.run_status[run_id]["status"] = "running"
            if "slow run" in text.lower():
                for _ in range(20):
                    if run_id in app.state.stopped_runs:
                        return
                    await asyncio.sleep(0.1)
            if run_id in app.state.stopped_runs:
                return
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
        if "delayed acceptance" in text.lower():
            await asyncio.sleep(0.75)
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
        app.state.stopped_runs.add(run_id)
        app.state.run_status[run_id]["status"] = "cancelled"
        return {"run_id": run_id, "status": "stopping"}

    def require_realtime_auth(request: Request) -> None:
        if not _auth_ok(request):
            raise HTTPException(status_code=401, detail="Invalid API key")

    def realtime_session(session_id: str) -> dict[str, Any]:
        value = app.state.realtime_sessions.get(session_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Realtime session not found")
        return value

    @app.post("/v1/realtime/sessions", status_code=201)
    async def realtime_create(request: Request) -> dict[str, Any]:
        require_realtime_auth(request)
        body = await request.json()
        app.state.realtime_create_payloads.append(body)
        conversation_id = str(body.get("conversation_id") or "")
        request_id = str(body.get("client_request_id") or "")
        offer = str(body.get("sdp_offer") or "")
        if not conversation_id or not request_id or not offer:
            raise HTTPException(status_code=400, detail="Missing Realtime session field")
        request_key = (conversation_id, request_id)
        cached = app.state.realtime_requests.get(request_key)
        if cached is not None:
            return cached
        unknown = unknown_result(conversation_id, request_id, "create")
        if unknown is not None:
            return unknown
        old_id = app.state.realtime_by_conversation.get(conversation_id)
        generation = (
            int(app.state.realtime_sessions[old_id]["session_generation"]) + 1
            if old_id in app.state.realtime_sessions
            else 1
        )
        session_id = f"rt_{uuid.uuid4().hex}"
        result = {
            "client_request_id": request_id,
            "contract_version": "1.0",
            "realtime_session_id": session_id,
            "conversation_id": conversation_id,
            "session_generation": generation,
            "state": "controller_ready",
            "turn_mode": str(body.get("turn_mode") or "server_vad"),
            "answer_sdp": "v=0\r\na=fake-answer",
        }
        app.state.realtime_sessions[session_id] = result
        app.state.realtime_audio_buffers[session_id] = []
        app.state.realtime_committed_audio[session_id] = []
        app.state.realtime_by_conversation[conversation_id] = session_id
        app.state.realtime_requests[request_key] = result
        app.state.realtime_events[conversation_id] = [
            {"event_id": "ev_1", "type": "session.created", "conversation_id": conversation_id, "payload": {"realtime_session_id": session_id}},
            {"event_id": "ev_2", "type": "approval.pending", "conversation_id": conversation_id, "payload": {"approval_id": "approval_1"}},
            {"event_id": "ev_3", "type": "worker.queued", "conversation_id": conversation_id, "payload": {"worker_job_id": "job_1"}},
        ]
        app.state.worker_jobs.setdefault(
            conversation_id,
            {"job_1": {"worker_job_id": "job_1", "conversation_key": conversation_id, "status": "running", "revision": 1, "commands": [], "events": [{"event_id": 1, "type": "worker.queued"}]}},
        )
        if request_id.startswith("ambiguous"):
            await asyncio.sleep(0.2)
        return overridden("create", result)

    @app.get("/v1/realtime/sessions/{session_id}")
    async def realtime_get(session_id: str, request: Request) -> dict[str, Any]:
        require_realtime_auth(request)
        return overridden("session", realtime_session(session_id))

    @app.delete("/v1/realtime/sessions/{session_id}")
    async def realtime_delete(session_id: str, request: Request) -> dict[str, Any]:
        require_realtime_auth(request)
        body = await request.json()
        document = realtime_session(session_id)
        conversation_id = str(body.get("conversation_id") or "")
        request_id = str(body.get("client_request_id") or "")
        if conversation_id != document["conversation_id"] or not request_id:
            raise HTTPException(status_code=400, detail="Invalid delete identity")
        cached = app.state.realtime_requests.get((conversation_id, request_id))
        if cached is not None:
            return cached
        unknown = unknown_result(conversation_id, request_id, "delete")
        if unknown is not None:
            return unknown
        document["state"] = "closed"
        result = overridden("delete", {"client_request_id": request_id, "realtime_session_id": session_id, "conversation_id": conversation_id, "state": "closed"})
        app.state.realtime_requests[(conversation_id, request_id)] = result
        return result

    @app.post("/v1/realtime/sessions/{session_id}/activate")
    async def realtime_activate(session_id: str, request: Request) -> dict[str, Any]:
        require_realtime_auth(request)
        body = await request.json()
        document = realtime_session(session_id)
        if body.get("conversation_id") != document["conversation_id"]:
            raise HTTPException(status_code=400, detail="conversation mismatch")
        if body.get("session_generation") != document["session_generation"]:
            raise HTTPException(status_code=409, detail="stale generation")
        request_id = str(body.get("client_request_id") or "")
        cached = app.state.realtime_requests.get((document["conversation_id"], request_id))
        if cached is not None:
            return cached
        unknown = unknown_result(document["conversation_id"], request_id, "activate")
        if unknown is not None:
            return unknown
        document["state"] = "active"
        result = overridden("activate", {**document, "client_request_id": request_id})
        app.state.realtime_requests[(document["conversation_id"], request_id)] = result
        return result

    @app.post("/v1/realtime/sessions/{session_id}/input")
    async def realtime_input(session_id: str, request: Request) -> dict[str, Any]:
        require_realtime_auth(request)
        body = await request.json()
        document = realtime_session(session_id)
        if body.get("conversation_id") != document["conversation_id"]:
            raise HTTPException(status_code=400, detail="conversation mismatch")
        request_id = str(body.get("client_request_id") or "")
        cached = app.state.realtime_requests.get((document["conversation_id"], request_id))
        if cached is not None:
            return cached
        unknown = unknown_result(document["conversation_id"], request_id, "input")
        if unknown is not None:
            return unknown
        result = overridden("input", {"client_request_id": request_id, "accepted": True, "state": "accepted"})
        app.state.realtime_requests[(document["conversation_id"], request_id)] = result
        return result

    @app.post("/v1/realtime/sessions/{session_id}/interrupt")
    async def realtime_interrupt(session_id: str, request: Request) -> dict[str, Any]:
        require_realtime_auth(request)
        body = await request.json()
        document = realtime_session(session_id)
        if body.get("conversation_id") != document["conversation_id"]:
            raise HTTPException(status_code=400, detail="conversation mismatch")
        request_id = str(body.get("client_request_id") or "")
        cached = app.state.realtime_requests.get((document["conversation_id"], request_id))
        if cached is not None:
            return cached
        unknown = unknown_result(document["conversation_id"], request_id, "interrupt")
        if unknown is not None:
            return unknown
        result = overridden("interrupt", {"client_request_id": request_id, "realtime_session_id": session_id, "interrupted": True, "state": "accepted"})
        app.state.realtime_requests[(document["conversation_id"], request_id)] = result
        return result

    async def manual_control_document(
        session_id: str, request: Request, operation: str
    ) -> dict[str, Any] | JSONResponse:
        require_realtime_auth(request)
        body = await request.json()
        document = realtime_session(session_id)
        conversation_id = document["conversation_id"]
        if body.get("conversation_id") != conversation_id:
            raise HTTPException(status_code=400, detail="conversation mismatch")
        request_id = str(body.get("client_request_id") or "")
        cached = app.state.realtime_requests.get((conversation_id, request_id))
        if cached is not None:
            status = 409 if cached.get("state") == "rejected" else 200
            return JSONResponse(status_code=status, content=cached)
        unknown = unknown_result(conversation_id, request_id, operation)
        if unknown is not None:
            return unknown
        if body.get("session_generation") != document["session_generation"]:
            return JSONResponse(
                status_code=409,
                content={"error": {"code": f"{operation}_unavailable"}},
            )
        if operation == "manual_audio_commit":
            if document["turn_mode"] != "manual":
                return JSONResponse(
                    status_code=409,
                    content={"error": {"code": "manual_audio_commit_unavailable"}},
                )
            key = (operation, session_id)
            app.state.realtime_control_calls[key] = (
                app.state.realtime_control_calls.get(key, 0) + 1
            )
            if request_id.startswith("empty_"):
                result = {
                    "client_request_id": request_id,
                    "operation": operation,
                    "state": "rejected",
                    "accepted": False,
                    "error": {"code": "audio_buffer_empty"},
                }
                app.state.realtime_requests[(conversation_id, request_id)] = result
                return JSONResponse(status_code=409, content=result)
            result = {
                "client_request_id": request_id,
                "realtime_session_id": session_id,
                "session_generation": document["session_generation"],
                "state": "accepted",
                "audio_commit_requested": True,
                "response_requested": True,
            }
            app.state.realtime_committed_audio[session_id].append(
                list(app.state.realtime_audio_buffers[session_id])
            )
            app.state.realtime_audio_buffers[session_id].clear()
        elif operation == "manual_audio_discard":
            if document["turn_mode"] != "manual":
                return JSONResponse(
                    status_code=409,
                    content={"error": {"code": "manual_audio_discard_unavailable"}},
                )
            key = (operation, session_id)
            app.state.realtime_control_calls[key] = (
                app.state.realtime_control_calls.get(key, 0) + 1
            )
            if request_id.startswith("reject_discard"):
                result = {
                    "client_request_id": request_id,
                    "operation": operation,
                    "state": "rejected",
                    "accepted": False,
                    "error": {"code": "audio_discard_rejected"},
                }
                app.state.realtime_requests[(conversation_id, request_id)] = result
                return JSONResponse(status_code=409, content=result)
            app.state.realtime_audio_buffers[session_id].clear()
            result = {
                "client_request_id": request_id,
                "realtime_session_id": session_id,
                "session_generation": document["session_generation"],
                "state": "accepted",
                "audio_discard_requested": True,
            }
        else:
            turn_mode = body.get("turn_mode")
            if turn_mode not in {"automatic", "manual"}:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"code": "invalid_turn_mode"}},
                )
            if turn_mode == "automatic" and document.get("manual_capture_active"):
                return JSONResponse(
                    status_code=409,
                    content={"error": {"code": "turn_mode_update_unavailable"}},
                )
            key = (operation, session_id)
            app.state.realtime_control_calls[key] = (
                app.state.realtime_control_calls.get(key, 0) + 1
            )
            document["turn_mode"] = turn_mode
            result = {
                "client_request_id": request_id,
                "realtime_session_id": session_id,
                "session_generation": document["session_generation"],
                "turn_mode": turn_mode,
                "state": "accepted",
            }
        result = overridden(operation, result)
        app.state.realtime_requests[(conversation_id, request_id)] = result
        if request_id.startswith("ambiguous"):
            await asyncio.sleep(0.2)
        return result

    @app.post("/v1/realtime/sessions/{session_id}/commit")
    async def realtime_commit(session_id: str, request: Request):
        return await manual_control_document(
            session_id, request, "manual_audio_commit"
        )

    @app.post("/v1/realtime/sessions/{session_id}/discard")
    async def realtime_discard(session_id: str, request: Request):
        return await manual_control_document(
            session_id, request, "manual_audio_discard"
        )

    @app.post("/v1/realtime/sessions/{session_id}/turn-mode")
    async def realtime_turn_mode(session_id: str, request: Request):
        return await manual_control_document(
            session_id, request, "turn_mode_update"
        )

    @app.get("/v1/realtime/sessions/{session_id}/events")
    async def realtime_event_replay(session_id: str, request: Request, after: str | None = None) -> dict[str, Any]:
        require_realtime_auth(request)
        document = realtime_session(session_id)
        events = app.state.realtime_events[document["conversation_id"]]
        if after and after not in {event["event_id"] for event in events}:
            return JSONResponse(status_code=409, content={"error": {"code": "event_replay_gap", "message": "Requested events are no longer retained", "details": {"oldest_event_id": events[0]["event_id"]}}})
        start = next((index + 1 for index, event in enumerate(events) if event["event_id"] == after), 0)
        selected = events[start:]
        return overridden("events", {"conversation_id": document["conversation_id"], "events": selected, "last_event_id": selected[-1]["event_id"] if selected else after})

    @app.post("/v1/realtime/sessions/{session_id}/approvals/{approval_id}")
    async def realtime_approval(session_id: str, approval_id: str, request: Request) -> dict[str, Any]:
        require_realtime_auth(request)
        body = await request.json()
        document = realtime_session(session_id)
        if body.get("conversation_id") != document["conversation_id"]:
            raise HTTPException(status_code=400, detail="conversation mismatch")
        request_id = str(body.get("client_request_id") or "")
        cached = app.state.realtime_requests.get((document["conversation_id"], request_id))
        if cached is not None:
            return cached
        unknown = unknown_result(document["conversation_id"], request_id, "approval")
        if unknown is not None:
            return unknown
        result = overridden("approval", {"client_request_id": request_id, "approval_id": approval_id, "state": "resolved", "accepted": body.get("choice") == "once"})
        app.state.realtime_requests[(document["conversation_id"], request_id)] = result
        return result

    @app.get("/v1/realtime/conversations/{conversation_id}")
    async def realtime_conversation(conversation_id: str, request: Request) -> dict[str, Any]:
        require_realtime_auth(request)
        session_id = app.state.realtime_by_conversation.get(conversation_id)
        return overridden("conversation", {
            "contract_version": "1.0",
            "conversation_id": conversation_id,
            "session": app.state.realtime_sessions.get(session_id),
            "pending_approvals": [{
                "approval_id": "approval_1",
                "state": "pending",
                "tool_call_id": "call_1",
                "tool_name": "run_shell",
                "expires_at": time.time() + 300,
            }],
            "worker_jobs": list(app.state.worker_jobs.get(conversation_id, {}).values()),
            "last_event_id": "ev_3",
        })

    @app.get("/v1/realtime/conversations/{conversation_id}/requests/{client_request_id}")
    async def realtime_request_result(
        conversation_id: str, client_request_id: str, request: Request
    ) -> dict[str, Any]:
        require_realtime_auth(request)
        result = app.state.realtime_requests.get((conversation_id, client_request_id))
        if result is None:
            raise HTTPException(status_code=404, detail="Request not found")
        return result

    worker_path = "/v1/realtime/conversations/{conversation_id}/worker-jobs"

    @app.get(worker_path)
    async def realtime_worker_jobs(conversation_id: str, request: Request) -> dict[str, Any]:
        require_realtime_auth(request)
        return {"object": "list", "data": list(app.state.worker_jobs.get(conversation_id, {}).values())}

    @app.get(worker_path + "/{worker_job_id}")
    async def realtime_worker_job(conversation_id: str, worker_job_id: str, request: Request) -> dict[str, Any]:
        require_realtime_auth(request)
        job = app.state.worker_jobs.get(conversation_id, {}).get(worker_job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Worker job not found")
        return overridden("worker_job", job)

    @app.get(worker_path + "/{worker_job_id}/events")
    async def realtime_worker_events(conversation_id: str, worker_job_id: str, request: Request, after: int = 0) -> dict[str, Any]:
        require_realtime_auth(request)
        job = app.state.worker_jobs.get(conversation_id, {}).get(worker_job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Worker job not found")
        events = [item for item in job["events"] if item["event_id"] > after]
        return {"worker_job_id": worker_job_id, "events": events, "last_event_id": events[-1]["event_id"] if events else after}

    @app.get(worker_path + "/{worker_job_id}/commands/{command_id}")
    async def realtime_worker_command_result(
        conversation_id: str,
        worker_job_id: str,
        command_id: str,
        request: Request,
    ) -> dict[str, Any]:
        require_realtime_auth(request)
        job = app.state.worker_jobs.get(conversation_id, {}).get(worker_job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Worker job not found")
        result = next(
            (item for item in job["commands"] if item["command_id"] == command_id),
            None,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Worker command not found")
        return dict(result)

    async def worker_command(conversation_id: str, worker_job_id: str, operation: str, request: Request) -> dict[str, Any]:
        require_realtime_auth(request)
        body = await request.json()
        job = app.state.worker_jobs.get(conversation_id, {}).get(worker_job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Worker job not found")
        command_id = body.get("command_id")
        app.state.worker_command_calls[command_id] = (
            app.state.worker_command_calls.get(command_id, 0) + 1
        )
        existing = next((item for item in job["commands"] if item["command_id"] == command_id), None)
        if existing is not None:
            return {
                **existing,
                "acknowledgement": (
                    "already_applied"
                    if existing["acknowledgement"] == "applied"
                    else existing["acknowledgement"]
                ),
                "control_signal_sent": False,
            }
        if job["status"] in {"completed", "failed", "cancelled", "outcome_unknown"}:
            result = {
                "command_id": command_id,
                "worker_job_id": worker_job_id,
                "acknowledgement": "rejected_terminal",
                "revision": job["revision"],
                "operation": operation,
                "control_signal_sent": False,
            }
            job["commands"].append(result)
            return result
        if body.get("expected_revision") != job["revision"]:
            result = {
                "command_id": command_id,
                "worker_job_id": worker_job_id,
                "acknowledgement": "rejected_stale_revision",
                "revision": job["revision"],
                "operation": operation,
                "control_signal_sent": False,
            }
            job["commands"].append(result)
            return result
        job["revision"] += 1
        result = {
            "command_id": command_id,
            "worker_job_id": worker_job_id,
            "acknowledgement": "applied",
            "revision": job["revision"],
            "operation": operation,
            "control_signal_sent": True,
        }
        if str(command_id).startswith("ambiguous_missing"):
            await asyncio.sleep(0.2)
            return result
        job["commands"].append(result)
        if str(command_id).startswith("ambiguous"):
            await asyncio.sleep(0.2)
        return result

    for operation in ("refine", "redirect", "cancel"):
        async def handler(conversation_id: str, worker_job_id: str, request: Request, op: str = operation):
            return await worker_command(conversation_id, worker_job_id, op, request)

        app.add_api_route(worker_path + f"/{{worker_job_id}}/{operation}", handler, methods=["POST"])

    return app
