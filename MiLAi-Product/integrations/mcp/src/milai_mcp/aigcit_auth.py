"""Bounded asynchronous external JWT verification for the AIGCIT resource server."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx2 as httpx
import jwt
from mcp.server.auth.provider import AccessToken
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from milai_mcp.auth_policy import (
    AdmissionDenied,
    AdmissionPolicy,
    AuthDependencyUnavailable,
    project_scope_digest,
    strict_json_object,
)
from milai_mcp.http_transport import validate_public_base_url

_MAX_DOCUMENT = 262_144
_MAX_TOKEN = 16_384


class JwksCache:
    """One bounded refresh per issuer, never one network request per random kid."""

    def __init__(
        self, issuer: str, *, client: httpx.AsyncClient | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if validate_public_base_url(
            issuer, oauth_enabled=True, allow_oauth_loopback_http=False,
        ) != issuer:
            raise ValueError("issuer must be an exact canonical HTTPS origin")
        self.issuer = issuer
        self._client = client
        self._owns_client = client is None
        self._clock = monotonic
        self._lock = asyncio.Lock()
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires = 0.0
        self._next_refresh = 0.0
        self._last_failed = False

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _document(self, url: str) -> dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=3.0, follow_redirects=False, trust_env=False,
                limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
            )
        async with self._client.stream(
            "GET", url, follow_redirects=False,
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        ) as response:
            if response.status_code != 200:
                raise ValueError("authentication document HTTP failure")
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("encoded authentication document")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > _MAX_DOCUMENT:
                    raise ValueError("authentication document too large")
            return strict_json_object(bytes(body))

    async def _refresh(self) -> None:
        metadata = await self._document(
            self.issuer + "/.well-known/oauth-authorization-server"
        )
        if metadata.get("issuer") != self.issuer:
            raise ValueError("discovery issuer mismatch")
        uri = metadata.get("jwks_uri")
        if not isinstance(uri, str):
            raise ValueError("missing trusted JWKS URI")
        parsed = urlsplit(uri)
        if (f"{parsed.scheme}://{parsed.netloc}" != self.issuer
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or not parsed.path.startswith("/")):
            raise ValueError("JWKS URI must remain on the trusted HTTPS issuer")
        document = await self._document(uri)
        entries = document.get("keys")
        if not isinstance(entries, list) or len(entries) > 64:
            raise ValueError("invalid bounded JWKS")
        keys: dict[str, jwt.PyJWK] = {}
        seen: set[str] = set()
        for entry in entries:
            if (not isinstance(entry, dict)
                    or {"d", "k", "p", "q", "dp", "dq", "qi", "oth"} & entry.keys()):
                raise ValueError("JWKS must contain public keys only")
            kid = entry.get("kid")
            if not isinstance(kid, str) or not kid or len(kid) > 256 or kid in seen:
                raise ValueError("invalid or duplicate JWKS kid")
            seen.add(kid)
            # Auth also publishes keys used for ID tokens; they are not access keys.
            if entry.get("kty") != "EC" or entry.get("crv") != "P-256":
                continue
            if (entry.get("alg", "ES256") != "ES256"
                    or entry.get("use", "sig") != "sig"
                    or entry.get("key_ops", ["verify"]) != ["verify"]):
                continue
            keys[kid] = jwt.PyJWK.from_dict(entry, algorithm="ES256")
        self._keys = keys
        self._expires = self._clock() + 600.0
        self._last_failed = False

    async def key(self, kid: str) -> jwt.PyJWK | None:
        now = self._clock()
        if now < self._expires and kid in self._keys:
            return self._keys[kid]
        try:
            async with asyncio.timeout(3.0), self._lock:
                now = self._clock()
                if now < self._expires and kid in self._keys:
                    return self._keys[kid]
                if now >= self._next_refresh:
                    self._next_refresh = now + 30.0
                    self._last_failed = True
                    await self._refresh()
                if self._last_failed or self._clock() >= self._expires:
                    raise AuthDependencyUnavailable("jwks_unavailable")
                return self._keys.get(kid)
        except (httpx.HTTPError, TimeoutError, ValueError, jwt.PyJWTError) as exc:
            raise AuthDependencyUnavailable("jwks_unavailable") from exc


class AigcitTokenVerifier:
    def __init__(
        self, *, cache: JwksCache, resource_url: str, scope_digest: str,
        policy: AdmissionPolicy,
    ) -> None:
        parsed = urlsplit(resource_url)
        if (parsed.scheme != "https" or not parsed.netloc or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment):
            raise ValueError("resource must be an exact HTTPS URL")
        if cache.issuer != policy.issuer:
            raise ValueError("issuer and admission policy must agree")
        self.cache = cache
        self.resource_url = resource_url
        self.scope_digest = scope_digest
        self.policy = policy

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or len(token) > _MAX_TOKEN:
            return None
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if (header.get("alg") != "ES256" or header.get("typ") != "at+jwt"
                    or header.get("crit") or not isinstance(kid, str)
                    or not kid or len(kid) > 256):
                return None
            # Unverified claims can only reject early; they never grant identity.
            unverified = jwt.decode(token, options={"verify_signature": False})
            if (unverified.get("iss") != self.cache.issuer
                    or unverified.get("aud") != self.resource_url):
                return None
            key = await self.cache.key(kid)
            if key is None:
                return None
            claims = jwt.decode(
                token, key, algorithms=["ES256"], issuer=self.cache.issuer,
                audience=self.resource_url, leeway=5,
                options={"require": ["exp", "iat", "sub", "client_id", "iss", "aud"],
                         "strict_aud": True},
            )
            for field in ("exp", "iat", "nbf"):
                if field in claims and type(claims[field]) is not int:
                    return None
            if claims["exp"] <= claims["iat"]:
                return None
            for field in ("sub", "client_id"):
                if (not isinstance(claims[field], str) or not claims[field].strip()
                        or len(claims[field]) > 512):
                    return None
            raw_scopes = claims.get("scope", "")
            if (not isinstance(raw_scopes, str) or len(raw_scopes) > 4096
                    or any(ord(c) < 32 or ord(c) >= 127 for c in raw_scopes)):
                return None
            granted = frozenset(raw_scopes.split(" ")) - {""}
        except (jwt.PyJWTError, ValueError, TypeError):
            return None
        admission = await asyncio.to_thread(self.policy.admit, claims["sub"], granted)
        scope_digest = (
            project_scope_digest(admission.project_id)
            if admission.project_id is not None else self.scope_digest
        )
        return AccessToken(
            token=token, client_id=claims["client_id"], subject=admission.principal_id,
            expires_at=claims["exp"], resource=self.resource_url,
            scopes=sorted(admission.effective_scopes),
            claims={
                "iss": self.cache.issuer,
                "milai_scope_sha256": scope_digest,
                "milai_deployment_scope_sha256": self.scope_digest,
                "milai_project_id": admission.project_id,
                "milai_access_profile": "codex-full",
                "milai_governance_mode": "SINGLE_HOST_FULL_CONTROL",
                "milai_auth_mode": "aigcit",
                "milai_external_sub": claims["sub"],
                "milai_policy_version": admission.policy_version,
                "milai_granted_scopes": sorted(admission.granted_scopes),
            },
        )


class AigcitErrorMiddleware:
    """Translate only known auth failures, without logging chained raw errors."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        started = False

        async def observe_send(message: Any) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, observe_send)
        except (AdmissionDenied, AuthDependencyUnavailable) as exc:
            if started or scope["type"] != "http":
                raise RuntimeError("authentication_failed_after_response") from None
            unavailable = isinstance(exc, AuthDependencyUnavailable)
            await JSONResponse(
                {"error": "auth_dependency_unavailable" if unavailable else "subject_not_admitted"},
                status_code=503 if unavailable else 403,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
