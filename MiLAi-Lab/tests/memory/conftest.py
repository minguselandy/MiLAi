"""Rebuild frozen public source comparisons from repository history, without HTTP."""

import hashlib
import subprocess
from pathlib import Path

import pytest

BASE = "8b1fdf3c017477ee80a0284f08ca4a1f5f52e670"
SOURCES = {
    "harness/contextual_artifacts.py":
        "b8c864b483656eb29fb3967a01bd1d1c18db8e47f1955030f7fb2e6a887ad22d",
    "providers/contextual_vllm.py":
        "a9f15fcbbcc0ead318f0871538269128eb904d6cbe13c2f3fbd7c23f5927809a",
    "memory/service_tools.py":
        "bc260664d78a3020eac396ac6fcd188872858843ee74bb03035659e1e465dde5",
    "methods/grounded_memory.py":
        "b96fc3af783b0056cef84c89d12d396cdd4a2846b5fc83ced8f9c9906300d681",
}


@pytest.fixture(scope="session")
def frozen_pre_http_sources(tmp_path_factory):
    root = tmp_path_factory.mktemp("frozen-pre-http-sources")
    for relative, expected in SOURCES.items():
        path = "src/milai_lab/" + relative
        content = subprocess.check_output(  # noqa: S603 -- fixed repository object and paths
            ["git", "show", BASE + ":MiLAi-Lab/" + path],  # noqa: S607
            cwd=Path(__file__).resolve().parents[3],
        )
        assert hashlib.sha256(content).hexdigest() == expected
        target = root / "base-source" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root
