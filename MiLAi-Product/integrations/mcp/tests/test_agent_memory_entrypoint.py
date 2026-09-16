from __future__ import annotations

import pytest

from milai_mcp import agent_memory


def test_agent_memory_entrypoint_forwards_only_fixed_product_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def server_main(argv: list[str] | None = None) -> None:
        captured.extend(argv or [])

    monkeypatch.setattr(agent_memory, "server_main", server_main)

    agent_memory.main(
        [
            "--host",
            "127.0.0.2",
            "--port",
            "7444",
            "--mcp-path",
            "/memory",
            "--resolve-budget-profile",
            "MCP_RESEARCH_V01",
        ]
    )

    assert captured == [
        "--transport",
        "streamable-http",
        "--host",
        "127.0.0.2",
        "--port",
        "7444",
        "--mcp-path",
        "/memory",
        "--profile",
        "agent-memory",
        "--max-retries",
        "0",
        "--resolve-budget-profile",
        "MCP_RESEARCH_V01",
    ]


@pytest.mark.parametrize(
    "forbidden",
    [
        ["--transport", "stdio"],
        ["--profile", "reader-lite"],
        ["--max-retries", "2"],
    ],
)
def test_agent_memory_entrypoint_rejects_policy_overrides(
    forbidden: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        agent_memory.main(forbidden)

    assert exc_info.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
