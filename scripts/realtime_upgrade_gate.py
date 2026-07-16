#!/usr/bin/env python
"""Verify the pinned Hermes lane and fail closed for unsupported upgrades."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml


REALTIME_CONTRACT_PATH = "gateway/realtime/contracts.py"
REALTIME_API_PATH = "gateway/realtime/api.py"


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def commit_exists(repo: Path, commit: str) -> bool:
    return git(repo, "cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode == 0


def path_exists(repo: Path, commit: str, path: str) -> bool:
    return git(repo, "cat-file", "-e", f"{commit}:{path}", check=False).returncode == 0


def evaluate(manifest_path: Path, hermes_repo: Path) -> dict[str, Any]:
    manifest = yaml.safe_load(manifest_path.read_text())
    hermes = manifest.get("hermes") or {}
    minimum = str(hermes.get("minimum_tested_commit") or "")
    pinned = str(hermes.get("production_pinned_commit") or "")
    main_result = git(hermes_repo, "rev-parse", "origin/main", check=False)
    if main_result.returncode:
        main_result = git(hermes_repo, "rev-parse", "main", check=False)
    current_main = main_result.stdout.strip() if main_result.returncode == 0 else ""
    head = git(hermes_repo, "rev-parse", "HEAD").stdout.strip()

    rows: list[dict[str, Any]] = []
    for lane, commit in (("minimum_supported", minimum), ("production_pinned", pinned)):
        exists = bool(commit) and commit_exists(hermes_repo, commit)
        contract = exists and all(
            path_exists(hermes_repo, commit, path)
            for path in (REALTIME_CONTRACT_PATH, REALTIME_API_PATH)
        )
        rows.append({
            "lane": lane,
            "commit": commit,
            "expected": "compatible",
            "observed": "compatible_source" if contract else "unsupported",
            "passed": contract,
        })

    main_contract = bool(current_main) and all(
        path_exists(hermes_repo, current_main, path)
        for path in (REALTIME_CONTRACT_PATH, REALTIME_API_PATH)
    )
    main_is_pinned = current_main == pinned
    if not main_contract:
        main_observed = "preflight_blocked_missing_contract"
        main_passed = True
    elif main_is_pinned:
        main_observed = "pinned_contract"
        main_passed = True
    else:
        # Source presence is not contract compatibility. A newly capable main
        # must run in a disposable lane before this gate can bless an update.
        main_observed = "runtime_validation_required"
        main_passed = False
    rows.append({
        "lane": "current_main_nonproduction",
        "commit": current_main,
        "expected": "compatible_or_preflight_blocked",
        "observed": main_observed,
        "passed": bool(current_main) and main_passed,
    })
    rows.extend(
        [
            {
                "lane": "realtime_disabled",
                "expected": "legacy_only",
                "observed": "legacy_only" if manifest.get("enabled") is False else "enabled",
                "passed": manifest.get("enabled") is False,
            },
            {
                "lane": "model_unavailable",
                "expected": "preflight_blocked",
                "observed": "covered_by_contract_matrix_test",
                "passed": True,
            },
        ]
    )
    pinned_checkout = head == pinned
    return {
        "passed": all(bool(row["passed"]) for row in rows) and pinned_checkout,
        "active_checkout": head,
        "pinned_checkout": pinned_checkout,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--manifest", type=Path, default=root / "config" / "hermes-realtime-compatibility.yaml"
    )
    parser.add_argument("--hermes-repo", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.manifest.resolve(), args.hermes_repo.resolve())
    print(json.dumps(result, indent=2) if args.json else (
        "Realtime upgrade gate passed" if result["passed"]
        else "Realtime upgrade gate failed"
    ))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
