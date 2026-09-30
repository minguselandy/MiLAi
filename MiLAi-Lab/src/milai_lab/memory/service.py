"""Opt-in grounded records in the ordinary Store, with immutable captured evidence.

The initial backend is the public SQLite Store SDK. A revision is one item write:
current content, history, proposals and receipts cannot be partly committed. All
cooperating service writers must use the same resource lock; legacy writers must
not concurrently mutate this isolated namespace. No cross-system exactly-once.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import unicodedata
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from langgraph.store.sqlite import SqliteStore

from milai_lab.contracts.memory import GroundingMode, SourceEvent, VerifiedObjectRef


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _body_hash(value: Any) -> str:
    return hashlib.sha256((value if isinstance(value, str) else _json(value)).encode()).hexdigest()


def _lexical_tokens(text: str, *, include_cjk_unigrams: bool = False) -> list[str]:
    """Unicode words plus overlapping Han/kana/Hangul bigrams, without a dictionary.

    Multi-character CJK query runs use bigrams rather than common individual
    characters. Candidate unigrams also allow an explicitly single-character
    query. Canonical normalization and case folding apply only to matching;
    original queries and stored bodies are untouched.
    """
    tokens: list[str] = []
    run: list[str] = []
    cjk = False

    def flush() -> None:
        if not run:
            return
        if cjk:
            if include_cjk_unigrams or len(run) == 1:
                tokens.extend(run)
            tokens.extend(run[index] + run[index + 1] for index in range(len(run) - 1))
        else:
            tokens.append("".join(run))
        run.clear()

    for character in unicodedata.normalize("NFC", text.casefold()):
        category = unicodedata.category(character)[0]
        if category in {"L", "N"}:
            is_cjk = unicodedata.name(character, "").startswith(
                (
                    "CJK UNIFIED",
                    "CJK COMPATIBILITY",
                    "HIRAGANA",
                    "KATAKANA",
                    "HALFWIDTH KATAKANA",
                    "HANGUL",
                )
            )
            if run and is_cjk != cjk:
                flush()
            cjk = is_cjk
            run.append(character)
        elif category == "M" and run:
            run.append(character)
        else:
            flush()
    flush()
    return tokens


class MemoryService:
    """One owner, one Store; refs and user events are captured only by trusted code."""

    def __init__(
        self,
        store: SqliteStore,
        namespace: tuple[str, ...],
        owner: str,
        lock_path: Path,
        *,
        mode: GroundingMode = "field_grounded",
    ) -> None:
        if not isinstance(store, SqliteStore):
            raise TypeError("V13_MEMORY_REQUIRES_SQLITE_STORE")
        if mode not in {"ref_only", "field_grounded"} or not owner or not namespace:
            raise ValueError("V13_MEMORY_CONFIGURATION_INVALID")
        if namespace[-1] != owner:
            raise ValueError("V13_MEMORY_OWNER_NAMESPACE_MISMATCH")
        self.store, self.namespace, self.owner = store, namespace, owner
        self.mode, self.lock_path = mode, lock_path.resolve()
        self.sources_namespace = (*namespace, "v13_1_sources")
        self.attempts_namespace = (*namespace, "v13_1_attempts")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def event_id(self, session: str, event_key: str, role: str) -> str:
        if not session or not event_key:
            raise ValueError("V13_SOURCE_IDENTITY_REQUIRED")
        return "src-" + _hash([self.namespace, session, event_key, role])

    def capture_user(self, session: str, event_key: str, content: Any) -> dict[str, Any]:
        """Capture an actual incoming user event, not a model-selected source body."""
        return self._capture(session, event_key, "user", "public_user_message", content, None)

    def capture_tool(
        self,
        session: str,
        event_key: str,
        tool_name: str,
        content: str,
        object_ref: VerifiedObjectRef | None,
    ) -> dict[str, Any]:
        """Trusted application adapter only; this API is never a Host tool."""
        return self._capture(session, event_key, "tool", tool_name, content, object_ref)

    def _capture(
        self,
        session: str,
        event_key: str,
        role: Any,
        origin: str,
        content: Any,
        object_ref: VerifiedObjectRef | None,
    ) -> dict[str, Any]:
        event_id = self.event_id(session, event_key, role)
        if object_ref is not None and (
            object_ref.owner != self.owner
            or object_ref.source_ref != event_id
            or object_ref.id != event_id + ":" + object_ref.external_id
        ):
            raise ValueError("V13_OBJECT_BINDING_MISMATCH")
        body = json.loads(_json(content))
        event: SourceEvent = {
            "event_id": event_id,
            "owner": self.owner,
            "session": session,
            "role": role,
            "origin": origin,
            "content": body,
            "content_sha256": _body_hash(body),
            "observed_at": datetime.now(UTC).isoformat(),
            "object_ref": asdict(object_ref) if object_ref is not None else None,
        }
        with self._locked():
            prior = self.store.get(self.sources_namespace, event_id)
            formed = False
            if prior is not None:
                comparable = {key: value for key, value in event.items() if key != "observed_at"}
                if comparable != {
                    key: value for key, value in prior.value.items() if key != "observed_at"
                }:
                    raise ValueError("V13_SOURCE_EVENT_CHANGED")
                event = cast(SourceEvent, prior.value)
                formed = any(
                    version["source_ref"] == event_id
                    for record in self._rows(self.namespace)
                    for version in record["value"].get("_v13_1", {}).get("history", [])
                )
            else:
                self.store.put(self.sources_namespace, event_id, dict(event), index=False)
        return {
            "ok": True,
            "status": "raw_captured",
            "source_ref": event_id,
            "observed_at": event["observed_at"],
            "formation_status": "formed" if formed else "pending",
            "object_ref": event["object_ref"],
        }

    def source(self, source_ref: str) -> dict[str, Any] | None:
        item = self.store.get(self.sources_namespace, source_ref)
        if item is None or item.value.get("owner") != self.owner:
            return None
        event = item.value
        if event.get("content_sha256") != _body_hash(event.get("content")):
            raise ValueError("V13_SOURCE_INTEGRITY_FAILED")
        return event

    def _rows(self, namespace: tuple[str, ...]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.store.search(namespace, limit=100, offset=offset)
            # Store namespace searches are prefix searches, not owner exact scans.
            rows.extend(
                {"id": item.key, "value": item.value}
                for item in page
                if item.namespace == namespace
            )
            if len(page) < 100:
                return rows
            offset += len(page)

    def sources(self, session: str | None = None) -> list[dict[str, Any]]:
        with self._locked():
            records = self._rows(self.namespace)
            result = []
            for row in self._rows(self.sources_namespace):
                event = self.source(row["id"])
                if event is None or (session is not None and event["session"] != session):
                    continue
                formed = any(
                    version["source_ref"] == row["id"]
                    for record in records
                    for version in record["value"].get("_v13_1", {}).get("history", [])
                )
                result.append({**event, "formation_status": "formed" if formed else "pending"})
            return sorted(result, key=lambda event: (event["observed_at"], event["event_id"]))

    def _validate(self, proposal: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
        if (
            not isinstance(proposal.get("content"), str)
            or proposal.get("kind") not in {"semantic", "episodic"}
            or not isinstance(proposal.get("scope"), dict)
            or proposal.get("basis")
            not in {"user_statement", "tool_observation", "plan", "inference"}
            or not isinstance(proposal.get("fields"), dict)
        ):
            return "invalid_proposal", None
        if proposal.get("target_resolution_error"):
            return "target_not_unique", None
        if proposal.get("action") == "update" and not proposal.get("id"):
            return "update_target_required", None
        if proposal.get("action") == "create" and proposal.get("id") is not None:
            return "create_must_omit_id", None
        source = self.source(proposal.get("source_ref", ""))
        if source is None:
            return "source_not_found_or_not_owned", None
        if (proposal["basis"] == "user_statement" and source["role"] != "user") or (
            proposal["basis"] == "tool_observation" and source["role"] != "tool"
        ):
            return "source_role_mismatch", source
        ref = source.get("object_ref")
        if proposal.get("object_ref") is not None:
            if (
                ref is None
                or ref["id"] != proposal["object_ref"]
                or ref["owner"] != self.owner
                or ref["source_ref"] != source["event_id"]
            ):
                return "object_ref_not_found_or_not_owned", source
        elif proposal["fields"]:
            return "operational_fields_require_object_ref", source
        if proposal["fields"] and proposal["basis"] != "tool_observation":
            return "operational_fields_require_tool_observation", source
        if self.mode == "field_grounded" and proposal["fields"]:
            assert ref is not None
            for field, value in proposal["fields"].items():
                if field not in {"status", "label_status"}:
                    return "unsupported_operational_field", source
                if not isinstance(value, str) or ref["fields"].get(field) != value:
                    return "field_conflict:" + field, source
        return None, source

    def commit(self, session: str, proposal_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
        """Commit a raw Host proposal; no semantic repair or fabricated result projection."""
        raw = json.loads(_json(proposal))
        if not session or not proposal_id:
            raise ValueError("V13_PROPOSAL_IDENTITY_REQUIRED")
        identity = _hash([session, proposal_id])
        target = raw.get("id") or str(
            uuid.uuid5(uuid.NAMESPACE_URL, _json([self.namespace, session, proposal_id]))
        )
        with self._locked():
            prior = self.store.get(self.namespace, target)
            attempt = self.store.get(self.attempts_namespace, identity)
            metadata = prior.value.get("_v13_1") if prior is not None else None
            previous = next(
                (
                    row["value"].get("_v13_1", {}).get("proposals", {})[identity]
                    for row in self._rows(self.namespace)
                    if identity in row["value"].get("_v13_1", {}).get("proposals", {})
                ),
                attempt.value if attempt is not None else None,
            )
            if previous is not None:
                if previous["raw"] == raw:
                    receipt = previous["receipt"]
                    return {
                        **receipt,
                        "status": "no_change" if receipt["ok"] else "rejected",
                        "replayed": True,
                        "original_status": receipt["status"],
                    }
                return self._reject(
                    identity + ":" + _hash(raw), raw, target, "proposal_id_conflict", None
                )
            reason, source = self._validate(raw)
            if reason is None and raw.get("id") is not None and prior is None:
                reason = "record_not_found"
            if reason is None and prior is not None and metadata is None:
                reason = "legacy_record_requires_explicit_migration"
            if reason is None and metadata is not None and metadata["owner"] != self.owner:
                reason = "record_not_found"
            revision = (metadata or {}).get("revision", 0)
            expected = raw.get("expected_revision")
            if reason is None and (type(expected) is not int or expected != revision):
                reason = "revision_conflict"
            # One tool receipt may support one record projection. Repeated consumption
            # cannot create a second fact or revise an old record again.
            if reason is None and source is not None and source["role"] == "tool":
                for row in self._rows(self.namespace):
                    for accepted in row["value"].get("_v13_1", {}).get("proposals", {}).values():
                        old = accepted["raw"]
                        if accepted["receipt"]["ok"] and old["source_ref"] == raw["source_ref"]:
                            comparable = (
                                "content",
                                "kind",
                                "scope",
                                "basis",
                                "object_ref",
                                "fields",
                            )
                            if (row["id"] == target or raw.get("id") is None) and all(
                                old.get(k) == raw.get(k) for k in comparable
                            ):
                                receipt = {**accepted["receipt"], "status": "no_change"}
                                return self._save_attempt(identity, raw, receipt)
                            reason = "receipt_already_consumed"
                            break
            if reason is not None:
                return self._reject(
                    identity,
                    raw,
                    target,
                    reason,
                    prior.value if prior is not None and metadata else None,
                )
            assert source is not None
            version = {
                "revision": revision + 1,
                "content": raw["content"],
                "kind": raw["kind"],
                "scope": raw["scope"],
                "basis": raw["basis"],
                "source_ref": raw["source_ref"],
                "object_ref": raw.get("object_ref"),
                "fields": raw["fields"],
                "mode": self.mode,
                "content_verification": "unchecked",
                "source_status": "captured",
                "fields_verification": "receipt_matched"
                if self.mode == "field_grounded" and raw["fields"]
                else "unchecked",
                "observed_at": source["observed_at"],
                "committed_at": datetime.now(UTC).isoformat(),
                "session": session,
            }
            receipt = {
                "ok": True,
                "status": "committed",
                "id": target,
                "revision": revision + 1,
                "source_ref": raw["source_ref"],
                "formation_status": "host_proposed",
                "content_verification": "unchecked",
                "fields_verification": version["fields_verification"],
                "effect": "memory_only",
                "mode": self.mode,
            }
            history = [*(metadata or {}).get("history", []), version]
            proposals = {
                **(metadata or {}).get("proposals", {}),
                identity: {"raw": raw, "receipt": receipt},
            }
            value = {
                "content": raw["content"],
                "_v13_1": {
                    "revision": revision + 1,
                    "current": version,
                    "history": history,
                    "proposals": proposals,
                    "owner": self.owner,
                },
            }
            # No embedding is needed to durably capture or commit. A failed put raises;
            # callers must never translate it to a successful save receipt.
            self.store.put(self.namespace, target, value, index=False)
            return receipt

    def _save_attempt(
        self, identity: str, raw: dict[str, Any], receipt: dict[str, Any]
    ) -> dict[str, Any]:
        self.store.put(
            self.attempts_namespace, identity, {"raw": raw, "receipt": receipt}, index=False
        )
        return receipt

    def _reject(
        self,
        identity: str,
        raw: dict[str, Any],
        target: str,
        reason: str,
        prior: dict[str, Any] | None,
    ) -> dict[str, Any]:
        receipt = {
            "ok": False,
            "status": "rejected",
            "reason": reason,
            "id": target,
            "revision": prior["_v13_1"]["revision"] if prior else None,
            "effect": "none",
            "content_verification": "unchecked",
        }
        if prior is None:
            return self._save_attempt(identity, raw, receipt)
        prior["_v13_1"]["proposals"][identity] = {"raw": raw, "receipt": receipt}
        self.store.put(self.namespace, target, prior, index=False)
        return receipt

    def read(self, memory_id: str, revision: int | None = None) -> dict[str, Any]:
        item = self.store.get(self.namespace, memory_id)
        if item is None:
            return {"ok": False, "status": "not_found", "id": memory_id}
        metadata = item.value.get("_v13_1")
        if metadata is None:
            return {
                "ok": revision is None,
                "status": "legacy_source_unknown",
                "id": memory_id,
                "value": item.value if revision is None else None,
                "source_status": "unknown",
                "content_verification": "unchecked",
            }
        if metadata["owner"] != self.owner:
            return {"ok": False, "status": "not_found", "id": memory_id}
        version = (
            metadata["current"]
            if revision is None
            else next((row for row in metadata["history"] if row["revision"] == revision), None)
        )
        return {
            "ok": version is not None,
            "status": "found" if version else "revision_not_found",
            "id": memory_id,
            "value": version,
            "observation_only": True,
        }

    def records(self) -> list[dict[str, Any]]:
        """Current material only; capture/attempt subnamespaces are not memory records."""
        return [self.read(row["id"]) for row in self._rows(self.namespace)]

    def search(
        self, query: str, limit: int = 10, *, dense: bool = False, include_raw: bool = True
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("V13_SEARCH_LIMIT_INVALID")
        degradation = None
        if dense:
            try:
                page = self.store.search(self.namespace, query=query, limit=limit)
                rows = [self.read(item.key) for item in page if item.namespace == self.namespace]
                if rows:
                    return {
                        "ok": True,
                        "status": "found",
                        "retrieval": "dense",
                        "records": rows,
                        "raw_events": [],
                    }
                degradation = "dense_no_indexed_results"
            except Exception as error:
                degradation = "dense_unavailable:" + type(error).__name__
        tokens = _lexical_tokens(query)
        enumerate_bank = not query.strip()
        records = self.records()
        raw = self.sources() if include_raw else []

        def rank(row: dict[str, Any]) -> int:
            text_tokens = set(_lexical_tokens(_json(row), include_cjk_unigrams=True))
            return sum(token in text_tokens for token in tokens)

        records = sorted(
            (row for row in records if row["ok"] and (enumerate_bank or rank(row))),
            key=lambda row: (-rank(row), row["id"]),
        )[:limit]
        raw = sorted(
            (row for row in raw if enumerate_bank or rank(row)),
            key=lambda row: (-rank(row), row["event_id"]),
        )[:limit]
        return {
            "ok": True,
            "status": "found" if records or raw else "no_results",
            "retrieval": "raw_keyword",
            "degraded": degradation is not None,
            "degradation_reason": degradation,
            "records": records,
            "raw_events": raw,
        }
