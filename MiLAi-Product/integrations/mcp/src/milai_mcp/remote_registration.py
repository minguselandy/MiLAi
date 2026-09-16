"""Server-issued, first-use remote MCP user registration.

Each Bearer credential is issued server-side, stored only as a SHA-256 digest,
and maps to exactly one server-owned principal. MCP clients need only the
standard HTTP Authorization header; identity is never selected by a client
supplied header or tool argument.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from mcp.server.auth.provider import AccessToken

from milai_mcp.http_transport import HttpPrincipalBinding

_LOGGER = logging.getLogger(__name__)
_AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_REGISTRY_SCHEMA = "milai-mcp-remote-user-registry-v1"
_AUDIT_SCHEMA = "milai-mcp-remote-registration-audit-v1"


def validate_agent_id(value: str) -> str:
    """Return a normalized transport identity or fail closed."""

    candidate = value.strip()
    if not _AGENT_ID.fullmatch(candidate):
        raise ValueError(
            "agent id must be 1-128 ASCII letters, digits, dot, underscore, colon, @ or hyphen"
        )
    return candidate


@dataclass(frozen=True, slots=True)
class RegisteredRemoteUser:
    """One authenticated edge identity returned by the registry."""

    agent_id: str
    principal_id: str
    newly_activated: bool


class RemoteUserRegistry:
    """Root-owned edge credential registry with atomic first-use activation."""

    def __init__(
        self,
        path: Path,
        *,
        audit_path: Path | None = None,
        log_events: bool = True,
    ) -> None:
        self.path = path.expanduser().resolve(strict=False)
        self.audit_path = (
            audit_path.expanduser().resolve(strict=False)
            if audit_path is not None
            else self.path.with_suffix(self.path.suffix + ".audit.jsonl")
        )
        if self.path == Path("/") or self.audit_path == Path("/"):
            raise ValueError("registration paths cannot be the filesystem root")
        self._log_events = log_events

    @property
    def _lock_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".lock")

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"schema_version": _REGISTRY_SCHEMA, "users": []}

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _principal_id(agent_id: str) -> str:
        digest = hashlib.sha256(agent_id.encode()).hexdigest()[:32]
        return f"codex-remote-{digest}"

    @staticmethod
    def _ensure_private(path: Path) -> None:
        if path.exists() and path.stat().st_mode & 0o077:
            raise PermissionError(f"{path} must not be accessible by group or other users")

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        self._ensure_private(self.path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != _REGISTRY_SCHEMA
            or not isinstance(payload.get("users"), list)
        ):
            raise ValueError("remote user registry has an invalid schema")
        return payload

    def _write_unlocked(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._ensure_private(self.path.parent)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def _audit_unlocked(self, event: str, entry: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._ensure_private(self.audit_path)
        record = {
            "schema_version": _AUDIT_SCHEMA,
            "event_id": str(uuid4()),
            "occurred_at": self._now(),
            "event": event,
            "agent_id": entry["agent_id"],
            "principal_id": entry["principal_id"],
            "status": entry["status"],
        }
        descriptor = os.open(
            self.audit_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(
                descriptor,
                (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if self._log_events:
            _LOGGER.warning(
                "MILAI_REMOTE_REGISTRATION_AUDIT %s",
                json.dumps(record, sort_keys=True),
            )

    def _locked(self) -> tuple[int, dict[str, Any]]:
        self._lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            self._ensure_private(self._lock_path)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            return descriptor, self._read_unlocked()
        except Exception:
            os.close(descriptor)
            raise

    @staticmethod
    def _unlock(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    def issue(self, agent_id: str, *, replace: bool = False) -> str:
        """Issue a unique pending Bearer credential and persist only its digest."""

        normalized = validate_agent_id(agent_id)
        descriptor, payload = self._locked()
        try:
            users = payload["users"]
            existing = [entry for entry in users if entry.get("agent_id") == normalized]
            live = [entry for entry in existing if entry.get("status") != "REVOKED"]
            if live and not replace:
                raise ValueError("agent id already has a live credential")
            if live:
                revoked_at = self._now()
                for entry in live:
                    entry["status"] = "REVOKED"
                    entry["revoked_at"] = revoked_at
            token = secrets.token_urlsafe(32)
            now = self._now()
            entry = {
                "agent_id": normalized,
                "principal_id": self._principal_id(normalized),
                "token_sha256": self._token_digest(token),
                "status": "PENDING",
                "issued_at": now,
                "registered_at": None,
                "revoked_at": None,
            }
            users.append(entry)
            self._write_unlocked(payload)
            for revoked_entry in live:
                self._audit_unlocked("CREDENTIAL_REVOKED", revoked_entry)
            self._audit_unlocked("CREDENTIAL_ISSUED", entry)
            return token
        finally:
            self._unlock(descriptor)

    def authenticate(self, token: str) -> RegisteredRemoteUser | None:
        """Authenticate and atomically activate the credential-owned principal."""

        token_digest = self._token_digest(token)
        descriptor, payload = self._locked()
        try:
            matched: dict[str, Any] | None = None
            for entry in payload["users"]:
                stored_digest = entry.get("token_sha256")
                if isinstance(stored_digest, str) and hmac.compare_digest(
                    token_digest, stored_digest
                ):
                    matched = entry
                    break
            if matched is None or matched.get("status") == "REVOKED":
                return None
            try:
                normalized = validate_agent_id(str(matched.get("agent_id", "")))
            except ValueError:
                return None
            newly_activated = matched.get("status") == "PENDING"
            if newly_activated:
                matched["status"] = "ACTIVE"
                matched["registered_at"] = self._now()
                self._write_unlocked(payload)
                self._audit_unlocked("USER_REGISTERED", matched)
            elif matched.get("status") != "ACTIVE":
                return None
            return RegisteredRemoteUser(
                agent_id=normalized,
                principal_id=str(matched["principal_id"]),
                newly_activated=newly_activated,
            )
        finally:
            self._unlock(descriptor)

    def revoke(self, agent_id: str) -> None:
        """Revoke every live edge credential for one agent identity."""

        normalized = validate_agent_id(agent_id)
        descriptor, payload = self._locked()
        try:
            live = [
                entry
                for entry in payload["users"]
                if entry.get("agent_id") == normalized and entry.get("status") != "REVOKED"
            ]
            if not live:
                raise ValueError("agent id has no live credential")
            revoked_at = self._now()
            for entry in live:
                entry["status"] = "REVOKED"
                entry["revoked_at"] = revoked_at
            self._write_unlocked(payload)
            for entry in live:
                self._audit_unlocked("CREDENTIAL_REVOKED", entry)
        finally:
            self._unlock(descriptor)

    def list_users(self) -> list[dict[str, Any]]:
        """Return credential metadata without token material or token digests."""

        descriptor, payload = self._locked()
        try:
            return [
                {key: value for key, value in entry.items() if key != "token_sha256"}
                for entry in payload["users"]
            ]
        finally:
            self._unlock(descriptor)


class RemoteRegistrationTokenVerifier:
    """Verify static compatibility or a server-issued per-user credential."""

    def __init__(
        self,
        binding: HttpPrincipalBinding,
        registry: RemoteUserRegistry,
    ) -> None:
        self._binding = binding
        self._registry = registry

    async def verify_token(self, token: str) -> AccessToken | None:
        if hmac.compare_digest(token, self._binding.bearer_token):
            return self._binding.access_token(token)
        registered = self._registry.authenticate(token)
        if registered is None:
            return None
        return self._binding.access_token(
            token,
            principal_id=registered.principal_id,
            extra_claims={
                "milai_agent_id": registered.agent_id,
                "milai_registration_mode": "FIRST_USE_AUTO_REGISTRATION",
            },
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Issue or revoke JSON-only MiLAi remote MCP user registration"
    )
    parser.add_argument(
        "--registry-file",
        type=Path,
        default=Path(
            os.environ.get(
                "MILAI_CODEX_USER_REGISTRY",
                "/var/lib/milai-mcp/codex-users.json",
            )
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    issue = subparsers.add_parser("issue")
    issue.add_argument("--agent-id", required=True)
    configured_origin = os.environ.get("MILAI_MCP_HTTP_PUBLIC_BASE_URL")
    configured_url = (
        configured_origin.rstrip("/") + "/mcp" if configured_origin else None
    )
    issue.add_argument(
        "--url",
        default=configured_url,
        required=configured_url is None,
        help=(
            "absolute deployment-specific MCP URL ending in /mcp; may be supplied "
            "through MILAI_MCP_HTTP_PUBLIC_BASE_URL"
        ),
    )
    issue.add_argument("--name", default="milai")
    issue.add_argument("--replace", action="store_true")
    revoke = subparsers.add_parser("revoke")
    revoke.add_argument("--agent-id", required=True)
    subparsers.add_parser("list")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Admin CLI; ``issue`` emits exactly the client JSON registration object."""

    args = _parser().parse_args(argv)
    registry = RemoteUserRegistry(args.registry_file, log_events=False)
    result: dict[str, Any]
    if args.command == "issue":
        parsed = urlsplit(args.url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/mcp"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("--url must be an absolute HTTP(S) URL ending exactly in /mcp")
        token = registry.issue(args.agent_id, replace=args.replace)
        result = {
            "mcpServers": {
                args.name: {
                    "type": "http",
                    "url": args.url,
                    "headers": {
                        "Authorization": f"Bearer {token}",
                    },
                }
            }
        }
    elif args.command == "revoke":
        registry.revoke(args.agent_id)
        result = {"agent_id": validate_agent_id(args.agent_id), "status": "REVOKED"}
    else:
        result = {"users": registry.list_users()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
