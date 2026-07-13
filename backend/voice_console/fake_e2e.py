from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
import yaml
from fastapi.testclient import TestClient

from .app import create_app
from .fake_target import API_KEY, create_fake_hermes_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ThreadedServer:
    def __init__(self, app, port: int) -> None:
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(self.config)
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
        raise RuntimeError("server did not start")

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)


def run_fake_e2e() -> dict:
    fake_port = _free_port()
    token = "service-" + "x" * 24
    scope_secret = "scope-" + "y" * 24
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        voice_config = tmp / "voice.yaml"
        targets_config = tmp / "targets.yaml"
        voice_config.write_text(
            yaml.safe_dump(
                {
                    "server": {
                        "host": "127.0.0.1",
                        "port": 8787,
                        "public_base_url": "http://localhost:8787",
                        "allowed_hosts": ["localhost", "testserver"],
                        "state_dir": str(tmp / "state"),
                    },
                    "auth": {
                        "mode": "service",
                        "service_token_env": "VOICE_CONSOLE_SERVICE_TOKEN",
                        "scope_secret_env": "VOICE_CONSOLE_SCOPE_SECRET",
                    },
                    "voice": {
                        "stt_provider": "fake",
                        "tts_provider": "fake",
                        "speak_replies_default": True,
                        "fake_transcript": "hello fake hermes",
                    },
                }
            )
        )
        targets_config.write_text(
            yaml.safe_dump(
                {
                    "targets": {
                        "fake": {
                            "label": "Fake Hermes",
                            "base_url": f"http://127.0.0.1:{fake_port}",
                            "api_key_env": "FAKE_HERMES_API_KEY",
                            "default_session_key": "voice-console:fake",
                            "preferred_transport": "runs",
                        }
                    }
                }
            )
        )
        os.environ["VOICE_CONSOLE_SERVICE_TOKEN"] = token
        os.environ["VOICE_CONSOLE_SCOPE_SECRET"] = scope_secret
        os.environ["FAKE_HERMES_API_KEY"] = API_KEY
        with ThreadedServer(create_fake_hermes_app(), fake_port):
            app = create_app(
                config_path=voice_config,
                targets_path=targets_config,
                env_path=None,
                static_dir=None,
            )
            with (
                TestClient(app) as client,
            ):
                created = client.post(
                    "/api/sessions",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"target": "fake", "title": "Fake E2E"},
                )
                if created.status_code != 201:
                    raise AssertionError(f"fake E2E session create failed: {created.text}")
                conversation_id = str(created.json()["conversation_id"])
                with client.websocket_connect("/ws/voice") as ws:
                    ws.send_text(json.dumps({"type": "auth", "token": token}))
                    authenticated = ws.receive_json()
                    if authenticated.get("type") != "auth.ok":
                        raise AssertionError(f"fake E2E auth failed: {authenticated}")
                    ws.send_text(
                        json.dumps(
                            {
                                "type": "hello",
                                "version": 1,
                                "target": "fake",
                                "conversation_id": conversation_id,
                                "mode": "push_to_talk",
                                "input_format": "pcm16",
                                "input_sample_rate": 16000,
                                "speak_replies": True,
                            }
                        )
                    )
                    seen = [ws.receive_json()]
                    ws.send_text(json.dumps({"type": "recording.start", "turn_id": "fake-turn-1"}))
                    seen.append(ws.receive_json())
                    ws.send_bytes(b"\x00\x00" * 1600)
                    ws.send_text(json.dumps({"type": "recording.stop", "turn_id": "fake-turn-1"}))
                    binary_chunks = 0
                    deadline = time.time() + 15
                    while time.time() < deadline:
                        msg = ws.receive()
                        if "bytes" in msg and msg["bytes"] is not None:
                            binary_chunks += 1
                            continue
                        if "text" in msg and msg["text"] is not None:
                            payload = json.loads(msg["text"])
                            seen.append(payload)
                            if payload.get("type") == "tts.end":
                                break
                    ws.send_text(
                        json.dumps(
                            {
                                "type": "text.submit",
                                "turn_id": "fake-turn-2",
                                "text": "recall nonce from the prior turn",
                            }
                        )
                    )
                    second_completed = False
                    deadline = time.time() + 15
                    while time.time() < deadline:
                        msg = ws.receive()
                        if "bytes" in msg and msg["bytes"] is not None:
                            binary_chunks += 1
                            continue
                        if "text" in msg and msg["text"] is not None:
                            payload = json.loads(msg["text"])
                            seen.append(payload)
                            if payload.get("type") == "agent.completed":
                                second_completed = True
                                break
                    if not second_completed:
                        raise AssertionError("fake E2E text turn did not complete")
                types = [m.get("type") for m in seen]
                required = {
                    "ready",
                    "recording.started",
                    "recording.stopped",
                    "transcript.final",
                    "text.accepted",
                    "agent.run.started",
                    "agent.delta",
                    "agent.tool.started",
                    "agent.tool.completed",
                    "agent.completed",
                    "tts.start",
                    "tts.end",
                }
                missing = sorted(required - set(types))
                if missing:
                    raise AssertionError(f"fake E2E missing frames: {missing}; saw {types}")
                if binary_chunks < 1:
                    raise AssertionError("fake E2E did not receive TTS binary audio")
                return {"ok": True, "frames": types, "binary_chunks": binary_chunks}
    raise AssertionError("unreachable")


def main() -> None:
    print(json.dumps(run_fake_e2e(), indent=2))


if __name__ == "__main__":
    main()
