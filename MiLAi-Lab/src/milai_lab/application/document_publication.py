"""Opt-in versioned draft, approval and publication over the existing SQLite world.

Publication is a durable audience-specific artifact, not a renamed label. A
draft edit invalidates its approval; every mutation checks the actual current
version/digest. Public history and discovery preserve older versions and effects.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from milai_lab.application.world import ApplicationWorld
from milai_lab.contracts.memory import RECEIPT_PROFILES

DOCUMENT_FIELDS = RECEIPT_PROFILES["document_publication_v1"]["fields"]
DOCUMENT_NAMES = (
    "create_or_update_draft",
    "approve_document_version",
    "publish_approved_document",
    "get_document_status",
)
DOCUMENT_MUTATIONS = frozenset(DOCUMENT_NAMES[:-1])
DOCUMENT_EFFECTS = {
    "create_or_update_draft": {
        "draft_created": "confirmed",
        "draft_updated": "confirmed",
        "draft_unchanged": "none",
        "stale_document_version": "none",
        "content_digest_conflict": "none",
        "invalid_arguments": "none",
    },
    "approve_document_version": {
        "document_approved": "confirmed",
        "already_approved": "none",
        "stale_document_version": "none",
        "content_digest_conflict": "none",
        "not_found": "none",
        "invalid_arguments": "none",
    },
    "publish_approved_document": {
        "document_published": "confirmed",
        "already_published": "none",
        "publish_service_unavailable": "none",
        "approval_required": "none",
        "stale_approval": "none",
        "stale_document_version": "none",
        "content_digest_conflict": "none",
        "not_found": "none",
        "invalid_arguments": "none",
    },
    "get_document_status": {"found": "observed", "not_found": "observed"},
}


def content_digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def document_sources(op: dict[str, Any]) -> list[str]:
    value = op.get("document_from")
    return value if isinstance(value, list) else [value] if isinstance(value, str) else []


class DocumentPublicationWorld(ApplicationWorld):
    def __init__(self, path: Path, publication_available: bool = True) -> None:
        if type(publication_available) is not bool:
            raise ValueError("DOCUMENT_AVAILABILITY_INVALID")
        super().__init__(path, True)
        with self.conn:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS documents (document_id TEXT PRIMARY KEY, "
                "user_id TEXT NOT NULL,title TEXT NOT NULL,document_version INTEGER NOT NULL, "
                "content TEXT NOT NULL,content_digest TEXT NOT NULL,UNIQUE(user_id,title))"
            )
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS document_versions (document_id TEXT, "
                "document_version INTEGER,content TEXT NOT NULL,content_digest TEXT NOT NULL, "
                "origin TEXT NOT NULL,created_at TEXT NOT NULL,"
                "PRIMARY KEY(document_id,document_version))"
            )
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS document_approvals (document_id TEXT, "
                "document_version INTEGER,content_digest TEXT NOT NULL,approved_at TEXT NOT NULL, "
                "PRIMARY KEY(document_id,document_version))"
            )
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS document_publications (document_id TEXT, "
                "document_version INTEGER,content_digest TEXT NOT NULL,audience TEXT NOT NULL, "
                "content TEXT NOT NULL,published_at TEXT NOT NULL, "
                "PRIMARY KEY(document_id,document_version,audience))"
            )
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS document_events "
                "(event_id TEXT PRIMARY KEY,parameters TEXT NOT NULL,result TEXT NOT NULL)"
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO settings VALUES('publication_available',?)",
                (int(publication_available),),
            )

    def _document(self, owner: str, title: str) -> sqlite3.Row | None:
        return cast(sqlite3.Row | None, self.conn.execute(
            "SELECT * FROM documents WHERE user_id=? AND title=?", (owner, title)
        ).fetchone())

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self.tool_lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            yield

    def _public(self, row: sqlite3.Row) -> dict[str, Any]:
        document_id, version = row["document_id"], row["document_version"]
        versions = [
            dict(value)
            for value in self.conn.execute(
                "SELECT document_version,content,content_digest,origin,created_at "
                "FROM document_versions "
                "WHERE document_id=? ORDER BY document_version",
                (document_id,),
            )
        ]
        approvals = [
            dict(value)
            for value in self.conn.execute(
                "SELECT document_version,content_digest,approved_at FROM document_approvals "
                "WHERE document_id=? ORDER BY document_version",
                (document_id,),
            )
        ]
        publications = [
            dict(value)
            for value in self.conn.execute(
                "SELECT document_version,content_digest,audience,content,published_at "
                "FROM document_publications "
                "WHERE document_id=? ORDER BY document_version,published_at,audience",
                (document_id,),
            )
        ]
        approval = next(
            (
                value
                for value in approvals
                if value["document_version"] == version
                and value["content_digest"] == row["content_digest"]
            ),
            None,
        )
        current = [
            value
            for value in publications
            if value["document_version"] == version
            and value["content_digest"] == row["content_digest"]
        ]
        return {
            "document_id": document_id,
            "title": row["title"],
            "content": row["content"],
            "document_version": version,
            "content_digest": row["content_digest"],
            "approval_status": "approved"
            if approval
            else "invalidated"
            if approvals
            else "not_approved",
            "approved_digest": approval["content_digest"] if approval else "",
            "approved_version": approval["document_version"] if approval else None,
            "publication_status": "published" if current else "not_published",
            "published_digest": current[-1]["content_digest"] if current else "",
            "published_version": current[-1]["document_version"] if current else None,
            "audience": current[-1]["audience"] if current else "",
            "versions": versions,
            "approvals": approvals,
            "publications": publications,
        }

    def _result(self, ok: bool, status: str, row: sqlite3.Row | None, **extra: Any) -> str:
        return self._receipt(ok=ok, status=status, **(self._public(row) if row else {}), **extra)

    @staticmethod
    def _version_error(row: sqlite3.Row, version: int, digest: str) -> str | None:
        if type(version) is not int or version != row["document_version"]:
            return "stale_document_version"
        return "content_digest_conflict" if digest != row["content_digest"] else None

    def create_or_update_draft(
        self,
        user_id: str,
        title: str,
        content: str,
        document_version: int = 0,
        content_digest: str = "",
    ) -> str:
        with self._transaction():
            return self._draft(user_id, title, content, document_version, content_digest, "user")

    def _draft(
        self, owner: str, title: str, content: str, version: int, digest: str, origin: str
    ) -> str:
        if not all(type(value) is str and value for value in (owner, title, content)):
            return self._result(False, "invalid_arguments", None)
        row = self._document(owner, title)
        if row is None:
            if type(version) is not int or version != 0 or digest != "":
                return self._result(False, "stale_document_version", None, title=title)
            document_id, next_version = "DOC-" + str(uuid.uuid4()), 1
            self.conn.execute(
                "INSERT INTO documents VALUES(?,?,?,?,?,?)",
                (document_id, owner, title, next_version, content, content_digest(content)),
            )
            status = "draft_created"
        else:
            if error := self._version_error(row, version, digest):
                return self._result(False, error, row)
            if row["content"] == content:
                return self._result(True, "draft_unchanged", row)
            document_id, next_version = row["document_id"], version + 1
            self.conn.execute(
                "UPDATE documents SET document_version=?,content=?,content_digest=? "
                "WHERE document_id=?",
                (next_version, content, content_digest(content), document_id),
            )
            status = "draft_updated"
        self.conn.execute(
            "INSERT INTO document_versions VALUES(?,?,?,?,?,?)",
            (
                document_id,
                next_version,
                content,
                content_digest(content),
                origin,
                datetime.now(UTC).isoformat(),
            ),
        )
        return self._result(True, status, self._document(owner, title))

    def get_document_status(self, user_id: str, title: str) -> str:
        with self._transaction():
            row = self._document(user_id, title)
            return self._result(
                bool(row), "found" if row else "not_found", row, **({} if row else {"title": title})
            )

    def approve_document_version(
        self, user_id: str, title: str, document_version: int, content_digest: str
    ) -> str:
        with self._transaction():
            row = self._document(user_id, title)
            if row is None:
                return self._result(False, "not_found", None, title=title)
            if error := self._version_error(row, document_version, content_digest):
                return self._result(False, error, row)
            if self._public(row)["approval_status"] == "approved":
                return self._result(False, "already_approved", row)
            self.conn.execute(
                "INSERT INTO document_approvals VALUES(?,?,?,?)",
                (
                    row["document_id"],
                    document_version,
                    content_digest,
                    datetime.now(UTC).isoformat(),
                ),
            )
            return self._result(True, "document_approved", row)

    def publish_approved_document(
        self, user_id: str, title: str, document_version: int, content_digest: str, audience: str
    ) -> str:
        with self._transaction():
            row = self._document(user_id, title)
            if row is None:
                return self._result(False, "not_found", None, title=title)
            if type(audience) is not str or not audience:
                return self._result(False, "invalid_arguments", row)
            if error := self._version_error(row, document_version, content_digest):
                return self._result(False, error, row)
            state = self._public(row)
            if state["approval_status"] != "approved":
                return self._result(
                    False, "stale_approval" if state["approvals"] else "approval_required", row
                )
            if any(
                value["document_version"] == document_version
                and value["content_digest"] == content_digest
                and value["audience"] == audience
                for value in state["publications"]
            ):
                return self._result(False, "already_published", row)
            available = self.conn.execute(
                "SELECT value FROM settings WHERE name='publication_available'"
            ).fetchone()
            if not available["value"]:
                return self._result(False, "publish_service_unavailable", row)
            self.conn.execute(
                "INSERT INTO document_publications VALUES(?,?,?,?,?,?)",
                (
                    row["document_id"],
                    document_version,
                    content_digest,
                    audience,
                    row["content"],
                    datetime.now(UTC).isoformat(),
                ),
            )
            return self._result(True, "document_published", row)

    def apply_backend_event(
        self,
        event_id: str,
        *,
        available: bool | None = None,
        edit: dict[str, str] | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        if (
            not event_id
            or (available is None and edit is None)
            or (available is not None and type(available) is not bool)
        ):
            raise ValueError("DOCUMENT_BACKEND_EVENT_INVALID")
        if edit is not None and (
            set(edit) != {"title", "content"}
            or not owner
            or any(type(value) is not str or not value for value in edit.values())
        ):
            raise ValueError("DOCUMENT_BACKEND_EDIT_INVALID")
        parameters = json.dumps(
            {"available": available, "edit": edit, "owner": owner if edit else None}, sort_keys=True
        )
        with self._transaction():
            prior = self.conn.execute(
                "SELECT * FROM document_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if prior:
                if prior["parameters"] != parameters:
                    raise ValueError("APPLICATION_WORLD_EVENT_CHANGED")
                return cast(dict[str, Any], json.loads(prior["result"]))
            result: dict[str, Any] = {}
            if edit is not None:
                row = self._document(str(owner), edit["title"])
                if row is None:
                    raise ValueError("DOCUMENT_BACKEND_EDIT_TARGET_NOT_FOUND")
                result["edit_receipt"] = json.loads(
                    self._draft(
                        str(owner),
                        edit["title"],
                        edit["content"],
                        row["document_version"],
                        row["content_digest"],
                        "collaborator",
                    )
                )
            if available is not None:
                self.conn.execute(
                    "UPDATE settings SET value=? WHERE name='publication_available'",
                    (int(available),),
                )
                result["publication_available"] = available
            self.conn.execute(
                "INSERT INTO document_events VALUES(?,?,?)",
                (event_id, parameters, json.dumps(result)),
            )
            return result

    def set_publication_available(self, event_id: str, available: bool) -> None:
        self.apply_backend_event(event_id, available=available)

    def snapshot(self) -> dict[str, Any]:
        return {
            "publication_available": bool(
                self.conn.execute(
                    "SELECT value FROM settings WHERE name='publication_available'"
                ).fetchone()["value"]
            ),
            "documents": [
                {"owner": row["user_id"], **self._public(row)}
                for row in self.conn.execute("SELECT * FROM documents ORDER BY user_id,title")
            ],
            "backend_events": [
                dict(row)
                for row in self.conn.execute("SELECT * FROM document_events ORDER BY rowid")
            ],
        }


def document_schemas() -> list[dict[str, Any]]:
    result = []
    for name in DOCUMENT_NAMES:
        properties: dict[str, Any] = {
            "title": {
                "type": "string",
                "description": "Exact public document title for the current owner.",
            }
        }
        required = ["title"]
        if name == "create_or_update_draft":
            properties["content"] = {
                "type": "string",
                "description": "Exact user-authorized draft body; never repair or substitute it.",
            }
            required.append("content")
        if name != "get_document_status":
            properties.update(
                document_version={"type": "integer", "minimum": 0},
                content_digest={"type": "string"},
            )
            if name == "create_or_update_draft":
                (
                    properties["document_version"]["default"],
                    properties["content_digest"]["default"],
                ) = 0, ""
            else:
                required.extend(["document_version", "content_digest"])
        if name == "publish_approved_document":
            properties["audience"] = {
                "type": "string",
                "description": "Exact user-authorized publication audience.",
            }
            required.append("audience")
        descriptions = {
            "create_or_update_draft": (
                "Save an actual draft. Create with version0/empty digest; edit using actual "
                "observed current version/digest. Edits invalidate approval; unchanged body "
                "has no new version."),
            "approve_document_version": (
                "Approve exactly the observed current document version/digest. Approval "
                "does not publish. A stale version/digest is rejected."),
            "publish_approved_document": (
                "Publish the approved current version/digest to the authorized audience. "
                "Stale/missing approval, unavailable publication or a duplicate returns no "
                "effect; draft/approval may remain."),
            "get_document_status": (
                "Read actual current draft, digest, approval/publication and original "
                "version/approval/audience publication history for this owner. No mutation."),
        }
        result.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": descriptions[name],
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                },
            }
        )
    return result


def validate_document_operation(op: dict[str, Any]) -> None:
    target, args, tool = op["target"], op["args"], op["tool"]
    if set(target) != {"title"} or type(target["title"]) is not str or not target["title"]:
        raise ValueError("DOCUMENT_AUTHORITY_TARGET_INVALID")
    if "effect_contract" in op or "reservation_from" in op:
        raise ValueError("DOCUMENT_NATIVE_CONTRACT_FIXED")
    keys = {"title"}
    if tool == "create_or_update_draft":
        keys.add("content")
    if tool == "publish_approved_document":
        keys.add("audience")
    sources = document_sources(op)
    if "document_from" in op and (
        not sources
        or len(set(sources)) != len(sources)
        or any(
            type(value) is not str or not value or value == op["operation_id"] for value in sources
        )
    ):
        raise ValueError("DOCUMENT_OBSERVATION_BINDING_INVALID")
    if tool == "get_document_status" and sources:
        raise ValueError("DOCUMENT_QUERY_MUST_USE_TITLE")
    if not sources and tool != "get_document_status":
        if tool != "create_or_update_draft":
            raise ValueError("DOCUMENT_MUTATION_REQUIRES_OBSERVATION")
        keys |= {"document_version", "content_digest"}
        if (
            type(args.get("document_version")) is not int
            or args["document_version"] != 0
            or args.get("content_digest") != ""
        ):
            raise ValueError("DOCUMENT_CREATE_REQUIRES_ZERO_VERSION")
    if (
        set(args) != keys
        or args.get("title") != target["title"]
        or any(
            type(args.get(key)) is not str or not args[key]
            for key in keys - {"document_version", "content_digest"}
        )
    ):
        raise ValueError("DOCUMENT_AUTHORITY_ARGUMENTS_INVALID")
    if "recovery_retry" in op:
        query_id = op.get("recovery_query_operation_id")
        if (
            tool != "publish_approved_document"
            or op["recovery_retry"] != "confirmed_no_effect_v1"
            or op.get("retry") != "no_effect"
            or type(query_id) is not str
            or not query_id
            or op.get("recovery_precondition") != {"status": "found", "approval_status": "approved"}
        ):
            raise ValueError("DOCUMENT_RECOVERY_RETRY_CONTRACT_INVALID")
    elif "recovery_query_operation_id" in op or "recovery_precondition" in op:
        raise ValueError("DOCUMENT_RECOVERY_RETRY_CONTRACT_INVALID")


def publication_matches(observation: dict[str, Any], args: dict[str, Any]) -> bool:
    return any(
        all(
            value.get(key) == args.get(key)
            for key in ("document_version", "content_digest", "audience")
        )
        for value in observation.get("publications", [])
    )


def document_recovery_effect(
    original: dict[str, Any], observation: dict[str, Any], matched: bool, binding: dict[str, Any]
) -> str:
    exclusive = all(
        binding.get("recovery", {}).get(field) is True
        for field in ("absence_means_no_effect", "no_deletion", "exclusive_writer")
    )
    if observation.get("status") == "not_found":
        return "none" if exclusive else "unknown"
    if observation.get("status") != "found" or not matched:
        return "unknown"
    args = original["args"]
    same = all(
        observation.get(key) == args.get(key) for key in ("document_version", "content_digest")
    )
    if original["name"] == "publish_approved_document":
        if publication_matches(observation, args):
            return "confirmed"
        return (
            "none"
            if same and exclusive and observation.get("approval_status") == "approved"
            else "unknown"
        )
    if original["name"] == "approve_document_version":
        if same and observation.get("approval_status") == "approved":
            return "confirmed"
        return "none" if same and exclusive else "unknown"
    wanted = content_digest(args["content"])
    if (
        observation.get("document_version") == args.get("document_version", 0) + 1
        and observation.get("content_digest") == wanted
    ):
        return "confirmed"
    return "none" if same and exclusive else "unknown"
