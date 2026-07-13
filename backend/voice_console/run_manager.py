from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .hermes_client import ApiRunsTransport
from .run_store import ConnectionRunStore


class RunManager:
    """Own the connection's run transport and lifecycle bookkeeping."""

    def __init__(
        self,
        transport: ApiRunsTransport,
        store: ConnectionRunStore | None = None,
    ) -> None:
        self.transport = transport
        self.store = store or ConnectionRunStore()

    @property
    def active_run_id(self) -> str | None:
        return self.store.active_run_id

    async def events(
        self,
        *,
        session_id: str,
        session_key: str,
        text: str,
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in self.transport.send_turn(
            session_id=session_id,
            session_key=session_key,
            text=text,
        ):
            run_id = str(event.get("run_id") or "")
            event_type = event.get("type")
            if event_type == "agent.run.started" and run_id:
                self.store.started(run_id)
            if event_type in {"agent.completed", "agent.failed", "agent.stopped"}:
                self.store.finished(run_id or None)
            yield event

    async def approve(self, run_id: str, decision: str) -> dict[str, Any]:
        return await self.transport.approve(run_id, decision)

    async def stop(self, run_id: str) -> dict[str, Any]:
        result = await self.transport.stop(run_id)
        return result
