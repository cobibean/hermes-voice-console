from __future__ import annotations

import json
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
from voice_console.realtime.hermes_client import RealtimeProxyError
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


def assert_phase4_shape(document: dict, shape: dict) -> None:
    assert set(document) == set(shape["keys"])
    expected_types = {
        "string": str,
        "integer": int,
        "boolean": bool,
        "object": dict,
    }
    for key, type_name in shape["types"].items():
        assert type(document[key]) is expected_types[type_name]
    for key, value in shape.get("constants", {}).items():
        assert document[key] == value


def test_fake_target_matches_frozen_hermes_phase4_mutation_shapes(console):
    client, app, conversation_id = console
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "hermes_realtime_phase4_mutation_shapes.json"
        ).read_text()
    )
    assert fixture["source_commit"] == "351da78c98564002effa32d57f5c8fd2fedfa1e9"
    shapes = fixture["mutations"]
    fake = app.state.fake_hermes_app

    session = create_realtime(client, conversation_id, "shape_create_1").json()
    session_id = session["realtime_session_id"]
    generation = session["session_generation"]
    assert_phase4_shape(
        fake.state.realtime_requests[(conversation_id, "shape_create_1")],
        shapes["create"],
    )

    mutations = [
        (
            "activate",
            "shape_activate_1",
            client.post(
                f"/api/realtime/sessions/{session_id}/activate?target=fake",
                json={
                    "client_request_id": "shape_activate_1",
                    "session_generation": generation,
                },
            ),
        ),
        (
            "turn_mode_update",
            "shape_turn_mode_1",
            client.post(
                f"/api/realtime/sessions/{session_id}/turn-mode?target=fake",
                json={
                    "client_request_id": "shape_turn_mode_1",
                    "session_generation": generation,
                    "turn_mode": "manual",
                },
            ),
        ),
        (
            "manual_audio_commit",
            "shape_commit_1",
            client.post(
                f"/api/realtime/sessions/{session_id}/commit?target=fake",
                json={
                    "client_request_id": "shape_commit_1",
                    "session_generation": generation,
                },
            ),
        ),
        (
            "input",
            "shape_input_1",
            client.post(
                f"/api/realtime/sessions/{session_id}/input?target=fake",
                json={
                    "client_request_id": "shape_input_1",
                    "session_generation": generation,
                    "text": "continue",
                },
            ),
        ),
        (
            "interrupt",
            "shape_interrupt_1",
            client.post(
                f"/api/realtime/sessions/{session_id}/interrupt?target=fake",
                json={
                    "client_request_id": "shape_interrupt_1",
                    "session_generation": generation,
                },
            ),
        ),
        (
            "approval",
            "shape_approval_1",
            client.post(
                f"/api/realtime/sessions/{session_id}/approvals/approval_1?target=fake",
                json={
                    "client_request_id": "shape_approval_1",
                    "session_generation": generation,
                    "choice": "once",
                },
            ),
        ),
    ]
    for operation, request_id, response in mutations:
        assert response.status_code == 200
        assert_phase4_shape(
            fake.state.realtime_requests[(conversation_id, request_id)],
            shapes[operation],
        )

    rejected = client.post(
        f"/api/realtime/sessions/{session_id}/commit?target=fake",
        json={
            "client_request_id": "empty_shape_commit_1",
            "session_generation": generation,
        },
    )
    assert rejected.status_code == 409
    assert_phase4_shape(
        fake.state.realtime_requests[(conversation_id, "empty_shape_commit_1")],
        shapes["manual_audio_commit_rejected"],
    )

    unknown = client.post(
        f"/api/realtime/sessions/{session_id}/interrupt?target=fake",
        json={
            "client_request_id": "unknown_shape_1",
            "session_generation": generation,
        },
    )
    assert unknown.status_code == 202
    assert_phase4_shape(
        fake.state.realtime_requests[(conversation_id, "unknown_shape_1")],
        shapes["outcome_unknown"],
    )

    deleted = client.request(
        "DELETE",
        f"/api/realtime/sessions/{session_id}?target=fake",
        json={"client_request_id": "shape_delete_1"},
    )
    assert deleted.status_code == 200
    assert_phase4_shape(
        fake.state.realtime_requests[(conversation_id, "shape_delete_1")],
        shapes["delete"],
    )


def test_capability_negotiation_is_strict_and_preserves_rich_contract(console):
    client, _app, _conversation_id = console
    response = client.get("/api/realtime/targets/fake/compatibility")
    assert response.status_code == 200
    document = response.json()
    assert document["compatible"] is True
    assert document["version"] == "1.0"
    assert document["contract"]["sideband_authority"] == "server"
    assert document["contract"]["models"] == ["gpt-realtime-2.1"]
    assert "behaviors" not in document["contract"]
    assert document["contract"]["workers"]["commands"] == ["refine", "redirect", "cancel"]
    assert document["contract"]["sessions"]["manual_audio_commit"] is True
    assert document["contract"]["sessions"]["turn_mode_update"] is True
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
    client, app, conversation_id = console
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
    # Reconciliation must use the durable owner/mutation ledger before asking
    # the upstream for an ephemeral session that may already be gone.
    app.state.fake_hermes_app.state.realtime_sessions.pop(session_id)
    duplicate = client.post(
        f"/api/realtime/sessions/{session_id}/approvals/approval_1?target=fake",
        json={
            "session_generation": generation,
            "client_request_id": "approval_request_1",
            "choice": "once",
        },
    )
    assert duplicate.json() == approval.json()
    assert duplicate.json()["accepted"] is True


def test_worker_job_routes_commands_and_idempotency(console):
    client, app, conversation_id = console
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
    assert first.json() == {
        "command_id": "command_1",
        "worker_job_id": "job_1",
        "acknowledgement": "applied",
        "revision": 2,
        "operation": "refine",
        "control_signal_sent": True,
    }
    assert second.json() == {
        **first.json(),
        "acknowledgement": "already_applied",
        "control_signal_sent": False,
    }
    shape = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "hermes_realtime_phase4_mutation_shapes.json"
        ).read_text()
    )["mutations"]["worker_command"]
    assert_phase4_shape(first.json(), shape)
    assert_phase4_shape(second.json(), shape)

    stale_command = {
        "command_id": "command_stale_1",
        "expected_revision": 1,
        "payload": {"context": "This revision is stale"},
    }
    stale = client.post(
        f"/api/realtime/conversations/{conversation_id}/worker-jobs/job_1/refine?target=fake",
        json=stale_command,
    )
    stale_duplicate = client.post(
        f"/api/realtime/conversations/{conversation_id}/worker-jobs/job_1/refine?target=fake",
        json=stale_command,
    )
    assert stale.status_code == stale_duplicate.status_code == 200
    assert stale.json() == stale_duplicate.json() == {
        "command_id": "command_stale_1",
        "worker_job_id": "job_1",
        "acknowledgement": "rejected_stale_revision",
        "revision": 2,
        "operation": "refine",
        "control_signal_sent": False,
    }
    assert_phase4_shape(stale.json(), shape)

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

    app.state.fake_hermes_app.state.worker_jobs[conversation_id]["job_1"][
        "status"
    ] = "completed"
    terminal = client.post(
        f"/api/realtime/conversations/{conversation_id}/worker-jobs/job_1/cancel?target=fake",
        json={"command_id": "command_terminal_1", "expected_revision": 2, "payload": {}},
    )
    assert terminal.status_code == 200
    assert terminal.json()["acknowledgement"] == "rejected_terminal"
    assert terminal.json()["control_signal_sent"] is False
    assert_phase4_shape(terminal.json(), shape)


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

    fake.state.realtime_overrides["conversation"] = {
        "work_summary": [
            {"message": "Bearer private-token", "metadata": {"content": "sk-secret"}}
        ]
    }
    sanitized = client.get(
        f"/api/realtime/conversations/{conversation_id}?target=fake"
    )
    assert sanitized.status_code == 200
    assert "private-token" not in sanitized.text
    assert "sk-secret" not in sanitized.text
    assert "[redacted]" in sanitized.text
    fake.state.realtime_overrides.pop("conversation")

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
        subscribed = socket.receive_json()
        assert subscribed["type"] == "subscribed"
        assert subscribed["after"] == "ev_3"
        assert subscribed["client_after"] == "ev_1"
        assert subscribed["cursor_rebased"] is True
        socket.send_json(
            {
                "type": "input",
                "client_request_id": "ws_input_1",
                "session_generation": session["session_generation"],
                "text": "Continue while the worker runs",
            }
        )
        ack = socket.receive_json()
        assert ack["type"] == "ack"
        assert ack["client_request_id"] == "ws_input_1"
        socket.send_json(
            {
                "type": "turn_mode_update",
                "client_request_id": "ws_turn_mode_1",
                "session_generation": session["session_generation"],
                "turn_mode": "manual",
            }
        )
        turn_ack = socket.receive_json()
        assert turn_ack == {
            "type": "ack",
            "client_request_id": "ws_turn_mode_1",
            "result": {
                "client_request_id": "ws_turn_mode_1",
                "realtime_session_id": session["realtime_session_id"],
                "session_generation": session["session_generation"],
                "turn_mode": "manual",
                "state": "accepted",
            },
        }
        socket.send_json(
            {
                "type": "manual_audio_commit",
                "client_request_id": "ws_commit_1",
                "session_generation": session["session_generation"],
            }
        )
        commit_ack = socket.receive_json()
        assert commit_ack == {
            "type": "ack",
            "client_request_id": "ws_commit_1",
            "result": {
                "client_request_id": "ws_commit_1",
                "realtime_session_id": session["realtime_session_id"],
                "session_generation": session["session_generation"],
                "state": "accepted",
                "audio_commit_requested": True,
                "response_requested": True,
            },
        }
        socket.send_json(
            {
                "type": "worker.command",
                "client_request_id": "ws_worker_1",
                "worker_job_id": "job_1",
                "operation": "refine",
                "expected_revision": 1,
                "payload": {"context": "Use the safer path"},
            }
        )
        worker_ack = socket.receive_json()
        assert worker_ack == {
            "type": "ack",
            "client_request_id": "ws_worker_1",
            "result": {
                "command_id": "ws_worker_1",
                "worker_job_id": "job_1",
                "acknowledgement": "applied",
                "revision": 2,
                "operation": "refine",
                "control_signal_sent": True,
            },
        }
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
    path = f"/api/realtime/sessions/{session_id}?target=fake"
    first = client.request("DELETE", path, json={"client_request_id": "delete_1"})
    second = client.request("DELETE", path, json={"client_request_id": "delete_1"})
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


def test_uniform_mutation_unknown_result_is_202_and_queryable(console):
    client, _app, conversation_id = console
    session = create_realtime(client, conversation_id).json()
    unknown = client.post(
        f"/api/realtime/sessions/{session['realtime_session_id']}/interrupt?target=fake",
        json={
            "client_request_id": "unknown_interrupt_1",
            "session_generation": session["session_generation"],
        },
    )
    assert unknown.status_code == 202
    assert unknown.json() == {
        "client_request_id": "unknown_interrupt_1",
        "state": "outcome_unknown",
        "accepted": False,
        "operation": "interrupt",
    }
    lookup = client.get(
        f"/api/realtime/conversations/{conversation_id}/requests/unknown_interrupt_1?target=fake"
    )
    assert lookup.status_code == 200
    assert lookup.json() == unknown.json()


def test_manual_controls_are_typed_idempotent_and_reconciled(console):
    client, app, conversation_id = console
    session = create_realtime(client, conversation_id, "manual_create_1").json()
    session_id = session["realtime_session_id"]
    generation = session["session_generation"]
    base = f"/api/realtime/sessions/{session_id}"

    unavailable = client.post(
        f"{base}/commit?target=fake",
        json={
            "client_request_id": "commit_automatic_1",
            "session_generation": generation,
        },
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == "manual_audio_commit_unavailable"

    manual_body = {
        "client_request_id": "mode_manual_1",
        "session_generation": generation,
        "turn_mode": "manual",
    }
    manual = client.post(f"{base}/turn-mode?target=fake", json=manual_body)
    manual_duplicate = client.post(f"{base}/turn-mode?target=fake", json=manual_body)
    assert manual.status_code == manual_duplicate.status_code == 200
    assert manual.json() == manual_duplicate.json() == {
        "client_request_id": "mode_manual_1",
        "realtime_session_id": session_id,
        "session_generation": generation,
        "turn_mode": "manual",
        "state": "accepted",
    }
    assert app.state.fake_hermes_app.state.realtime_control_calls[
        ("turn_mode_update", session_id)
    ] == 1

    commit_body = {
        "client_request_id": "commit_manual_1",
        "session_generation": generation,
    }
    committed = client.post(f"{base}/commit?target=fake", json=commit_body)
    duplicate = client.post(f"{base}/commit?target=fake", json=commit_body)
    assert committed.status_code == duplicate.status_code == 200
    assert committed.json() == duplicate.json() == {
        "client_request_id": "commit_manual_1",
        "realtime_session_id": session_id,
        "session_generation": generation,
        "state": "accepted",
        "audio_commit_requested": True,
        "response_requested": True,
    }
    assert app.state.fake_hermes_app.state.realtime_control_calls[
        ("manual_audio_commit", session_id)
    ] == 1

    conflict = client.post(
        f"{base}/commit?target=fake",
        json={**commit_body, "session_generation": generation + 1},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"

    stale = client.post(
        f"{base}/turn-mode?target=fake",
        json={
            "client_request_id": "mode_stale_1",
            "session_generation": generation + 1,
            "turn_mode": "automatic",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "turn_mode_update_unavailable"

    unknown_body = {
        "client_request_id": "unknown_manual_audio_1",
        "session_generation": generation,
    }
    unknown = client.post(f"{base}/commit?target=fake", json=unknown_body)
    unknown_duplicate = client.post(f"{base}/commit?target=fake", json=unknown_body)
    assert unknown.status_code == unknown_duplicate.status_code == 202
    assert unknown.json() == unknown_duplicate.json() == {
        "client_request_id": "unknown_manual_audio_1",
        "operation": "manual_audio_commit",
        "state": "outcome_unknown",
        "accepted": False,
    }
    assert app.state.fake_hermes_app.state.realtime_control_calls[
        ("manual_audio_commit", session_id)
    ] == 1

    rejected_body = {
        "client_request_id": "empty_manual_audio_1",
        "session_generation": generation,
    }
    rejected = client.post(f"{base}/commit?target=fake", json=rejected_body)
    rejected_duplicate = client.post(f"{base}/commit?target=fake", json=rejected_body)
    expected_rejection = {
        "client_request_id": "empty_manual_audio_1",
        "operation": "manual_audio_commit",
        "state": "rejected",
        "accepted": False,
        "error": {"code": "audio_buffer_empty"},
    }
    assert rejected.status_code == rejected_duplicate.status_code == 409
    assert rejected.json() == rejected_duplicate.json() == expected_rejection
    lookup = client.get(
        f"/api/realtime/conversations/{conversation_id}/requests/empty_manual_audio_1?target=fake"
    )
    assert lookup.status_code == 200
    assert lookup.json() == expected_rejection
    assert app.state.fake_hermes_app.state.realtime_control_calls[
        ("manual_audio_commit", session_id)
    ] == 2

    automatic = client.post(
        f"{base}/turn-mode?target=fake",
        json={
            "client_request_id": "mode_automatic_1",
            "session_generation": generation,
            "turn_mode": "automatic",
        },
    )
    assert automatic.status_code == 200
    assert automatic.json()["turn_mode"] == "automatic"
    current = client.get(f"{base}?target=fake")
    snapshot = client.get(
        f"/api/realtime/conversations/{conversation_id}?target=fake"
    )
    assert current.json()["turn_mode"] == "automatic"
    assert snapshot.json()["session"]["turn_mode"] == "automatic"
    unavailable_again = client.post(
        f"{base}/commit?target=fake",
        json={
            "client_request_id": "commit_automatic_2",
            "session_generation": generation,
        },
    )
    assert unavailable_again.status_code == 409


def test_ambiguous_manual_commit_reconciles_without_provider_retry(console):
    client, app, conversation_id = console
    app.state.console_state.realtime.request_timeout_seconds = 0.05
    session = create_realtime(client, conversation_id, "manual_ambiguous_create").json()
    session_id = session["realtime_session_id"]
    generation = session["session_generation"]
    base = f"/api/realtime/sessions/{session_id}"
    mode = client.post(
        f"{base}/turn-mode?target=fake",
        json={
            "client_request_id": "manual_ambiguous_mode",
            "session_generation": generation,
            "turn_mode": "manual",
        },
    )
    assert mode.status_code == 200

    committed = client.post(
        f"{base}/commit?target=fake",
        json={
            "client_request_id": "ambiguous_manual_commit_1",
            "session_generation": generation,
        },
    )
    assert committed.status_code == 200
    assert committed.json()["audio_commit_requested"] is True
    assert app.state.fake_hermes_app.state.realtime_control_calls[
        ("manual_audio_commit", session_id)
    ] == 1


def test_session_mapping_rejects_compromised_identifier_collision(tmp_path):
    store = RealtimeMappingStore(tmp_path)
    document = {
        "realtime_session_id": "rt_collision",
        "conversation_id": "conversation_1",
        "session_generation": 1,
        "state": "controller_ready",
    }
    store.record_session(
        document, owner_key="owner_1", target_name="fake", request_id="request_1"
    )
    with pytest.raises(RealtimeProxyError, match="owned by another request"):
        store.record_session(
            {**document, "conversation_id": "conversation_2"},
            owner_key="owner_2",
            target_name="fake",
            request_id="request_2",
        )
    store.close()


def test_session_mapping_collision_is_atomic_across_connections(tmp_path):
    stores = [RealtimeMappingStore(tmp_path), RealtimeMappingStore(tmp_path)]
    barrier = threading.Barrier(2)
    outcomes: list[object] = []

    def record(index: int) -> None:
        barrier.wait()
        try:
            stores[index].record_session(
                {
                    "realtime_session_id": "rt_atomic_collision",
                    "conversation_id": f"conversation_{index}",
                    "session_generation": 1,
                    "state": "controller_ready",
                },
                owner_key=f"owner_{index}",
                target_name="fake",
                request_id=f"request_{index}",
            )
            outcomes.append("accepted")
        except RealtimeProxyError as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=record, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert not any(thread.is_alive() for thread in threads)

    assert outcomes.count("accepted") == 1
    errors = [item for item in outcomes if isinstance(item, RealtimeProxyError)]
    assert len(errors) == 1
    assert errors[0].code == "target_identity_mismatch"
    for store in stores:
        store.close()


def test_request_claim_is_atomic_across_connections(tmp_path):
    stores = [RealtimeMappingStore(tmp_path), RealtimeMappingStore(tmp_path)]
    barrier = threading.Barrier(2)
    identical: list[object] = []

    def claim_identical(index: int) -> None:
        barrier.wait()
        try:
            identical.append(
                stores[index].claim_request(
                    owner_key="owner_1",
                    target_name="fake",
                    scope_id="conversation_1",
                    request_id="request_identical",
                    operation="create",
                    payload={"turn_mode": "manual"},
                )
            )
        except BaseException as exc:
            identical.append(exc)

    threads = [threading.Thread(target=claim_identical, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert all(isinstance(item, str) for item in identical)
    assert sorted(identical) == ["new", "pending"]

    barrier = threading.Barrier(2)
    conflicting: list[object] = []

    def claim_conflicting(index: int) -> None:
        barrier.wait()
        try:
            conflicting.append(
                stores[index].claim_request(
                    owner_key="owner_1",
                    target_name="fake",
                    scope_id="conversation_1",
                    request_id="request_conflicting",
                    operation="input",
                    payload={"text": f"value {index}"},
                )
            )
        except BaseException as exc:
            conflicting.append(exc)

    threads = [threading.Thread(target=claim_conflicting, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert conflicting.count("new") == 1
    errors = [item for item in conflicting if isinstance(item, RealtimeProxyError)]
    assert len(errors) == 1
    assert errors[0].code == "idempotency_conflict"
    assert errors[0].status == 409
    for store in stores:
        store.close()


def test_compromised_mutation_results_are_rejected_before_cache(console):
    client, app, conversation_id = console
    fake = app.state.fake_hermes_app
    session = create_realtime(client, conversation_id, "strict_create_1").json()
    session_id = session["realtime_session_id"]
    generation = session["session_generation"]

    fake.state.realtime_overrides["activate"] = {"client_request_id": "wrong_request"}
    activate = client.post(
        f"/api/realtime/sessions/{session_id}/activate?target=fake",
        json={"client_request_id": "strict_activate_1", "session_generation": generation},
    )
    assert activate.status_code == 502
    assert activate.json()["error"]["code"] == "target_identity_mismatch"
    fake.state.realtime_overrides.pop("activate")

    fake.state.realtime_overrides["input"] = {"accepted": "yes"}
    input_result = client.post(
        f"/api/realtime/sessions/{session_id}/input?target=fake",
        json={
            "client_request_id": "strict_input_1",
            "session_generation": generation,
            "text": "continue",
        },
    )
    assert input_result.status_code == 502
    assert input_result.json()["error"]["code"] == "invalid_target_response"
    duplicate_input = client.post(
        f"/api/realtime/sessions/{session_id}/input?target=fake",
        json={
            "client_request_id": "strict_input_1",
            "session_generation": generation,
            "text": "continue",
        },
    )
    assert duplicate_input.status_code == 502
    fake.state.realtime_overrides.pop("input")

    fake.state.realtime_overrides["interrupt"] = {"realtime_session_id": "rt_wrong"}
    interrupt = client.post(
        f"/api/realtime/sessions/{session_id}/interrupt?target=fake",
        json={"client_request_id": "strict_interrupt_1", "session_generation": generation},
    )
    assert interrupt.status_code == 502
    assert interrupt.json()["error"]["code"] == "target_identity_mismatch"
    fake.state.realtime_overrides.pop("interrupt")

    fake.state.realtime_overrides["approval"] = {"accepted": "yes"}
    approval = client.post(
        f"/api/realtime/sessions/{session_id}/approvals/approval_1?target=fake",
        json={
            "client_request_id": "strict_approval_1",
            "session_generation": generation,
            "choice": "once",
        },
    )
    assert approval.status_code == 502
    assert approval.json()["error"]["code"] == "invalid_target_response"
    fake.state.realtime_overrides.pop("approval")

    fake.state.realtime_overrides["delete"] = {"conversation_id": "conversation_wrong"}
    deleted = client.request(
        "DELETE",
        f"/api/realtime/sessions/{session_id}?target=fake",
        json={"client_request_id": "strict_delete_1"},
    )
    assert deleted.status_code == 502
    assert deleted.json()["error"]["code"] == "target_identity_mismatch"
