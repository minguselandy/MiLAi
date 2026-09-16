"""Persistent OAuth 2.1 provider for URL-only Streamable HTTP MCP onboarding."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from mcp.server import MCPServer
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from milai_mcp.http_transport import HttpPrincipalBinding
from milai_mcp.remote_registration import RemoteUserRegistry, validate_agent_id

_LOGGER = logging.getLogger(__name__)
_SCHEMA_VERSION = "milai-mcp-oauth-v1"
_AUTHORIZATION_TTL_SECONDS = 10 * 60
_AUTHORIZATION_CODE_TTL_SECONDS = 5 * 60
_ACCESS_TOKEN_TTL_SECONDS = 60 * 60
_REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
_MAX_CONSENT_ATTEMPTS = 5
_MAX_CLIENTS = 2048
_MAX_TOKEN_REQUEST_BYTES = 65_536


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _principal_id(agent_id: str) -> str:
    return f"codex-oauth-{hashlib.sha256(agent_id.encode()).hexdigest()[:32]}"


def _append_query(url: str, **values: str | None) -> str:
    parsed = urlsplit(url)
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    query.extend((key, value) for key, value in values.items() if value is not None)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


class OAuthTokenResourceBindingMiddleware:
    """Require the exact MCP RFC 8707 resource on every token request.

    The MCP SDK validates the resource on the authorization request, but its token
    handler does not pass the token request's resource to the provider. Enforce that
    external boundary before an authorization code or refresh token can be consumed.
    """

    def __init__(self, app: ASGIApp, *, resource_url: str) -> None:
        self.app = app
        self.resource_url = resource_url

    @staticmethod
    async def _error(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        error: str,
        description: str,
    ) -> None:
        response = Response(
            json.dumps(
                {"error": error, "error_description": description},
                separators=(",", ":"),
            ),
            status_code=400,
            media_type="application/json",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != "/token"
        ):
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").casefold(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        content_type = (
            headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        )
        if content_type != "application/x-www-form-urlencoded":
            await self._error(
                scope,
                receive,
                send,
                error="invalid_request",
                description="token request must use application/x-www-form-urlencoded",
            )
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                await self._error(
                    scope,
                    receive,
                    send,
                    error="invalid_request",
                    description="token request body is unavailable",
                )
                return
            body.extend(message.get("body", b""))
            if len(body) > _MAX_TOKEN_REQUEST_BYTES:
                await self._error(
                    scope,
                    receive,
                    send,
                    error="invalid_request",
                    description="token request body is too large",
                )
                return
            if not message.get("more_body", False):
                break

        try:
            form = parse_qs(
                body.decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=32,
            )
        except (UnicodeDecodeError, ValueError):
            await self._error(
                scope,
                receive,
                send,
                error="invalid_request",
                description="token request form is invalid",
            )
            return
        if form.get("resource") != [self.resource_url]:
            await self._error(
                scope,
                receive,
                send,
                error="invalid_target",
                description="resource must exactly match the MiLAi MCP resource",
            )
            return

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


class OAuthPublicClientMetadataMiddleware:
    """Advertise the public-client method accepted by the locked MCP SDK.

    MCP SDK 2.0.0 accepts DCR clients using ``token_endpoint_auth_method=none``
    but omits ``none`` from both relevant discovery fields. Codex is a native
    public client using Authorization Code + PKCE, so make the wire metadata
    accurately describe the methods the generated endpoints already accept.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not (
            scope["type"] == "http"
            and scope.get("method") == "GET"
            and scope.get("path") == "/.well-known/oauth-authorization-server"
        ):
            await self.app(scope, receive, send)
            return

        messages: list[Message] = []

        async def capture(message: Message) -> None:
            messages.append(message)

        await self.app(scope, receive, capture)
        starts = [
            message for message in messages if message["type"] == "http.response.start"
        ]
        bodies = [message for message in messages if message["type"] == "http.response.body"]
        if (
            len(starts) != 1
            or starts[0].get("status") != 200
            or not bodies
            or any(message.get("more_body", False) for message in bodies)
        ):
            for message in messages:
                await send(message)
            return
        try:
            payload = json.loads(b"".join(message.get("body", b"") for message in bodies))
        except (UnicodeDecodeError, json.JSONDecodeError):
            for message in messages:
                await send(message)
            return
        if not isinstance(payload, dict):
            for message in messages:
                await send(message)
            return

        for field in (
            "token_endpoint_auth_methods_supported",
            "revocation_endpoint_auth_methods_supported",
        ):
            methods = payload.get(field)
            if isinstance(methods, list) and "none" not in methods:
                payload[field] = ["none", *methods]

        encoded = json.dumps(payload, separators=(",", ":")).encode()
        start = dict(starts[0])
        response_headers = [
            (key, value)
            for key, value in start.get("headers", [])
            if key.lower() != b"content-length"
        ]
        response_headers.append((b"content-length", str(len(encoded)).encode("ascii")))
        start["headers"] = response_headers
        await send(start)
        await send({"type": "http.response.body", "body": encoded})


class OAuthStore:
    """Owner-only SQLite persistence for clients, grants, users and audit."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve(strict=False)
        if self.path == Path("/"):
            raise ValueError("OAuth database cannot be the filesystem root")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.stat().st_mode & 0o077:
            raise PermissionError(
                f"{self.path.parent} must not be accessible by group or other users"
            )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS oauth_meta (
                    schema_version TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS oauth_users (
                    agent_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL UNIQUE,
                    enrollment_sha256 TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK (status IN ('PENDING','ACTIVE','REVOKED')),
                    issued_at TEXT NOT NULL,
                    activated_at TEXT,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS oauth_clients (
                    client_id TEXT PRIMARY KEY,
                    client_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_pending_authorizations (
                    request_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL REFERENCES oauth_clients(client_id),
                    params_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    consumed_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
                    code_sha256 TEXT PRIMARY KEY,
                    code_json TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    consumed_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS oauth_access_tokens (
                    token_sha256 TEXT PRIMARY KEY,
                    token_json TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
                    token_sha256 TEXT PRIMARY KEY,
                    token_json TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS oauth_audit (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    event TEXT NOT NULL,
                    agent_id TEXT,
                    principal_id TEXT,
                    client_id TEXT,
                    detail_json TEXT NOT NULL
                );
                COMMIT;
                """
            )
            versions = connection.execute(
                "SELECT schema_version FROM oauth_meta"
            ).fetchall()
            if not versions:
                connection.execute(
                    "INSERT INTO oauth_meta(schema_version) VALUES (?)",
                    (_SCHEMA_VERSION,),
                )
            elif [row["schema_version"] for row in versions] != [_SCHEMA_VERSION]:
                raise ValueError("OAuth database has an unsupported schema")
        finally:
            connection.close()
        os.chmod(self.path, 0o600)

    def audit(
        self,
        connection: sqlite3.Connection,
        event: str,
        *,
        agent_id: str | None = None,
        principal_id: str | None = None,
        client_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "event_id": str(uuid4()),
            "occurred_at": _now_iso(),
            "event": event,
            "agent_id": agent_id,
            "principal_id": principal_id,
            "client_id": client_id,
            "detail": detail or {},
        }
        connection.execute(
            """
            INSERT INTO oauth_audit(
                event_id, occurred_at, event, agent_id, principal_id, client_id,
                detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["event_id"],
                record["occurred_at"],
                event,
                agent_id,
                principal_id,
                client_id,
                json.dumps(record["detail"], sort_keys=True, separators=(",", ":")),
            ),
        )
        _LOGGER.warning(
            "MILAI_OAUTH_AUDIT %s",
            json.dumps(record, sort_keys=True, separators=(",", ":")),
        )

    @staticmethod
    def _invalidate_principal_credentials(
        connection: sqlite3.Connection,
        *,
        principal_id: str,
        revoked_at: int,
    ) -> None:
        for table in ("oauth_access_tokens", "oauth_refresh_tokens"):
            records = connection.execute(
                f"SELECT token_sha256, token_json FROM {table} "  # noqa: S608
                "WHERE revoked_at IS NULL"
            ).fetchall()
            for token_row in records:
                metadata = json.loads(token_row["token_json"])
                if metadata.get("subject") == principal_id:
                    connection.execute(
                        f"UPDATE {table} SET revoked_at=? "  # noqa: S608
                        "WHERE token_sha256=?",
                        (revoked_at, token_row["token_sha256"]),
                    )
        code_records = connection.execute(
            """
            SELECT code_sha256, code_json FROM oauth_authorization_codes
            WHERE consumed_at IS NULL AND expires_at >= ?
            """,
            (revoked_at,),
        ).fetchall()
        for code_row in code_records:
            metadata = json.loads(code_row["code_json"])
            if metadata.get("subject") == principal_id:
                connection.execute(
                    """
                    UPDATE oauth_authorization_codes SET consumed_at=?
                    WHERE code_sha256=?
                    """,
                    (revoked_at, code_row["code_sha256"]),
                )

    def issue_enrollment(self, agent_id: str, *, replace: bool = False) -> str:
        normalized = validate_agent_id(agent_id)
        enrollment_code = secrets.token_urlsafe(32)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT principal_id, status FROM oauth_users WHERE agent_id = ?",
                (normalized,),
            ).fetchone()
            if existing is not None and existing["status"] != "REVOKED" and not replace:
                raise ValueError("agent id already has a live OAuth enrollment")
            now = _now_iso()
            principal_id = _principal_id(normalized)
            if existing is not None:
                revoked_at = int(time.time())
                self._invalidate_principal_credentials(
                    connection,
                    principal_id=str(existing["principal_id"]),
                    revoked_at=revoked_at,
                )
                self.audit(
                    connection,
                    "OAUTH_USER_CREDENTIALS_REVOKED",
                    agent_id=normalized,
                    principal_id=principal_id,
                    detail={
                        "reason": (
                            "ENROLLMENT_REPLACED"
                            if replace
                            else "REVOKED_ENROLLMENT_REISSUED"
                        )
                    },
                )
            connection.execute(
                """
                INSERT INTO oauth_users(
                    agent_id, principal_id, enrollment_sha256, status, issued_at,
                    activated_at, revoked_at
                ) VALUES (?, ?, ?, 'PENDING', ?, NULL, NULL)
                ON CONFLICT(agent_id) DO UPDATE SET
                    principal_id=excluded.principal_id,
                    enrollment_sha256=excluded.enrollment_sha256,
                    status='PENDING',
                    issued_at=excluded.issued_at,
                    activated_at=NULL,
                    revoked_at=NULL
                """,
                (normalized, principal_id, _digest(enrollment_code), now),
            )
            self.audit(
                connection,
                "OAUTH_ENROLLMENT_ISSUED",
                agent_id=normalized,
                principal_id=principal_id,
            )
            connection.commit()
            return enrollment_code
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_users(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT agent_id, principal_id, status, issued_at, activated_at,
                       revoked_at
                FROM oauth_users ORDER BY agent_id
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def revoke_user(self, agent_id: str) -> None:
        normalized = validate_agent_id(agent_id)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT principal_id, status FROM oauth_users WHERE agent_id = ?",
                (normalized,),
            ).fetchone()
            if row is None or row["status"] == "REVOKED":
                raise ValueError("agent id has no live OAuth enrollment")
            now_iso = _now_iso()
            now = int(time.time())
            connection.execute(
                "UPDATE oauth_users SET status='REVOKED', revoked_at=? WHERE agent_id=?",
                (now_iso, normalized),
            )
            principal_id = str(row["principal_id"])
            self._invalidate_principal_credentials(
                connection,
                principal_id=principal_id,
                revoked_at=now,
            )
            self.audit(
                connection,
                "OAUTH_USER_REVOKED",
                agent_id=normalized,
                principal_id=principal_id,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class MilaiOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """OAuth provider with DCR, PKCE, rotating refresh tokens and user consent."""

    def __init__(
        self,
        store: OAuthStore,
        binding: HttpPrincipalBinding,
        *,
        legacy_registry: RemoteUserRegistry | None = None,
    ) -> None:
        self.store = store
        self.binding = binding
        self.legacy_registry = legacy_registry
        self.issuer_url = binding.issuer_url.rstrip("/")
        self.resource_url = binding.resource_url

    @staticmethod
    def _validate_client(client: OAuthClientInformationFull) -> None:
        if client.token_endpoint_auth_method not in {
            "none",
            "client_secret_basic",
            "client_secret_post",
        }:
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description="unsupported token endpoint authentication method",
            )
        if not client.redirect_uris:
            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description="at least one redirect URI is required",
            )
        for redirect in client.redirect_uris:
            parsed = urlsplit(str(redirect))
            loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if parsed.fragment or parsed.username or parsed.password:
                raise RegistrationError(
                    error="invalid_redirect_uri",
                    error_description="redirect URI cannot contain userinfo or fragment",
                )
            if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
                raise RegistrationError(
                    error="invalid_redirect_uri",
                    error_description="redirect URI must use HTTPS or loopback HTTP",
                )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        connection = self.store._connect()
        try:
            row = connection.execute(
                "SELECT client_json FROM oauth_clients WHERE client_id = ?",
                (client_id,),
            ).fetchone()
            if row is None:
                return None
            return OAuthClientInformationFull.model_validate_json(row["client_json"])
        finally:
            connection.close()

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._validate_client(client_info)
        connection = self.store._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            count = connection.execute("SELECT COUNT(*) AS n FROM oauth_clients").fetchone()[
                "n"
            ]
            if count >= _MAX_CLIENTS:
                raise RegistrationError(
                    error="invalid_client_metadata",
                    error_description="OAuth client capacity reached",
                )
            connection.execute(
                "INSERT INTO oauth_clients(client_id, client_json, created_at) VALUES (?, ?, ?)",
                (
                    client_info.client_id,
                    client_info.model_dump_json(),
                    int(time.time()),
                ),
            )
            self.store.audit(
                connection,
                "OAUTH_CLIENT_REGISTERED",
                client_id=client_info.client_id,
                detail={"redirect_uri_count": len(client_info.redirect_uris or [])},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if params.resource != self.resource_url:
            raise AuthorizeError(
                error="invalid_target",
                error_description="resource must exactly match the MiLAi MCP resource",
            )
        scopes = params.scopes or []
        if not set(scopes).issubset(self.binding.scopes):
            raise AuthorizeError(
                error="invalid_scope",
                error_description="requested scope is not available",
            )
        request_id = secrets.token_urlsafe(32)
        now = int(time.time())
        connection = self.store._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO oauth_pending_authorizations(
                    request_id, client_id, params_json, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    client.client_id,
                    params.model_dump_json(),
                    now,
                    now + _AUTHORIZATION_TTL_SECONDS,
                ),
            )
            self.store.audit(
                connection,
                "OAUTH_AUTHORIZATION_STARTED",
                client_id=client.client_id,
                detail={"scope_count": len(scopes)},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return f"{self.issuer_url}/oauth/consent?{urlencode({'request_id': request_id})}"

    def consent_view(self, request_id: str) -> dict[str, Any] | None:
        connection = self.store._connect()
        try:
            row = connection.execute(
                """
                SELECT p.client_id, p.params_json, p.expires_at, p.attempt_count,
                       p.consumed_at, c.client_json
                FROM oauth_pending_authorizations p
                JOIN oauth_clients c ON c.client_id = p.client_id
                WHERE p.request_id = ?
                """,
                (request_id,),
            ).fetchone()
            if (
                row is None
                or row["consumed_at"] is not None
                or row["expires_at"] < int(time.time())
                or row["attempt_count"] >= _MAX_CONSENT_ATTEMPTS
            ):
                return None
            params = AuthorizationParams.model_validate_json(row["params_json"])
            client = OAuthClientInformationFull.model_validate_json(row["client_json"])
            return {
                "client_id": row["client_id"],
                "client_name": client.client_name or "Codex MCP client",
                "scopes": params.scopes or [],
            }
        finally:
            connection.close()

    def complete_consent(
        self,
        request_id: str,
        enrollment_code: str,
        *,
        approved: bool,
    ) -> str | None:
        connection = self.store._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT client_id, params_json, expires_at, attempt_count, consumed_at
                FROM oauth_pending_authorizations WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
            now = int(time.time())
            if (
                row is None
                or row["consumed_at"] is not None
                or row["expires_at"] < now
                or row["attempt_count"] >= _MAX_CONSENT_ATTEMPTS
            ):
                connection.rollback()
                return None
            params = AuthorizationParams.model_validate_json(row["params_json"])
            if not approved:
                connection.execute(
                    "UPDATE oauth_pending_authorizations SET consumed_at=? WHERE request_id=?",
                    (now, request_id),
                )
                self.store.audit(
                    connection,
                    "OAUTH_AUTHORIZATION_DENIED",
                    client_id=row["client_id"],
                )
                connection.commit()
                return _append_query(
                    str(params.redirect_uri),
                    error="access_denied",
                    state=params.state,
                )

            user = connection.execute(
                """
                SELECT agent_id, principal_id, status
                FROM oauth_users WHERE enrollment_sha256 = ?
                """,
                (_digest(enrollment_code),),
            ).fetchone()
            if user is None or user["status"] != "PENDING":
                connection.execute(
                    """
                    UPDATE oauth_pending_authorizations
                    SET attempt_count=attempt_count+1 WHERE request_id=?
                    """,
                    (request_id,),
                )
                connection.commit()
                return None

            code = secrets.token_urlsafe(32)
            authorization_code = AuthorizationCode(
                code=code,
                scopes=params.scopes or [],
                expires_at=now + _AUTHORIZATION_CODE_TTL_SECONDS,
                client_id=row["client_id"],
                code_challenge=params.code_challenge,
                redirect_uri=params.redirect_uri,
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=params.resource,
                subject=user["principal_id"],
            )
            metadata = authorization_code.model_dump(mode="json", exclude={"code"})
            metadata["agent_id"] = user["agent_id"]
            connection.execute(
                """
                INSERT INTO oauth_authorization_codes(
                    code_sha256, code_json, expires_at, consumed_at
                ) VALUES (?, ?, ?, NULL)
                """,
                (
                    _digest(code),
                    json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                    now + _AUTHORIZATION_CODE_TTL_SECONDS,
                ),
            )
            connection.execute(
                """
                UPDATE oauth_pending_authorizations SET consumed_at=? WHERE request_id=?
                """,
                (now, request_id),
            )
            connection.execute(
                """
                UPDATE oauth_users SET status='ACTIVE', activated_at=?
                WHERE agent_id=? AND status='PENDING'
                """,
                (_now_iso(), user["agent_id"]),
            )
            self.store.audit(
                connection,
                "OAUTH_USER_REGISTERED",
                agent_id=user["agent_id"],
                principal_id=user["principal_id"],
                client_id=row["client_id"],
            )
            self.store.audit(
                connection,
                "OAUTH_AUTHORIZATION_APPROVED",
                agent_id=user["agent_id"],
                principal_id=user["principal_id"],
                client_id=row["client_id"],
                detail={"scope_count": len(params.scopes or [])},
            )
            connection.commit()
            return _append_query(
                str(params.redirect_uri), code=code, state=params.state
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        connection = self.store._connect()
        try:
            row = connection.execute(
                """
                SELECT code_json, expires_at, consumed_at
                FROM oauth_authorization_codes WHERE code_sha256=?
                """,
                (_digest(authorization_code),),
            ).fetchone()
            if (
                row is None
                or row["consumed_at"] is not None
                or row["expires_at"] < int(time.time())
            ):
                return None
            metadata = json.loads(row["code_json"])
            if metadata.get("client_id") != client.client_id:
                return None
            metadata.pop("agent_id", None)
            return AuthorizationCode.model_validate(
                {**metadata, "code": authorization_code}
            )
        finally:
            connection.close()

    def _issue_token_pair(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
        subject: str,
        agent_id: str,
        scopes: list[str],
        family_id: str,
    ) -> OAuthToken:
        now = int(time.time())
        access_value = secrets.token_urlsafe(32)
        refresh_value = secrets.token_urlsafe(48)
        access = self.binding.access_token(
            access_value,
            principal_id=subject,
            extra_claims={
                "milai_agent_id": agent_id,
                "milai_registration_mode": "OAUTH_DCR_AUTHORIZATION_CODE",
                "iss": self.issuer_url,
            },
        ).model_copy(
            update={
                "client_id": client_id,
                "scopes": scopes,
                "expires_at": now + _ACCESS_TOKEN_TTL_SECONDS,
                "resource": self.resource_url,
            }
        )
        refresh = RefreshToken(
            token=refresh_value,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + _REFRESH_TOKEN_TTL_SECONDS,
            subject=subject,
        )
        access_json = access.model_dump(mode="json", exclude={"token"})
        access_json["agent_id"] = agent_id
        refresh_json = refresh.model_dump(mode="json", exclude={"token"})
        refresh_json["agent_id"] = agent_id
        connection.execute(
            """
            INSERT INTO oauth_access_tokens(
                token_sha256, token_json, family_id, expires_at, revoked_at
            ) VALUES (?, ?, ?, ?, NULL)
            """,
            (
                _digest(access_value),
                json.dumps(access_json, sort_keys=True, separators=(",", ":")),
                family_id,
                now + _ACCESS_TOKEN_TTL_SECONDS,
            ),
        )
        connection.execute(
            """
            INSERT INTO oauth_refresh_tokens(
                token_sha256, token_json, family_id, expires_at, revoked_at
            ) VALUES (?, ?, ?, ?, NULL)
            """,
            (
                _digest(refresh_value),
                json.dumps(refresh_json, sort_keys=True, separators=(",", ":")),
                family_id,
                now + _REFRESH_TOKEN_TTL_SECONDS,
            ),
        )
        return OAuthToken(
            access_token=access_value,
            expires_in=_ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes),
            refresh_token=refresh_value,
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        connection = self.store._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT code_json, expires_at, consumed_at
                FROM oauth_authorization_codes WHERE code_sha256=?
                """,
                (_digest(authorization_code.code),),
            ).fetchone()
            now = int(time.time())
            if (
                row is None
                or row["consumed_at"] is not None
                or row["expires_at"] < now
            ):
                raise TokenError(
                    error="invalid_grant",
                    error_description="authorization code is invalid or already consumed",
                )
            metadata = json.loads(row["code_json"])
            if metadata.get("client_id") != client.client_id:
                raise TokenError(error="invalid_grant", error_description="client mismatch")
            user = connection.execute(
                """
                SELECT principal_id, status FROM oauth_users WHERE agent_id=?
                """,
                (metadata.get("agent_id"),),
            ).fetchone()
            if (
                user is None
                or user["status"] != "ACTIVE"
                or user["principal_id"] != metadata.get("subject")
            ):
                connection.execute(
                    "UPDATE oauth_authorization_codes SET consumed_at=? WHERE code_sha256=?",
                    (now, _digest(authorization_code.code)),
                )
                connection.commit()
                raise TokenError(
                    error="invalid_grant",
                    error_description="resource owner authorization is no longer active",
                )
            connection.execute(
                "UPDATE oauth_authorization_codes SET consumed_at=? WHERE code_sha256=?",
                (now, _digest(authorization_code.code)),
            )
            token = self._issue_token_pair(
                connection,
                client_id=client.client_id,
                subject=str(metadata["subject"]),
                agent_id=str(metadata["agent_id"]),
                scopes=list(metadata["scopes"]),
                family_id=str(uuid4()),
            )
            self.store.audit(
                connection,
                "OAUTH_TOKEN_ISSUED",
                agent_id=metadata["agent_id"],
                principal_id=metadata["subject"],
                client_id=client.client_id,
                detail={"grant_type": "authorization_code"},
            )
            connection.commit()
            return token
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        connection = self.store._connect()
        try:
            row = connection.execute(
                """
                SELECT token_json, expires_at, revoked_at FROM oauth_refresh_tokens
                WHERE token_sha256=?
                """,
                (_digest(refresh_token),),
            ).fetchone()
            if (
                row is None
                or row["revoked_at"] is not None
                or row["expires_at"] < int(time.time())
            ):
                return None
            metadata = json.loads(row["token_json"])
            if metadata.get("client_id") != client.client_id:
                return None
            metadata.pop("agent_id", None)
            return RefreshToken.model_validate({**metadata, "token": refresh_token})
        finally:
            connection.close()

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        connection = self.store._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT token_json, family_id, expires_at, revoked_at
                FROM oauth_refresh_tokens WHERE token_sha256=?
                """,
                (_digest(refresh_token.token),),
            ).fetchone()
            now = int(time.time())
            if (
                row is None
                or row["revoked_at"] is not None
                or row["expires_at"] < now
            ):
                raise TokenError(
                    error="invalid_grant",
                    error_description="refresh token is invalid or already rotated",
                )
            metadata = json.loads(row["token_json"])
            if metadata.get("client_id") != client.client_id:
                raise TokenError(error="invalid_grant", error_description="client mismatch")
            family_id = str(row["family_id"])
            connection.execute(
                """
                UPDATE oauth_access_tokens SET revoked_at=?
                WHERE family_id=? AND revoked_at IS NULL
                """,
                (now, family_id),
            )
            connection.execute(
                """
                UPDATE oauth_refresh_tokens SET revoked_at=?
                WHERE family_id=? AND revoked_at IS NULL
                """,
                (now, family_id),
            )
            token = self._issue_token_pair(
                connection,
                client_id=client.client_id,
                subject=str(metadata["subject"]),
                agent_id=str(metadata["agent_id"]),
                scopes=scopes,
                family_id=family_id,
            )
            self.store.audit(
                connection,
                "OAUTH_TOKEN_ROTATED",
                agent_id=metadata["agent_id"],
                principal_id=metadata["subject"],
                client_id=client.client_id,
            )
            connection.commit()
            return token
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def load_access_token(self, token: str) -> AccessToken | None:
        if hmac.compare_digest(token, self.binding.bearer_token):
            return self.binding.access_token(token)
        if self.legacy_registry is not None:
            registered = self.legacy_registry.authenticate(token)
            if registered is not None:
                return self.binding.access_token(
                    token,
                    principal_id=registered.principal_id,
                    extra_claims={
                        "milai_agent_id": registered.agent_id,
                        "milai_registration_mode": "LEGACY_SERVER_ISSUED_BEARER",
                    },
                )
        connection = self.store._connect()
        try:
            row = connection.execute(
                """
                SELECT token_json, expires_at, revoked_at FROM oauth_access_tokens
                WHERE token_sha256=?
                """,
                (_digest(token),),
            ).fetchone()
            if (
                row is None
                or row["revoked_at"] is not None
                or row["expires_at"] < int(time.time())
            ):
                return None
            metadata = json.loads(row["token_json"])
            if metadata.get("resource") != self.resource_url:
                return None
            metadata.pop("agent_id", None)
            return AccessToken.model_validate({**metadata, "token": token})
        finally:
            connection.close()

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_digest = _digest(token.token)
        connection = self.store._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            family_id: str | None = None
            for table in ("oauth_access_tokens", "oauth_refresh_tokens"):
                row = connection.execute(
                    f"SELECT family_id FROM {table} WHERE token_sha256=?",  # noqa: S608
                    (token_digest,),
                ).fetchone()
                if row is not None:
                    family_id = str(row["family_id"])
                    break
            if family_id is not None:
                now = int(time.time())
                connection.execute(
                    """
                    UPDATE oauth_access_tokens SET revoked_at=?
                    WHERE family_id=? AND revoked_at IS NULL
                    """,
                    (now, family_id),
                )
                connection.execute(
                    """
                    UPDATE oauth_refresh_tokens SET revoked_at=?
                    WHERE family_id=? AND revoked_at IS NULL
                    """,
                    (now, family_id),
                )
                self.store.audit(
                    connection,
                    "OAUTH_TOKEN_REVOKED",
                    client_id=token.client_id,
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def install_oauth_consent_routes(
    server: MCPServer[Any], provider: MilaiOAuthProvider
) -> None:
    """Install the browser step that binds DCR authorization to a real user."""

    security_headers = {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; frame-ancestors 'none'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }

    @server.custom_route(  # type: ignore[untyped-decorator]
        "/oauth/consent", methods=["GET", "POST"]
    )
    async def oauth_consent(request: Request) -> Response:
        if request.method == "POST":
            form = await request.form()
            request_id = str(form.get("request_id", ""))
            decision = str(form.get("decision", ""))
            enrollment_code = str(form.get("enrollment_code", ""))
            if decision not in {"APPROVE", "DENY"}:
                return HTMLResponse(
                    "<h1>Authorization failed</h1><p>Invalid consent decision.</p>",
                    status_code=400,
                    headers=security_headers,
                )
            redirect = provider.complete_consent(
                request_id,
                enrollment_code,
                approved=decision == "APPROVE",
            )
            if redirect is not None:
                return RedirectResponse(redirect, status_code=302, headers=security_headers)
            return HTMLResponse(
                "<h1>Authorization failed</h1>"
                "<p>The request or enrollment code is invalid, expired, or already used.</p>",
                status_code=400,
                headers=security_headers,
            )

        request_id = request.query_params.get("request_id", "")
        view = provider.consent_view(request_id)
        if view is None:
            return HTMLResponse(
                "<h1>Authorization request unavailable</h1><p>Start the Codex MCP login again.</p>",
                status_code=400,
                headers=security_headers,
            )
        client_name = html.escape(str(view["client_name"]))
        scopes = " ".join(html.escape(str(scope)) for scope in view["scopes"])
        request_value = html.escape(request_id, quote=True)
        body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Authorize MiLAi</title><style>
body{{font:16px system-ui;max-width:42rem;margin:3rem auto;padding:0 1rem;line-height:1.5}}
input,button{{font:inherit;padding:.65rem;margin:.35rem 0}}
input{{width:100%;box-sizing:border-box}}
.danger{{color:#8b1a1a}} code{{overflow-wrap:anywhere}}
</style></head><body><h1>Authorize MiLAi MCP</h1>
<p><strong>{client_name}</strong> requests the following scopes:</p><p><code>{scopes}</code></p>
<p class="danger">This profile can read, write, review, revoke and clean
the bound MiLAi project.</p>
<form method="post" action="/oauth/consent">
<input type="hidden" name="request_id" value="{request_value}">
<label>One-time enrollment code
<input type="password" name="enrollment_code" required autocomplete="one-time-code">
</label>
<button type="submit" name="decision" value="APPROVE">Approve</button>
<button type="submit" name="decision" value="DENY">Deny</button>
</form></body></html>"""
        return HTMLResponse(body, headers=security_headers)
