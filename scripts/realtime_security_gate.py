#!/usr/bin/env python
"""Fail closed if browser artifacts contain provider credentials or unsafe storage."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PROVIDER_MARKERS = (
    "OPENAI_API_KEY",
    "HERMES_API_KEY",
    "ANTHROPIC_API_KEY",
    "FAKE_HERMES_API_KEY",
    "sk-proj-",
    "sk-live-",
    "Bearer fake",
)
ALLOWED_STORAGE_KEYS = frozenset({"hvc.recovery.v1", "hvc_debug"})
STORAGE_WRITE = re.compile(
    r"(?:window\.)?(?:localStorage|sessionStorage)\.setItem\(\s*"
    r"(?:(?P<quote>['\"])(?P<literal>[^'\"]+)(?P=quote)|(?P<symbol>[A-Za-z_$][\w$]*))"
)
STRING_CONSTANT = re.compile(
    r"\bconst\s+(?P<symbol>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?P<quote>['\"])(?P<value>[^'\"]+)(?P=quote)\s*;"
)


def audit(root: Path) -> dict[str, object]:
    source_root = root / "frontend" / "src"
    dist_root = root / "frontend" / "dist"
    failures: list[str] = []
    files: list[Path] = [
        path
        for path in source_root.rglob("*")
        if path.is_file() and ".test." not in path.name
    ]
    if not dist_root.is_dir():
        failures.append("frontend/dist is missing; build before running the security gate")
    else:
        files.extend(path for path in dist_root.rglob("*") if path.is_file())
        maps = sorted(path.relative_to(root).as_posix() for path in dist_root.rglob("*.map"))
        if maps:
            failures.append("browser source maps are present: " + ", ".join(maps))

    storage_keys: set[str] = set()
    scanned = 0
    for path in files:
        try:
            text = path.read_text(errors="ignore")
        except OSError as exc:
            failures.append(f"could not scan {path.relative_to(root)}: {exc.__class__.__name__}")
            continue
        scanned += len(text.encode(errors="ignore"))
        relative = path.relative_to(root).as_posix()
        for marker in PROVIDER_MARKERS:
            if marker in text:
                failures.append(f"provider credential marker {marker!r} appears in {relative}")
        if re.search(r"sk-[A-Za-z0-9_-]{20,}", text):
            failures.append(f"OpenAI-style secret appears in {relative}")
        if path.is_relative_to(source_root):
            constants = {
                match.group("symbol"): match.group("value")
                for match in STRING_CONSTANT.finditer(text)
            }
            for match in STORAGE_WRITE.finditer(text):
                key = match.group("literal") or constants.get(match.group("symbol") or "")
                if key is None:
                    failures.append(f"dynamic browser storage key appears in {relative}")
                else:
                    storage_keys.add(key)

    unknown = sorted(storage_keys - ALLOWED_STORAGE_KEYS)
    if unknown:
        failures.append("unapproved browser storage keys: " + ", ".join(unknown))

    recovery_source = (source_root / "lib" / "recovery.ts").read_text()
    forbidden_recovery_fields = {"transcript", "response", "approval", "toolArguments"}
    leaked_fields = sorted(field for field in forbidden_recovery_fields if field in recovery_source)
    if leaked_fields:
        failures.append("recovery storage references content fields: " + ", ".join(leaked_fields))

    return {
        "passed": not failures,
        "files_scanned": len(files),
        "bytes_scanned": scanned,
        "storage_keys": sorted(storage_keys),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(args.root.resolve())
    print(json.dumps(result, indent=2) if args.json else (
        "Realtime browser security gate passed" if result["passed"]
        else "Realtime browser security gate failed: " + "; ".join(result["failures"])
    ))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
