"""Run-owned public full-MCP observer binding; no private Product imports."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import run_v02_memory_flow as base


@contextmanager
def observer(root: Path, directory: Path, project: str, task: str) -> Iterator[Any]:
    base.assert_services(root)
    values = base._load_environment(root / "runtime.env")
    token, port = secrets.token_urlsafe(32), base._free_port()
    values.update({"MILAI_CODEX_PRINCIPAL_ID": "v02-lme-host", "MILAI_CODEX_TASK_REF": task,
                   "MILAI_AGENT_SCOPE_JSON": json.dumps({"project_ids": [project]}),
                   "MILAI_CODEX_TOKEN": token,
                   "MILAI_MCP_HTTP_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}"})
    group = base.ProcessGroup(directory)
    try:
        server = group.start("observer-mcp", [str(base.MCP / ".venv/bin/milai-codex-full-mcp"),
                                              "--port", str(port)], cwd=base.MCP,
                             env=base._clean_environment(values))
        base._wait_http(f"http://127.0.0.1:{port}/readyz", server)

        def call(tool: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
            result = asyncio.run(base.mcp_call(f"http://127.0.0.1:{port}/mcp", token,
                                              tool, arguments))
            return result if tool is None else base.structured(result)

        yield call, values
    finally:
        group.stop()
