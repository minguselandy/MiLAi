#!/usr/bin/env python3
"""Run an explicit local cleanup validation profile."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PRODUCT_ROOT / "docs" / "cleanup" / "validation-profiles.json"
REQUIRED_LEVEL_FIELDS = {
    "ruff",
    "mypy",
    "tests",
    "integration_requirement",
    "build",
    "manifest",
    "boundary",
}
COMMAND_GROUPS = ("ruff", "mypy", "tests", "build", "manifest", "boundary")


def _load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "milai-cleanup-validation-profiles-v1":
        raise ValueError("unsupported validation profile schema")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("profiles must be a non-empty object")
    for profile_name, profile in profiles.items():
        if not isinstance(profile.get("changed_paths"), list) or not profile["changed_paths"]:
            raise ValueError(f"{profile_name}: changed_paths must be a non-empty list")
        levels = profile.get("levels")
        if not isinstance(levels, dict) or not levels:
            raise ValueError(f"{profile_name}: levels must be a non-empty object")
        for level_name, level in levels.items():
            missing = REQUIRED_LEVEL_FIELDS - set(level)
            if missing:
                raise ValueError(f"{profile_name}/{level_name}: missing {sorted(missing)}")
            if not isinstance(level["integration_requirement"], str):
                raise ValueError(
                    f"{profile_name}/{level_name}: integration_requirement must be text"
                )
            for group in COMMAND_GROUPS:
                if not isinstance(level[group], list):
                    raise ValueError(f"{profile_name}/{level_name}/{group}: must be a list")
                for command in level[group]:
                    if set(command) != {"cwd", "argv"} or not isinstance(command["argv"], list):
                        raise ValueError(
                            f"{profile_name}/{level_name}/{group}: invalid command entry"
                        )
    return payload


def _roots() -> dict[str, Path]:
    workspace = PRODUCT_ROOT.parent
    return {
        "product": PRODUCT_ROOT,
        "runtime": PRODUCT_ROOT / "runtime",
        "mcp": PRODUCT_ROOT / "integrations" / "mcp",
        "openworker": PRODUCT_ROOT / "integrations" / "openworker-mcp",
        "client": PRODUCT_ROOT / "integrations" / "python-client",
        "lab": workspace / "MiLAi-Lab",
        "workspace": workspace,
    }


def _expanded_argv(argv: list[str]) -> list[str]:
    replacements = {
        "{python}": sys.executable,
        "{runtime_python}": str(PRODUCT_ROOT / "runtime" / ".venv" / "bin" / "python"),
    }
    return [replacements.get(value, value) for value in argv]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?")
    parser.add_argument("--level", choices=("dev", "prepush"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    config = _load_config(args.config.resolve())
    profiles = config["profiles"]
    if args.list:
        for name, profile in sorted(profiles.items()):
            print(f"{name}: {', '.join(sorted(profile['levels']))}")
        return 0
    if not args.profile or not args.level:
        parser.error("profile and --level are required unless --list is used")
    if args.profile not in profiles:
        parser.error(f"unknown profile: {args.profile}")
    profile = profiles[args.profile]
    if args.level not in profile["levels"]:
        parser.error(f"profile {args.profile!r} does not define level {args.level!r}")

    level = profile["levels"][args.level]
    roots = _roots()
    print(
        json.dumps(
            {
                "profile": args.profile,
                "level": args.level,
                "changed_paths": profile["changed_paths"],
                "integration_requirement": level["integration_requirement"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    for group in COMMAND_GROUPS:
        for command in level[group]:
            cwd_name = command["cwd"]
            if cwd_name not in roots:
                raise ValueError(f"unknown cwd anchor: {cwd_name}")
            cwd = roots[cwd_name]
            argv = _expanded_argv(command["argv"])
            if not cwd.is_dir():
                raise FileNotFoundError(f"required checkout is absent: {cwd}")
            print(f"[{group}] ({cwd}) {shlex.join(argv)}", flush=True)
            if not args.dry_run:
                subprocess.run(  # noqa: S603 -- commands are checked-in profile data.
                    argv, cwd=cwd, check=True
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
