from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn
from voice_console.config import TargetConfig
from voice_console.fake_target import API_KEY, create_fake_hermes_app
from voice_console.hermes_client import ApiRunsTransport, HermesApiClient


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Server:
    def __init__(self, app, port: int) -> None:
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.port = port

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                if sock.connect_ex(("127.0.0.1", self.port)) == 0:
                    return self
            time.sleep(0.05)
        raise RuntimeError("server failed to start")

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.mark.asyncio
async def test_api_runs_transport_streams_fake_events(monkeypatch):
    port = free_port()
    monkeypatch.setenv("FAKE_HERMES_API_KEY", API_KEY)
    target = TargetConfig(
        name="fake",
        label="Fake",
        base_url=f"http://127.0.0.1:{port}",
        api_key_env="FAKE_HERMES_API_KEY",
        default_session_key="voice-console:fake",
    )
    with Server(create_fake_hermes_app(), port):
        transport = ApiRunsTransport(HermesApiClient(target))
        caps = await transport.capabilities()
        assert caps.supports_runs() is True
        seen = []
        async for event in transport.send_turn(session_id="s1", session_key="sk1", text="hello"):
            seen.append(event)
        types = [e["type"] for e in seen]
        assert "agent.run.started" in types
        assert "agent.delta" in types
        assert "agent.tool.started" in types
        assert "agent.completed" in types
        assert seen[-1]["text"] == "Fake response to: hello"
        messages = await transport.client.session_messages("s1")
        assert [message["role"] for message in messages["messages"]] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_api_runs_transport_approval_flow(monkeypatch):
    port = free_port()
    monkeypatch.setenv("FAKE_HERMES_API_KEY", API_KEY)
    target = TargetConfig(
        name="fake",
        label="Fake",
        base_url=f"http://127.0.0.1:{port}",
        api_key_env="FAKE_HERMES_API_KEY",
        default_session_key="voice-console:fake",
    )
    with Server(create_fake_hermes_app(), port):
        transport = ApiRunsTransport(HermesApiClient(target))
        events = []
        async for event in transport.send_turn(
            session_id="s1", session_key="sk1", text="need approval"
        ):
            events.append(event)
            if event["type"] == "agent.approval.request":
                await transport.approve(str(event["run_id"]), "once")
        assert "agent.approval.request" in [e["type"] for e in events]
        assert events[-1]["type"] == "agent.completed"


def test_capabilities_require_stop_and_approval_features():
    from voice_console.hermes_client import Capabilities

    good = Capabilities(
        {
            "features": {
                "run_submission": True,
                "run_events_sse": True,
                "run_stop": True,
                "run_approval_response": True,
                "approval_events": True,
            },
            "endpoints": {"runs": {}, "run_events": {}, "run_approval": {}, "run_stop": {}},
        }
    )
    assert good.supports_runs() is True
    missing_stop = Capabilities(
        {
            "features": {
                "run_submission": True,
                "run_events_sse": True,
                "run_approval_response": True,
                "approval_events": True,
            },
            "endpoints": {"runs": {}, "run_events": {}, "run_approval": {}},
        }
    )
    assert missing_stop.supports_runs() is False


@pytest.mark.asyncio
async def test_session_client_accepts_real_hermes_resource_shapes(monkeypatch):
    class Response:
        status_code = 201

        def json(self):
            return {"object": "hermes.session", "session": {"id": "hvc_real"}}

    class AsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(
        "voice_console.hermes_client.httpx.AsyncClient", lambda **_kwargs: AsyncClient()
    )
    monkeypatch.setenv("FAKE_KEY", API_KEY)
    client = HermesApiClient(
        TargetConfig(
            name="fake",
            label="Fake",
            base_url="http://127.0.0.1:1",
            api_key_env="FAKE_KEY",
            default_session_key="voice-console:fake",
        )
    )
    assert await client.create_session("hvc_real") == "hvc_real"
