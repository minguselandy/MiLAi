from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from pydantic import AnyHttpUrl


def validate_public_base_url(
    value: str,
    *,
    oauth_enabled: bool = False,
    allow_oauth_loopback_http: bool = True,
) -> str:
    """Validate the configured external origin without trusting proxy headers."""

    if (
        not value
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("MCP public base URL must be a non-empty HTTP(S) origin")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("MCP public base URL must be an HTTP(S) origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("MCP public base URL cannot contain userinfo")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("MCP public base URL must not contain a path, query or fragment")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("MCP public base URL contains an invalid port") from exc
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("MCP public base URL must contain a host")
    loopback = hostname.casefold() == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            loopback = False
    if oauth_enabled and parsed.scheme != "https" and not (
        allow_oauth_loopback_http and loopback
    ):
        raise ValueError(
            "OAuth requires an HTTPS public base URL; HTTP is allowed only for "
            "loopback development"
        )
    # Use the same canonical origin representation as AuthSettings. This avoids
    # split issuer/resource identities for equivalent inputs such as an uppercase
    # host or an explicit default HTTPS port.
    return str(AnyHttpUrl(value)).rstrip("/")


@dataclass(frozen=True, slots=True)
class HttpPrincipalBinding:
    """Bind one HTTP credential to one server-owned principal and Memory scope."""

    bearer_token: str
    principal_id: str
    issuer_url: str
    resource_url: str
    scope_digest: str
    access_profile: Literal["agent-memory", "codex-full"]
    governance_mode: Literal["SEPARATED_AUTHORITY", "SINGLE_HOST_FULL_CONTROL"]
    scopes: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        bearer_token: str,
        principal_id: str,
        issuer_url: str,
        resource_url: str,
        scope: dict[str, Any],
        access_profile: Literal["agent-memory", "codex-full"] = "agent-memory",
    ) -> HttpPrincipalBinding:
        if len(bearer_token) < 32:
            raise ValueError("HTTP bearer token must contain at least 32 characters")
        if not principal_id.strip():
            raise ValueError("HTTP principal identity is required")
        if not scope:
            raise ValueError("HTTP principal must be bound to a non-empty Memory scope")
        AnyHttpUrl(issuer_url)
        AnyHttpUrl(resource_url)
        encoded_scope = json.dumps(
            scope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        governance_mode: Literal["SEPARATED_AUTHORITY", "SINGLE_HOST_FULL_CONTROL"] = (
            "SINGLE_HOST_FULL_CONTROL"
            if access_profile == "codex-full"
            else "SEPARATED_AUTHORITY"
        )
        scopes = (
            (
                "memory:read",
                "evidence:capture",
                "proposal:create",
                "proposal:review",
                "evidence:revoke",
                "operations:admin",
                "working-state:read",
                "working-state:write",
            )
            if access_profile == "codex-full"
            else ("memory:read",)
        )
        return cls(
            bearer_token=bearer_token,
            principal_id=principal_id.strip(),
            issuer_url=issuer_url,
            resource_url=resource_url,
            scope_digest=hashlib.sha256(encoded_scope).hexdigest(),
            access_profile=access_profile,
            governance_mode=governance_mode,
            scopes=scopes,
        )

    def auth_settings(self, *, oauth_enabled: bool = False) -> AuthSettings:
        return AuthSettings(
            issuer_url=AnyHttpUrl(self.issuer_url),
            resource_server_url=AnyHttpUrl(self.resource_url),
            required_scopes=list(self.scopes),
            client_registration_options=(
                ClientRegistrationOptions(
                    enabled=True,
                    client_secret_expiry_seconds=30 * 24 * 60 * 60,
                    valid_scopes=list(self.scopes),
                    default_scopes=list(self.scopes),
                )
                if oauth_enabled
                else None
            ),
            revocation_options=(
                RevocationOptions(enabled=True) if oauth_enabled else None
            ),
        )

    def access_token(
        self,
        token: str,
        *,
        principal_id: str | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> AccessToken:
        """Build request identity from server-owned binding data."""

        return AccessToken(
            token=token,
            client_id="milai-codex-http",
            subject=principal_id or self.principal_id,
            scopes=list(self.scopes),
            resource=self.resource_url,
            claims={
                "milai_scope_sha256": self.scope_digest,
                "milai_access_profile": self.access_profile,
                "milai_governance_mode": self.governance_mode,
                **(extra_claims or {}),
            },
        )


class StaticBearerTokenVerifier:
    """Verify the first P08 project-scoped bearer credential."""

    def __init__(self, binding: HttpPrincipalBinding) -> None:
        self._binding = binding

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self._binding.bearer_token):
            return None
        return self._binding.access_token(token)


@dataclass(frozen=True, slots=True)
class HttpResourceBinding:
    """External resource identity without a static credential or default user."""

    issuer_url: str
    resource_url: str
    scope_digest: str
    scopes: tuple[str, ...]

    @classmethod
    def create(
        cls, *, issuer_url: str, resource_url: str, scope: dict[str, Any],
        scopes: tuple[str, ...],
    ) -> HttpResourceBinding:
        if not scope:
            raise ValueError("resource requires a non-empty Memory scope")
        encoded = json.dumps(
            scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()
        return cls(issuer_url, resource_url, hashlib.sha256(encoded).hexdigest(), scopes)

    def auth_settings(self, *, oauth_enabled: bool = False) -> AuthSettings:
        if oauth_enabled:
            raise ValueError("external resource cannot install a local OAuth provider")
        return AuthSettings(
            issuer_url=AnyHttpUrl(self.issuer_url),
            resource_server_url=AnyHttpUrl(self.resource_url),
            # Discovery advertises supported scopes separately; requiring their union
            # here would reject legitimate tokens granting only one read capability.
            required_scopes=[],
        )
