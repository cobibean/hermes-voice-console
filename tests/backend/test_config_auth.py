from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from voice_console.app import create_app
from voice_console.config import ConfigError, load_console_config, load_targets_config
from voice_console.fake_target import API_KEY


def write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data))


def test_config_loading_and_redacted_target_public_dict(tmp_path, monkeypatch):
    voice = tmp_path / "voice.yaml"
    targets = tmp_path / "targets.yaml"
    write_yaml(voice, {"server": {"auth_required": False}, "voice": {"stt_provider": "fake", "tts_provider": "fake", "max_buffer_mb": 2}})
    write_yaml(targets, {"targets": {"fake": {"label": "Fake", "base_url": "http://127.0.0.1:9999", "api_key_env": "FAKE_KEY", "default_session_key": "voice-console:fake"}}})
    monkeypatch.setenv("FAKE_KEY", API_KEY)
    config = load_console_config(voice)
    assert config.voice.max_buffer_bytes == 2 * 1024 * 1024
    target_config = load_targets_config(targets)
    public = target_config.require("fake").public_dict()
    assert public["api_key_configured"] is True
    assert "api_key" not in public
    assert "fake-target-key" not in str(public)


def test_targets_require_env_name(tmp_path):
    targets = tmp_path / "targets.yaml"
    write_yaml(targets, {"targets": {"bad": {"base_url": "http://127.0.0.1:1"}}})
    with pytest.raises(ConfigError):
        load_targets_config(targets)


def test_http_auth_rejects_without_secret(tmp_path, monkeypatch):
    voice = tmp_path / "voice.yaml"
    targets = tmp_path / "targets.yaml"
    write_yaml(voice, {"server": {"auth_required": True}, "voice": {"stt_provider": "fake", "tts_provider": "fake"}})
    write_yaml(targets, {"targets": {"fake": {"label": "Fake", "base_url": "http://127.0.0.1:9999", "api_key_env": "FAKE_KEY", "default_session_key": "voice-console:fake"}}})
    monkeypatch.setenv("FAKE_KEY", API_KEY)
    monkeypatch.delenv("VOICE_CONSOLE_SESSION_SECRET", raising=False)
    app = create_app(config_path=voice, targets_path=targets, env_path=None, static_dir=None)
    client = TestClient(app)
    assert client.get("/api/bootstrap").status_code == 401


def test_http_auth_accepts_bearer(tmp_path, monkeypatch):
    voice = tmp_path / "voice.yaml"
    targets = tmp_path / "targets.yaml"
    write_yaml(voice, {"server": {"auth_required": True}, "voice": {"stt_provider": "fake", "tts_provider": "fake"}})
    write_yaml(targets, {"targets": {"fake": {"label": "Fake", "base_url": "http://127.0.0.1:9999", "api_key_env": "FAKE_KEY", "default_session_key": "voice-console:fake"}}})
    monkeypatch.setenv("FAKE_KEY", API_KEY)
    monkeypatch.setenv("VOICE_CONSOLE_SESSION_SECRET", "test-secret-000000000000000")
    app = create_app(config_path=voice, targets_path=targets, env_path=None, static_dir=None)
    client = TestClient(app)
    resp = client.get("/api/bootstrap", headers={"Authorization": "Bearer test-secret-000000000000000"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["targets"][0]["api_key_configured"] is True
    assert "fake-target-key" not in str(data)
