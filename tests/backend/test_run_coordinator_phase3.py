from __future__ import annotations

import asyncio
import os
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from voice_console.auth import AuthGate
from voice_console.config import AuthConfig, AuthMode, TargetConfig, TargetsConfig
from voice_console.hermes_client import HermesAmbiguousSubmission, HermesApiError
from voice_console.run_coordinator import AcceptanceUnknown, RunCoordinator
from voice_console.run_store import ConsoleStore, SessionRecord
from voice_console.session_manager import SessionManager
from voice_console.voice_socket import _safe_approval_event


class ControlledTransport:
    def __init__(self) -> None:
        self.starts = 0
        self.histories: list[list[dict[str, str]]] = []
        self.release = asyncio.Event()
        self.run_id = "run-controlled"
        self.approvals: list[tuple[str, str]] = []
        self.stops: list[str] = []

    async def start(
        self,
        *,
        session_id: str,
        session_key: str,
        text: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        assert session_id.startswith("hvc_")
        assert session_key.startswith("voice-console:")
        assert text
        self.starts += 1
        self.histories.append(conversation_history or [])
        return f"{self.run_id}-{self.starts}"

    async def events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        await self.release.wait()
        yield {"type": "agent.delta", "run_id": run_id, "delta": "private-content"}
        yield {"type": "agent.completed", "run_id": run_id, "text": "private-content"}

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "status": "completed", "output": "private-content"}

    async def approve(self, run_id: str, decision: str) -> dict[str, Any]:
        self.approvals.append((run_id, decision))
        return {"run_id": run_id, "choice": decision}

    async def stop(self, run_id: str) -> dict[str, Any]:
        self.stops.append(run_id)
        return {"run_id": run_id, "status": "stopping"}


class AmbiguousTransport(ControlledTransport):
    async def start(self, **_kwargs: Any) -> str:
        self.starts += 1
        raise HermesAmbiguousSubmission("response dropped after acceptance")


class MissingRunTransport(ControlledTransport):
    async def get_run(self, run_id: str) -> dict[str, Any]:
        raise HermesApiError(f"run not found: {run_id}")


class BurstTransport(ControlledTransport):
    def __init__(self) -> None:
        super().__init__()
        self.finish = asyncio.Event()

    async def events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        for index in range(100):
            yield {"type": "agent.delta", "run_id": run_id, "delta": str(index)}
        await self.finish.wait()
        yield {"type": "agent.completed", "run_id": run_id, "text": "done"}


def coordinator_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    gate = AuthGate(
        AuthConfig(mode=AuthMode.DEVELOPMENT),
        public_base_url="http://localhost:8787",
        allowed_hosts=("localhost",),
    )
    store = ConsoleStore(tmp_path / "state")
    assert (os.stat(store.path.parent).st_mode & 0o777) == 0o700
    assert (os.stat(store.path).st_mode & 0o777) == 0o600
    sessions = SessionManager(store, gate)
    target = TargetConfig(
        name="fake",
        label="Fake",
        base_url="http://127.0.0.1:9999",
        api_key_env="FAKE_KEY",
        default_session_key="voice-console:fake",
    )
    record = store.create_session(
        conversation_id="hvc_session",
        target_name="fake",
        hermes_session_id="hvc_session",
        memory_session_key="voice-console:owner",
        owner_key="owner",
        title="Test",
    )
    coordinator = RunCoordinator(
        store=store,
        sessions=sessions,
        targets=TargetsConfig({"fake": target}),
        max_events=10,
    )

    history: list[dict[str, str]] = []

    async def fake_history(
        session: SessionRecord, *, target: TargetConfig
    ) -> tuple[SessionRecord, list[dict[str, str]]]:
        return session, list(history)

    monkeypatch.setattr(sessions, "history", fake_history)
    return coordinator, store, target, record, history


async def drain(queue: asyncio.Queue[dict[str, Any] | None]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=2)
        if event is None:
            return events
        events.append(event)


@pytest.mark.asyncio
async def test_disconnect_reconnect_keeps_one_backend_owned_post(tmp_path, monkeypatch) -> None:
    coordinator, store, target, session, _history = coordinator_fixture(tmp_path, monkeypatch)
    transport = ControlledTransport()
    monkeypatch.setattr(coordinator, "_transport", lambda _target: transport)

    run, first_queue = await coordinator.start(
        target=target,
        session=session,
        turn_id="turn-1",
        text="unique-private-prompt",
    )
    assert (await first_queue.get())["type"] == "agent.run.started"
    coordinator.unsubscribe(run.run_id or "", first_queue)

    with pytest.raises(KeyError):
        coordinator.subscribe(run_id=run.run_id or "", owner_key="other")
    with pytest.raises(KeyError):
        await coordinator.approve(run.run_id or "", "once", owner_key="other")
    with pytest.raises(KeyError):
        await coordinator.stop(run.run_id or "", owner_key="other")

    resumed = coordinator.subscribe(run_id=run.run_id or "", owner_key="owner")
    transport.release.set()
    events = await drain(resumed)
    assert transport.starts == 1
    assert [event["type"] for event in events][-1] == "agent.completed"
    assert store.require_run(run_id=run.run_id).status == "completed"
    assert "unique-private-prompt" not in store.path.read_bytes().decode(errors="ignore")
    assert "private-content" not in store.path.read_bytes().decode(errors="ignore")


@pytest.mark.asyncio
async def test_ambiguous_submission_stays_locked_until_owner_acknowledges(
    tmp_path, monkeypatch
) -> None:
    coordinator, store, target, session, _history = coordinator_fixture(tmp_path, monkeypatch)
    transport = AmbiguousTransport()
    monkeypatch.setattr(coordinator, "_transport", lambda _target: transport)

    with pytest.raises(AcceptanceUnknown) as unknown:
        await coordinator.start(target=target, session=session, turn_id="turn-1", text="hello")
    assert transport.starts == 1
    locked = store.active_run_for_conversation(session.conversation_id, owner_key="owner")
    assert locked and locked.status == "acceptance_unknown"
    with pytest.raises(RuntimeError, match="locked"):
        await coordinator.start(target=target, session=session, turn_id="turn-2", text="retry")
    other_session = store.create_session(
        conversation_id="hvc_other_conversation",
        target_name="fake",
        hermes_session_id="hvc_other_conversation",
        memory_session_key=session.memory_session_key,
        owner_key="owner",
        title="Other conversation",
    )
    with pytest.raises(RuntimeError, match="owner-target"):
        await coordinator.start(
            target=target,
            session=other_session,
            turn_id="turn-3",
            text="bypass attempt",
        )
    coordinator.acknowledge_unknown(unknown.value.local_turn_id, owner_key="owner")
    assert store.active_run_for_conversation(session.conversation_id, owner_key="owner") is None
    with pytest.raises(KeyError):
        coordinator.acknowledge_unknown(unknown.value.local_turn_id, owner_key="other")


@pytest.mark.asyncio
async def test_second_turn_receives_first_turn_history_without_sqlite_content(
    tmp_path, monkeypatch
) -> None:
    coordinator, store, target, session, history = coordinator_fixture(tmp_path, monkeypatch)
    transport = ControlledTransport()
    monkeypatch.setattr(coordinator, "_transport", lambda _target: transport)

    _first, first_queue = await coordinator.start(
        target=target, session=session, turn_id="turn-1", text="nonce cobalt-77"
    )
    transport.release.set()
    await drain(first_queue)
    history.extend(
        [
            {"role": "user", "content": "nonce cobalt-77"},
            {"role": "assistant", "content": "acknowledged"},
        ]
    )
    _second, second_queue = await coordinator.start(
        target=target, session=session, turn_id="turn-2", text="recall nonce"
    )
    await drain(second_queue)
    assert transport.histories[1] == history
    with sqlite3.connect(store.path) as database:
        columns = {
            row[1]
            for table in ("sessions", "runs")
            for row in database.execute(f"PRAGMA table_info({table})")
        }
    assert not {"content", "transcript", "response", "approval"}.intersection(columns)


def test_session_ownership_rotation_conflict_and_approval_scope(tmp_path, monkeypatch) -> None:
    _coordinator, store, _target, session, _history = coordinator_fixture(tmp_path, monkeypatch)
    with pytest.raises(KeyError):
        store.require_session(session.conversation_id, owner_key="other")

    store.create_session(
        conversation_id="hvc_other",
        target_name="fake",
        hermes_session_id="hvc_rotated",
        memory_session_key="voice-console:other",
        owner_key="other",
        title="Other",
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.adopt_hermes_session(
            session.conversation_id,
            owner_key="owner",
            hermes_session_id="hvc_rotated",
        )

    raw = {
        "type": "agent.approval.request",
        "approval": {
            "choices": ["once", "session", "always", "deny"],
            "allow_permanent": False,
        },
    }
    safe = _safe_approval_event(raw, persistent_enabled=True)
    assert safe["approval"]["choices"] == ["once", "session", "deny"]
    allowed = _safe_approval_event(
        {**raw, "approval": {**raw["approval"], "allow_permanent": True}},
        persistent_enabled=True,
    )
    assert "always" in allowed["approval"]["choices"]


@pytest.mark.asyncio
async def test_session_manager_adopts_authoritative_rotated_id_and_fails_conflict(
    tmp_path, monkeypatch
) -> None:
    _coordinator, store, target, session, _history = coordinator_fixture(tmp_path, monkeypatch)

    class RotatingClient:
        def __init__(self, _target: TargetConfig) -> None:
            pass

        async def session_messages(self, _session_id: str) -> dict[str, Any]:
            return {
                "session_id": "hvc_rotated",
                "messages": [{"role": "user", "content": "prior"}],
            }

    monkeypatch.setattr("voice_console.session_manager.HermesApiClient", RotatingClient)
    manager = SessionManager(
        store,
        AuthGate(
            AuthConfig(mode=AuthMode.DEVELOPMENT),
            public_base_url="http://localhost:8787",
            allowed_hosts=("localhost",),
        ),
    )
    rotated, history = await manager.history(session, target=target)
    assert rotated.hermes_session_id == "hvc_rotated"
    assert history == [{"role": "user", "content": "prior"}]

    store.create_session(
        conversation_id="hvc_conflict_owner",
        target_name="fake",
        hermes_session_id="hvc_conflict",
        memory_session_key="voice-console:other",
        owner_key="other",
        title="Conflict",
    )

    class ConflictingClient(RotatingClient):
        async def session_messages(self, _session_id: str) -> dict[str, Any]:
            return {"session_id": "hvc_conflict", "messages": []}

    monkeypatch.setattr("voice_console.session_manager.HermesApiClient", ConflictingClient)
    with pytest.raises(sqlite3.IntegrityError):
        await manager.history(rotated, target=target)


@pytest.mark.asyncio
async def test_process_metadata_reload_reconciles_without_reposting(tmp_path, monkeypatch) -> None:
    coordinator, store, target, session, _history = coordinator_fixture(tmp_path, monkeypatch)
    pending = store.insert_run(
        local_turn_id="local-restart",
        target_name=target.name,
        session=session,
        turn_id="turn-restart",
    )
    store.update_run(pending.local_turn_id, run_id="run-restart", status="running")
    transport = ControlledTransport()
    monkeypatch.setattr(coordinator, "_transport", lambda _target: transport)

    await coordinator.recover()
    for _attempt in range(20):
        if store.require_run(run_id="run-restart").status == "completed":
            break
        await asyncio.sleep(0.01)
    assert store.require_run(run_id="run-restart").status == "completed"
    assert transport.starts == 0
    await coordinator.close()


@pytest.mark.asyncio
async def test_missing_run_after_restart_stays_locked_until_acknowledged(
    tmp_path, monkeypatch
) -> None:
    coordinator, store, target, session, _history = coordinator_fixture(tmp_path, monkeypatch)
    pending = store.insert_run(
        local_turn_id="local-missing",
        target_name=target.name,
        session=session,
        turn_id="turn-missing",
    )
    store.update_run(pending.local_turn_id, run_id="run-missing", status="running")
    transport = MissingRunTransport()
    monkeypatch.setattr(coordinator, "_transport", lambda _target: transport)

    await coordinator.recover()
    for _attempt in range(20):
        if store.require_run(run_id="run-missing").status == "unrecoverable":
            break
        await asyncio.sleep(0.01)
    assert store.require_run(run_id="run-missing").status == "unrecoverable"
    assert store.active_run_for_conversation(session.conversation_id, owner_key="owner")
    coordinator.acknowledge_unrecoverable("run-missing", owner_key="owner")
    assert store.active_run_for_conversation(session.conversation_id, owner_key="owner") is None
    await coordinator.close()


@pytest.mark.asyncio
async def test_bounded_subscriber_replay_emits_gap_snapshot(tmp_path, monkeypatch) -> None:
    coordinator, store, target, session, _history = coordinator_fixture(tmp_path, monkeypatch)
    transport = BurstTransport()
    monkeypatch.setattr(coordinator, "_transport", lambda _target: transport)
    run, _ignored_queue = await coordinator.start(
        target=target,
        session=session,
        turn_id="turn-burst",
        text="burst",
    )
    for _attempt in range(50):
        if store.require_run(run_id=run.run_id).last_sequence >= 100:
            break
        await asyncio.sleep(0.01)
    replay = coordinator.subscribe(run_id=run.run_id or "", owner_key="owner", last_sequence=1)
    snapshot = await replay.get()
    assert snapshot["type"] == "run.snapshot"
    assert snapshot["gap"] is True
    assert replay.qsize() <= 62
    transport.finish.set()
    await coordinator.close()
