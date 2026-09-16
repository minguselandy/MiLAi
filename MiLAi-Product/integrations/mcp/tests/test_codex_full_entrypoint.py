# ruff: noqa: S104
from __future__ import annotations

from pathlib import Path

import pytest

from milai_mcp import codex_full, server
from milai_mcp.http_transport import validate_public_base_url

# The wildcard address below is test data for the explicit public-listener guard.


def test_codex_full_entrypoint_freezes_transport_profile_and_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def server_main(argv: list[str] | None = None) -> None:
        captured.extend(argv or [])

    monkeypatch.setattr(codex_full, "server_main", server_main)
    codex_full.main(["--host", "127.0.0.2", "--port", "7444", "--mcp-path", "/memory"])

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
        "codex-full",
        "--max-retries",
        "0",
        "--resolve-budget-profile",
        "MCP_INTERACTIVE_STANDARD_V01",
    ]
    captured.clear()
    codex_full.main(["--catalog", "ordinary-memory-v1"])
    assert captured[-2:] == ["--catalog", "ordinary-memory-v1"]


def test_codex_full_entrypoint_forwards_explicit_non_loopback_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def server_main(argv: list[str] | None = None) -> None:
        captured.extend(argv or [])

    monkeypatch.setattr(codex_full, "server_main", server_main)
    codex_full.main(
        ["--host", "0.0.0.0", "--port", "7968", "--allow-non-loopback"]
    )

    assert captured[-1] == "--allow-non-loopback"
    assert captured[captured.index("--host") + 1] == "0.0.0.0"
    assert captured[captured.index("--port") + 1] == "7968"


def test_server_rejects_non_loopback_without_explicit_opt_in() -> None:
    with pytest.raises(SystemExit, match="requires --allow-non-loopback"):
        server.main(
            [
                "--transport",
                "streamable-http",
                "--profile",
                "codex-full",
                "--host",
                "0.0.0.0",
            ]
        )


def test_server_requires_public_identity_for_non_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MILAI_MCP_HTTP_PUBLIC_BASE_URL", raising=False)
    with pytest.raises(SystemExit, match="requires MILAI_MCP_HTTP_PUBLIC_BASE_URL"):
        server.main(
            [
                "--transport",
                "streamable-http",
                "--profile",
                "codex-full",
                "--host",
                "0.0.0.0",
                "--allow-non-loopback",
            ]
        )


def test_server_rejects_public_http_oauth_before_creating_edge_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_database = tmp_path / "edge" / "oauth.sqlite3"
    monkeypatch.setenv("MILAI_OAUTH_DB", str(oauth_database))
    monkeypatch.setenv(
        "MILAI_MCP_HTTP_PUBLIC_BASE_URL", "http://36.140.33.19:7968"
    )

    with pytest.raises(SystemExit, match="OAuth requires an HTTPS public base URL"):
        server.main(
            [
                "--transport",
                "streamable-http",
                "--profile",
                "codex-full",
                "--host",
                "127.0.0.1",
            ]
        )

    assert not oauth_database.exists()
    assert not oauth_database.parent.exists()


def test_oauth_origin_accepts_loopback_http_and_public_ip_https() -> None:
    assert (
        validate_public_base_url("http://127.0.0.1:7337", oauth_enabled=True)
        == "http://127.0.0.1:7337"
    )
    assert (
        validate_public_base_url("https://36.140.33.19", oauth_enabled=True)
        == "https://36.140.33.19"
    )
    assert (
        validate_public_base_url("https://EXAMPLE.com:443/", oauth_enabled=True)
        == "https://example.com"
    )


@pytest.mark.parametrize(
    "public_base_url",
    [
        "https://user@example.com",
        "https://example.com/oauth",
        "https://example.com?issuer=other",
        "https://example.com/#fragment",
    ],
)
def test_public_base_url_rejects_values_that_are_not_origins(
    public_base_url: str,
) -> None:
    with pytest.raises(ValueError, match="public base URL"):
        validate_public_base_url(public_base_url, oauth_enabled=True)


@pytest.mark.parametrize(
    "forbidden",
    [["--transport", "stdio"], ["--profile", "agent-memory"], ["--max-retries", "2"]],
)
def test_codex_full_entrypoint_rejects_policy_overrides(
    forbidden: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        codex_full.main(forbidden)
    assert exc_info.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
