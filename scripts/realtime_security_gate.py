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
BRACKET_PROPERTY = re.compile(r"\[['\"](?P<name>[A-Za-z_$][\w$]*)['\"]\]")
STORAGE_ALIAS = re.compile(
    r"\b(?:const|let|var)\s+(?P<alias>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:window\.)?(?:localStorage|sessionStorage)\b"
)
FORBIDDEN_PERSISTENCE = {
    "IndexedDB write": re.compile(r"\bindexedDB\s*(?:\.|\[)\s*(?:open|deleteDatabase)\b"),
    "cookie write": re.compile(r"\bdocument\s*\.\s*cookie\s*="),
    "Cache API write": re.compile(r"\bcaches\s*\.\s*open\s*\("),
}


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
    persistence_surfaces: set[str] = set()
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
            normalized = BRACKET_PROPERTY.sub(lambda match: "." + match.group("name"), text)
            constants = {
                match.group("symbol"): match.group("value")
                for match in STRING_CONSTANT.finditer(normalized)
            }
            for match in STORAGE_WRITE.finditer(normalized):
                key = match.group("literal") or constants.get(match.group("symbol") or "")
                if key is None:
                    failures.append(f"dynamic browser storage key appears in {relative}")
                else:
                    storage_keys.add(key)
                    persistence_surfaces.add("Web Storage")
            for alias_match in STORAGE_ALIAS.finditer(normalized):
                alias = alias_match.group("alias")
                alias_write = re.compile(
                    rf"\b{re.escape(alias)}\s*(?:\.\s*setItem\s*\(|\[)"
                )
                if alias_write.search(normalized):
                    failures.append(f"aliased or computed browser storage write appears in {relative}")
            if re.search(r"(?:localStorage|sessionStorage)\s*\[", normalized):
                failures.append(f"computed browser storage access appears in {relative}")
            for label, pattern in FORBIDDEN_PERSISTENCE.items():
                if pattern.search(normalized):
                    failures.append(f"{label} appears in application source {relative}")

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
        "persistence_surfaces": sorted(persistence_surfaces),
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
