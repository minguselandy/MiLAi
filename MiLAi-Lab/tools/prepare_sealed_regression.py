"""Materialize the sealed pre-Edit protocol for its historical regression tests."""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import tarfile
from pathlib import Path

SEALED_COMMIT = "fc1c6c93f6e75f8775e2d5195bb35e6e8ce0e0b1"


def prepare(destination: Path) -> None:
    if destination.exists():
        raise ValueError("SEALED_REGRESSION_DESTINATION_EXISTS")
    repository = Path(__file__).resolve().parents[2]
    git = shutil.which("git")
    if git is None:
        raise ValueError("SEALED_REGRESSION_GIT_UNAVAILABLE")
    archive_bytes = subprocess.check_output(  # noqa: S603 -- fixed archive arguments, no shell
        [git, "archive", SEALED_COMMIT, "MiLAi-Lab"], cwd=repository
    )
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        archive.extractall(destination, filter="data")
    print(destination / "MiLAi-Lab")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    prepare(parser.parse_args().destination)
