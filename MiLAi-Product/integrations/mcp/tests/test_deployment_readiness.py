from __future__ import annotations

import json
from typing import Any
from urllib.request import Request

import pytest

from milai_mcp import deployment_readiness
from milai_mcp.deployment_readiness import HttpObservation, ReadinessError

_ORIGIN = "https://36.140.33.19"
_MCP_URL = _ORIGIN + "/mcp"
_PROTECTED_URL = _ORIGIN + "/.well-known/oauth-protected-resource/mcp"


@pytest.mark.parametrize("failure", [None, "inactive", "wrong-scopes", "redirected-endpoint"])
def test_external_as_discovered_independently_and_registration_required(
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    from urllib.parse import urlencode

    issuer = "https://auth.example.test"
    responses = _successful_responses()
    responses[("GET", _PROTECTED_URL)] = _json_observation(
        {
            "resource": _MCP_URL,
            "authorization_servers": [issuer],
            "scopes_supported": ["milai.memory.read", "milai.state.read"],
        }
    )
    metadata = json.loads(
        responses.pop(("GET", _ORIGIN + "/.well-known/oauth-authorization-server")).body
    )
    metadata["issuer"] = issuer
    for field, path in [
        ("registration_endpoint", "register"),
        ("authorization_endpoint", "authorize"),
        ("token_endpoint", "token"),
        ("revocation_endpoint", "revoke"),
    ]:
        metadata[field] = issuer + "/oauth/" + path
    metadata["jwks_uri"] = issuer + "/jwks"
    if failure == "redirected-endpoint":
        metadata["token_endpoint"] = "https://attacker.test/token"  # noqa: S105
    responses[("GET", issuer + "/.well-known/oauth-authorization-server")] = _json_observation(
        metadata
    )
    responses[("GET", issuer + "/jwks")] = _json_observation({"keys": [{"kid": "test"}]})
    responses[("GET", issuer + "/resources/status?" + urlencode({"resource": _MCP_URL}))] = (
        _json_observation(
            {
                "resource": _MCP_URL,
                "status": "active",
                "active": failure != "inactive",
                "scopes": ["milai.state.read", "milai.memory.read"]
                if failure != "wrong-scopes"
                else [],
            }
        )
    )
    seen: list[tuple[str, str]] = []

    def fetch(request: Request, *, timeout_seconds: float) -> HttpObservation:
        key = (request.get_method(), request.full_url)
        seen.append(key)
        assert not request.has_header("Authorization")
        return responses[key]

    monkeypatch.setattr(deployment_readiness, "_fetch", fetch)
    if failure:
        with pytest.raises(ReadinessError):
            deployment_readiness.probe_oauth_https_edge(_ORIGIN, external_issuer=issuer)
    else:
        result = deployment_readiness.probe_oauth_https_edge(_ORIGIN, external_issuer=issuer)
        assert result["authorization_issuer"] == issuer
        assert result["mutating_requests"] == 0
        assert result["public_oauth_login_verified"] is False
    assert all(method == "GET" or url == _MCP_URL for method, url in seen)


def _json_observation(value: dict[str, Any], *, status: int = 200) -> HttpObservation:
    return HttpObservation(
        status=status,
        headers={"content-type": "application/json"},
        body=json.dumps(value).encode(),
    )


def _successful_responses(
    origin: str = _ORIGIN,
) -> dict[tuple[str, str], HttpObservation]:
    mcp_url = origin + "/mcp"
    protected_url = origin + "/.well-known/oauth-protected-resource/mcp"
    return {
        ("GET", origin + "/healthz"): _json_observation({"status": "ok"}),
        ("GET", origin + "/readyz"): _json_observation({"status": "ready"}),
        ("GET", protected_url): _json_observation(
            {
                "resource": mcp_url,
                "authorization_servers": [origin + "/"],
                "scopes_supported": ["memory:read"],
            }
        ),
        (
            "GET",
            origin + "/.well-known/oauth-authorization-server",
        ): _json_observation(
            {
                "issuer": origin + "/",
                "registration_endpoint": origin + "/register",
                "authorization_endpoint": origin + "/authorize",
                "token_endpoint": origin + "/token",
                "revocation_endpoint": origin + "/revoke",
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": [
                    "none",
                    "client_secret_post",
                    "client_secret_basic",
                ],
                "revocation_endpoint_auth_methods_supported": [
                    "none",
                    "client_secret_post",
                    "client_secret_basic",
                ],
            }
        ),
        ("POST", mcp_url): HttpObservation(
            status=401,
            headers={
                "www-authenticate": (
                    'Bearer realm="milai", resource_metadata="' + protected_url + '"'
                )
            },
            body=b"",
        ),
    }


@pytest.mark.parametrize("origin", [_ORIGIN, "https://milai.example:7960"])
def test_probe_verifies_https_discovery_and_challenge_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
) -> None:
    responses = _successful_responses(origin)
    mcp_url = origin + "/mcp"
    protected_url = origin + "/.well-known/oauth-protected-resource/mcp"
    requests: list[tuple[str, str]] = []

    def fake_fetch(request: Request, *, timeout_seconds: float) -> HttpObservation:
        assert timeout_seconds == 4
        key = (request.get_method(), request.full_url)
        requests.append(key)
        return responses[key]

    monkeypatch.setattr(deployment_readiness, "_fetch", fake_fetch)

    result = deployment_readiness.probe_oauth_https_edge(origin, timeout_seconds=4)

    assert result == {
        "schema_version": "milai-oauth-edge-readiness-v1",
        "status": "READY",
        "public_base_url": origin,
        "mcp_url": mcp_url,
        "checks": [
            "trusted_https_healthz",
            "runtime_readyz",
            "protected_resource_metadata",
            "authorization_server_metadata",
            "unauthenticated_mcp_oauth_challenge",
        ],
        "mutating_requests": 0,
    }
    assert requests == [
        ("GET", origin + "/healthz"),
        ("GET", origin + "/readyz"),
        ("GET", protected_url),
        ("GET", origin + "/.well-known/oauth-authorization-server"),
        ("POST", mcp_url),
    ]


def test_probe_rejects_metadata_that_drops_the_https_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = "https://milai.example:7960"
    responses = _successful_responses(origin)
    metadata_url = origin + "/.well-known/oauth-authorization-server"
    metadata = json.loads(responses[("GET", metadata_url)].body)
    metadata["token_endpoint"] = "https://milai.example/token"  # noqa: S105 - endpoint URL
    responses[("GET", metadata_url)] = _json_observation(metadata)

    def fake_fetch(request: Request, *, timeout_seconds: float) -> HttpObservation:
        return responses[(request.get_method(), request.full_url)]

    monkeypatch.setattr(deployment_readiness, "_fetch", fake_fetch)

    with pytest.raises(ReadinessError, match="token_endpoint"):
        deployment_readiness.probe_oauth_https_edge(origin)


def test_probe_rejects_http_before_network_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_fetch(request: Request, *, timeout_seconds: float) -> HttpObservation:
        raise AssertionError((request, timeout_seconds))

    monkeypatch.setattr(deployment_readiness, "_fetch", unexpected_fetch)

    with pytest.raises(ValueError, match="OAuth requires an HTTPS public base URL"):
        deployment_readiness.probe_oauth_https_edge("http://127.0.0.1:7337")


def test_probe_rejects_metadata_that_downgrades_the_resource_to_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = _successful_responses()
    responses[("GET", _PROTECTED_URL)] = _json_observation(
        {
            "resource": "http://36.140.33.19/mcp",
            "authorization_servers": [_ORIGIN],
        }
    )

    def fake_fetch(request: Request, *, timeout_seconds: float) -> HttpObservation:
        return responses[(request.get_method(), request.full_url)]

    monkeypatch.setattr(deployment_readiness, "_fetch", fake_fetch)

    with pytest.raises(ReadinessError, match="protected resource"):
        deployment_readiness.probe_oauth_https_edge(_ORIGIN)


def test_probe_rejects_false_positive_ready_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = _successful_responses()
    responses[("GET", _ORIGIN + "/readyz")] = _json_observation(
        {"status": "not_ready", "reason": "RUNTIME_UNAVAILABLE"}
    )

    def fake_fetch(request: Request, *, timeout_seconds: float) -> HttpObservation:
        return responses[(request.get_method(), request.full_url)]

    monkeypatch.setattr(deployment_readiness, "_fetch", fake_fetch)

    with pytest.raises(ReadinessError, match="readyz did not report status=ready"):
        deployment_readiness.probe_oauth_https_edge(_ORIGIN)


def test_probe_rejects_metadata_that_omits_public_client_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = _successful_responses()
    metadata_url = _ORIGIN + "/.well-known/oauth-authorization-server"
    metadata = json.loads(responses[("GET", metadata_url)].body)
    metadata["token_endpoint_auth_methods_supported"] = ["client_secret_post"]
    responses[("GET", metadata_url)] = _json_observation(metadata)

    def fake_fetch(request: Request, *, timeout_seconds: float) -> HttpObservation:
        return responses[(request.get_method(), request.full_url)]

    monkeypatch.setattr(deployment_readiness, "_fetch", fake_fetch)

    with pytest.raises(
        ReadinessError,
        match="token_endpoint_auth_methods_supported must advertise",
    ):
        deployment_readiness.probe_oauth_https_edge(_ORIGIN)
