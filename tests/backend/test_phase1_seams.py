from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from voice_console.config import TargetConfig, VoiceConfig
from voice_console.protocol import VoiceProtocolError
from voice_console.run_manager import RunManager
from voice_console.run_store import ConnectionRunStore
from voice_console.session_manager import SessionManager
from voice_console.tts_session import TtsSession
from voice_console.voice_session import RecordingSession


class FakeRunsTransport:
    async def send_turn(
        self,
        *,
        session_id: str,
        session_key: str,
        text: str,
    ) -> AsyncIterator[dict[str, Any]]:
        assert (session_id, session_key, text) == ("session", "key", "hello")
        yield {"type": "agent.run.started", "run_id": "run-1"}
        yield {"type": "agent.completed", "run_id": "run-1", "text": "done"}

    async def approve(self, run_id: str, decision: str) -> dict[str, Any]:
        return {"run_id": run_id, "decision": decision}

    async def stop(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "stopped": True}


def test_connection_run_store_only_finishes_the_active_run() -> None:
    store = ConnectionRunStore()
    store.started("run-1")
    store.finished("run-2")
    assert store.active_run_id == "run-1"
    store.finished("run-1")
    assert store.active_run_id is None


def test_session_manager_normalizes_hello_and_defaults() -> None:
    target = TargetConfig(
        name="fake",
        label="Fake",
        base_url="http://127.0.0.1:9000",
        api_key_env="FAKE_KEY",
        default_session_key="voice-console:fake",
    )
    assert SessionManager.from_hello({}, target).session_key == "voice-console:fake"
    selection = SessionManager.from_hello(
        {"session_id": "phone", "session_key": "jobhunter"}, target
    )
    assert (selection.session_id, selection.session_key) == ("phone", "jobhunter")
    with pytest.raises(VoiceProtocolError):
        SessionManager.from_hello({"session_id": "has\ncontrol"}, target)


@pytest.mark.asyncio
async def test_run_manager_tracks_lifecycle_and_delegates_commands() -> None:
    manager = RunManager(FakeRunsTransport())  # type: ignore[arg-type]
    seen = [
        event
        async for event in manager.events(session_id="session", session_key="key", text="hello")
    ]
    assert [event["type"] for event in seen] == ["agent.run.started", "agent.completed"]
    assert manager.active_run_id is None
    assert await manager.approve("run-1", "once") == {
        "run_id": "run-1",
        "decision": "once",
    }
    assert await manager.stop("run-1") == {"run_id": "run-1", "stopped": True}


@pytest.mark.asyncio
async def test_tts_session_cancel_is_connection_local() -> None:
    sent: list[dict[str, Any]] = []

    async def send_json(message: dict[str, Any]) -> None:
        sent.append(message)

    async def send_bytes(_chunk: bytes) -> None:
        raise AssertionError("cancel should not stream audio")

    async def send_error(_error: VoiceProtocolError) -> None:
        raise AssertionError("cancel should not emit an error")

    recording = RecordingSession(VoiceConfig())
    tts = TtsSession(
        config=VoiceConfig(),
        provider=object(),  # type: ignore[arg-type]
        audio_store=object(),  # type: ignore[arg-type]
        recording_session=recording,
        send_json=send_json,
        send_bytes=send_bytes,
        send_error=send_error,
    )
    await tts.cancel("turn-1")
    assert recording.is_cancelled("turn-1")
    assert sent == [{"type": "tts.cancelled", "turn_id": "turn-1"}]
