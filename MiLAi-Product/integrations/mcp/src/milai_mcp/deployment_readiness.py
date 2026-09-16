"""Credential-free verification of a public HTTPS OAuth MCP edge."""

from __future__ import annotations

import argparse
import json
import re
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from milai_mcp.auth_policy import ALL_SCOPES
from milai_mcp.http_transport import validate_public_base_url

_MAX_RESPONSE_BYTES = 262_144


class ReadinessError(RuntimeError):
    """A public edge failed a non-mutating deployment gate."""


@dataclass(frozen=True, slots=True)
class HttpObservation:
    status: int
    headers: dict[str, str]
    body: bytes


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


def _https_request(
    url: str,
    *,
    data: bytes | None = None,
    method: str | None = None,
    headers: dict[str, str] | None = None,
) -> Request:
    if not url.startswith("https://"):
        raise ValueError("readiness requests must use HTTPS")
    return Request(  # noqa: S310 - scheme is constrained immediately above
        url,
        data=data,
        method=method,
        headers=headers or {},
    )


def _fetch(request: Request, *, timeout_seconds: float) -> HttpObservation:
    """Fetch with the platform trust store and no insecure TLS escape hatch."""

    opener = build_opener(
        HTTPSHandler(context=ssl.create_default_context()),
        _RejectRedirects(),
    )
    try:
        response = opener.open(
            request,
            timeout=timeout_seconds,
        )
    except HTTPError as exc:
        response = exc
    except (OSError, URLError) as exc:
        raise ReadinessError(f"request failed for {request.full_url}: {exc}") from exc
    try:
        body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ReadinessError(f"response is too large for {request.full_url}")
        return HttpObservation(
            status=int(response.getcode()),
            headers={key.casefold(): value for key, value in response.headers.items()},
            body=body,
        )
    finally:
        response.close()


def _expect_status(
    request: Request,
    expected_status: int,
    *,
    timeout_seconds: float,
) -> HttpObservation:
    observed = _fetch(request, timeout_seconds=timeout_seconds)
    if observed.status != expected_status:
        raise ReadinessError(
            f"{request.get_method()} {request.full_url} returned HTTP "
            f"{observed.status}; expected {expected_status}"
        )
    return observed


def _json_object(observed: HttpObservation, *, url: str) -> dict[str, Any]:
    try:
        value = json.loads(observed.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"{url} did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise ReadinessError(f"{url} did not return a JSON object")
    return value


def _require_exact(value: object, expected: str, *, field: str) -> None:
    if value != expected:
        raise ReadinessError(f"{field} does not match its expected HTTPS URL")


def _require_origin(value: object, expected: str, *, field: str) -> None:
    if value not in {expected, expected + "/"}:
        raise ReadinessError(f"{field} does not match the configured HTTPS origin")


def probe_oauth_https_edge(
    public_base_url: str,
    *,
    mcp_path: str = "/mcp",
    timeout_seconds: float = 10.0,
    external_issuer: str | None = None,
) -> dict[str, Any]:
    """Verify TLS, health, discovery and the unauthenticated OAuth challenge.

    The probe deliberately does not register a client, create an authorization request,
    issue a token, or call an authenticated MCP tool.
    """

    origin = validate_public_base_url(
        public_base_url,
        oauth_enabled=True,
        allow_oauth_loopback_http=False,
    )
    if not mcp_path.startswith("/") or "?" in mcp_path or "#" in mcp_path:
        raise ValueError("MCP path must be absolute and cannot contain query or fragment")
    if not 0 < timeout_seconds <= 60:
        raise ValueError("timeout must be greater than 0 and no more than 60 seconds")

    health_url = origin + "/healthz"
    ready_url = origin + "/readyz"
    resource_url = origin + mcp_path
    protected_metadata_url = (
        origin + "/.well-known/oauth-protected-resource" + mcp_path
    )
    issuer = origin
    if external_issuer is not None:
        issuer = validate_public_base_url(
            external_issuer, oauth_enabled=True, allow_oauth_loopback_http=False,
        )
        if issuer != external_issuer:
            raise ValueError("external issuer must be an exact canonical HTTPS origin")
    authorization_metadata_url = issuer + "/.well-known/oauth-authorization-server"
    checks: list[str] = []

    health = _expect_status(
        _https_request(health_url, headers={"Accept": "application/json"}),
        200,
        timeout_seconds=timeout_seconds,
    )
    health_payload = _json_object(health, url=health_url)
    if health_payload.get("status") != "ok":
        raise ReadinessError("healthz did not report status=ok")
    checks.append("trusted_https_healthz")

    ready = _expect_status(
        _https_request(ready_url, headers={"Accept": "application/json"}),
        200,
        timeout_seconds=timeout_seconds,
    )
    ready_payload = _json_object(ready, url=ready_url)
    if ready_payload.get("status") != "ready":
        raise ReadinessError("readyz did not report status=ready")
    checks.append("runtime_readyz")

    protected = _expect_status(
        _https_request(protected_metadata_url, headers={"Accept": "application/json"}),
        200,
        timeout_seconds=timeout_seconds,
    )
    protected_payload = _json_object(protected, url=protected_metadata_url)
    _require_exact(
        protected_payload.get("resource"), resource_url, field="protected resource"
    )
    authorization_servers = protected_payload.get("authorization_servers")
    if not isinstance(authorization_servers, list) or len(authorization_servers) != 1:
        raise ReadinessError("protected resource must advertise exactly one authorization server")
    _require_origin(
        authorization_servers[0], issuer, field="protected authorization server"
    )
    checks.append("protected_resource_metadata")

    metadata = _expect_status(
        _https_request(
            authorization_metadata_url, headers={"Accept": "application/json"}
        ),
        200,
        timeout_seconds=timeout_seconds,
    )
    metadata_payload = _json_object(metadata, url=authorization_metadata_url)
    _require_origin(metadata_payload.get("issuer"), issuer, field="authorization issuer")
    for field, path in {
        "registration_endpoint": "/register",
        "authorization_endpoint": "/authorize",
        "token_endpoint": "/token",
        "revocation_endpoint": "/revoke",
    }.items():
        if external_issuer is None:
            _require_exact(metadata_payload.get(field), origin + path, field=field)
        else:
            value = metadata_payload.get(field)
            if not isinstance(value, str):
                raise ReadinessError(f"missing external {field}")
            parsed = urlsplit(value)
            if (f"{parsed.scheme}://{parsed.netloc}" != issuer or not parsed.path
                    or parsed.query or parsed.fragment):
                raise ReadinessError(f"untrusted external {field}")
    if metadata_payload.get("code_challenge_methods_supported") != ["S256"]:
        raise ReadinessError("authorization metadata must require S256 PKCE")
    for field in (
        "token_endpoint_auth_methods_supported",
        "revocation_endpoint_auth_methods_supported",
    ):
        methods = metadata_payload.get(field)
        if not isinstance(methods, list) or "none" not in methods:
            raise ReadinessError(f"{field} must advertise public-client method none")
    checks.append("authorization_server_metadata")

    initialize_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "readiness",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "milai-oauth-readiness", "version": "0.1"},
            },
        },
        separators=(",", ":"),
    ).encode()
    challenge = _expect_status(
        _https_request(
            resource_url,
            data=initialize_body,
            method="POST",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        ),
        401,
        timeout_seconds=timeout_seconds,
    )
    authenticate = challenge.headers.get("www-authenticate", "")
    match = re.search(r'(?:^|[,\s])resource_metadata="([^"]+)"', authenticate)
    if match is None or match.group(1) != protected_metadata_url:
        raise ReadinessError(
            "unauthenticated MCP challenge does not advertise the exact HTTPS "
            "protected-resource metadata URL"
        )
    checks.append("unauthenticated_mcp_oauth_challenge")

    if external_issuer is not None:
        scopes = protected_payload.get("scopes_supported")
        if (not isinstance(scopes, list) or not scopes
                or not all(isinstance(scope, str) for scope in scopes)
                or not set(scopes) <= ALL_SCOPES):
            raise ReadinessError("protected metadata must advertise implemented MCP scopes")
        jwks_uri = metadata_payload.get("jwks_uri")
        if not isinstance(jwks_uri, str):
            raise ReadinessError("external discovery lacks JWKS")
        parsed = urlsplit(jwks_uri)
        if (f"{parsed.scheme}://{parsed.netloc}" != issuer
                or parsed.query or parsed.fragment or not parsed.path):
            raise ReadinessError("external discovery has untrusted JWKS")
        jwks = _json_object(_expect_status(
            _https_request(jwks_uri), 200, timeout_seconds=timeout_seconds,
        ), url=jwks_uri)
        if not isinstance(jwks.get("keys"), list) or not jwks["keys"]:
            raise ReadinessError("external JWKS has no keys")
        checks.append("external_jwks_reachable")
        status_url = issuer + "/resources/status?" + urlencode({"resource": resource_url})
        status = _json_object(_expect_status(
            _https_request(status_url), 200, timeout_seconds=timeout_seconds,
        ), url=status_url)
        if (status.get("resource") != resource_url or status.get("active") is not True
                or status.get("status") != "active" or not isinstance(status.get("scopes"), list)
                or not all(isinstance(scope, str) for scope in status["scopes"])
                or set(status["scopes"]) != set(scopes)):
            raise ReadinessError("exact resource registration is not active with matching scopes")
        checks.append("external_resource_registration_active")

    return {
        "schema_version": "milai-oauth-edge-readiness-v1",
        "status": "READY",
        "public_base_url": origin,
        "mcp_url": resource_url,
        "checks": checks,
        "mutating_requests": 0,
        **({"authorization_issuer": issuer, "public_oauth_login_verified": False}
           if external_issuer is not None else {}),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run credential-free trusted-HTTPS and OAuth discovery checks against "
            "a deployed MiLAi MCP edge"
        )
    )
    parser.add_argument("--base-url", required=True, help="public HTTPS origin")
    parser.add_argument("--mcp-path", default="/mcp")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--external-issuer", help="trusted external HTTPS authorization issuer")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        result = probe_oauth_https_edge(
            args.base_url,
            mcp_path=args.mcp_path,
            timeout_seconds=args.timeout,
            external_issuer=args.external_issuer,
        )
    except (ReadinessError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "milai-oauth-edge-readiness-v1",
                    "status": "BLOCKED",
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        raise SystemExit(1) from exc
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
