#!/usr/bin/env python3
"""Classify changed paths for MiLAi's fast and full verification gates."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from pathlib import Path

CLASSIFICATIONS = (
    "runtime",
    "mcp",
    "openworker",
    "python-client",
    "hooks",
    "langgraph",
    "autogen",
    "lab",
    "archive",
)
INTEGRATION_KEYS = ("python-client", "mcp", "openworker", "hooks", "langgraph", "autogen")
INTEGRATION_PACKAGE = {
    **{key: key for key in INTEGRATION_KEYS},
    "openworker": "openworker-mcp",
}


def _matches(path: str, prefix: str) -> bool:
    return path == prefix.rstrip("/") or path.startswith(prefix)


def classify(paths: Iterable[str], *, full_requested: bool = False) -> dict[str, object]:
    normalized = []
    for path in paths:
        candidate = path.strip()
        if candidate.startswith("./"):
            candidate = candidate[2:]
        if candidate:
            normalized.append(candidate)
    changed = sorted(set(normalized))
    flags = {name: False for name in CLASSIFICATIONS}
    behavior_or_ci = False
    product_other = False

    for path in changed:
        if _matches(path, "MiLAi-Product/runtime/"):
            flags["runtime"] = True
        elif _matches(path, "MiLAi-Product/integrations/mcp/"):
            flags["mcp"] = True
        elif _matches(path, "MiLAi-Product/integrations/openworker-mcp/"):
            flags["openworker"] = True
        elif _matches(path, "MiLAi-Product/integrations/python-client/"):
            flags["python-client"] = True
        elif _matches(path, "MiLAi-Product/integrations/hooks/"):
            flags["hooks"] = True
        elif _matches(path, "MiLAi-Product/integrations/langgraph/"):
            flags["langgraph"] = True
        elif _matches(path, "MiLAi-Product/integrations/autogen/"):
            flags["autogen"] = True
        elif _matches(path, "MiLAi-Lab/docs/") and path.endswith(".md"):
            # Narrative documentation cannot select the Lab package test/build gate.
            # Keep source, tests, data, policies, tools and non-Markdown inputs conservative.
            pass
        elif _matches(path, "MiLAi-Lab/"):
            flags["lab"] = True
        elif _matches(path, "MiLAi-Artifact-Archive/"):
            flags["archive"] = True
        elif _matches(path, ".github/"):
            behavior_or_ci = True
        elif _matches(path, "MiLAi-Product/"):
            product_other = True
            if any(
                _matches(path, prefix)
                for prefix in (
                    "MiLAi-Product/architecture/",
                    "MiLAi-Product/contracts/",
                    "MiLAi-Product/runtime/migrations/",
                )
            ):
                behavior_or_ci = True
        elif path in {
            "AGENTS.md",
            "SOURCE_OF_TRUTH.md",
            "REPO_MAP.md",
            "LEGACY_READ_ONLY.md",
        }:
            behavior_or_ci = True

    affected_subsystems = sum(bool(flags[name]) for name in CLASSIFICATIONS)
    full_required = behavior_or_ci or affected_subsystems > 1
    if full_requested:
        flags = {name: True for name in CLASSIFICATIONS}

    packages = [INTEGRATION_PACKAGE[name] for name in INTEGRATION_KEYS if flags[name]]
    return {
        **flags,
        "product": product_other or any(flags[name] for name in ("runtime", *INTEGRATION_KEYS)),
        "full_required": full_required,
        "full_run": full_requested,
        "integration_matrix": {"package": packages},
        "integration_count": len(packages),
        "changed_paths": changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="repository-relative changed paths")
    parser.add_argument("--paths-file", type=Path)
    parser.add_argument("--full-requested", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    paths = list(args.paths)
    if args.paths_file:
        paths.extend(args.paths_file.read_text(encoding="utf-8").splitlines())
    result = classify(paths, full_requested=args.full_requested)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            for key, value in result.items():
                output_key = key.replace("-", "_")
                if isinstance(value, bool):
                    rendered = str(value).lower()
                elif isinstance(value, (dict, list)):
                    rendered = json.dumps(value, separators=(",", ":"), sort_keys=True)
                else:
                    rendered = str(value)
                stream.write(f"{output_key}={rendered}{os.linesep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
