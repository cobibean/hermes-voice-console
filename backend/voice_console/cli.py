from __future__ import annotations

import argparse
import json

import uvicorn

from .app import create_app
from .fake_e2e import run_fake_e2e
from .fake_target import create_fake_hermes_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="voice-console")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run the standalone voice console")
    serve.add_argument("--config", default="config/voice.yaml")
    serve.add_argument("--targets", default="config/targets.yaml")
    serve.add_argument("--env", default=".env")
    serve.add_argument("--static-dir", default="frontend/dist")

    fake = sub.add_parser("fake-target", help="Run a fake Hermes API Server target")
    fake.add_argument("--host", default="127.0.0.1")
    fake.add_argument("--port", type=int, default=9876)

    sub.add_parser("fake-e2e", help="Run deterministic fake voice-console E2E")

    args = parser.parse_args()
    if args.cmd == "serve":
        app = create_app(config_path=args.config, targets_path=args.targets, env_path=args.env, static_dir=args.static_dir)
        state = app.state.console_state
        uvicorn.run(app, host=state.config.server.host, port=state.config.server.port)
    elif args.cmd == "fake-target":
        uvicorn.run(create_fake_hermes_app(), host=args.host, port=args.port)
    elif args.cmd == "fake-e2e":
        print(json.dumps(run_fake_e2e(), indent=2))
