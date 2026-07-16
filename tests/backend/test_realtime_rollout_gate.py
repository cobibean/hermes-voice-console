from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "realtime_rollout_gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("realtime_rollout_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_manifest(path: Path, *, enabled: bool = False) -> None:
    path.write_text(
        "schema_version: 1\n"
        f"enabled: {'true' if enabled else 'false'}\n"
        "models:\n  realtime: gpt-realtime-2.1\n  lead_worker: gpt-5.6-sol\n"
        "hermes:\n  production_pinned_commit: abc123\n"
    )


def write_targets(path: Path, *, staging_enabled: bool, production_enabled: bool = False) -> None:
    path.write_text(
        "targets:\n"
        "  staging:\n"
        "    base_url: http://127.0.0.1:8642\n"
        "    api_key_env: STAGING_KEY\n"
        "    realtime_rollout_scope: staging\n"
        f"    realtime_enabled: {'true' if staging_enabled else 'false'}\n"
        "  production:\n"
        "    base_url: http://127.0.0.1:8643\n"
        "    api_key_env: PRODUCTION_KEY\n"
        "    realtime_rollout_scope: production\n"
        f"    realtime_enabled: {'true' if production_enabled else 'false'}\n"
    )


def test_staging_gate_requires_one_selected_target_and_redacts_key(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "manifest.yaml"
    targets = tmp_path / "targets.yaml"
    write_manifest(manifest)
    write_targets(targets, staging_enabled=True)
    secret = "a-very-private-target-key"
    monkeypatch.setenv("STAGING_KEY", secret)

    result = load_gate().inspect_target_gate(
        manifest, targets, target_name="staging", mode="staging"
    )

    assert result["passed"] is True
    assert result["enabled_targets"] == ["staging"]
    assert result["target_key"] == {
        "environment_variable": "STAGING_KEY",
        "configured": True,
    }
    assert secret not in json.dumps(result)
    assert result["global_default_enabled"] is False
    assert result["acceptance"] == {"owner": "pending", "physical_phone": "pending"}


def test_staging_gate_blocks_global_or_multi_target_enablement(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "manifest.yaml"
    targets = tmp_path / "targets.yaml"
    write_manifest(manifest, enabled=True)
    write_targets(targets, staging_enabled=True, production_enabled=True)
    monkeypatch.setenv("STAGING_KEY", "configured")

    result = load_gate().inspect_target_gate(
        manifest, targets, target_name="staging", mode="staging"
    )

    assert result["passed"] is False
    assert "compatibility manifest must remain globally disabled" in result["failures"]
    assert "Realtime must be enabled for exactly the selected staging target" in result["failures"]


def test_rollback_gate_passes_only_after_every_target_is_disabled(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    targets = tmp_path / "targets.yaml"
    write_manifest(manifest)
    write_targets(targets, staging_enabled=False)

    passed = load_gate().evaluate(
        manifest, targets, target_name="staging", mode="rollback"
    )
    assert passed["passed"] is True
    assert passed["external_deployment_performed"] is False

    write_targets(targets, staging_enabled=True)
    failed = load_gate().evaluate(
        manifest, targets, target_name="staging", mode="rollback"
    )
    assert failed["passed"] is False
    assert (
        "rollback requires Realtime disabled for every configured target"
        in failed["target_gate"]["failures"]
    )

    write_targets(targets, staging_enabled=False, production_enabled=True)
    production_left_on = load_gate().evaluate(
        manifest, targets, target_name="staging", mode="rollback"
    )
    assert production_left_on["passed"] is False


def test_staging_gate_rejects_production_classification_and_malformed_target(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "manifest.yaml"
    targets = tmp_path / "targets.yaml"
    write_manifest(manifest)
    write_targets(targets, staging_enabled=False, production_enabled=True)
    monkeypatch.setenv("PRODUCTION_KEY", "configured")

    production = load_gate().inspect_target_gate(
        manifest, targets, target_name="production", mode="staging"
    )
    assert production["passed"] is False
    assert "selected target is not explicitly classified for staging" in production["failures"]

    targets.write_text(
        "targets:\n  staging:\n    api_key_env: STAGING_KEY\n"
        "    realtime_rollout_scope: staging\n    realtime_enabled: true\n"
    )
    monkeypatch.setenv("STAGING_KEY", "configured")
    malformed = load_gate().inspect_target_gate(
        manifest, targets, target_name="staging", mode="staging"
    )
    assert malformed["passed"] is False
    assert any("invalid runtime targets config" in reason for reason in malformed["failures"])


def test_current_main_advisory_rejects_dirty_checkout(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    repo = tmp_path / "hermes"
    repo.mkdir()
    write_manifest(manifest)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "gate@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Gate Test"], check=True)
    (repo / "README.md").write_text("clean\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", sha], check=True
    )
    (repo / "dirty.txt").write_text("untracked\n")

    result = load_gate().inspect_current_main(manifest, repo, expected_current_main=sha)
    assert result["status"] == "dirty_checkout"
    assert result["compatible"] is False


def test_rollback_uses_runtime_boolean_semantics(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    targets = tmp_path / "targets.yaml"
    write_manifest(manifest)
    targets.write_text(
        "targets:\n  staging:\n    base_url: http://127.0.0.1:8642\n"
        "    api_key_env: STAGING_KEY\n    realtime_rollout_scope: staging\n"
        '    realtime_enabled: "true"\n'
    )

    result = load_gate().evaluate(
        manifest, targets, target_name="staging", mode="rollback"
    )
    assert result["passed"] is False
    assert result["target_gate"]["enabled_targets"] == ["staging"]


def test_cli_never_prints_target_secret(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    targets = tmp_path / "targets.yaml"
    write_manifest(manifest)
    write_targets(targets, staging_enabled=False)
    env = os.environ.copy()
    env["STAGING_KEY"] = "secret-that-must-not-appear"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "rollback",
            "--target",
            "staging",
            "--targets",
            str(targets),
            "--manifest",
            str(manifest),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert "secret-that-must-not-appear" not in result.stdout
    assert json.loads(result.stdout)["passed"] is True
