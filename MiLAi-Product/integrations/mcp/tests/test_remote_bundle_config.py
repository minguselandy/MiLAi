from __future__ import annotations

import json
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "codex-mcp"
    / "remote-client"
    / "configure_clients.py"
)
_NAMESPACE = runpy.run_path(str(_SCRIPT))
_configure_generic = cast(Callable[..., None], _NAMESPACE["configure_generic"])
_configure_codex = cast(Callable[..., None], _NAMESPACE["configure_codex"])


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_generic_config_preserves_unrelated_servers_and_root_keys(tmp_path: Path) -> None:
    path = tmp_path / "mcpServers.json"
    path.write_text(
        json.dumps(
            {
                "clientSetting": True,
                "mcpServers": {
                    "other": {
                        "type": "http",
                        "url": "https://other.example/mcp",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    _configure_generic(
        path,
        name="milai",
        url="https://memory.example/mcp",
        token="a" * 32,
        replace=False,
    )

    configured = _read(path)
    assert configured["clientSetting"] is True
    assert set(configured["mcpServers"]) == {"other", "milai"}
    assert configured["mcpServers"]["other"]["url"] == "https://other.example/mcp"


def test_generic_config_requires_replace_for_same_name_different_url(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mcpServers.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "milai": {
                        "type": "http",
                        "url": "https://old.example/mcp",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="use --replace"):
        _configure_generic(
            path,
            name="milai",
            url="https://new.example/mcp",
            token="b" * 32,
            replace=False,
        )

    _configure_generic(
        path,
        name="milai",
        url="https://new.example/mcp",
        token="b" * 32,
        replace=True,
    )
    assert _read(path)["mcpServers"]["milai"]["url"] == "https://new.example/mcp"


def test_codex_config_uses_token_environment_name_not_inline_secret(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    inline_header_value = "do-not-retain-this-sensitive-value"
    path.write_text(
        "[mcp_servers.milai]\n"
        'url = "https://memory.example/mcp"\n'
        f'http_headers = {{ Authorization = "Bearer {inline_header_value}" }}\n'
        "enabled = true\n",
        encoding="utf-8",
    )

    _configure_codex(
        path,
        name="milai",
        bearer_token_env_var="MILAI_CODEX_TOKEN",  # noqa: S106 - variable name, not a secret
    )

    text = path.read_text(encoding="utf-8")
    assert 'bearer_token_env_var = "MILAI_CODEX_TOKEN"' in text
    assert "http_headers" not in text
    assert inline_header_value not in text
