from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn
from voice_console.config import TargetConfig
from voice_console.fake_target import API_KEY, create_fake_hermes_app
from voice_console.smoke import run_smoke


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Server:
    def __init__(self, port: int) -> None:
        self.server = uvicorn.Server(
            uvicorn.Config(
                create_fake_hermes_app(), host="127.0.0.1", port=port, log_level="warning"
            )
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.port = port

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                if sock.connect_ex(("127.0.0.1", self.port)) == 0:
                    return self
            time.sleep(0.02)
        raise RuntimeError("server failed to start")

    def __exit__(self, *_exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.mark.asyncio
async def test_read_only_smoke_is_sanitized(monkeypatch) -> None:
    port = free_port()
    monkeypatch.setenv("FAKE_KEY", API_KEY)
    target = TargetConfig(
        name="fake",
        label="Fake",
        base_url=f"http://127.0.0.1:{port}",
        api_key_env="FAKE_KEY",
        default_session_key="voice-console:fake",
    )
    with Server(port):
        result = await run_smoke(target, read_only=True)
    assert result["ok"] is True
    assert [check["name"] for check in result["checks"]] == [
        "health",
        "health_detailed",
        "capabilities",
        "toolsets",
        "models",
    ]
    assert "Bearer" not in str(result)
    assert "authorization" not in str(result).lower()
    assert target.base_url not in str(result)


@pytest.mark.asyncio
async def test_write_smoke_requires_double_opt_in_and_omits_content(monkeypatch) -> None:
    port = free_port()
    monkeypatch.setenv("FAKE_KEY", API_KEY)
    target = TargetConfig(
        name="fake",
        label="Fake",
        base_url=f"http://127.0.0.1:{port}",
        api_key_env="FAKE_KEY",
        default_session_key="voice-console:fake",
    )
    with pytest.raises(ValueError):
        await run_smoke(target, read_only=False, allow_run=False, text="secret prompt")
    with Server(port):
        result = await run_smoke(
            target,
            read_only=False,
            allow_run=True,
            text="secret prompt",
        )
    assert "agent.completed" in result["run"]["events"]
    assert "secret prompt" not in str(result)
    assert "Fake response" not in str(result)
