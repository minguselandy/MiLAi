"""Server-owned AIGCIT admission and tool scopes; no account provisioning."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

TOOL_SCOPES = {
    "milai_memory_resolve": "milai.memory.read",
    "milai_memory_get": "milai.memory.read",
    "milai_working_state_get": "milai.state.read",
    "milai_working_state_update": "milai.state.write",
    "milai_evidence_capture": "milai.evidence.capture",
    "milai_proposal_create": "milai.proposal.create",
    "milai_proposals_list": "milai.memory.read",
    "milai_proposal_get": "milai.memory.read",
    "milai_memory_review": "milai.proposal.review",
    "milai_evidence_revoke": "milai.evidence.revoke",
    "milai_deletion_status_get": "milai.memory.read",
    "milai_namespace_cleanup_submit": "milai.operations.admin",
    "milai_namespace_cleanup_status": "milai.operations.admin",
}
PILOT_TOOLS = frozenset({
    "milai_memory_resolve", "milai_memory_get", "milai_working_state_get",
    "milai_working_state_update", "milai_evidence_capture",
})
READ_SCOPES = frozenset({"milai.memory.read", "milai.state.read"})
PILOT_SCOPES = READ_SCOPES | {"milai.state.write", "milai.evidence.capture"}
FULL_SCOPES = frozenset(TOOL_SCOPES.values())
ORDINARY_TOOL_SCOPES = {
    "milai_memory_search": "milai.memory.read",
    "milai_note_add": "milai.note.write",
    "milai_note_update": "milai.note.write",
    "milai_note_delete": "milai.note.delete",
    "milai_note_get": "milai.note.read",
    "milai_note_list": "milai.note.read",
    "milai_note_search": "milai.note.read",
    "milai_note_operation_get": "milai.note.read",
    "milai_evidence_get": "milai.evidence.read",
    "milai_evidence_list": "milai.evidence.read",
}
ORDINARY_CATALOG_TOOL_SCOPES = {
    name: scope for name, scope in {**TOOL_SCOPES, **ORDINARY_TOOL_SCOPES}.items()
    if name != "milai_namespace_cleanup_submit"
}
COMPACT_CATALOG_TOOL_SCOPES = {
    "milai_memory_search": "milai.memory.read",
    "milai_memory_read": "milai.note.read",
    "milai_memory_list": "milai.note.read",
    "milai_memory_save": "milai.note.write",
    "milai_memory_delete": "milai.note.delete",
    "milai_memory_status": "milai.note.read",
    "milai_working_state_get": "milai.state.read",
    "milai_working_state_update": "milai.state.write",
}
ALL_TOOL_SCOPES = {**TOOL_SCOPES, **ORDINARY_TOOL_SCOPES, **COMPACT_CATALOG_TOOL_SCOPES}
ALL_SCOPES = frozenset(ALL_TOOL_SCOPES.values())
# Discovery is usable with either read capability. This grants only entry to
# the facade: its nested tool dispatches independently enforce each source scope.
TOOL_SCOPE_ALTERNATIVES = {
    "milai_memory_search": frozenset({"milai.memory.read", "milai.note.read"}),
    "milai_memory_read": frozenset({
        "milai.note.read", "milai.evidence.read", "milai.memory.read",
    }),
    "milai_memory_list": frozenset({"milai.note.read", "milai.evidence.read"}),
    "milai_memory_save": frozenset({"milai.note.write", "milai.evidence.capture"}),
    "milai_memory_delete": frozenset({"milai.note.delete", "milai.evidence.revoke"}),
    "milai_memory_status": frozenset({"milai.note.read", "milai.memory.read"}),
}


def authentication_mode(environment: Mapping[str, str]) -> str:
    """Preserve implicit legacy selection, reject mixed explicit configurations."""
    mode = environment.get("MILAI_MCP_AUTH_MODE", "").strip()
    local = bool(environment.get("MILAI_OAUTH_DB", "").strip())
    if not mode:
        if any(key.startswith("MILAI_AIGCIT_") and value for key, value in environment.items()):
            raise ValueError("AIGCIT configuration requires explicit auth mode")
        return "local-oauth" if local else "legacy"
    if mode not in {"legacy", "local-oauth", "aigcit"}:
        raise ValueError("unknown MCP authentication mode")
    if mode == "local-oauth" and not local:
        raise ValueError("local-oauth requires MILAI_OAUTH_DB")
    if mode == "legacy" and local:
        raise ValueError("legacy mode cannot load local OAuth configuration")
    if mode == "aigcit":
        conflicting = {
            "MILAI_OAUTH_DB", "MILAI_CODEX_USER_REGISTRY", "MILAI_CODEX_TOKEN",
            "MILAI_MCP_HTTP_BEARER_TOKEN", "MILAI_CODEX_PRINCIPAL_ID",
            "MILAI_MCP_HTTP_PRINCIPAL_ID",
        }
        if any(environment.get(key, "").strip() for key in conflicting):
            raise ValueError("aigcit mode cannot load legacy credentials or identity")
    elif any(key.startswith("MILAI_AIGCIT_") and value for key, value in environment.items()):
        raise ValueError("AIGCIT configuration cannot be loaded by another auth mode")
    return mode


class AuthDependencyUnavailable(RuntimeError):
    """Safe fixed error; never include source content or credentials."""


class AdmissionDenied(PermissionError):
    """Verified identity has no current local admission."""


def strict_json_object(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def principal_for(issuer: str, subject: str, project_id: str) -> str:
    encoded = json.dumps([issuer, subject, project_id], ensure_ascii=False).encode()
    return "aigcit:" + hashlib.sha256(encoded).hexdigest()


def private_project_for(issuer: str, subject: str, namespace: str) -> str:
    encoded = json.dumps([namespace, issuer, subject], ensure_ascii=False).encode()
    return "private:" + hashlib.sha256(encoded).hexdigest()


def project_scope_digest(project_id: str) -> str:
    encoded = json.dumps(
        {"project_ids": [project_id]}, sort_keys=True, separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class OwnerBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sub: str = Field(min_length=1, max_length=512)
    principal_id: str = Field(min_length=1, max_length=128)
    allowed_scopes: list[str] = Field(max_length=16)
    enabled: bool


class AdmissionDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(ge=1)
    issuer: str
    project_id: str = Field(min_length=1, max_length=512)
    owners: list[OwnerBinding] = Field(max_length=32)
    mode: Literal["explicit_owners", "authenticated_private"] = "explicit_owners"
    disabled_subjects: list[str] = Field(default_factory=list, max_length=1024)


@dataclass(frozen=True, slots=True)
class Admission:
    principal_id: str
    policy_version: int
    granted_scopes: frozenset[str]
    effective_scopes: frozenset[str]
    project_id: str | None = None


class AdmissionPolicy:
    """Read an atomically replaced, root-owned policy on every request.

    There is deliberately no cached fallback and no mutation method. The dedicated
    parent directory and file must not be writable by the MCP service account.
    """

    def __init__(
        self, path: Path, *, issuer: str, project_id: str,
        enabled_scopes: frozenset[str] = READ_SCOPES,
        trusted_owner_uid: int = 0,
        mode: str = "explicit_owners",
    ) -> None:
        if not enabled_scopes <= ALL_SCOPES:
            raise ValueError("only implemented MCP scopes may be enabled")
        self.path = path
        self.issuer = issuer
        self.project_id = project_id
        self.enabled_scopes = enabled_scopes
        if mode not in {"explicit_owners", "authenticated_private"}:
            raise ValueError("unknown admission mode")
        self.mode = mode
        # Production assembly always uses root (0). Explicit injection lets isolated
        # library tests exercise the same file checks under an unprivileged CI user.
        self._trusted_owner_uid = trusted_owner_uid

    def load(self) -> AdmissionDocument:
        try:
            parent = self.path.parent.stat()
            if parent.st_uid != self._trusted_owner_uid or parent.st_mode & 0o022:
                raise ValueError("unsafe admission directory")
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != self._trusted_owner_uid
                        or info.st_mode & 0o022 or info.st_size > 262_144):
                    raise ValueError("unsafe admission file")
                raw = stream.read(262_145)
            if len(raw) > 262_144:
                raise ValueError("oversized admission file")
            doc = AdmissionDocument.model_validate(strict_json_object(raw))
            if doc.issuer != self.issuer or doc.project_id != self.project_id:
                raise ValueError("admission deployment mismatch")
            if doc.mode != self.mode or (self.mode == "authenticated_private" and doc.owners):
                raise ValueError("admission mode mismatch")
            if (len(set(doc.disabled_subjects)) != len(doc.disabled_subjects)
                    or any(not value.strip() or len(value) > 512
                           for value in doc.disabled_subjects)):
                raise ValueError("invalid disabled subjects")
            subjects = set()
            for owner in doc.owners:
                if (not owner.sub.strip() or owner.sub in subjects
                        or owner.principal_id != principal_for(
                            self.issuer, owner.sub, self.project_id
                        ) or not set(owner.allowed_scopes) <= ALL_SCOPES):
                    raise ValueError("invalid owner binding")
                subjects.add(owner.sub)
            if sum(owner.enabled for owner in doc.owners) > 1:
                raise ValueError("pilot permits one enabled owner")
            return doc
        except (OSError, ValueError, ValidationError) as exc:
            raise AuthDependencyUnavailable("admission_unavailable") from exc

    def admit(self, subject: str, granted_scopes: frozenset[str]) -> Admission:
        doc = self.load()
        if not subject.strip() or len(subject) > 512 or subject in doc.disabled_subjects:
            raise AdmissionDenied("subject_not_admitted")
        if self.mode == "authenticated_private":
            project_id = private_project_for(self.issuer, subject, self.project_id)
            return Admission(
                principal_for(self.issuer, subject, project_id), doc.version,
                granted_scopes, granted_scopes & self.enabled_scopes, project_id,
            )
        for owner in doc.owners:
            if owner.sub == subject and owner.enabled:
                return Admission(
                    owner.principal_id, doc.version, granted_scopes,
                    granted_scopes & frozenset(owner.allowed_scopes) & self.enabled_scopes,
                )
        raise AdmissionDenied("subject_not_admitted")

    def validate_tools(self, names: set[str], *, catalog: str = "legacy") -> None:
        catalogs = {
            "legacy": TOOL_SCOPES,
            "ordinary-memory-v1": ORDINARY_CATALOG_TOOL_SCOPES,
            "compact-memory-v1": COMPACT_CATALOG_TOOL_SCOPES,
        }
        if catalog not in catalogs:
            raise ValueError("unknown MCP tool catalog")
        expected = catalogs[catalog]
        if names != set(expected):
            raise ValueError("codex-full tool scope mapping is incomplete")

    @staticmethod
    def allows_tool(name: str, scopes: set[str]) -> bool:
        if name not in ALL_TOOL_SCOPES:
            return False
        required = TOOL_SCOPE_ALTERNATIVES.get(name, frozenset({ALL_TOOL_SCOPES[name]}))
        return bool(required & scopes)
