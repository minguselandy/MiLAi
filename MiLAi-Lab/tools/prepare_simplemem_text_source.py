"""Verify pinned public text source; acquire it only with explicit --prepare in CI."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from milai_lab.integrations.memory.simplemem import POLICY, SOURCE_COMMIT, dependency_identity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("artifacts/simplemem-text/source"))
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.source.exists():
        if not args.prepare:
            raise ValueError("SIMPLEMEM_SOURCE_MISSING")
        args.source.mkdir(parents=True)
        git = shutil.which("git") or "/usr/bin/git"
        for command in (
            [git, "init"],
            [
                git,
                "fetch",
                "--depth=1",
                "https://github.com/aiming-lab/SimpleMem.git",
                SOURCE_COMMIT,
            ],
            [git, "checkout", "--detach", "FETCH_HEAD"],
        ):
            subprocess.run(command, cwd=args.source, check=True)  # noqa: S603 - fixed public pin
    identity = dependency_identity({**POLICY, "source_root": str(args.source.resolve())})
    print(json.dumps(identity, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
