from __future__ import annotations

import json
import logging
from typing import Any


def diagnostic(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Emit one content-free structured lifecycle record for humans and agents."""
    payload = {"component": "hermes-voice-console", "event": event, **fields}
    logger.log(level, json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))
