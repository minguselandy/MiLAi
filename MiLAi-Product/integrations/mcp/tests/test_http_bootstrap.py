# ruff: noqa: S105 -- Deliberately fake ordinary-client credentials in offline tests.

from __future__ import annotations

import asyncio
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from milai_mcp import launcher, prepare_http_working_context


def state() -> dict[str, Any]:
    return {"schema_version": "host-cognitive-state-v1", "schema_name": "codex-cognitive-state-v1",
            "scope": "TASK", "status": "ACTIVE", "authority": "HOST_WORKING",
            "state_id": "existing", "version": 3, "payload": {"note": "首\r\n尾 \n"}}


def test_remote_launcher_uses_existing_identity_and_preserves_user_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text('developer_instructions = "existing guide"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("MILAI_MCP_BEARER_TOKEN", "ordinary-client-token")
    monkeypatch.setenv("MILAI_AGENT_READER_TOKEN", "runtime-not-needed")
    seen = []

    async def prefetch(url: str, token: str) -> dict[str, Any]:
        assert url == "https://memory.example/mcp" and token == "ordinary-client-token"
        seen.append("get")
        return state()

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append("codex")
        profile = tomllib.loads((home / (command[2] + ".config.toml")).read_text())
        assert profile["mcp_servers"]["milai"]["url"] == "https://memory.example/mcp"
        assert "existing guide" in profile["developer_instructions"]
        assert "MILA_HOST_WORKING_STATE_DATA" in profile["developer_instructions"]
        assert "runtime-not-needed" not in str(kwargs["env"])
        assert kwargs["env"]["MILAI_CODEX_LAUNCHER_TOKEN"] == "ordinary-client-token"
        assert "ordinary-client-token" not in str(command)
        return subprocess.CompletedProcess(command, 0)

    def no_server(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Remote bootstrap must not launch a private Runtime/MCP server")

    monkeypatch.setattr(launcher, "_prefetch_working_state", prefetch)
    monkeypatch.setattr(launcher.subprocess, "run", run)
    monkeypatch.setattr(launcher.subprocess, "Popen", no_server)
    args = launcher._parser().parse_args(["codex", "--cwd", str(tmp_path), "--mcp-url",
        "https://memory.example/mcp", "--codex-bin", "/bin/codex", "--", "exec", "continue"])
    assert launcher._run_codex(args) == 0 and seen == ["get", "codex"]
    assert list(home.glob("milai-host-*.config.toml")) == []
    assert (home / "config.toml").read_text() == 'developer_instructions = "existing guide"\n'


@pytest.mark.parametrize("url", ["http://public.example/mcp", "file:///tmp/mcp",
                                 "https://user:password@memory.example/mcp"])
def test_credentials_not_sent_to_unsupported_transport(url: str, monkeypatch: pytest.MonkeyPatch):
    async def never(*args: Any) -> dict[str, Any]:
        pytest.fail("must reject before network")
    monkeypatch.setattr(launcher, "_prefetch_working_state", never)
    with pytest.raises(launcher.ActivationError, match="HTTPS"):
        asyncio.run(prepare_http_working_context(url, "token"))


def test_explicit_deadline_stops_prefetch_before_context(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(*args: Any) -> dict[str, Any]:
        await asyncio.sleep(1)
        return state()
    monkeypatch.setattr(launcher, "_prefetch_working_state", slow)
    with pytest.raises(launcher.ActivationError, match="timed out"):
        asyncio.run(prepare_http_working_context("http://127.0.0.1:1234/mcp", "token",
                                                timeout_seconds=0.01))


def test_remote_mode_cannot_override_server_workflow() -> None:
    args = launcher._parser().parse_args(["codex", "--mcp-url", "https://memory.example/mcp",
                                         "--project-id", "forged"])
    with pytest.raises(launcher.ActivationError, match="bindings conflict"):
        launcher._run_codex(args)


def test_unavailable_prefetch_is_not_converted_to_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unavailable(*args: Any) -> dict[str, Any]:
        raise launcher.ActivationError("MCP unavailable")
    monkeypatch.setattr(launcher, "_prefetch_working_state", unavailable)
    with pytest.raises(launcher.ActivationError, match="unavailable"):
        asyncio.run(prepare_http_working_context("https://memory.example/mcp", "token"))
