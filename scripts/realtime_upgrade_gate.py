#!/usr/bin/env python
"""Execute the pinned Hermes contract suite and fail closed on upgrades."""

from __future__ import annotations

import argparse
import ast
import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from voice_console.realtime.contracts import (  # noqa: E402
    REQUIRED_ENDPOINTS,
    REQUIRED_FEATURES,
    check_realtime_compatibility,
)

REALTIME_CONTRACT_PATH = "gateway/realtime/contracts.py"
REALTIME_API_PATH = "gateway/realtime/api.py"
REALTIME_HTTP_PATH = "gateway/realtime/http.py"
REQUIRED_API_METHODS = {
    "capabilities", "create", "get_session", "delete_session", "activate", "input",
    "commit_manual_audio", "discard_manual_audio", "update_turn_mode",
    "interrupt", "events", "resolve_approval", "conversation",
    "request_result", "list_worker_jobs", "get_worker_job", "worker_events",
    "worker_command_result", "worker_command",
}

CAPABILITY_PROBE = r'''
import json
from gateway.realtime.api import RealtimeSessionAPI

api = RealtimeSessionAPI(
    None,
    instructions="compatibility probe",
    tools=({"type": "function", "name": "get_status", "parameters": {"type": "object"}},),
    model="gpt-realtime-2.1",
    voice="marin",
    state=object(),
    capability_config={
        "provider": "openai",
        "direct_tools": ["get_status"],
        "worker_model": "gpt-5.6-sol",
        "max_concurrency": 1,
        "max_fanout": 1,
        "retention": {
            "event_count": 2048,
            "event_bytes": 4194304,
            "context_bytes": 65536,
            "completed_item_days": 30,
        },
        "timeouts": {
            "provider_request_seconds": 30,
            "controller_ready_seconds": 10,
            "tool_seconds": 120,
            "worker_seconds": 3600,
            "approval_seconds": 300,
        },
    },
)
print(json.dumps(api.capabilities(), sort_keys=True))
'''


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def commit_exists(repo: Path, commit: str) -> bool:
    return git(repo, "cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode == 0


def source_at(repo: Path, commit: str, path: str) -> str | None:
    result = git(repo, "show", f"{commit}:{path}", check=False)
    return result.stdout if result.returncode == 0 else None


def static_contract_check(repo: Path, commit: str) -> tuple[bool, list[str]]:
    failures: list[str] = []
    contracts = source_at(repo, commit, REALTIME_CONTRACT_PATH)
    api = source_at(repo, commit, REALTIME_API_PATH)
    http = source_at(repo, commit, REALTIME_HTTP_PATH)
    if contracts is None or api is None or http is None:
        return False, ["required Realtime source modules are missing"]
    version = re.search(r'REALTIME_CONTRACT_VERSION\s*=\s*["\']([^"\']+)', contracts)
    if version is None or version.group(1).split(".", 1)[0] != "1":
        failures.append("contracts.realtime major is not 1.x")
    try:
        tree = ast.parse(api)
    except SyntaxError:
        failures.append("Realtime API source is not valid Python")
    else:
        methods = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        missing_methods = sorted(REQUIRED_API_METHODS - methods)
        if missing_methods:
            failures.append("missing API methods: " + ", ".join(missing_methods))
    required_semantics = (
        "gpt-realtime-2.1", "gpt-5.6-sol", "manual_audio_commit",
        "manual_audio_discard", "turn_mode_update", "delegate_work",
        "raw_delegate_task_exposed", "exactly_once_durable_inbox",
        "announce_without_prompting",
    )
    missing_semantics = [token for token in required_semantics if token not in api]
    if missing_semantics:
        failures.append("missing contract semantics: " + ", ".join(missing_semantics))
    required_routes = (
        'add_post("/v1/realtime/sessions"',
        'add_get("/v1/realtime/sessions/{session_id}"',
        'add_delete("/v1/realtime/sessions/{session_id}"',
        '"/v1/realtime/sessions/{session_id}/approvals/{approval_id}"',
        '"/v1/realtime/conversations/{conversation_id}"',
        '"/v1/realtime/conversations/{conversation_id}/requests/{client_request_id}"',
        'base = "/v1/realtime/conversations/{conversation_id}/worker-jobs"',
    )
    missing_routes = [token for token in required_routes if token not in http]
    for suffix in ("activate", "input", "commit", "discard", "turn-mode", "interrupt", "events"):
        if f'"/v1/realtime/sessions/{{session_id}}/{suffix}"' not in http:
            missing_routes.append(suffix)
    if missing_routes:
        failures.append("missing HTTP routes: " + ", ".join(missing_routes))
    return not failures, failures


def runtime_contract(repo: Path) -> tuple[dict[str, Any] | None, str]:
    python = repo / ".venv" / "bin" / "python"
    if not python.is_file():
        return None, "Hermes virtualenv is missing"
    try:
        result = subprocess.run(
            [str(python), "-c", CAPABILITY_PROBE],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None, "runtime capability probe timed out"
    if result.returncode != 0:
        return None, "runtime capability probe failed"
    try:
        value = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return None, "runtime capability probe returned invalid JSON"
    return (value, "runtime capability probe passed") if isinstance(value, dict) else (
        None, "runtime capability probe was not an object"
    )


def compatibility_document(contract: dict[str, Any]) -> dict[str, Any]:
    endpoints: dict[str, dict[str, str]] = {}
    index = 0
    for path, methods in REQUIRED_ENDPOINTS.items():
        for method in methods.split("|"):
            endpoints[f"required_{index}"] = {"path": path, "method": method}
            index += 1
    return {
        "features": {feature: True for feature in REQUIRED_FEATURES},
        "contracts": {"realtime": contract},
        "endpoints": endpoints,
    }


def run_runtime_tests(repo: Path) -> tuple[bool, str]:
    python = repo / ".venv" / "bin" / "python"
    if not python.is_file():
        return False, "Hermes virtualenv is missing"
    try:
        result = subprocess.run(
            [str(python), "-m", "pytest", "tests/gateway/realtime", "-q"],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return False, "focused Realtime suite timed out"
    summary = next(
        (line.strip() for line in reversed(result.stdout.splitlines()) if "passed" in line),
        "focused Realtime suite failed",
    )
    return result.returncode == 0, summary[:200]


def evaluate(manifest_path: Path, hermes_repo: Path) -> dict[str, Any]:
    manifest = yaml.safe_load(manifest_path.read_text())
    hermes = manifest.get("hermes") or {}
    minimum = str(hermes.get("minimum_tested_commit") or "")
    pinned = str(hermes.get("production_pinned_commit") or "")
    main_result = git(hermes_repo, "rev-parse", "origin/main", check=False)
    if main_result.returncode:
        main_result = git(hermes_repo, "rev-parse", "main", check=False)
    current_main = main_result.stdout.strip() if main_result.returncode == 0 else ""
    head_result = git(hermes_repo, "rev-parse", "HEAD", check=False)
    head = head_result.stdout.strip() if head_result.returncode == 0 else ""

    static_ok, static_failures = (
        static_contract_check(hermes_repo, pinned)
        if pinned and commit_exists(hermes_repo, pinned)
        else (False, ["production pin is missing"])
    )
    contract, probe_detail = runtime_contract(hermes_repo) if head == pinned and static_ok else (
        None, "runtime probe not run because checkout or static contract did not pass"
    )
    configured_models = manifest.get("models") or {}
    runtime_compatibility = None
    model_blocked = False
    if contract is not None:
        document = compatibility_document(contract)
        runtime_compatibility = check_realtime_compatibility(document)
        unavailable = copy.deepcopy(document)
        unavailable["contracts"]["realtime"]["models"] = []
        unavailable["contracts"]["realtime"]["provider"]["model"] = "unavailable"
        model_blocked = not check_realtime_compatibility(unavailable).compatible
        if contract.get("provider", {}).get("model") != configured_models.get("realtime"):
            runtime_compatibility = None
            probe_detail = "runtime Realtime model does not match manifest"
        if contract.get("workers", {}).get("lead_model") != configured_models.get("lead_worker"):
            runtime_compatibility = None
            probe_detail = "runtime worker model does not match manifest"

    tests_ok, tests_detail = (
        run_runtime_tests(hermes_repo)
        if runtime_compatibility is not None and runtime_compatibility.compatible
        else (False, "focused Realtime suite not run because contract preflight failed")
    )
    pinned_ok = bool(
        head == pinned and static_ok and runtime_compatibility is not None
        and runtime_compatibility.compatible and tests_ok
    )

    rows: list[dict[str, Any]] = [
        {
            "lane": "minimum_supported",
            "commit": minimum,
            "expected": "compatible",
            "observed": "same_executable_lane_as_pin" if minimum == pinned and pinned_ok else "not_validated",
            "passed": minimum == pinned and pinned_ok,
        },
        {
            "lane": "production_pinned",
            "commit": pinned,
            "expected": "compatible",
            "observed": "runtime_compatible" if pinned_ok else "blocked",
            "passed": pinned_ok,
            "static_failures": static_failures,
            "probe": probe_detail,
            "tests": tests_detail,
            "reasons": list(runtime_compatibility.reasons) if runtime_compatibility else [],
        },
    ]

    main_static, main_failures = (
        static_contract_check(hermes_repo, current_main)
        if current_main and commit_exists(hermes_repo, current_main)
        else (False, ["current main is unavailable"])
    )
    if not main_static:
        main_observed = "preflight_blocked"
        main_passed = True
    elif current_main == pinned and pinned_ok:
        main_observed = "same_executable_lane_as_pin"
        main_passed = True
    else:
        main_observed = "runtime_validation_required"
        main_passed = False
    rows.extend([
        {
            "lane": "current_main_nonproduction",
            "commit": current_main,
            "expected": "compatible_or_preflight_blocked",
            "observed": main_observed,
            "passed": bool(current_main) and main_passed,
            "static_failures": main_failures,
        },
        {
            "lane": "realtime_disabled",
            "expected": "legacy_only",
            "observed": "legacy_only" if manifest.get("enabled") is False else "enabled",
            "passed": manifest.get("enabled") is False,
        },
        {
            "lane": "model_unavailable",
            "expected": "preflight_blocked",
            "observed": "preflight_blocked" if model_blocked else "not_validated",
            "passed": model_blocked,
        },
    ])
    return {
        "passed": all(bool(row["passed"]) for row in rows),
        "active_checkout": head,
        "pinned_checkout": head == pinned,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "config" / "hermes-realtime-compatibility.yaml"
    )
    parser.add_argument("--hermes-repo", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.manifest.resolve(), args.hermes_repo.resolve())
    print(json.dumps(result, indent=2) if args.json else (
        "Realtime upgrade gate passed" if result["passed"] else "Realtime upgrade gate failed"
    ))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
