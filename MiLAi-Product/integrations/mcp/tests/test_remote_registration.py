from __future__ import annotations

import asyncio
import json
import secrets
import stat
from pathlib import Path

import pytest

from milai_mcp.http_transport import HttpPrincipalBinding
from milai_mcp.remote_registration import (
    RemoteRegistrationTokenVerifier,
    RemoteUserRegistry,
    main,
)

_STATIC_TOKEN = secrets.token_urlsafe(32)


def _binding() -> HttpPrincipalBinding:
    return HttpPrincipalBinding.create(
        bearer_token=_STATIC_TOKEN,
        principal_id="codex-public-milai",
        issuer_url="http://127.0.0.1:7968",
        resource_url="http://127.0.0.1:7968/mcp",
        scope={"project_ids": ["milai"]},
        access_profile="codex-full",
    )


def test_issue_first_use_activation_and_revoke_are_private_and_audited(
    tmp_path: Path,
) -> None:
    registry = RemoteUserRegistry(tmp_path / "users.json")
    token = registry.issue("user-a")

    assert token not in registry.path.read_text(encoding="utf-8")
    assert stat.S_IMODE(registry.path.stat().st_mode) == 0o600
    first = registry.authenticate(token)
    second = registry.authenticate(token)

    assert first is not None and first.newly_activated is True
    assert second is not None and second.newly_activated is False
    assert first.principal_id == second.principal_id
    assert registry.list_users()[0]["status"] == "ACTIVE"
    assert "token_sha256" not in registry.list_users()[0]
    events = [
        json.loads(line)["event"]
        for line in registry.audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events == ["CREDENTIAL_ISSUED", "USER_REGISTERED"]
    assert stat.S_IMODE(registry.audit_path.stat().st_mode) == 0o600

    registry.revoke("user-a")
    assert registry.authenticate(token) is None
    assert registry.list_users()[0]["status"] == "REVOKED"


def test_issue_is_unique_and_replacement_revokes_previous_token(tmp_path: Path) -> None:
    registry = RemoteUserRegistry(tmp_path / "users.json")
    first = registry.issue("user-a")
    with pytest.raises(ValueError, match="already has a live credential"):
        registry.issue("user-a")

    second = registry.issue("user-a", replace=True)

    assert first != second
    assert registry.authenticate(first) is None
    assert registry.authenticate(second) is not None


def test_registration_verifier_maps_bearer_to_server_owned_principal(
    tmp_path: Path,
) -> None:
    registry = RemoteUserRegistry(tmp_path / "users.json")
    token = registry.issue("user-a")
    verifier = RemoteRegistrationTokenVerifier(_binding(), registry)
    result = asyncio.run(verifier.verify_token(token))

    assert result is not None
    assert result.subject.startswith("codex-remote-")
    assert result.claims["milai_agent_id"] == "user-a"
    assert asyncio.run(verifier.verify_token("wrong-token")) is None


def test_issue_cli_emits_only_generic_remote_registration_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry_path = tmp_path / "users.json"
    main(
        [
            "--registry-file",
            str(registry_path),
            "issue",
            "--agent-id",
            "user-a",
            "--url",
            "http://36.140.33.19:7968/mcp",
        ]
    )
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert set(output) == {"mcpServers"}
    assert output["mcpServers"]["milai"]["type"] == "http"
    assert output["mcpServers"]["milai"]["url"] == (
        "http://36.140.33.19:7968/mcp"
    )
    assert set(output["mcpServers"]["milai"]["headers"]) == {"Authorization"}
    assert output["mcpServers"]["milai"]["headers"]["Authorization"].startswith(
        "Bearer "
    )
    assert captured.err == ""


def test_issue_cli_requires_deployment_url_when_environment_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MILAI_MCP_HTTP_PUBLIC_BASE_URL", raising=False)
    with pytest.raises(SystemExit):
        main(
            [
                "--registry-file",
                str(tmp_path / "users.json"),
                "issue",
                "--agent-id",
                "user-a",
            ]
        )


@pytest.mark.parametrize(
    "agent_id",
    ["", "contains space", "../escape", "用户A", "x" * 129],
)
def test_invalid_agent_ids_fail_closed(tmp_path: Path, agent_id: str) -> None:
    with pytest.raises(ValueError, match="agent id"):
        RemoteUserRegistry(tmp_path / "users.json").issue(agent_id)
