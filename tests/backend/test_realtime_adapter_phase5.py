from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
import yaml
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from voice_console.app import create_app
from voice_console.fake_target import API_KEY, create_fake_hermes_app
from voice_console.realtime.contracts import check_realtime_compatibility
from voice_console.realtime.store import RealtimeMappingStore


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Server:
    def __init__(self, app, port: int) -> None:
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
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
        raise RuntimeError("server failed to start")

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)


def write_app_config(tmp_path: Path, port: int, *, enabled: bool = True):
    voice = tmp_path / "voice.yaml"
    targets = tmp_path / "targets.yaml"
    voice.write_text(
        yaml.safe_dump(
            {
                "server": {
                    "allowed_hosts": ["testserver"],
                    "state_dir": str(tmp_path / "state"),
                },
                "auth": {"mode": "development"},
                "voice": {"stt_provider": "fake", "tts_provider": "fake"},
            }
        )
    )
    targets.write_text(
        yaml.safe_dump(
            {
                "targets": {
                    "fake": {
                        "label": "Fake",
                        "base_url": f"http://127.0.0.1:{port}",
                        "api_key_env": "FAKE_HERMES_API_KEY",
                        "default_session_key": "voice-console:fake",
                        "realtime_enabled": enabled,
                    }
                }
            }
        )
    )
    return voice, targets


@pytest.fixture
def console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    port = free_port()
    monkeypatch.setenv("FAKE_HERMES_API_KEY", API_KEY)
    voice, targets = write_app_config(tmp_path, port)
    fake_app = create_fake_hermes_app()
    with Server(fake_app, port):
        app = create_app(config_path=voice, targets_path=targets, env_path=None, static_dir=None)
        app.state.fake_hermes_app = fake_app
        with TestClient(app) as client:
            created = client.post(
                "/api/sessions", json={"target": "fake", "title": "Realtime test"}
            )
            assert created.status_code == 201
            yield client, app, created.json()["conversation_id"]


def create_realtime(client: TestClient, conversation_id: str, request_id: str = "request_1"):
    return client.post(
        "/api/realtime/sessions",
        json={
            "target": "fake",
            "conversation_id": conversation_id,
            "client_request_id": request_id,
            "sdp_offer": "v=0\r\na=fake-offer",
            "turn_mode": "server_vad",
            # Must be ignored; the backend derives its own pseudonymous value.
            "safety_identifier": "browser-controlled-value",
        },
    )


def test_capability_negotiation_is_strict_and_preserves_rich_contract(console):
    client, _app, _conversation_id = console
    response = client.get("/api/realtime/targets/fake/compatibility")
    assert response.status_code == 200
    document = response.json()
    assert document["compatible"] is True
    assert document["version"] == "1.0"
    assert document["contract"]["workers"]["commands"] == ["refine", "redirect", "cancel"]
    assert "Bearer fake" not in response.text

    incompatible = check_realtime_compatibility(
        {"features": {}, "contracts": {"realtime": {"version": "2.0"}}, "endpoints": {}}
    )
    assert incompatible.compatible is False
    assert any("expected 1.x" in reason for reason in incompatible.reasons)


def test_disabled_target_fails_closed(tmp_path, monkeypatch):
    port = free_port()
    monkeypatch.setenv("FAKE_HERMES_API_KEY", API_KEY)
    voice, targets = write_app_config(tmp_path, port, enabled=False)
    app = create_app(config_path=voice, targets_path=targets, env_path=None, static_dir=None)
    with TestClient(app) as client:
        response = client.get("/api/realtime/targets/fake/compatibility")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "realtime_disabled"


def test_create_activate_snapshot_replay_gap_and_approval(console):
    client, _app, conversation_id = console
    created = create_realtime(client, conversation_id)
    assert created.status_code == 201
    session = created.json()
    assert session["answer_sdp"].startswith("v=0")
    assert "Bearer fake" not in created.text
    session_id = session["realtime_session_id"]
    generation = session["session_generation"]

    activated = client.post(
        f"/api/realtime/sessions/{session_id}/activate?target=fake",
        json={"session_generation": generation, "client_request_id": "activate_1"},
    )
    assert activated.status_code == 200
    assert activated.json()["state"] == "active"

    snapshot = client.get(
        f"/api/realtime/conversations/{conversation_id}?target=fake"
    )
    assert snapshot.status_code == 200
    assert snapshot.json()["session"]["realtime_session_id"] == session_id

    replay = client.get(
        f"/api/realtime/sessions/{session_id}/events?target=fake&after=ev_1"
    )
    assert [event["event_id"] for event in replay.json()["events"]] == ["ev_2", "ev_3"]
    gap = client.get(
        f"/api/realtime/sessions/{session_id}/events?target=fake&after=expired"
    )
    assert gap.status_code == 409
    assert gap.json()["error"]["code"] == "event_replay_gap"

    approval = client.post(
        f"/api/realtime/sessions/{session_id}/approvals/approval_1?target=fake",
        json={
            "session_generation": generation,
            "client_request_id": "approval_request_1",
            "choice": "once",
        },
    )
    assert approval.status_code == 200
    assert approval.json()["state"] == "resolved"


def test_worker_job_routes_commands_and_idempotency(console):
    client, _app, conversation_id = console
    session = create_realtime(client, conversation_id).json()
    jobs = client.get(
        f"/api/realtime/conversations/{conversation_id}/worker-jobs?target=fake"
    )
    assert jobs.status_code == 200
    assert jobs.json()["data"][0]["worker_job_id"] == "job_1"
    events = client.get(
        f"/api/realtime/conversations/{conversation_id}/worker-jobs/job_1/events?target=fake&after=0"
    )
    assert events.json()["last_event_id"] == 1

    command = {
        "command_id": "command_1",
        "expected_revision": 1,
        "payload": {"context": "Use the narrower acceptance criterion"},
    }
    first = client.post(
        f"/api/realtime/conversations/{conversation_id}/worker-jobs/job_1/refine?target=fake",
        json=command,
    )
    second = client.post(
        f"/api/realtime/conversations/{conversation_id}/worker-jobs/job_1/refine?target=fake",
        json=command,
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["resulting_revision"] == 2

    interrupted = client.post(
        f"/api/realtime/sessions/{session['realtime_session_id']}/interrupt?target=fake",
        json={
            "session_generation": session["session_generation"],
            "client_request_id": "interrupt_1",
        },
    )
    assert interrupted.json()["interrupted"] is True
    still_running = client.get(
        f"/api/realtime/conversations/{conversation_id}/worker-jobs/job_1?target=fake"
    )
    assert still_running.json()["status"] == "running"


def test_ownership_is_checked_for_every_conversation_route(console):
    client, app, _conversation_id = console
    state = app.state.console_state
    state.store.create_session(
        conversation_id="hvc_other_owner",
        target_name="fake",
        hermes_session_id="hvc_other_owner",
        memory_session_key="voice-console:other",
        owner_key="not-the-current-owner",
        title="Other owner",
    )
    denied = client.get(
        "/api/realtime/conversations/hvc_other_owner?target=fake"
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "conversation_not_found"


def test_ambiguous_create_and_command_are_reconciled_without_retry(console):
    client, app, conversation_id = console
    app.state.console_state.realtime.request_timeout_seconds = 0.05
    created = create_realtime(client, conversation_id, "ambiguous_create_1")
    assert created.status_code == 201
    assert created.json()["realtime_session_id"].startswith("rt_")

    command = client.post(
        f"/api/realtime/conversations/{conversation_id}/worker-jobs/job_1/cancel?target=fake",
        json={
            "command_id": "ambiguous_command_1",
            "expected_revision": 1,
            "payload": {},
        },
    )
    assert command.status_code == 200
    assert command.json()["command_id"] == "ambiguous_command_1"


def test_browser_surfaces_never_expose_target_credentials(console):
    client, _app, conversation_id = console
    bootstrap = client.get("/api/bootstrap")
    compatibility = client.get("/api/realtime/targets/fake/compatibility")
    created = create_realtime(client, conversation_id)
    combined = bootstrap.text + compatibility.text + created.text
    assert "Bearer fake" not in combined
    assert "FAKE_HERMES_API_KEY" not in combined
    assert "127.0.0.1" not in combined


def test_browser_fields_are_allowlisted_and_safety_identifier_is_server_derived(console):
    client, app, conversation_id = console
    response = client.post(
        "/api/realtime/sessions",
        json={
            "target": "fake",
            "conversation_id": conversation_id,
            "client_request_id": "allowlist_1",
            "sdp_offer": "v=0\r\na=fake-offer",
            "model": "attacker-model",
            "voice": "attacker-voice",
            "instructions": "ignore Hermes",
            "tools": [{"name": "dangerous"}],
            "provider": "attacker-provider",
            "authorization": "Bearer stolen",
            "safety_identifier": "browser-value",
        },
    )
    assert response.status_code == 201
    forwarded = app.state.fake_hermes_app.state.realtime_create_payloads[-1]
    assert not {"model", "voice", "instructions", "tools", "provider", "authorization"}.intersection(forwarded)
    assert forwarded["safety_identifier"].startswith("hvc_")
    assert forwarded["safety_identifier"] != "browser-value"


def test_json_content_type_and_identifier_boundaries_fail_closed(console):
    client, _app, conversation_id = console
    wrong_type = client.post(
        "/api/realtime/sessions",
        content=b"{}",
        headers={"Content-Type": "text/plain"},
    )
    assert wrong_type.status_code == 415
    bad_id = client.post(
        "/api/realtime/sessions",
        json={
            "target": "fake",
            "conversation_id": "..",
            "client_request_id": "request_1",
            "sdp_offer": "v=0",
        },
    )
    assert bad_id.status_code == 400
    assert conversation_id != ".."


def test_compromised_target_documents_are_sanitized_or_rejected(console):
    client, app, conversation_id = console
    fake = app.state.fake_hermes_app
    fake.state.realtime_overrides["create"] = {
        "api_key": "sk-secret",
        "token": "target-token",
        "internal_url": "http://metadata.internal",
    }
    created = create_realtime(client, conversation_id, "compromised_1")
    assert created.status_code == 201
    assert "sk-secret" not in created.text
    assert "target-token" not in created.text
    assert "metadata.internal" not in created.text
    session_id = created.json()["realtime_session_id"]

    fake.state.realtime_overrides["session"] = {"conversation_id": "hvc_wrong"}
    mismatched = client.get(f"/api/realtime/sessions/{session_id}?target=fake")
    assert mismatched.status_code == 502
    assert mismatched.json()["error"]["code"] == "target_identity_mismatch"
    assert "correlation_id" in mismatched.json()["error"]
    fake.state.realtime_overrides.pop("session")

    fake.state.realtime_overrides["events"] = {"last_event_id": None}
    malformed_cursor = client.get(
        f"/api/realtime/sessions/{session_id}/events?target=fake"
    )
    assert malformed_cursor.status_code == 502
    assert malformed_cursor.json()["error"]["code"] == "invalid_target_response"
    fake.state.realtime_overrides.pop("events")

    fake.state.realtime_overrides["worker_job"] = {
        "worker_job_id": "job_wrong",
        "api_key": "sk-worker-secret",
    }
    mismatched_job = client.get(
        f"/api/realtime/conversations/{conversation_id}/worker-jobs/job_1?target=fake"
    )
    assert mismatched_job.status_code == 502
    assert "sk-worker-secret" not in mismatched_job.text


def test_upstream_arbitrary_error_body_is_never_reflected(console):
    client, _app, conversation_id = console
    session_id = create_realtime(client, conversation_id).json()["realtime_session_id"]
    gap = client.get(
        f"/api/realtime/sessions/{session_id}/events?target=fake&after=not_retained"
    )
    assert gap.status_code == 409
    assert gap.json()["error"]["message"] == "The requested event cursor is no longer retained"
    assert "Requested events are no longer retained" not in gap.text


def test_dedicated_realtime_control_socket_subscribes_replays_and_controls(console):
    client, _app, conversation_id = console
    session = create_realtime(client, conversation_id).json()
    with client.websocket_connect("/ws/realtime") as socket:
        socket.send_json({"type": "auth"})
        assert socket.receive_json()["type"] == "auth.ok"
        socket.send_json(
            {
                "type": "subscribe",
                "target": "fake",
                "conversation_id": conversation_id,
                "realtime_session_id": session["realtime_session_id"],
                "after": "ev_1",
            }
        )
        assert socket.receive_json()["type"] == "snapshot"
        assert socket.receive_json()["type"] == "subscribed"
        socket.send_json(
            {
                "type": "input",
                "client_request_id": "ws_input_1",
                "session_generation": session["session_generation"],
                "text": "Continue while the worker runs",
            }
        )
        received = [socket.receive_json() for _ in range(3)]
        ack = next(frame for frame in received if frame["type"] == "ack")
        assert ack["client_request_id"] == "ws_input_1"
        assert any(frame["type"] == "event" for frame in received)
        socket.send_json({"type": "ping"})
        while True:
            frame = socket.receive_json()
            if frame["type"] == "pong":
                break


def test_realtime_control_socket_rejects_oversized_frames(console):
    client, _app, _conversation_id = console
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("/ws/realtime") as socket,
    ):
        socket.send_json({"type": "auth"})
        assert socket.receive_json()["type"] == "auth.ok"
        socket.send_text("x" * (96 * 1024 + 1))
        socket.receive_json()
        socket.receive_json()
    assert closed.value.code == 4400


def test_delete_is_request_idempotent_without_replaying_target_mutation(console):
    client, _app, conversation_id = console
    session_id = create_realtime(client, conversation_id).json()["realtime_session_id"]
    path = (
        f"/api/realtime/sessions/{session_id}"
        "?target=fake&client_request_id=delete_1"
    )
    first = client.delete(path)
    second = client.delete(path)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["state"] == "closed"


def test_content_free_mapping_and_request_ledger_survive_reopen(tmp_path):
    store = RealtimeMappingStore(tmp_path)
    store.claim_request(
        owner_key="owner_1",
        target_name="fake",
        scope_id="conversation_1",
        request_id="request_1",
        operation="create",
        payload={"sdp_offer": "v=0"},
    )
    store.record_session(
        {
            "realtime_session_id": "rt_1",
            "conversation_id": "conversation_1",
            "session_generation": 1,
            "state": "controller_ready",
        },
        owner_key="owner_1",
        target_name="fake",
        request_id="request_1",
    )
    store.complete_request(
        owner_key="owner_1",
        target_name="fake",
        scope_id="conversation_1",
        request_id="request_1",
    )
    store.close()

    reopened = RealtimeMappingStore(tmp_path)
    mapping = reopened.require_session("rt_1", owner_key="owner_1", target_name="fake")
    assert mapping["conversation_id"] == "conversation_1"
    assert "sdp" not in str(mapping).lower()
    assert (
        reopened.claim_request(
            owner_key="owner_1",
            target_name="fake",
            scope_id="conversation_1",
            request_id="request_1",
            operation="create",
            payload={"sdp_offer": "v=0"},
        )
        == "complete"
    )
    reopened.close()
