from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

Scope = Literal["project", "user"]
_EVENTS = ("SessionStart", "UserPrompt", "PostToolUse", "PreCompact", "Stop")
_MARKER = "milai-hooks-v1"


def install(config_path: Path, *, scope: Scope) -> dict[str, Any]:
    document = _read_document(config_path)
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("existing hooks field must be an object")
    added = 0
    for event in _EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise ValueError(f"existing hooks.{event} must be an array")
        if any(isinstance(item, dict) and item.get("_managed_by") == _MARKER for item in entries):
            continue
        entries.append(
            {
                "_managed_by": _MARKER,
                "scope": scope,
                "type": "command",
                "command": "milai-hook",
                "args": [event],
                "capture_default": "OFF",
            }
        )
        added += 1
    _atomic_write(config_path, document)
    return {
        "status": "INSTALLED" if added else "ALREADY_INSTALLED",
        "config": str(config_path.resolve()),
        "scope": scope,
        "entries_added": added,
        "secrets_written": False,
    }


def uninstall(config_path: Path) -> dict[str, Any]:
    document = _read_document(config_path)
    hooks = document.get("hooks")
    removed = 0
    if isinstance(hooks, dict):
        for event in list(hooks):
            entries = hooks[event]
            if not isinstance(entries, list):
                continue
            retained = [
                item
                for item in entries
                if not (isinstance(item, dict) and item.get("_managed_by") == _MARKER)
            ]
            removed += len(entries) - len(retained)
            if retained:
                hooks[event] = retained
            else:
                del hooks[event]
    _atomic_write(config_path, document)
    return {
        "status": "UNINSTALLED" if removed else "NOT_INSTALLED",
        "config": str(config_path.resolve()),
        "entries_removed": removed,
    }


def _read_document(path: Path) -> dict[str, Any]:
    target = path.expanduser().resolve(strict=False)
    if not target.parent.is_dir():
        raise ValueError("config parent directory must already exist")
    if not target.exists():
        return {}
    if not target.is_file() or target.is_symlink():
        raise ValueError("config must be a regular non-symlink file")
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("hook config must contain a JSON object")
    return value


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    target = path.expanduser().resolve(strict=False)
    current_mode = (target.stat().st_mode & 0o777) if target.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, current_mode)
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Install or remove MiLAi lifecycle hooks")
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--scope", choices=("project", "user"))
    args = parser.parse_args()
    if args.action == "install":
        if args.scope is None:
            raise SystemExit("install requires explicit --scope project|user")
        result = install(args.config, scope=args.scope)
    else:
        result = uninstall(args.config)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
