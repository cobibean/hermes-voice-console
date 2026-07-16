from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from voice_console.fake_target import create_fake_hermes_app
from voice_console.realtime.contracts import check_realtime_compatibility


def valid_capabilities() -> dict:
    with TestClient(create_fake_hermes_app()) as client:
        return client.get(
            "/v1/capabilities", headers={"Authorization": "Bearer fake"}
        ).json()


def test_phase8_capability_and_model_failure_matrix_fails_closed() -> None:
    baseline = valid_capabilities()
    assert check_realtime_compatibility(baseline).compatible is True

    mutations = [
        lambda value: value.pop("contracts"),
        lambda value: value["contracts"]["realtime"].update(version="2.0"),
        lambda value: value["contracts"]["realtime"].update(models=[]),
        lambda value: value["contracts"]["realtime"]["provider"].update(model="missing"),
        lambda value: value["features"].update(realtime_sideband_tools=False),
        lambda value: value["contracts"]["realtime"]["media"].update(sideband_authority="browser"),
        lambda value: value["contracts"]["realtime"]["tools"].update(execution="browser"),
        lambda value: value["contracts"]["realtime"]["workers"].update(max_fanout=0),
        lambda value: value["contracts"]["realtime"]["approvals"].update(server_authoritative=False),
    ]
    for mutate in mutations:
        candidate = copy.deepcopy(baseline)
        mutate(candidate)
        result = check_realtime_compatibility(candidate)
        assert result.compatible is False
        assert result.reasons


def test_phase8_public_contract_is_allowlisted_and_content_free() -> None:
    capabilities = valid_capabilities()
    capabilities["contracts"]["realtime"].update(
        api_key="sk-proj-this-must-never-cross-the-proxy",
        internal_url="https://provider.invalid/private",
        instructions="private persona prompt",
    )
    public = check_realtime_compatibility(capabilities).public_dict()
    rendered = str(public)
    assert public["compatible"] is True
    assert "sk-proj" not in rendered
    assert "provider.invalid" not in rendered
    assert "private persona prompt" not in rendered
    assert "api_key" not in public["contract"]
    assert "instructions" not in public["contract"]


def test_phase8_default_worker_policy_is_one_and_fanout_is_bounded() -> None:
    capabilities = valid_capabilities()
    contract = capabilities["contracts"]["realtime"]
    assert contract["routing_policy"]["default_fanout"] == 1
    assert contract["workers"]["max_concurrency"] == 1
    assert contract["workers"]["max_fanout"] == 1
    assert contract["workers"]["queue"] == "fifo_per_conversation"
    assert check_realtime_compatibility(capabilities).compatible is True


def test_phase8_browser_cannot_authorize_policy_or_tool_results() -> None:
    capabilities = valid_capabilities()
    contract = capabilities["contracts"]["realtime"]
    assert contract["sideband_authority"] == "server"
    assert contract["tools"]["execution"] == "server"
    assert contract["tools"]["raw_delegate_task_exposed"] is False
    assert contract["approvals"]["server_authoritative"] is True
    assert set(contract["approvals"]["choices"]) == {"once", "deny"}


def test_phase8_asset_gate_detects_browser_secret_and_source_map(tmp_path: Path) -> None:
    source = tmp_path / "frontend" / "src" / "lib"
    dist = tmp_path / "frontend" / "dist"
    source.mkdir(parents=True)
    dist.mkdir(parents=True)
    (source / "recovery.ts").write_text(
        "const RECOVERY_KEY = 'hvc.recovery.v1';\n"
        "window.sessionStorage.setItem(RECOVERY_KEY, JSON.stringify({version: 1}));\n"
    )
    (dist / "app.js").write_text("console.log('safe build')")
    script = Path(__file__).resolve().parents[2] / "scripts" / "realtime_security_gate.py"
    passed = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert passed.returncode == 0, passed.stdout

    (dist / "app.js").write_text("const leaked = 'sk-proj-" + "x" * 24 + "';")
    (dist / "app.js.map").write_text("{}")
    failed = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode == 1
    assert "OpenAI-style secret" in failed.stdout
    assert "source maps are present" in failed.stdout
