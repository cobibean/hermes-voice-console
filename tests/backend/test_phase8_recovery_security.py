from __future__ import annotations

import copy
import json
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


def test_phase8_public_context_only_exposes_path_free_booleans() -> None:
    capabilities = valid_capabilities()
    context = capabilities["contracts"]["realtime"]["context"]
    context["workspace_attached"] = "/Users/example/private-workspace"
    context["soul_available"] = "SOUL.md"

    public = check_realtime_compatibility(capabilities).public_dict()

    assert public["compatible"] is True
    assert public["contract"]["context"] == {"filesystem_tools_available": False}
    assert "/Users/example/private-workspace" not in str(public)
    assert "SOUL.md" not in str(public)


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


def test_phase8_filesystem_tools_require_an_attached_workspace() -> None:
    capabilities = valid_capabilities()
    contract = capabilities["contracts"]["realtime"]
    contract["tools"]["direct_allowlist"] = ["read_file", "search_files"]

    missing_context = check_realtime_compatibility(capabilities)
    assert missing_context.compatible is False
    assert missing_context.reasons.count("Hermes workspace unavailable") == 1

    contract["context"] = {
        "workspace_attached": False,
        "filesystem_tools_available": False,
        "soul_available": True,
    }
    detached = check_realtime_compatibility(capabilities)
    assert detached.compatible is False
    assert detached.reasons.count("Hermes workspace unavailable") == 1

    contract["context"]["workspace_attached"] = True
    unavailable = check_realtime_compatibility(capabilities)
    assert unavailable.compatible is False
    assert unavailable.reasons.count("Hermes workspace unavailable") == 1

    contract["context"]["filesystem_tools_available"] = True
    attached = check_realtime_compatibility(capabilities)
    assert attached.compatible is True


def test_phase8_chat_only_target_does_not_require_a_workspace() -> None:
    capabilities = valid_capabilities()
    contract = capabilities["contracts"]["realtime"]
    assert contract["tools"]["direct_allowlist"] == ["get_status"]
    assert contract["context"]["workspace_attached"] is False
    assert check_realtime_compatibility(capabilities).compatible is True


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
    (source / "unsafe.ts").write_text(
        "window['sessionStorage']['setItem']('unapproved', 'secret');\n"
        "const store = window.localStorage; store[method]('x', 'y');\n"
        "indexedDB.open('private'); document.cookie = 'private=1'; caches.open('private');\n"
    )
    failed = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode == 1
    assert "OpenAI-style secret" in failed.stdout
    assert "source maps are present" in failed.stdout
    assert "unapproved browser storage keys" in failed.stdout
    assert "aliased or computed browser storage write" in failed.stdout
    assert "IndexedDB write" in failed.stdout
    assert "cookie write" in failed.stdout
    assert "Cache API write" in failed.stdout


def test_phase8_upgrade_gate_rejects_empty_pinned_contract(tmp_path: Path) -> None:
    repo = tmp_path / "hermes"
    (repo / "gateway" / "realtime").mkdir(parents=True)
    for name in ("contracts.py", "api.py", "http.py"):
        (repo / "gateway" / "realtime" / name).write_text("")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "gate@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Gate Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "empty contract"], check=True)
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "schema_version: 1\nstatus: test\nenabled: false\n"
        "contract:\n  name: hermes.realtime\n  required_major: 1\n"
        "models:\n  realtime: gpt-realtime-2.1\n  lead_worker: gpt-5.6-sol\n"
        f"hermes:\n  minimum_tested_commit: {commit}\n  production_pinned_commit: {commit}\n"
    )
    script = Path(__file__).resolve().parents[2] / "scripts" / "realtime_upgrade_gate.py"
    result = subprocess.run(
        [sys.executable, str(script), "--manifest", str(manifest), "--hermes-repo", str(repo), "--json"],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 1
    document = json.loads(result.stdout)
    pinned = next(row for row in document["rows"] if row["lane"] == "production_pinned")
    assert pinned["passed"] is False
    assert any("major" in reason or "methods" in reason for reason in pinned["static_failures"])
    model = next(row for row in document["rows"] if row["lane"] == "model_unavailable")
    assert model == {
        "lane": "model_unavailable",
        "expected": "preflight_blocked",
        "observed": "not_validated",
        "passed": False,
    }

    untracked_override = repo / "gateway" / "realtime" / "untracked_override.py"
    untracked_override.write_text("uncommitted test override")
    untracked = subprocess.run(
        [sys.executable, str(script), "--manifest", str(manifest), "--hermes-repo", str(repo), "--json"],
        check=False, capture_output=True, text=True,
    )
    assert untracked.returncode == 1
    untracked_document = json.loads(untracked.stdout)
    assert untracked_document["checkout_clean"] is False
    untracked_pin = next(
        row for row in untracked_document["rows"] if row["lane"] == "production_pinned"
    )
    assert untracked_pin["checkout"] == "dirty"
    assert untracked_pin["passed"] is False
    untracked_override.unlink()

    (repo / "gateway" / "realtime" / "api.py").write_text("uncommitted runtime override")
    dirty = subprocess.run(
        [sys.executable, str(script), "--manifest", str(manifest), "--hermes-repo", str(repo), "--json"],
        check=False, capture_output=True, text=True,
    )
    assert dirty.returncode == 1
    dirty_document = json.loads(dirty.stdout)
    assert dirty_document["checkout_clean"] is False
    dirty_pin = next(
        row for row in dirty_document["rows"] if row["lane"] == "production_pinned"
    )
    assert dirty_pin["checkout"] == "dirty"
    assert dirty_pin["passed"] is False
