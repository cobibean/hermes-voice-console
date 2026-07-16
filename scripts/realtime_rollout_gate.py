#!/usr/bin/env python
"""Fail-closed local preflight for a target-scoped Realtime rollout or rollback."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
UPGRADE_GATE_PATH = ROOT / "scripts" / "realtime_upgrade_gate.py"
sys.path.insert(0, str(ROOT / "backend"))

from voice_console.config import ConfigError, load_targets_config  # noqa: E402


def _read_mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a mapping")
    return value


def _load_upgrade_gate():
    spec = importlib.util.spec_from_file_location("realtime_upgrade_gate", UPGRADE_GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the Realtime upgrade gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect_target_gate(
    manifest_path: Path,
    targets_path: Path,
    *,
    target_name: str,
    mode: str,
) -> dict[str, Any]:
    manifest = _read_mapping(manifest_path)
    target_document = _read_mapping(targets_path)
    targets = target_document.get("targets")
    failures: list[str] = []
    if not isinstance(targets, dict) or not targets:
        return {"passed": False, "failures": ["targets config contains no targets"]}
    parsed_targets = None
    try:
        parsed_targets = load_targets_config(targets_path)
    except ConfigError as exc:
        failures.append(f"invalid runtime targets config: {exc}")
    target = targets.get(target_name)
    if not isinstance(target, dict):
        return {"passed": False, "failures": [f"target {target_name!r} is not configured"]}

    if manifest.get("enabled") is not False:
        failures.append("compatibility manifest must remain globally disabled")
    models = manifest.get("models") or {}
    if models.get("realtime") != "gpt-realtime-2.1":
        failures.append("Realtime model does not match the locked product model")
    if models.get("lead_worker") != "gpt-5.6-sol":
        failures.append("lead worker model does not match the locked product model")
    hermes = manifest.get("hermes") or {}
    if not hermes.get("production_pinned_commit"):
        failures.append("production Hermes pin is missing")

    enabled_targets = sorted(
        name
        for name, value in (parsed_targets.targets.items() if parsed_targets else ())
        if value.realtime_enabled
    )
    selected_enabled = bool(
        parsed_targets
        and target_name in parsed_targets.targets
        and parsed_targets.targets[target_name].realtime_enabled
    )
    if mode == "staging":
        if target.get("realtime_rollout_scope") != "staging":
            failures.append("selected target is not explicitly classified for staging")
        if not selected_enabled:
            failures.append("selected staging target is not Realtime-enabled")
        if enabled_targets != [target_name]:
            failures.append("Realtime must be enabled for exactly the selected staging target")
    elif enabled_targets:
        failures.append("rollback requires Realtime disabled for every configured target")

    key_env = str(target.get("api_key_env") or "").strip()
    key_configured = bool(key_env and os.environ.get(key_env, "").strip())
    if mode == "staging" and not key_configured:
        failures.append("selected target API key environment variable is not configured")

    return {
        "passed": not failures,
        "mode": mode,
        "target": target_name,
        "target_realtime_enabled": selected_enabled,
        "enabled_targets": enabled_targets,
        "target_key": {"environment_variable": key_env or None, "configured": key_configured},
        "global_default_enabled": manifest.get("enabled"),
        "production_pinned_commit": hermes.get("production_pinned_commit"),
        "acceptance": {
            "owner": "pending",
            "physical_phone": "pending",
        },
        "failures": failures,
    }


def inspect_current_main(
    manifest_path: Path, repo: Path, *, expected_current_main: str
) -> dict[str, Any]:
    gate = _load_upgrade_gate()
    head_result = gate.git(repo, "rev-parse", "HEAD", check=False)
    head = head_result.stdout.strip() if head_result.returncode == 0 else ""
    if not head:
        return {"status": "not_run", "compatible": False, "detail": "checkout has no HEAD"}
    main_result = gate.git(repo, "rev-parse", "origin/main", check=False)
    if main_result.returncode:
        main_result = gate.git(repo, "rev-parse", "main", check=False)
    current_main = main_result.stdout.strip() if main_result.returncode == 0 else ""
    if not expected_current_main or current_main != expected_current_main or head != current_main:
        return {
            "status": "wrong_checkout",
            "compatible": False,
            "commit": head,
            "expected_current_main": current_main or None,
            "requested_current_main": expected_current_main or None,
            "detail": "current-main lane must match the explicitly refreshed upstream SHA",
        }
    if not gate.working_tree_clean(repo):
        return {
            "status": "dirty_checkout",
            "compatible": False,
            "commit": head,
            "detail": "current-main evidence requires a clean tracked and untracked worktree",
        }
    static_ok, static_failures = gate.static_contract_check(repo, head)
    if not static_ok:
        return {
            "status": "preflight_blocked",
            "compatible": False,
            "commit": head,
            "detail": static_failures,
        }

    contract, probe_detail = gate.runtime_contract(repo)
    if contract is None:
        return {
            "status": "runtime_blocked",
            "compatible": False,
            "commit": head,
            "detail": probe_detail,
        }
    manifest = _read_mapping(manifest_path)
    models = manifest.get("models") or {}
    model_matches = (
        contract.get("provider", {}).get("model") == models.get("realtime")
        and contract.get("workers", {}).get("lead_model") == models.get("lead_worker")
    )
    document = gate.compatibility_document(contract)
    compatibility = gate.check_realtime_compatibility(document)
    tests_ok, tests_detail = gate.run_runtime_tests(repo) if compatibility.compatible else (
        False,
        "focused suite not run because contract preflight failed",
    )
    compatible = compatibility.compatible and model_matches and tests_ok
    return {
        "status": "compatible" if compatible else "runtime_blocked",
        "compatible": compatible,
        "commit": head,
        "detail": tests_detail if compatible else list(compatibility.reasons),
        "model_matches": model_matches,
    }


def evaluate(
    manifest_path: Path,
    targets_path: Path,
    *,
    target_name: str,
    mode: str,
    supported_repo: Path | None = None,
    current_main_repo: Path | None = None,
    current_main_sha: str | None = None,
) -> dict[str, Any]:
    target_gate = inspect_target_gate(
        manifest_path, targets_path, target_name=target_name, mode=mode
    )
    supported = None
    if mode == "staging":
        if supported_repo is None:
            supported = {"passed": False, "detail": "supported Hermes checkout is required"}
        else:
            supported = _load_upgrade_gate().evaluate(manifest_path, supported_repo)
    current_main = (
        inspect_current_main(
            manifest_path, current_main_repo, expected_current_main=current_main_sha or ""
        )
        if current_main_repo is not None
        else {"status": "not_run", "compatible": False}
    )
    blocking_passed = target_gate["passed"] and (
        mode == "rollback" or bool(supported and supported.get("passed"))
    )
    return {
        "passed": blocking_passed,
        "mode": mode,
        "target_gate": target_gate,
        "supported_pin": supported,
        "current_main_advisory": current_main,
        "external_deployment_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("staging", "rollback"), required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "config" / "hermes-realtime-compatibility.yaml"
    )
    parser.add_argument("--supported-hermes-repo", type=Path)
    parser.add_argument("--current-main-repo", type=Path)
    parser.add_argument("--current-main-sha")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate(
        args.manifest.resolve(),
        args.targets.resolve(),
        target_name=args.target,
        mode=args.mode,
        supported_repo=(args.supported_hermes_repo.resolve() if args.supported_hermes_repo else None),
        current_main_repo=(args.current_main_repo.resolve() if args.current_main_repo else None),
        current_main_sha=args.current_main_sha,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Realtime rollout gate passed" if result["passed"] else "Realtime rollout gate failed")
        advisory = result["current_main_advisory"]
        print(f"Current-main advisory: {advisory['status']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
