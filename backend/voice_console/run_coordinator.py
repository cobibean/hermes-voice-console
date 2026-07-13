from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from .config import TargetConfig, TargetsConfig
from .diagnostics import diagnostic
from .hermes_client import (
    ApiRunsTransport,
    HermesAmbiguousSubmission,
    HermesApiClient,
    HermesApiError,
)
from .run_store import ConsoleStore, RunRecord, SessionRecord
from .session_manager import SessionManager

log = logging.getLogger(__name__)
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "rejected"}


@dataclass(frozen=True)
class AcceptanceUnknown(Exception):
    local_turn_id: str


@dataclass
class ActiveRun:
    record: RunRecord
    transport: ApiRunsTransport
    max_events: int
    events: deque[dict[str, Any]] = field(default_factory=deque)
    subscribers: set[asyncio.Queue[dict[str, Any] | None]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None


class RunCoordinator:
    """Backend-owned Hermes run lifecycle with bounded reconnect fan-out."""

    def __init__(
        self,
        *,
        store: ConsoleStore,
        sessions: SessionManager,
        targets: TargetsConfig,
        max_events: int = 250,
        terminal_retention_seconds: int = 7_200,
    ) -> None:
        self.store = store
        self.sessions = sessions
        self.targets = targets
        self.max_events = max_events
        self.terminal_retention_seconds = terminal_retention_seconds
        self._active: dict[str, ActiveRun] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def _transport(self, target: TargetConfig) -> ApiRunsTransport:
        return ApiRunsTransport(HermesApiClient(target))

    async def start(
        self,
        *,
        target: TargetConfig,
        session: SessionRecord,
        turn_id: str,
        text: str,
    ) -> tuple[RunRecord, asyncio.Queue[dict[str, Any] | None]]:
        diagnostic(
            log,
            "coordinator.start",
            target=target.name,
            conversation_id=session.conversation_id,
            turn_id=turn_id,
            input_chars=len(text),
        )
        lock = self._locks.setdefault((target.name, session.conversation_id), asyncio.Lock())
        async with lock:
            uncertainty_fence = self.store.acceptance_unknown_for_owner_target(
                owner_key=session.owner_key,
                target_name=target.name,
            )
            if uncertainty_fence:
                raise RuntimeError("owner-target is locked by an acceptance_unknown turn")
            existing = self.store.active_run_for_conversation(
                session.conversation_id, owner_key=session.owner_key
            )
            if existing:
                raise RuntimeError(f"conversation is locked by {existing.status}")

            local_turn_id = f"local_{uuid.uuid4().hex}"
            record = self.store.insert_run(
                local_turn_id=local_turn_id,
                target_name=target.name,
                session=session,
                turn_id=turn_id,
            )
            transport = self._transport(target)
            try:
                has_prior = self.store.has_completed_run(
                    session.conversation_id, owner_key=session.owner_key
                )
                for attempt in range(3):
                    resolved_session, history = await self.sessions.history(session, target=target)
                    roles = {item["role"] for item in history}
                    if not has_prior or {"user", "assistant"}.issubset(roles):
                        break
                    if attempt < 2:
                        await asyncio.sleep(0.2)
                else:
                    raise HermesApiError("prior completed turn is not visible in Hermes SessionDB")
                run_id = await transport.start(
                    session_id=resolved_session.hermes_session_id,
                    session_key=resolved_session.memory_session_key,
                    text=text,
                    conversation_history=history,
                )
                diagnostic(
                    log,
                    "coordinator.hermes.accepted",
                    target=target.name,
                    conversation_id=session.conversation_id,
                    turn_id=turn_id,
                    run_id=run_id,
                    history_messages=len(history),
                    history_attempts=attempt + 1,
                )
            except HermesAmbiguousSubmission as exc:
                self.store.update_run(
                    local_turn_id,
                    status="acceptance_unknown",
                    failure_category="ambiguous_submission",
                )
                raise AcceptanceUnknown(local_turn_id) from exc
            except Exception:
                self.store.update_run(
                    local_turn_id,
                    status="rejected",
                    failure_category="submission_failed",
                    terminal=True,
                )
                raise

            record = self.store.update_run(local_turn_id, run_id=run_id, status="running")
            active = ActiveRun(record=record, transport=transport, max_events=self.max_events)
            active.events = deque(maxlen=self.max_events)
            self._active[run_id] = active
            queue = self._subscribe_active(active, last_sequence=0)
            await self._emit(
                active,
                {
                    "type": "agent.run.started",
                    "run_id": run_id,
                    "session_id": record.hermes_session_id,
                    "turn_id": turn_id,
                },
            )
            active.task = asyncio.create_task(self._consume(active))
            return active.record, queue

    async def _consume(self, active: ActiveRun) -> None:
        try:
            assert active.record.run_id
            async for event in active.transport.events(active.record.run_id):
                event["turn_id"] = active.record.turn_id
                await self._emit(active, event)
                if event.get("type") in {"agent.completed", "agent.failed", "agent.stopped"}:
                    diagnostic(
                        log,
                        "coordinator.terminal",
                        run_id=active.record.run_id,
                        turn_id=active.record.turn_id,
                        terminal_event=event.get("type"),
                        sequence=active.record.last_sequence,
                    )
                    return
            if active.record.status not in TERMINAL_STATUSES:
                await self._reconcile(active)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning(
                "Hermes event stream lost run=%s owner=%s",
                active.record.run_id,
                active.record.owner_key[:10],
            )
            diagnostic(
                log,
                "coordinator.reconcile.started",
                level=logging.WARNING,
                run_id=active.record.run_id,
                turn_id=active.record.turn_id,
            )
            await self._reconcile(active)

    async def _reconcile(self, active: ActiveRun) -> None:
        assert active.record.run_id
        for _attempt in range(120):
            try:
                document = await active.transport.get_run(active.record.run_id)
            except HermesApiError:
                active.record = self.store.update_run(
                    active.record.local_turn_id,
                    status="unrecoverable",
                    failure_category="run_unrecoverable",
                )
                await self._emit(
                    active,
                    {
                        "type": "run.unrecoverable",
                        "run_id": active.record.run_id,
                        "turn_id": active.record.turn_id,
                        "error": "Hermes no longer exposes this run; acknowledgement is required",
                    },
                )
                return
            status = str(document.get("status") or "").lower()
            if status == "completed":
                await self._terminal(
                    active,
                    {
                        "type": "agent.completed",
                        "run_id": active.record.run_id,
                        "turn_id": active.record.turn_id,
                        "text": str(document.get("output") or ""),
                        "recovered": True,
                    },
                    status="completed",
                )
                return
            if status in {"cancelled", "stopped"}:
                await self._terminal(
                    active,
                    {
                        "type": "agent.stopped",
                        "run_id": active.record.run_id,
                        "turn_id": active.record.turn_id,
                        "recovered": True,
                    },
                    status="cancelled",
                )
                return
            if status == "failed":
                await self._terminal(
                    active,
                    {
                        "type": "agent.failed",
                        "run_id": active.record.run_id,
                        "turn_id": active.record.turn_id,
                        "error": "Hermes run failed",
                        "recovered": True,
                    },
                    status="failed",
                    failure_category="target_failed",
                )
                return
            if status == "waiting_for_approval":
                await self._emit(
                    active,
                    {
                        "type": "agent.approval.context_missing",
                        "run_id": active.record.run_id,
                        "turn_id": active.record.turn_id,
                        "message": "Approval details are unavailable after recovery; stop is the only safe action.",
                    },
                )
                return
            await asyncio.sleep(1)

    async def _emit(self, active: ActiveRun, event: dict[str, Any]) -> None:
        sequence = active.record.last_sequence + 1
        event = {**event, "sequence": sequence}
        active.events.append(event)
        terminal_type = event.get("type")
        status = {
            "agent.completed": "completed",
            "agent.failed": "failed",
            "agent.stopped": "cancelled",
            "agent.approval.request": "waiting_for_approval",
            "agent.approval.responded": "running",
            "agent.approval.resolved": "running",
        }.get(str(terminal_type))
        active.record = self.store.update_run(
            active.record.local_turn_id,
            status=status,
            last_sequence=sequence,
            terminal=terminal_type in {"agent.completed", "agent.failed", "agent.stopped"},
        )
        dead: list[asyncio.Queue[dict[str, Any] | None]] = []
        for queue in active.subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            active.subscribers.discard(queue)
        if terminal_type in {"agent.completed", "agent.failed", "agent.stopped"}:
            for queue in active.subscribers:
                with suppress(asyncio.QueueFull):
                    queue.put_nowait(None)
            self._active.pop(active.record.run_id or "", None)

    async def _terminal(
        self,
        active: ActiveRun,
        event: dict[str, Any],
        *,
        status: str,
        failure_category: str | None = None,
    ) -> None:
        active.record = self.store.update_run(
            active.record.local_turn_id,
            status=status,
            failure_category=failure_category,
        )
        await self._emit(active, event)

    def _subscribe_active(
        self, active: ActiveRun, *, last_sequence: int
    ) -> asyncio.Queue[dict[str, Any] | None]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=64)
        if active.events:
            oldest = int(active.events[0].get("sequence") or 0)
            pending = [
                event for event in active.events if int(event.get("sequence") or 0) > last_sequence
            ]
            gap = bool(last_sequence and last_sequence < oldest - 1) or len(pending) > 62
            if gap:
                queue.put_nowait(
                    {
                        "type": "run.snapshot",
                        "run_id": active.record.run_id,
                        "status": active.record.status,
                        "last_sequence": active.record.last_sequence,
                        "gap": True,
                    }
                )
                pending = pending[-62:]
            for event in pending:
                queue.put_nowait(event)
        active.subscribers.add(queue)
        return queue

    def subscribe(
        self,
        *,
        run_id: str,
        owner_key: str,
        last_sequence: int = 0,
    ) -> asyncio.Queue[dict[str, Any] | None]:
        record = self.store.require_run(run_id=run_id, owner_key=owner_key)
        active = self._active.get(run_id)
        if active:
            return self._subscribe_active(active, last_sequence=last_sequence)
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=2)
        queue.put_nowait(
            {
                "type": "run.snapshot",
                "run_id": run_id,
                "status": record.status,
                "last_sequence": record.last_sequence,
                "gap": True,
            }
        )
        if record.status in TERMINAL_STATUSES:
            queue.put_nowait(None)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        active = self._active.get(run_id)
        if active:
            active.subscribers.discard(queue)

    async def approve(self, run_id: str, decision: str, *, owner_key: str) -> dict[str, Any]:
        self.store.require_run(run_id=run_id, owner_key=owner_key)
        active = self._active.get(run_id)
        if not active:
            raise RuntimeError("approval context is unavailable; stop the run instead")
        if decision == "always":
            approval_events = [
                event for event in active.events if event.get("type") == "agent.approval.request"
            ]
            latest_approval = approval_events[-1].get("approval") if approval_events else None
            if (
                not isinstance(latest_approval, dict)
                or latest_approval.get("allow_permanent") is not True
            ):
                raise RuntimeError("Hermes did not authorize a persistent approval")
        result = await active.transport.approve(run_id, decision)
        await self._emit(
            active,
            {"type": "agent.approval.resolved", "run_id": run_id, "result": result},
        )
        return result

    async def stop(self, run_id: str, *, owner_key: str) -> dict[str, Any]:
        record = self.store.require_run(run_id=run_id, owner_key=owner_key)
        active = self._active.get(run_id)
        transport = (
            active.transport
            if active
            else self._transport(self.targets.require(record.target_name))
        )
        result = await transport.stop(run_id)
        if active:
            await self._emit(
                active,
                {"type": "agent.stop.requested", "run_id": run_id, "result": result},
            )
        return result

    def acknowledge_unknown(self, local_turn_id: str, *, owner_key: str) -> RunRecord:
        return self.store.acknowledge_unknown(local_turn_id, owner_key=owner_key)

    def acknowledge_unrecoverable(self, run_id: str, *, owner_key: str) -> RunRecord:
        self._active.pop(run_id, None)
        return self.store.acknowledge_unrecoverable(run_id, owner_key=owner_key)

    async def recover(self) -> None:
        self.store.cleanup_terminal(time.time() - self.terminal_retention_seconds)
        for record in self.store.list_recoverable_runs():
            if not record.run_id or record.status in {"acceptance_unknown", "unrecoverable"}:
                continue
            target = self.targets.require(record.target_name)
            active = ActiveRun(
                record=record,
                transport=self._transport(target),
                max_events=self.max_events,
                events=deque(maxlen=self.max_events),
            )
            self._active[record.run_id] = active
            active.task = asyncio.create_task(self._reconcile(active))

    async def close(self) -> None:
        tasks = [active.task for active in self._active.values() if active.task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
