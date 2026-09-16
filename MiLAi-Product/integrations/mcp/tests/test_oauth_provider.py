from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

from milai_mcp.http_transport import HttpPrincipalBinding, validate_public_base_url
from milai_mcp.oauth_provider import MilaiOAuthProvider, OAuthStore
from milai_mcp.server import build_server

_ISSUER = "http://127.0.0.1:8765"
_RESOURCE = _ISSUER + "/mcp"
_STATIC_TOKEN = secrets.token_urlsafe(32)


def _binding(issuer: str = _ISSUER) -> HttpPrincipalBinding:
    return HttpPrincipalBinding.create(
        bearer_token=_STATIC_TOKEN,
        principal_id="oauth-breakglass",
        issuer_url=issuer,
        resource_url=issuer + "/mcp",
        scope={"project_ids": ["milai"]},
        access_profile="agent-memory",
    )


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


def _register(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/register",
        json={
            "client_name": "Codex OAuth test",
            "redirect_uris": ["http://127.0.0.1:34567/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": "memory:read",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def _authorize(
    client: TestClient,
    *,
    client_id: str,
    challenge: str,
    issuer: str = _ISSUER,
) -> str:
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "http://127.0.0.1:34567/callback",
            "scope": "memory:read",
            "state": "state-one",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": issuer + "/mcp",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(issuer + "/oauth/consent?")
    return parse_qs(urlsplit(location).query)["request_id"][0]


def _approve(
    client: TestClient,
    *,
    request_id: str,
    enrollment_code: str,
) -> str:
    consent = client.get("/oauth/consent", params={"request_id": request_id})
    assert consent.status_code == 200
    assert "Codex OAuth test" in consent.text
    response = client.post(
        "/oauth/consent",
        data={
            "request_id": request_id,
            "enrollment_code": enrollment_code,
            "decision": "APPROVE",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    callback = urlsplit(response.headers["location"])
    assert callback.scheme == "http"
    assert callback.hostname == "127.0.0.1"
    assert callback.port == 34567
    values = parse_qs(callback.query)
    assert values["state"] == ["state-one"]
    return values["code"][0]


def _token(
    client: TestClient,
    *,
    client_id: str,
    code: str,
    verifier: str,
    resource: str = _RESOURCE,
) -> dict[str, object]:
    response = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": "http://127.0.0.1:34567/callback",
            "resource": resource,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize("issuer", [_ISSUER, "https://milai.example:7960"])
def test_discovery_dcr_pkce_consent_token_and_mcp_initialize(
    tmp_path: Path, issuer: str
) -> None:
    assert validate_public_base_url(issuer, oauth_enabled=True) == issuer
    resource = issuer + "/mcp"
    store = OAuthStore(tmp_path / "oauth.sqlite3")
    enrollment_code = store.issue_enrollment("user-a")
    binding = _binding(issuer)
    provider = MilaiOAuthProvider(store, binding)
    server = build_server(
        "agent-memory",
        client=cast(Any, object()),
        default_scope={"project_ids": ["milai"]},
        http_principal_binding=binding,
        http_oauth_provider=provider,
    )
    app = server.streamable_http_app(host="127.0.0.1")

    with TestClient(app, base_url=issuer) as client:
        protected = client.get("/.well-known/oauth-protected-resource/mcp")
        assert protected.status_code == 200
        assert protected.json()["resource"] == resource
        authorization_server = protected.json()["authorization_servers"][0]
        assert authorization_server.rstrip("/") == issuer

        metadata = client.get("/.well-known/oauth-authorization-server")
        assert metadata.status_code == 200
        assert metadata.json()["issuer"] == authorization_server
        assert metadata.json()["registration_endpoint"] == issuer + "/register"
        assert metadata.json()["authorization_endpoint"] == issuer + "/authorize"
        assert metadata.json()["token_endpoint"] == issuer + "/token"
        assert metadata.json()["revocation_endpoint"] == issuer + "/revoke"
        assert metadata.json()["code_challenge_methods_supported"] == ["S256"]
        assert "none" in metadata.json()["token_endpoint_auth_methods_supported"]
        assert "none" in metadata.json()[
            "revocation_endpoint_auth_methods_supported"
        ]

        unauthenticated = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "oauth-test", "version": "1"},
                },
            },
        )
        assert unauthenticated.status_code == 401
        challenge_header = unauthenticated.headers["www-authenticate"]
        assert (
            'resource_metadata="' + issuer + '/.well-known/oauth-protected-resource/mcp"'
        ) in challenge_header

        registered = _register(client)
        client_id = str(registered["client_id"])
        verifier, challenge = _pkce()
        request_id = _authorize(
            client, client_id=client_id, challenge=challenge, issuer=issuer
        )

        invalid = client.post(
            "/oauth/consent",
            data={
                "request_id": request_id,
                "enrollment_code": "not-the-code",
                "decision": "APPROVE",
            },
        )
        assert invalid.status_code == 400

        code = _approve(
            client,
            request_id=request_id,
            enrollment_code=enrollment_code,
        )
        issued = _token(
            client,
            client_id=client_id,
            code=code,
            verifier=verifier,
            resource=resource,
        )
        access_token = str(issued["access_token"])
        refresh_token = str(issued["refresh_token"])
        assert issued["token_type"] == "Bearer"  # noqa: S105 - OAuth token type
        assert issued["scope"] == "memory:read"

        initialized = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "oauth-test", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200, initialized.text
        assert initialized.headers.get("mcp-session-id")

        rotated_response = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "scope": "memory:read",
                "resource": resource,
            },
        )
        assert rotated_response.status_code == 200, rotated_response.text
        rotated = rotated_response.json()
        assert rotated["access_token"] != access_token
        assert rotated["refresh_token"] != refresh_token
        assert provider.store.list_users()[0]["status"] == "ACTIVE"

        replay = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "resource": resource,
            },
        )
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"

        revoked = client.post(
            "/revoke",
            data={
                "client_id": client_id,
                "client_secret": "",
                "token": rotated["refresh_token"],
                "token_type_hint": "refresh_token",
            },
        )
        assert revoked.status_code == 200, revoked.text
        assert provider.store.list_users()[0]["status"] == "ACTIVE"

        rejected = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {rotated['access_token']}",
            },
            json={"jsonrpc": "2.0", "id": 3, "method": "ping"},
        )
        assert rejected.status_code == 401

    database_bytes = store.path.read_bytes()
    assert enrollment_code.encode() not in database_bytes
    assert access_token.encode() not in database_bytes
    assert refresh_token.encode() not in database_bytes
    connection = sqlite3.connect(store.path)
    try:
        events = [row[0] for row in connection.execute("SELECT event FROM oauth_audit")]
    finally:
        connection.close()
    assert events == [
        "OAUTH_ENROLLMENT_ISSUED",
        "OAUTH_CLIENT_REGISTERED",
        "OAUTH_AUTHORIZATION_STARTED",
        "OAUTH_USER_REGISTERED",
        "OAUTH_AUTHORIZATION_APPROVED",
        "OAUTH_TOKEN_ISSUED",
        "OAUTH_TOKEN_ROTATED",
        "OAUTH_TOKEN_REVOKED",
    ]


@pytest.mark.parametrize(
    ("request_headers", "expected_status"),
    [
        ({}, 200),
        ({"Origin": "https://milai.example:7960"}, 200),
        ({"Host": "milai.example"}, 421),
        ({"Host": "milai.example:7966"}, 421),
        (
            {
                "Host": "attacker.example:7960",
                "X-Forwarded-Host": "milai.example:7960",
                "X-Forwarded-Proto": "https",
            },
            421,
        ),
        ({"Origin": "https://milai.example"}, 403),
        ({"Origin": "http://milai.example:7960"}, 403),
        ({"Origin": "https://attacker.example:7960"}, 403),
    ],
)
def test_oauth_transport_accepts_only_configured_public_host_and_origin(
    tmp_path: Path,
    request_headers: dict[str, str],
    expected_status: int,
) -> None:
    issuer = "https://milai.example:7960"
    binding = _binding(issuer)
    provider = MilaiOAuthProvider(OAuthStore(tmp_path / "oauth.sqlite3"), binding)
    server = build_server(
        "agent-memory",
        client=cast(Any, object()),
        default_scope={"project_ids": ["milai"]},
        http_principal_binding=binding,
        http_oauth_provider=provider,
    )
    app = server.streamable_http_app(
        host="127.0.0.1",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    with TestClient(app, base_url=issuer) as client:
        response = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {_STATIC_TOKEN}",
                **request_headers,
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "oauth-proxy-test", "version": "1"},
                },
            },
        )
        assert response.status_code == expected_status, response.text


def test_dcr_rejects_non_https_non_loopback_redirect(tmp_path: Path) -> None:
    store = OAuthStore(tmp_path / "oauth.sqlite3")
    provider = MilaiOAuthProvider(store, _binding())
    server = build_server(
        "agent-memory",
        client=cast(Any, object()),
        default_scope={"project_ids": ["milai"]},
        http_principal_binding=_binding(),
        http_oauth_provider=provider,
    )
    with TestClient(
        server.streamable_http_app(host="127.0.0.1"), base_url=_ISSUER
    ) as client:
        response = client.post(
            "/register",
            json={
                "client_name": "malicious client",
                "redirect_uris": ["http://example.com/callback"],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "memory:read",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_redirect_uri"


def test_authorization_requires_s256_pkce(tmp_path: Path) -> None:
    store = OAuthStore(tmp_path / "oauth.sqlite3")
    provider = MilaiOAuthProvider(store, _binding())
    server = build_server(
        "agent-memory",
        client=cast(Any, object()),
        default_scope={"project_ids": ["milai"]},
        http_principal_binding=_binding(),
        http_oauth_provider=provider,
    )
    with TestClient(
        server.streamable_http_app(host="127.0.0.1"), base_url=_ISSUER
    ) as client:
        registered = _register(client)
        response = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": str(registered["client_id"]),
                "redirect_uri": "http://127.0.0.1:34567/callback",
                "scope": "memory:read",
                "state": "state-without-pkce",
                "resource": _RESOURCE,
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        callback = urlsplit(response.headers["location"])
        assert callback.scheme == "http"
        assert callback.hostname == "127.0.0.1"
        assert callback.port == 34567
        values = parse_qs(callback.query)
        assert values["error"] == ["invalid_request"]
        assert values["state"] == ["state-without-pkce"]


def test_revoking_user_invalidates_all_live_oauth_tokens(tmp_path: Path) -> None:
    store = OAuthStore(tmp_path / "oauth.sqlite3")
    enrollment_code = store.issue_enrollment("user-to-revoke")
    provider = MilaiOAuthProvider(store, _binding())
    server = build_server(
        "agent-memory",
        client=cast(Any, object()),
        default_scope={"project_ids": ["milai"]},
        http_principal_binding=_binding(),
        http_oauth_provider=provider,
    )
    with TestClient(
        server.streamable_http_app(host="127.0.0.1"), base_url=_ISSUER
    ) as client:
        registered = _register(client)
        client_id = str(registered["client_id"])
        verifier, challenge = _pkce()
        request_id = _authorize(client, client_id=client_id, challenge=challenge)
        code = _approve(
            client,
            request_id=request_id,
            enrollment_code=enrollment_code,
        )
        issued = _token(
            client,
            client_id=client_id,
            code=code,
            verifier=verifier,
        )

        store.revoke_user("user-to-revoke")

        rejected = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {issued['access_token']}",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "revoked-test", "version": "1"},
                },
            },
        )
        assert rejected.status_code == 401

        refresh = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": issued["refresh_token"],
                "resource": _RESOURCE,
            },
        )
        assert refresh.status_code == 400
        assert refresh.json()["error"] == "invalid_grant"
        assert store.list_users()[0]["status"] == "REVOKED"


def test_revoking_user_invalidates_unexchanged_authorization_code(
    tmp_path: Path,
) -> None:
    store = OAuthStore(tmp_path / "oauth.sqlite3")
    enrollment_code = store.issue_enrollment("user-revoked-before-exchange")
    binding = _binding()
    provider = MilaiOAuthProvider(store, binding)
    server = build_server(
        "agent-memory",
        client=cast(Any, object()),
        default_scope={"project_ids": ["milai"]},
        http_principal_binding=binding,
        http_oauth_provider=provider,
    )
    with TestClient(
        server.streamable_http_app(host="127.0.0.1"), base_url=_ISSUER
    ) as client:
        registered = _register(client)
        client_id = str(registered["client_id"])
        verifier, challenge = _pkce()
        request_id = _authorize(client, client_id=client_id, challenge=challenge)
        code = _approve(
            client,
            request_id=request_id,
            enrollment_code=enrollment_code,
        )

        store.revoke_user("user-revoked-before-exchange")

        response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": "http://127.0.0.1:34567/callback",
                "resource": _RESOURCE,
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"


def test_token_request_requires_exact_mcp_resource(tmp_path: Path) -> None:
    store = OAuthStore(tmp_path / "oauth.sqlite3")
    enrollment_code = store.issue_enrollment("wrong-resource-user")
    binding = _binding()
    provider = MilaiOAuthProvider(store, binding)
    server = build_server(
        "agent-memory",
        client=cast(Any, object()),
        default_scope={"project_ids": ["milai"]},
        http_principal_binding=binding,
        http_oauth_provider=provider,
    )
    with TestClient(
        server.streamable_http_app(host="127.0.0.1"), base_url=_ISSUER
    ) as client:
        registered = _register(client)
        client_id = str(registered["client_id"])
        verifier, challenge = _pkce()
        request_id = _authorize(client, client_id=client_id, challenge=challenge)
        code = _approve(
            client,
            request_id=request_id,
            enrollment_code=enrollment_code,
        )

        response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": "http://127.0.0.1:34567/callback",
                "resource": "https://other.example/mcp",
            },
        )
        assert response.status_code == 400
        assert response.json() == {
            "error": "invalid_target",
            "error_description": "resource must exactly match the MiLAi MCP resource",
        }
