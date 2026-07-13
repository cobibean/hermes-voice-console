from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import os

import uvicorn

from .app import create_app
from .config import load_env_file, load_targets_config
from .fake_e2e import run_fake_e2e
from .fake_target import create_fake_hermes_app
from .smoke import run_smoke


def main() -> None:
    parser = argparse.ArgumentParser(prog="voice-console")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run the standalone voice console")
    serve.add_argument("--config", default="config/voice.yaml")
    serve.add_argument("--targets", default="config/targets.yaml")
    serve.add_argument("--env", default=".env")
    serve.add_argument("--static-dir", default="auto")

    fake = sub.add_parser("fake-target", help="Run a fake Hermes API Server target")
    fake.add_argument("--host", default="127.0.0.1")
    fake.add_argument("--port", type=int, default=9876)

    sub.add_parser("fake-e2e", help="Run deterministic fake voice-console E2E")

    smoke = sub.add_parser("smoke", help="Probe one Hermes API Server target safely")
    smoke.add_argument("--targets", default="config/targets.yaml")
    smoke.add_argument("--env", default=".env")
    smoke.add_argument("--target", required=True)
    smoke.add_argument("--read-only", action="store_true")
    smoke.add_argument("--allow-run", action="store_true")
    smoke.add_argument("--text")

    args = parser.parse_args()
    if args.cmd == "serve":
        app = create_app(
            config_path=args.config,
            targets_path=args.targets,
            env_path=args.env,
            static_dir=args.static_dir,
        )
        state = app.state.console_state
        level_name = os.environ.get("VOICE_CONSOLE_LOG_LEVEL", "INFO").strip().upper()
        level = getattr(logging, level_name, logging.INFO)
        log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
        log_config["loggers"]["voice_console"] = {
            "handlers": ["default"],
            "level": logging.getLevelName(level),
            "propagate": False,
        }
        uvicorn.run(
            app,
            host=state.config.server.host,
            port=state.config.server.port,
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
            workers=1,
            log_config=log_config,
            log_level=logging.getLevelName(level).lower(),
        )
    elif args.cmd == "fake-target":
        uvicorn.run(create_fake_hermes_app(), host=args.host, port=args.port)
    elif args.cmd == "fake-e2e":
        print(json.dumps(run_fake_e2e(), indent=2))
    elif args.cmd == "smoke":
        load_env_file(args.env)
        target = load_targets_config(args.targets).require(args.target)
        result = asyncio.run(
            run_smoke(
                target,
                read_only=args.read_only,
                allow_run=args.allow_run,
                text=args.text,
            )
        )
        print(json.dumps(result, indent=2))
