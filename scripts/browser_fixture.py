#!/usr/bin/env python
from __future__ import annotations

import os
import signal
import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
import yaml
from voice_console.app import create_app
from voice_console.fake_target import API_KEY, create_fake_hermes_app

ROOT = Path(__file__).resolve().parents[1]
CONSOLE_PORT = int(os.environ.get("HVC_BROWSER_CONSOLE_PORT", "8790"))
FAKE_PORT = int(os.environ.get("HVC_BROWSER_FAKE_PORT", "9877"))


class ServerThread:
    def __init__(self, app, port: int) -> None:
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.port = port

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                if sock.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.05)
        raise RuntimeError(f"browser fixture port {self.port} did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def main() -> None:
    os.environ["VOICE_CONSOLE_SCOPE_SECRET"] = "browser-scope-" + "s" * 24
    os.environ["FAKE_HERMES_API_KEY"] = API_KEY
    with tempfile.TemporaryDirectory(prefix="hvc-browser-") as directory:
        temp = Path(directory)
        voice = temp / "voice.yaml"
        targets = temp / "targets.yaml"
        voice.write_text(
            yaml.safe_dump(
                {
                    "server": {
                        "host": "127.0.0.1",
                        "port": CONSOLE_PORT,
                        "public_base_url": f"http://127.0.0.1:{CONSOLE_PORT}",
                        "allowed_hosts": ["127.0.0.1", "localhost"],
                        "state_dir": str(temp / "state"),
                    },
                    "auth": {"mode": "development"},
                    "voice": {
                        "stt_provider": "fake",
                        "tts_provider": "fake",
                        "speak_replies_default": False,
                        "fake_transcript": "browser microphone turn",
                        "min_recording_rms": 0,
                    },
                }
            )
        )
        targets.write_text(
            yaml.safe_dump(
                {
                    "targets": {
                        "fake": {
                            "label": "Browser Fake Hermes",
                            "base_url": f"http://127.0.0.1:{FAKE_PORT}",
                            "api_key_env": "FAKE_HERMES_API_KEY",
                            "default_session_key": "voice-console:browser-fake",
                            # Visual QA can exercise the Realtime presentation against the
                            # deterministic fake target without changing the default E2E lane.
                            "realtime_enabled": os.environ.get("HVC_BROWSER_REALTIME") == "1",
                        }
                    }
                }
            )
        )
        fake = ServerThread(create_fake_hermes_app(), FAKE_PORT)
        console = ServerThread(
            create_app(
                config_path=voice,
                targets_path=targets,
                env_path=None,
                static_dir=ROOT / "frontend" / "dist",
            ),
            CONSOLE_PORT,
        )
        fake.start()
        console.start()
        stopped = threading.Event()

        def request_stop(*_args) -> None:
            stopped.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        try:
            stopped.wait()
        finally:
            console.stop()
            fake.stop()


if __name__ == "__main__":
    main()
