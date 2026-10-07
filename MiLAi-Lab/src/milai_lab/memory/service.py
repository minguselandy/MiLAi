"""Opt-in grounded records in the ordinary Store, with immutable captured evidence.

The initial backend is the public SQLite Store SDK. A revision is one item write:
current content, history, proposals and receipts cannot be partly committed. All
cooperating service writers must use the same resource lock; legacy writers must
not concurrently mutate this isolated namespace. No cross-system exactly-once.
"""

from __future__ import annotations

import fcntl
import json
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from langgraph.store.sqlite import SqliteStore

from milai_lab.contracts.memory import (
    RECEIPT_PROFILES,
    GroundingMode,
    ObservationProfile,
    SourceEvent,
    VerifiedObjectRef,
)
from milai_lab.contracts.public_memory_contracts import profile as public_profile
from milai_lab.contracts.read_protocol import profile, reject
from milai_lab.memory.functional_state import (
    FunctionalIntegrityError,
    FunctionalOperationError,
    FunctionalRejection,
)
from milai_lab.memory.observation import (
    PROJECTOR_VERSION,
    ObservationError,
    derive_observations,
    profile_identity,
)
from milai_lab.memory.observation import (
    observation_view as field_observation_view,
)
from milai_lab.memory.retrieval import SemanticRetriever, semantic_text


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def reference_key(identifiers: Any) -> str:
    """A readable key of explicit IDs/versions, never a content fingerprint."""
    return _json(identifiers)


def _receipt_json(content: str) -> Any:
    """Read declared JSON without silently discarding duplicate literal claims."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_receipt_key")
            result[key] = value
        return result

    def invalid_constant(value: str) -> Any:
        raise ValueError("non_json_constant:" + value)

    return json.loads(content, object_pairs_hook=unique_object, parse_constant=invalid_constant)


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
        receipt_contract: str = "optional",
        operational_projection: str = "enabled",
        receipt_profile: str = "reservation_v1",
        mutation_contract: str = "legacy",
        source_backlinks: str = "disabled",
        candidate_contract: str | None = None,
        support_contract: str = "legacy",
        memory_read_protocol: str = "legacy",
        tool_read_feedback: str = "legacy",
        tool_save_communication: str = "legacy",
        tool_parameter_contract: str = "legacy",
        observation_capture_feedback: str = "legacy",
        functional_contract: str = "legacy",
        observer: Callable[[dict[str, Any]], None] | None = None,
        semantic_retriever: SemanticRetriever | None = None,
        memory_profile: str = "ordinary",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if functional_contract == "functional_v1":
            mutation_contract = (
                "event_bound_v1" if mutation_contract == "legacy" else mutation_contract
            )
            candidate_contract = candidate_contract or "read_handle_v1"
            support_contract = (
                "direct_support_v1" if support_contract == "legacy" else support_contract
            )
            memory_read_protocol = (
                "selected_snapshot_v1" if memory_read_protocol == "legacy" else memory_read_protocol
            )
            source_backlinks = "enabled"
        if not isinstance(store, SqliteStore):
            raise TypeError("V13_MEMORY_REQUIRES_SQLITE_STORE")
        if mode not in {"ref_only", "field_grounded"} or not owner or not namespace:
            raise ValueError("V13_MEMORY_CONFIGURATION_INVALID")
        if namespace[-1] != owner:
            raise ValueError("V13_MEMORY_OWNER_NAMESPACE_MISMATCH")
        self.store, self.namespace, self.owner = store, namespace, owner
        self.semantic_retriever = semantic_retriever
        self._thread_lock = threading.RLock()
        self._lock_depth = 0
        self.memory_profile = memory_profile
        self.clock = clock or (lambda: datetime.now(UTC))
        self.mode, self.lock_path = mode, lock_path.resolve()
        self.receipt_contract = self.validate_receipt_contract(receipt_contract)
        self.mutation_contract = self.validate_mutation_contract(mutation_contract)
        if type(source_backlinks) is not str or source_backlinks not in {"disabled", "enabled"}:
            raise ValueError("V13_SOURCE_BACKLINKS_INVALID")
        self.source_backlinks = source_backlinks
        explicit_candidate_contract = candidate_contract
        if candidate_contract is None:
            candidate_contract = (
                "read_handle_v1"
                if self.mutation_contract == "event_bound_v1"
                else "legacy_query_v1"
            )
        if type(candidate_contract) is not str or candidate_contract not in {
            "legacy_query_v1",
            "id_revision_v1",
            "read_handle_v1",
        }:
            raise ValueError("V13_CANDIDATE_CONTRACT_INVALID")
        self.candidate_contract = candidate_contract
        if functional_contract not in {"legacy", "functional_v1"}:
            raise ValueError("V13_5_FUNCTIONAL_CONTRACT_INVALID")
        if functional_contract == "functional_v1" and (
            self.mutation_contract != "event_bound_v1" or candidate_contract != "read_handle_v1"
        ):
            raise ValueError("V13_5_FUNCTIONAL_REQUIRES_BOUND_READ_HANDLE")
        self.functional_contract = functional_contract
        self._uncertain_captures: set[str] = set()
        if type(support_contract) is not str or support_contract not in {
            "legacy",
            "direct_support_v1",
        }:
            raise ValueError("V13_MEMORY_SUPPORT_CONTRACT_INVALID")
        if support_contract != "legacy" and (
            mutation_contract != "event_bound_v1" or explicit_candidate_contract != "read_handle_v1"
        ):
            raise ValueError("V13_DIRECT_SUPPORT_REQUIRES_EVENT_BOUND_READ_HANDLE")
        self.support_contract = support_contract
        self.tool_parameter_contract = public_profile(
            "tool_parameter_contract", tool_parameter_contract
        )
        self.observation_capture_feedback = public_profile(
            "observation_capture_feedback", observation_capture_feedback
        )
        self.memory_read_protocol = profile("memory_read_protocol", memory_read_protocol)
        self.tool_read_feedback = profile("tool_read_feedback", tool_read_feedback)
        self.tool_save_communication = profile("tool_save_communication", tool_save_communication)
        if self.memory_read_protocol != "legacy" and (
            mutation_contract != "event_bound_v1" or explicit_candidate_contract != "read_handle_v1"
        ):
            raise ValueError("V13_SELECTED_SNAPSHOT_REQUIRES_BOUND_READ_HANDLE")
        if type(receipt_profile) is not str or receipt_profile not in RECEIPT_PROFILES:
            raise ValueError("V13_MEMORY_RECEIPT_PROFILE_INVALID")
        self.receipt_profile = receipt_profile
        self.receipt_fields: dict[str, str] = RECEIPT_PROFILES[receipt_profile]["fields"]
        if type(operational_projection) is not str or operational_projection not in {
            "enabled",
            "disabled",
        }:
            raise ValueError("V13_OPERATIONAL_PROJECTION_INVALID")
        self.operational_projection = operational_projection
        self.observer = observer
        self.sources_namespace = (*namespace, "v13_1_sources")
        self.attempts_namespace = (*namespace, "v13_1_attempts")
        self.candidates_namespace = (*namespace, "v13_2_candidates")
        self.observations_namespace = (*namespace, "v13_2_observations")
        self.projections_namespace = (*namespace, "v13_2_projections")
        self.backlinks_namespace = (*namespace, "v13_2_backlinks")
        self._source_boundaries: dict[str, tuple[str, list[str]]] = {}
        self.turns_namespace = (*namespace, "v13_2_public_turns")
        self._public_turns: dict[str, dict[str, Any]] = {}
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate_receipt_contract(value: Any) -> str:
        if not isinstance(value, str) or value not in ("optional", "explicit_receipt_v1"):
            raise ValueError("V13_MEMORY_RECEIPT_CONTRACT_INVALID")
        return value

    @staticmethod
    def validate_mutation_contract(value: Any) -> str:
        if type(value) is not str or value not in {"legacy", "event_bound_v1"}:
            raise ValueError("V13_MEMORY_MUTATION_CONTRACT_INVALID")
        return value

    def bind_source_boundary(
        self, session: str, boundary_id: str, source_refs: list[str], *, append: bool = False
    ) -> None:
        """Trusted runner binding to actual events, never a latest-role lookup.

        A tool batch uses its generating message identity as boundary_id; all
        observed events in that batch accumulate rather than selecting its last
        completion. A new public user message starts a new singleton boundary.
        This transient binding is established again from actual input on reopen.
        """
        if self.mutation_contract != "event_bound_v1":
            return
        if not session or not boundary_id or not source_refs:
            raise ValueError("V13_SOURCE_BOUNDARY_REQUIRED")
        with self._locked():
            for source_ref in source_refs:
                event = self.source(source_ref)
                if (
                    event is None
                    and self.functional_contract == "functional_v1"
                    and source_ref == self.event_id(session, boundary_id, "user")
                    and self.store.get(self.turns_namespace, reference_key([session, boundary_id]))
                ):
                    event = self._source(source_ref, binding_only=True)
                if event is None or event["session"] != session:
                    raise ValueError("V13_SOURCE_BOUNDARY_SCOPE_MISMATCH")
            prior_id, prior_refs = self._source_boundaries.get(session, ("", []))
            refs = prior_refs if append and prior_id == boundary_id else []
            self._source_boundaries[session] = (
                boundary_id,
                list(dict.fromkeys([*refs, *source_refs])),
            )

    def bind_public_turn(
        self,
        session: str,
        message_id: str,
        source_ref: str,
        *,
        config_version: str | None = None,
        phase: str,
        config_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Bind an actual input to its immutable source and ordinary configuration version.

        The old keyword is accepted as an opaque version for historical callers;
        it is neither recomputed nor interpreted as a content digest.
        """
        config_version = config_version or config_sha256
        if (
            (self.support_contract != "direct_support_v1" and self.memory_read_protocol == "legacy")
            or not session
            or not message_id
            or phase not in {"start", "resume"}
            or not isinstance(config_version, str)
            or not config_version
        ):
            raise ValueError("V13_PUBLIC_TURN_BINDING_INVALID")
        with self._locked():
            key = reference_key([session, message_id])
            prior = self.store.get(self.turns_namespace, key)
            source = self._source(source_ref, binding_only=True)
            if (
                source is None
                or source["session"] != session
                or source["role"] != "user"
                or source_ref != self.event_id(session, message_id, "user")
            ):
                raise ValueError("V13_PUBLIC_TURN_SOURCE_MISMATCH")
            if phase == "resume" and prior is None:
                raise ValueError("V13_PUBLIC_TURN_RESUME_MISSING")
            bound = {
                "owner": self.owner,
                "bank": list(self.namespace),
                "session": session,
                "message_id": message_id,
                "source_ref": source_ref,
                "source_revision": source.get("source_revision", 1),
                "config_version": config_version,
                "support_contract": self.support_contract,
                "origin_phase": "start",
                "trigger_ref": (
                    prior.value["binding"]["trigger_ref"] if prior else "turn-" + str(uuid.uuid4())
                ),
            }
            if prior is not None and prior.value.get("binding") != bound:
                raise ValueError("V13_PUBLIC_TURN_IDENTITY_CHANGED")
            self.store.put(
                self.turns_namespace,
                key,
                {"binding": bound, "last_binding_phase": phase},
                index=False,
            )
            self._public_turns[session] = bound
            return cast(dict[str, Any], json.loads(_json(bound)))

    def public_turn(
        self,
        session: str,
        *,
        message_id: str | None = None,
        config_version: str | None = None,
        config_sha256: str | None = None,
    ) -> dict[str, Any] | None:
        """Resolve the explicit current binding; no latest-event fallback."""
        config_version = config_version or config_sha256
        bound = self._public_turns.get(session)
        if (
            bound is None
            or (message_id is not None and message_id != bound["message_id"])
            or (config_version is not None and config_version != bound["config_version"])
        ):
            return None
        item = self.store.get(self.turns_namespace, reference_key([session, bound["message_id"]]))
        source = self._source(bound["source_ref"], binding_only=True)
        if (
            item is None
            or item.value.get("binding") != bound
            or source is None
            or source["role"] != "user"
            or source["session"] != session
            or source.get("source_revision", 1) != bound["source_revision"]
        ):
            return None
        return cast(dict[str, Any], json.loads(_json(bound)))

    def active_public_input(
        self,
        session: str,
        message_id: str,
        config_version: str,
    ) -> dict[str, Any] | None:
        """The exact in-flight input remains usable for continuation after forgetting."""
        bound = self.public_turn(session, message_id=message_id, config_version=config_version)
        if bound is None:
            item = self.store.get(self.turns_namespace, reference_key([session, message_id]))
            if (
                item is None
                or item.value["binding"]["config_version"] != config_version
                or item.value["binding"]["source_ref"] != self.event_id(session, message_id, "user")
            ):
                return None
            bound = self.bind_public_turn(
                session,
                message_id,
                item.value["binding"]["source_ref"],
                config_version=config_version,
                phase="resume",
            )
        return self._source(bound["source_ref"], binding_only=True)

    def semantic_receipts_for_turn(self, session: str) -> list[dict[str, Any]]:
        """Actual successful Host semantic commits, not whole-turn coverage."""
        bound = self.public_turn(session)
        if bound is None:
            return []
        return [
            entry["receipt"]
            for row in self._rows(self.namespace)
            if row["value"].get("_v13_1", {}).get("owner") == self.owner
            for entry in row["value"].get("_v13_1", {}).get("proposals", {}).values()
            if entry["receipt"].get("ok")
            and entry["receipt"].get("effect") == "memory_only"
            and entry["raw"].get("trigger_binding") == bound
        ]

    def argument_ids(self, source: dict[str, Any]) -> dict[str, Any]:
        """Literal companion to this captured DTO; never changes Source or selects a source."""
        ref = source.get("object_ref")
        return {
            "source_ref": source["event_id"],
            "role": source["role"],
            "source_revision": source.get("source_revision", 1),
            "tool_argument_ids": {"object_ref": ref["id"]} if ref else {},
            "body_visibility": "metadata_only",
            "content_verification": "unchecked",
        }

    def boundary_sources(self, session: str) -> list[str]:
        """Only explicitly bound current events; history cannot fill a missing binding."""
        with self._locked():
            return list(self._source_boundaries.get(session, ("", []))[1])

    def source_boundary(
        self,
        session: str,
        *,
        cursor: str | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        """Page a persisted source-ID snapshot, bound to the actual current input."""
        if type(limit) is not int or not 1 <= limit <= 6:
            raise ValueError("V13_SOURCE_INDEX_LIMIT_INVALID")
        with self._locked():
            boundary_id, refs = self._source_boundaries.get(session, ("", []))
            snapshot_ns = (*self.namespace, "source_index_snapshots")
            start = 0
            if cursor is None:
                members = []
                for ref in refs:
                    event = self.source(ref)
                    if event is None or event["session"] != session:
                        raise ValueError("V13_SOURCE_BOUNDARY_SCOPE_MISMATCH")
                    member = {
                        "source_ref": ref,
                        "role": event["role"],
                        "source_revision": event.get("source_revision", 1),
                        "origin": event["origin"],
                        "observed_at": event["observed_at"],
                    }
                    if self.support_contract == "direct_support_v1":
                        member["tool_argument_ids"] = self.argument_ids(event)["tool_argument_ids"]
                    members.append(member)
                snapshot_id = "sources-" + str(uuid.uuid4())
                value = {
                    "owner": self.owner,
                    "session": session,
                    "boundary_id": boundary_id,
                    "members": members,
                }
                self.store.put(snapshot_ns, snapshot_id, value, index=False)
            else:
                snapshot_id, sep, offset = cursor.rpartition(":")
                stored = self.store.get(snapshot_ns, snapshot_id)
                if (
                    sep != ":"
                    or not offset.isdecimal()
                    or stored is None
                    or stored.value.get("owner") != self.owner
                    or stored.value.get("session") != session
                    or stored.value.get("boundary_id") != boundary_id
                ):
                    reject(
                        "V13_SOURCE_INDEX_CURSOR_CHANGED_OR_INVALID",
                        "memory_service",
                        self.tool_read_feedback,
                    )
                value, start = stored.value, int(offset)
                members = cast(list[dict[str, Any]], value["members"])
                if not 0 <= start < len(members):
                    reject(
                        "V13_SOURCE_INDEX_CURSOR_CHANGED_OR_INVALID",
                        "memory_service",
                        self.tool_read_feedback,
                    )
                if any(self.source(member["source_ref"]) is None for member in members):
                    reject(
                        "V13_SELECTED_SNAPSHOT_REVOKED", "memory_service", self.tool_read_feedback
                    )
            end = min(start + limit, len(members))
            return {
                "owner": self.owner,
                "boundary_ref": boundary_id or None,
                "members": members[start:end],
                "snapshot_id": snapshot_id,
                "content_verification": "unchecked",
                "member_count": len(members),
                "start": start,
                "omitted_count": len(members) - end,
                "next_cursor": snapshot_id + ":" + str(end) if end < len(members) else None,
            }

    @staticmethod
    def _version_source_refs(version: dict[str, Any]) -> list[str]:
        return cast(list[str], version.get("source_refs", [version["source_ref"]]))

    def _source_bindings(self, source_refs: list[str]) -> list[dict[str, Any]] | None:
        bindings = []
        for source_ref in source_refs:
            event = self.source(source_ref)
            if event is None:
                return None
            bindings.append(
                {
                    "source_ref": source_ref,
                    "role": event["role"],
                    "source_revision": event.get("source_revision", 1),
                }
            )
        return bindings

    @staticmethod
    def _reference_bindings(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Read historical digest-bearing bindings without interpreting their digests."""
        return [
            {
                "source_ref": row["source_ref"],
                "role": row["role"],
                "source_revision": row.get("source_revision", 1),
            }
            for row in bindings
        ]

    def _issue_candidate(self, record_id: str, version: dict[str, Any]) -> str:
        bindings = self._source_bindings(self._version_source_refs(version))
        if bindings is None:
            raise ValueError("V13_CANDIDATE_SUPPORT_UNAVAILABLE")
        if "source_bindings" in version and bindings != self._reference_bindings(
            version["source_bindings"]
        ):
            raise ValueError("V13_CANDIDATE_SUPPORT_CHANGED")
        bound = {
            "owner": self.owner,
            "namespace": list(self.namespace),
            "record_id": record_id,
            "revision": version["revision"],
            "support_sources": bindings,
        }
        handle = "read:" + reference_key(
            [self.namespace, self.owner, record_id, version["revision"]]
        )
        prior = self.store.get(self.candidates_namespace, handle)
        if prior is not None and prior.value != bound:
            raise ValueError("V13_CANDIDATE_HANDLE_COLLISION")
        if prior is None:
            self.store.put(self.candidates_namespace, handle, bound, index=False)
        return handle

    def candidate(self, handle: str | None) -> dict[str, Any] | None:
        """Resolve only an issued owner-bound read-time version, including after reopen."""
        if not isinstance(handle, str):
            return None
        item = self.store.get(self.candidates_namespace, handle)
        if item is None:
            return None
        bound = item.value
        if bound.get("owner") != self.owner or bound.get("namespace") != list(self.namespace):
            return None
        if self._functional_hidden(record_id=bound["record_id"]):
            return None
        bindings = self._source_bindings([row["source_ref"] for row in bound["support_sources"]])
        if bindings is None or bindings != self._reference_bindings(bound["support_sources"]):
            return None
        item = self.store.get(self.namespace, bound["record_id"])
        metadata = item.value.get("_v13_1", {}) if item is not None else {}
        version = next(
            (row for row in metadata.get("history", []) if row["revision"] == bound["revision"]),
            None,
        )
        if (
            metadata.get("owner") != self.owner
            or version is None
            or self._version_source_refs(version) != [row["source_ref"] for row in bindings]
        ):
            return None
        return bound

    def candidate_for_version(self, memory_id: str, revision: int) -> str | None:
        """Ablation ID+revision interface still resolves only an issued read version."""
        for row in self._rows(self.candidates_namespace):
            bound = row["value"]
            if bound.get("record_id") == memory_id and bound.get("revision") == revision:
                if self.candidate(row["id"]) is not None:
                    return str(row["id"])
        return None

    def backlink_candidates(self, source_refs: list[str], limit: int = 6) -> list[dict[str, Any]]:
        """Source-to-record discovery from authoritative revision references.

        The small existing backend scans history; no fingerprint cache is necessary.
        Discovery never chooses a semantic target or grants write permission.
        """
        if self.source_backlinks != "enabled":
            return []
        if not 1 <= limit <= 100:
            raise ValueError("V13_SEARCH_LIMIT_INVALID")
        sources = {ref: source for ref in source_refs if (source := self.source(ref)) is not None}
        matches: dict[str, list[dict[str, Any]]] = {}
        with self._locked():
            for row in self._rows(self.namespace):
                metadata = row["value"].get("_v13_1", {})
                if metadata.get("owner") != self.owner:
                    continue
                for ref, source in sources.items():
                    revisions = [
                        v["revision"]
                        for v in metadata["history"]
                        if ref in self._version_source_refs(v)
                    ]
                    if revisions:
                        matches.setdefault(row["id"], []).append(
                            {
                                "source_ref": ref,
                                "source_revision": source.get("source_revision", 1),
                                "matched_revisions": revisions[:6],
                                "matched_revision_count": len(revisions),
                                "omitted_matched_revision_count": max(0, len(revisions) - 6),
                                "read_more": {
                                    "tool": "read_memory",
                                    "id": row["id"],
                                    "view": "history",
                                    "source_ref": ref,
                                },
                            }
                        )
        result = []
        for record_id in sorted(matches)[:limit]:
            row = self.read(record_id)
            if row["ok"]:
                selected = [
                    {
                        **m,
                        "current_revision_at_read": row["value"]["revision"],
                        "current_version_cites_source": m["source_ref"]
                        in self._version_source_refs(row["value"]),
                        "content_verification": "unchecked",
                    }
                    for m in matches[record_id]
                ]
                row.update(
                    source_matches=selected[:6],
                    source_match_count=len(selected),
                    omitted_source_match_count=max(0, len(selected) - 6),
                    source_matches_read_more={
                        "tool": "read_memory",
                        "id": record_id,
                        "view": "history",
                    },
                )
            result.append(row)
        return result

    def history_index(
        self,
        memory_id: str,
        *,
        cursor: str | None = None,
        limit: int = 6,
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        """Enumerate actual owner-bound stored revisions; this grants no write authority."""
        if type(limit) is not int or not 1 <= limit <= 6:
            raise ValueError("V13_HISTORY_INDEX_LIMIT_INVALID")
        if self._functional_hidden(record_id=memory_id):
            return {"ok": False, "status": "visibility_revoked", "id": memory_id}
        item = self.store.get(self.namespace, memory_id)
        metadata = item.value.get("_v13_1") if item is not None else None
        if item is None or (metadata is not None and metadata.get("owner") != self.owner):
            return {"ok": False, "status": "not_found", "id": memory_id}
        if metadata is None:
            return {
                "ok": True,
                "status": "history_unavailable",
                "id": memory_id,
                "revision_count": None,
                "revisions": [],
                "omitted_count": None,
                "content_verification": "unchecked",
            }
        versions = sorted(metadata["history"], key=lambda row: row["revision"])
        if self.functional_contract == "functional_v1":
            versions = [
                version
                for version in versions
                if not any(
                    self._functional_hidden(source_ref=ref)
                    for ref in self._version_source_refs(version)
                )
            ]
        source = self.source(source_ref) if source_ref is not None else None
        if source_ref is not None:
            if source is None:
                raise ValueError("V13_HISTORY_SOURCE_NOT_FOUND")
            versions = [row for row in versions if source_ref in self._version_source_refs(row)]
        revisions = [version["revision"] for version in versions]
        if len(set(revisions)) != len(revisions) or any(
            type(revision) is not int or revision < 1 for revision in revisions
        ):
            raise ValueError("V13_HISTORY_INDEX_INVALID")
        snapshot_ns = (*self.namespace, "history_index_snapshots")
        start = 0
        if cursor is None:
            snapshot_id = "history-" + str(uuid.uuid4())
            snapshot = {
                "owner": self.owner,
                "record_id": memory_id,
                "source_ref": source_ref,
                "revisions": revisions,
                "current_revision": metadata["revision"],
            }
            self.store.put(snapshot_ns, snapshot_id, snapshot, index=False)
        else:
            snapshot_id, separator, offset = cursor.rpartition(":")
            stored = self.store.get(snapshot_ns, snapshot_id)
            if (
                separator != ":"
                or not offset.isdecimal()
                or stored is None
                or stored.value.get("owner") != self.owner
                or stored.value.get("record_id") != memory_id
                or stored.value.get("source_ref") != source_ref
            ):
                reject(
                    "V13_HISTORY_CURSOR_CHANGED_OR_INVALID",
                    "memory_service",
                    self.tool_read_feedback,
                )
            snapshot = stored.value
            revisions = snapshot["revisions"]
            # Later appends do not alter the issued history page. Revocation still applies.
            available = {v["revision"] for v in versions}
            if not set(revisions) <= available:
                reject("V13_SELECTED_SNAPSHOT_REVOKED", "memory_service", self.tool_read_feedback)
            start = int(offset)
            if not 0 <= start < len(revisions):
                reject(
                    "V13_HISTORY_CURSOR_CHANGED_OR_INVALID",
                    "memory_service",
                    self.tool_read_feedback,
                )
        end = min(start + limit, len(revisions))
        return {
            "ok": True,
            "status": "available",
            "id": memory_id,
            "current_revision_at_snapshot": snapshot["current_revision"],
            "revision_count": len(revisions),
            "revisions": revisions[start:end],
            "start": start,
            "omitted_count": len(revisions) - end,
            "index_kind": "source_citations" if source_ref is not None else "stored_history",
            "source_ref": source_ref,
            "source_revision": source.get("source_revision", 1) if source else None,
            "snapshot_id": snapshot_id,
            "next_cursor": snapshot_id + ":" + str(end) if end < len(revisions) else None,
            "content_verification": "unchecked",
            "business_authority": False,
        }

    def revise(
        self,
        session: str,
        proposal_id: str,
        candidate_handle: str,
        semantic_patch: dict[str, Any],
        source_refs: list[str] | None = None,
        *,
        operation: str = "revise",
        field_support: dict[str, Any] | None = None,
        trigger_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Small semantic patch over the version actually read; observed literals are immutable."""
        requested = {
            "candidate_handle": candidate_handle,
            "semantic_patch": semantic_patch,
            "source_refs": source_refs,
            "operation": operation,
        }
        if self.support_contract == "direct_support_v1":
            requested.update(field_support=field_support, trigger_binding=trigger_binding)

        def rejected(reason: str) -> dict[str, Any]:
            identity = reference_key([session, proposal_id])
            with self._locked():
                return self._save_attempt(
                    identity,
                    {"requested": requested},
                    {
                        "ok": False,
                        "status": "rejected",
                        "reason": reason,
                        "effect": "none",
                        "formation_status": "pending",
                        "raw_preserved": True,
                        "content_verification": "unchecked",
                        "id": None,
                        "revision": None,
                    },
                )

        if source_refs is None:
            if self.support_contract == "direct_support_v1":
                return rejected("source_selection_required")
            source_refs = self.boundary_sources(session)
            if len(source_refs) != 1:
                return rejected("source_selection_required")

        try:
            bound = self.candidate(candidate_handle)
        except ValueError:
            if self.support_contract != "direct_support_v1":
                raise
            return rejected("candidate_support_integrity_failed")
        if bound is None:
            return rejected("candidate_handle_required_or_invalid")
        if (
            operation not in {"revise", "supersede", "no_change"}
            or not isinstance(semantic_patch, dict)
            or not semantic_patch.keys() <= {"content", "scope", "basis", "kind"}
            or not source_refs
        ):
            return rejected("invalid_semantic_patch")
        version = self.read(bound["record_id"], bound["revision"])["value"]
        scope = semantic_patch.get("scope", {})
        if not isinstance(scope, dict):
            return rejected("invalid_semantic_patch")
        proposal = {
            "action": "update",
            "id": bound["record_id"],
            "expected_revision": bound["revision"],
            "candidate_handle": candidate_handle,
            "source_ref": source_refs[0],
            "source_refs": source_refs,
            "content": semantic_patch.get("content", version["content"]),
            "kind": semantic_patch.get("kind", version["kind"]),
            "scope": {**version["scope"], **scope},
            "basis": semantic_patch.get("basis", version["basis"]),
            "fields": {},
            "object_ref": None,
            "patch_operation": operation,
            "requested": requested,
        }
        if self.support_contract == "direct_support_v1":
            proposal.update(field_support=field_support, trigger_binding=trigger_binding)
        if self.functional_contract == "functional_v1" and all(
            _json(proposal[field]) == _json(version[field])
            for field in ("content", "kind", "scope", "basis")
        ):
            proposal["patch_operation"] = "no_change"
        return self.commit(session, proposal_id, proposal)

    def _field_lineage(
        self,
        raw: dict[str, Any],
        metadata: dict[str, Any] | None,
    ) -> tuple[str | None, dict[str, Any]]:
        """Validate model-selected leaf sets and explicit byte-equal whole-field reuse."""
        selection = raw.get("field_support")
        fields = {"content", "scope", "basis", "kind"}
        if not isinstance(selection, dict) or selection.keys() != fields:
            return "field_support_required", {}
        result: dict[str, Any] = {}
        for field in sorted(fields):
            entry = selection[field]
            if not isinstance(entry, dict):
                return "field_support_invalid", {}
            reused = None
            attribution = "model_selected"
            if entry.keys() == {"source_refs"}:
                refs = entry["source_refs"]
            elif entry.keys() == {"reuse_support_from"}:
                handle = entry["reuse_support_from"]
                bound = self.candidate(handle)
                if (
                    metadata is None
                    or bound is None
                    or handle != raw.get("candidate_handle")
                    or bound["record_id"] != raw.get("id")
                    or bound["revision"] != metadata["revision"]
                ):
                    return "field_support_candidate_mismatch", {}
                version = metadata["current"]
                if field not in version or _json(raw[field]) != _json(version[field]):
                    return "field_support_changed_field", {}
                old = version.get("field_support", {}).get(field)
                refs = old["source_refs"] if old else self._version_source_refs(version)
                old_bindings = old["source_bindings"] if old else version.get("source_bindings")
                if old_bindings is None or self._source_bindings(refs) != self._reference_bindings(
                    old_bindings
                ):
                    return "field_support_source_changed", {}
                attribution = "reused_equal_whole_field"
                reused = {
                    "candidate_handle": handle,
                    "record_id": bound["record_id"],
                    "revision": bound["revision"],
                    "field": field,
                    "lineage_scope": "field_map" if old else "legacy_whole_version_set",
                }
            else:
                return "field_support_invalid", {}
            if (
                not isinstance(refs, list)
                or not refs
                or not all(isinstance(r, str) for r in refs)
                or len(set(refs)) != len(refs)
                or not set(refs) <= set(raw["source_refs"])
            ):
                return "field_support_selected_leaves_required", {}
            bindings = self._source_bindings(refs)
            if bindings is None:
                return "source_not_found_or_not_owned", {}
            result[field] = {
                "source_refs": refs,
                "source_bindings": bindings,
                "attribution": attribution,
                "content_verification": "unchecked",
            }
            if reused is not None:
                result[field]["reused_from"] = reused
        return None, result

    def semantic_receipts(self, source_ref: str) -> list[dict[str, Any]]:
        """Successful semantic submissions citing one owner-checked actual source."""
        if self.source(source_ref) is None:
            return []
        return [
            entry["receipt"]
            for row in self._rows(self.namespace)
            if row["value"].get("_v13_1", {}).get("owner") == self.owner
            for entry in row["value"].get("_v13_1", {}).get("proposals", {}).values()
            if entry["receipt"]["ok"]
            and source_ref in entry["raw"].get("source_refs", [entry["raw"].get("source_ref")])
        ]

    @staticmethod
    def _projection_id(source_ref: str, profile: ObservationProfile) -> str:
        return "projection:" + reference_key(
            [source_ref, profile.profile_id, profile.adapter_version, PROJECTOR_VERSION]
        )

    def observe(self, source_ref: str, profile: ObservationProfile) -> dict[str, Any]:
        """Derive only real source literals, with detectable pending and idempotent replay.

        The public Store has no multi-item transaction here. A complete marker
        follows verified fact writes; partial writes remain invisible in the
        complete view and can be replayed without repeating any business tool.
        """
        if self.mutation_contract != "event_bound_v1":
            raise ValueError("V13_OBSERVATION_REQUIRES_EVENT_BOUND")
        profile_version = profile_identity(profile)
        projection_id = self._projection_id(source_ref, profile)
        initial_source = self.source(source_ref)
        if initial_source is None:
            return {
                "ok": False,
                "status": "rejected",
                "reason": "source_not_found_or_not_owned",
                "effect": "none",
            }
        initial_binding = {
            "owner": self.owner,
            "source_event_id": source_ref,
            "source_revision": initial_source.get("source_revision", 1),
            "adapter_id": profile.profile_id,
            "adapter_version": profile.adapter_version,
            "adapter_ref": profile_version,
            "projector_version": PROJECTOR_VERSION,
        }
        with self._locked():
            # A public adapter version identifies one immutable mapping. Compare
            # only when registering that version, rather than fingerprinting facts.
            adapters_ns = (*self.namespace, "observation_adapters")
            adapter = self.store.get(adapters_ns, profile_version)
            definition = json.loads(_json(asdict(profile)))
            if adapter is not None and adapter.value["definition"] != definition:
                return {
                    "ok": False,
                    "status": "rejected",
                    "effect": "none",
                    "reason": "projection_binding_changed",
                    "projection_id": projection_id,
                }
            if adapter is None:
                self.store.put(
                    adapters_ns,
                    profile_version,
                    {"adapter_ref": profile_version, "definition": definition},
                    index=False,
                )
            initial_projection = self.store.get(self.projections_namespace, projection_id)
            if initial_projection is not None and any(
                initial_projection.value.get(key) != value for key, value in initial_binding.items()
            ):
                return {
                    "ok": False,
                    "status": "rejected",
                    "reason": "projection_binding_changed",
                    "projection_id": projection_id,
                    "effect": "none",
                }
            if initial_projection is None:
                # A real kill at W2 must leave a public, profile-bound dirty witness.
                witness = {
                    **initial_binding,
                    "status": "pending",
                    "receipt": {
                        "ok": False,
                        "status": "pending",
                        "projection_id": projection_id,
                        "source_ref": source_ref,
                        "source_revision": initial_source.get("source_revision", 1),
                        "projector_version": PROJECTOR_VERSION,
                        "raw_preserved": True,
                        "effect": "memory_projection_only",
                        "current_verified": False,
                        "reason": "projection_not_started",
                    },
                }
                self.store.put(self.projections_namespace, projection_id, witness, index=False)
                persisted = self.store.get(self.projections_namespace, projection_id)
                if persisted is None or persisted.value != witness:
                    raise RuntimeError("V13_PROJECTION_PENDING_NOT_VISIBLE")
        if self.observer is not None and (
            initial_projection is None or initial_projection.value["status"] != "complete"
        ):
            # Driver evidence can read the service; callbacks run outside its lock.
            self.observer(
                {
                    "event": "v13_observation_boundary",
                    "phase": "source_persisted",
                    "source_ref": source_ref,
                    "projection_id": projection_id,
                }
            )
        with self._locked():
            source = self.source(source_ref)
            if source is None:
                return {
                    "ok": False,
                    "status": "rejected",
                    "reason": "source_not_found_or_not_owned",
                    "effect": "none",
                }
            item = self.store.get(self.projections_namespace, projection_id)
            prior = item.value if item is not None else None
            binding = {
                "owner": self.owner,
                "source_event_id": source_ref,
                "source_revision": source.get("source_revision", 1),
                "adapter_id": profile.profile_id,
                "adapter_version": profile.adapter_version,
                "adapter_ref": profile_version,
                "projector_version": PROJECTOR_VERSION,
            }
            if prior is not None and any(prior.get(key) != value for key, value in binding.items()):
                return {
                    "ok": False,
                    "status": "rejected",
                    "reason": "projection_binding_changed",
                    "projection_id": projection_id,
                    "effect": "none",
                }
            receipt: dict[str, Any] = {
                "ok": False,
                "status": "pending",
                "projection_id": projection_id,
                "source_ref": source_ref,
                "source_revision": source.get("source_revision", 1),
                "projector_version": PROJECTOR_VERSION,
                "raw_preserved": True,
                "effect": "memory_projection_only",
                "current_verified": False,
            }
            try:
                facts, outcome = derive_observations(source, profile)
            except ObservationError as error:
                receipt.update(reason=str(error), observation_count=0)
                if prior is None or prior.get("status") != "complete":
                    self.store.put(
                        self.projections_namespace,
                        projection_id,
                        {**binding, "status": "pending", "receipt": receipt},
                        index=False,
                    )
                return receipt
            facts = [{**fact, "projection_id": projection_id} for fact in facts]
            fact_ids = [fact["observation_id"] for fact in facts]
            receipt["expected_observation_count"] = len(facts)
            if prior is not None and prior.get("status") == "complete":
                if prior.get("observation_ids") == fact_ids and all(
                    self.store.get(self.observations_namespace, fact_id) is not None
                    for fact_id in fact_ids
                ):
                    return {
                        **prior["receipt"],
                        "status": "no_change",
                        "replayed": True,
                        "original_status": prior["receipt"]["status"],
                    }
            pending = {
                **binding,
                "status": "pending",
                "observation_ids": fact_ids,
                "receipt": receipt,
                "outcome": outcome,
            }
            # Persist the recovery witness before any independent fact writes.
            self.store.put(self.projections_namespace, projection_id, pending, index=False)
            try:
                for fact in facts:
                    existing = self.store.get(self.observations_namespace, fact["observation_id"])
                    if existing is not None and existing.value != fact:
                        raise ValueError("V13_OBSERVATION_IDENTITY_CHANGED")
                    if existing is None:
                        self.store.put(
                            self.observations_namespace, fact["observation_id"], fact, index=False
                        )
                    written = self.store.get(self.observations_namespace, fact["observation_id"])
                    if written is None or written.value != fact:
                        raise RuntimeError("V13_OBSERVATION_WRITE_NOT_VISIBLE")
                receipt.update(
                    ok=True,
                    status="observed_unknown" if outcome == "unknown" else "projected",
                    observation_count=len(facts),
                    outcome=outcome,
                )
                complete = {
                    **pending,
                    "status": "complete",
                    "observation_ids": fact_ids,
                    "receipt": receipt,
                }
                self.store.put(self.projections_namespace, projection_id, complete, index=False)
                readback = self.store.get(self.projections_namespace, projection_id)
                if readback is None or readback.value != complete:
                    raise RuntimeError("V13_PROJECTION_COMMIT_NOT_VISIBLE")
            except Exception as error:
                receipt.pop("observation_count", None)
                receipt.update(
                    ok=False,
                    status="pending",
                    reason="projection_write_incomplete",
                    error_type=type(error).__name__,
                    error=str(error),
                )
                pending = {**pending, "observation_ids": fact_ids, "receipt": receipt}
                self.store.put(self.projections_namespace, projection_id, pending, index=False)
                pending_witness = self.store.get(self.projections_namespace, projection_id)
                if pending_witness is None or pending_witness.value != pending:
                    raise RuntimeError("V13_PROJECTION_PENDING_NOT_VISIBLE") from error
                return receipt
        if self.observer is not None:
            self.observer(
                {
                    "event": "v13_observation_boundary",
                    "phase": "projection_committed",
                    "source_ref": source_ref,
                    "projection_id": projection_id,
                    "receipt": receipt,
                }
            )
        return receipt

    def projection_receipt(
        self, source_ref: str, profile: ObservationProfile
    ) -> dict[str, Any] | None:
        if self._functional_hidden(source_ref=source_ref):
            return None
        item = self.store.get(self.projections_namespace, self._projection_id(source_ref, profile))
        return item.value["receipt"] if item is not None else None

    def observations(self) -> dict[str, Any]:
        """Only complete verified projections; dirty events and unknown outcomes stay explicit."""
        with self._locked():
            facts, pending, unknown = [], [], []
            for marker in self._rows(self.projections_namespace):
                state = marker["value"]
                if state["owner"] != self.owner:
                    continue
                if self._functional_hidden(source_ref=state["source_event_id"]):
                    continue
                source = self.source(state["source_event_id"])
                if source is None or source.get("source_revision", 1) != state.get(
                    "source_revision", 1
                ):
                    raise ValueError("V13_OBSERVATION_SOURCE_CHANGED")
                if state["status"] != "complete":
                    pending.append(state["receipt"])
                    continue
                collected = []
                for fact_id in state.get("observation_ids", state.get("fact_sha256", {})):
                    item = self.store.get(self.observations_namespace, fact_id)
                    if item is None or item.value.get("projection_id") != marker["id"]:
                        raise ValueError("V13_OBSERVATION_COMMIT_INCOMPLETE")
                    collected.append(item.value)
                facts.extend(collected)
                if state["outcome"] == "unknown":
                    unknown.append(state["receipt"])
            return {
                "ok": True,
                "observations": sorted(facts, key=lambda row: row["observation_id"]),
                "objects": field_observation_view(facts),
                "pending": pending,
                "unknown": unknown,
                "current_verified": False,
            }

    def selected_observation_member(
        self,
        observation_id: str,
        object_id: str,
        field: str,
    ) -> dict[str, Any]:
        """Exact selected member/projection reads; no latest view or bank enumeration."""
        if self.memory_read_protocol != "selected_snapshot_v1":
            raise ValueError("V13_SELECTED_SNAPSHOT_PROFILE_REQUIRED")
        with self._locked():
            item = self.store.get(self.observations_namespace, observation_id)
            if item is None:
                raise ValueError("V13_SELECTED_OBSERVATION_UNAVAILABLE")
            fact = item.value
            if (
                fact.get("owner") != self.owner
                or fact.get("observation_id") != observation_id
                or fact.get("object_ref", {}).get("id") != object_id
                or fact.get("field") != field
                or not fact.get("projection_id")
            ):
                raise ValueError("V13_SELECTED_OBSERVATION_BINDING_CHANGED")
            marker = self.store.get(self.projections_namespace, fact["projection_id"])
            state = marker.value if marker is not None else None
            if (
                state is None
                or state.get("owner") != self.owner
                or state.get("status") != "complete"
                or observation_id not in state.get("observation_ids", state.get("fact_sha256", {}))
                or state.get("source_event_id") != fact.get("source_event_id")
                or state.get("source_revision", 1) != fact.get("source_revision", 1)
            ):
                raise ValueError("V13_SELECTED_OBSERVATION_COMMIT_CHANGED")
            source = self.source(fact["source_event_id"])
            if (
                source is None
                or source["role"] != "tool"
                or source.get("source_revision", 1) != fact.get("source_revision", 1)
            ):
                raise ValueError("V13_SELECTED_OBSERVATION_SOURCE_CHANGED")
            return cast(dict[str, Any], json.loads(_json(fact)))

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            if self._lock_depth:
                self._lock_depth += 1
                try:
                    yield
                finally:
                    self._lock_depth -= 1
                return
            with self.lock_path.open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                self._lock_depth = 1
                try:
                    yield
                finally:
                    self._lock_depth = 0
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def event_id(self, session: str, event_key: str, role: str) -> str:
        """Resolve a persisted Source identity from the trusted external capture key."""
        if not session or not event_key:
            raise ValueError("V13_SOURCE_IDENTITY_REQUIRED")
        ns = (*self.namespace, "source_identities")
        key = reference_key([self.owner, session, event_key, role])
        with self._locked():
            prior = self.store.get(ns, key)
            if prior is not None:
                return str(prior.value["source_ref"])
            # Keep IDs issued before this index existed. Do not reconstruct an
            # ID from content or reinterpret old digest-shaped IDs.
            existing = next(
                (
                    row["id"]
                    for row in self._rows(self.sources_namespace)
                    if row["value"].get("owner") == self.owner
                    and row["value"].get("session") == session
                    and row["value"].get("role") == role
                    and row["value"].get("capture_key") == event_key
                ),
                None,
            )
            source_ref = existing or "source-" + str(uuid.uuid4())
            self.store.put(ns, key, {"source_ref": source_ref}, index=False)
            return str(source_ref)

    def capture_user(
        self, session: str, event_key: str, content: Any, *, occurred_at: str | None = None
    ) -> dict[str, Any]:
        """Capture an actual incoming user event, not a model-selected source body."""
        return self._capture(
            session,
            event_key,
            "user",
            "public_user_message",
            content,
            None,
            occurred_at=occurred_at,
        )

    def capture_assistant(
        self, session: str, event_key: str, content: Any, *, occurred_at: str | None = None
    ) -> dict[str, Any]:
        """Trusted actual assistant message; proposals/packets are never original messages."""
        if self.mutation_contract != "event_bound_v1":
            raise ValueError("V13_ASSISTANT_CAPTURE_REQUIRES_EVENT_BOUND")
        if self.functional_contract == "functional_v1":
            from milai_lab.memory.functional_state import namespace, note_exposure

            bound = self.public_turn(session)
            if bound is not None:
                with self._locked():
                    exposed = self.store.get(namespace(self), "exposure:" + bound["source_ref"])
                    note_exposure(
                        self,
                        self.event_id(session, event_key, "assistant"),
                        [
                            bound["source_ref"],
                            *(exposed.value["source_refs"] if exposed is not None else []),
                        ],
                        kind="assistant_output",
                    )
        return self._capture(
            session,
            event_key,
            "assistant",
            "public_assistant_message",
            content,
            None,
            occurred_at=occurred_at,
        )

    def capture_tool(
        self,
        session: str,
        event_key: str,
        tool_name: str,
        content: str,
        object_ref: VerifiedObjectRef | None,
        *,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        """Trusted application adapter only; this API is never a Host tool."""
        return self._capture(
            session, event_key, "tool", tool_name, content, object_ref, occurred_at=occurred_at
        )

    def _capture(
        self,
        session: str,
        event_key: str,
        role: Any,
        origin: str,
        content: Any,
        object_ref: VerifiedObjectRef | None,
        *,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        if occurred_at is not None and (
            not isinstance(occurred_at, str) or not occurred_at.strip()
        ):
            raise ValueError("V13_SOURCE_OCCURRENCE_TIME_INVALID")
        event_id = self.event_id(session, event_key, role)
        if self._functional_hidden(source_ref=event_id):
            actual = self._source(event_id, binding_only=True)
            turn = self.store.get(self.turns_namespace, reference_key([session, event_key]))
            if (
                role == "user"
                and turn is not None
                and actual is not None
                and actual["content"] == json.loads(_json(content))
            ):
                return {
                    "ok": True,
                    "status": "raw_captured",
                    "source_ref": event_id,
                    "formation_status": "visibility_revoked",
                    "effect": "none",
                    "visibility": "current_live_input_only",
                    "replayed": True,
                }
            if role != "assistant":
                return {
                    "ok": False,
                    "status": "visibility_revoked",
                    "source_ref": event_id,
                    "effect": "none",
                    "formation_status": "not_requested",
                }
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
            "source_revision": 1,
            "capture_key": event_key,
            "observed_at": self.clock().isoformat(),
            "object_ref": asdict(object_ref) if object_ref is not None else None,
        }
        if occurred_at is not None:
            event["occurred_at"] = occurred_at
        if self.memory_profile == "unified_v1":
            event["episode_id"] = reference_key([session, event_key, role])
        with self._locked():
            prior = self.store.get(self.sources_namespace, event_id)
            formed = False
            if prior is not None:
                if occurred_at is not None and prior.value.get("occurred_at") != occurred_at:
                    raise ValueError("V13_SOURCE_OCCURRENCE_TIME_CHANGED")
                comparable = {
                    key: dict(event)[key]
                    for key in (
                        "event_id",
                        "owner",
                        "session",
                        "role",
                        "origin",
                        "content",
                        "object_ref",
                    )
                }
                if comparable != {key: prior.value.get(key) for key in comparable}:
                    raise ValueError("V13_SOURCE_EVENT_CHANGED")
                event = cast(
                    SourceEvent,
                    {**prior.value, "source_revision": prior.value.get("source_revision", 1)},
                )
                formed = any(
                    event_id in self._version_source_refs(version)
                    for record in self._rows(self.namespace)
                    for version in record["value"].get("_v13_1", {}).get("history", [])
                )
            else:
                try:
                    self.store.put(self.sources_namespace, event_id, dict(event), index=False)
                except Exception as error:
                    if self.functional_contract != "functional_v1":
                        raise
                    self._uncertain_captures.add(event_id)
                    return {
                        "ok": False,
                        "status": "outcome_unknown",
                        "source_ref": event_id,
                        "formation_status": "not_requested",
                        "effect": "unconfirmed",
                        "error_type": type(error).__name__,
                    }
            if self.functional_contract == "functional_v1":
                from milai_lab.memory.functional_state import namespace

                # A Source put that raises after committing must not issue fragments.
                # An explicit same-event capture on reopen verifies the original input
                # before writing this confirmation; it never invents another event.
                try:
                    self.store.put(
                        namespace(self),
                        "capture:" + event_id,
                        {
                            "source_ref": event_id,
                            "source_revision": event.get("source_revision", 1),
                        },
                        index=False,
                    )
                except Exception as error:
                    self._uncertain_captures.add(event_id)
                    return {
                        "ok": False,
                        "status": "outcome_unknown",
                        "source_ref": event_id,
                        "formation_status": "not_requested",
                        "effect": "unconfirmed",
                        "error_type": type(error).__name__,
                    }
                self._uncertain_captures.discard(event_id)
        episode_id = event.get("episode_id")
        if self.memory_profile == "unified_v1":
            from milai_lab.memory.episodes import EpisodeIndex

            episode_id = episode_id or reference_key([session, event_key, role])
            EpisodeIndex(self).register(episode_id, [event_id])
        return {
            "ok": True,
            "status": "raw_captured",
            "source_ref": event_id,
            "observed_at": event["observed_at"],
            "formation_status": "formed" if formed else "pending",
            "object_ref": event["object_ref"],
            **({"episode_id": episode_id} if episode_id is not None else {}),
            **({"visibility": "revoked"} if self._functional_hidden(source_ref=event_id) else {}),
        }

    def source(self, source_ref: str) -> dict[str, Any] | None:
        return self._source(source_ref)

    def _source(self, source_ref: str, *, binding_only: bool = False) -> dict[str, Any] | None:
        if source_ref in self._uncertain_captures or (
            not binding_only and self._functional_hidden(source_ref=source_ref)
        ):
            return None
        item = self.store.get(self.sources_namespace, source_ref)
        if item is None or item.value.get("owner") != self.owner:
            return None
        event = item.value
        if self.functional_contract == "functional_v1":
            from milai_lab.memory.functional_state import namespace, validate_source

            validate_source(source_ref, event, self.owner)
            confirmation = self.store.get(namespace(self), "capture:" + source_ref)
            if confirmation is None:
                return None
            if confirmation.value.get("source_ref") != source_ref or confirmation.value.get(
                "source_revision", 1
            ) != event.get("source_revision", 1):
                raise FunctionalIntegrityError("V13_5_SOURCE_CAPTURE_CONFIRMATION_CHANGED")
        # Captured Sources are immutable at the service boundary. Historical digest
        # fields may remain in stored evidence but are not recomputed or consulted.
        return event

    def _functional_hidden(
        self,
        *,
        source_ref: str | None = None,
        record_id: str | None = None,
    ) -> bool:
        if self.functional_contract != "functional_v1":
            return False
        from milai_lab.memory.functional_state import visibility

        state = visibility(self)
        return (
            source_ref in state["sources"]
            if source_ref is not None
            else record_id in state["records"]
        )

    def source_fragments(self, source_ref: str, *, max_chars: int = 1200) -> list[dict[str, Any]]:
        """Issue actual original-text fragments; this is provenance, not semantic truth."""
        if self.functional_contract != "functional_v1":
            raise ValueError("V13_5_FUNCTIONAL_CONTRACT_REQUIRED")
        from milai_lab.memory.functional_state import issue_fragments

        with self._locked():
            return issue_fragments(self, source_ref, max_chars)

    def source_fragment_range(self, source_ref: str, start: int, end: int) -> dict[str, Any]:
        """Issue a trusted retriever's exact original range; no model-authored hash or quote."""
        if self.functional_contract != "functional_v1":
            raise ValueError("V13_5_FUNCTIONAL_CONTRACT_REQUIRED")
        from milai_lab.memory.functional_state import issue_fragment_range

        with self._locked():
            return issue_fragment_range(self, source_ref, start, end)

    def source_fragment(self, handle: str) -> dict[str, Any]:
        if self.functional_contract != "functional_v1":
            raise ValueError("V13_5_FUNCTIONAL_CONTRACT_REQUIRED")
        from milai_lab.memory.functional_state import resolve_fragment

        return resolve_fragment(self, handle)

    def note_tool_delivery(self, session: str, message_id: str, source_refs: list[str]) -> None:
        """Record actual tool delivery for future assistant output, not user derivation.

        Called by trusted tool delivery after its receipt is captured. The public
        input already existed before retrieval; it is only the exposure anchor.
        """
        if self.functional_contract != "functional_v1" or not session or not message_id:
            raise ValueError("V13_5_TOOL_DELIVERY_CONTEXT_INVALID")
        from milai_lab.memory.functional_state import note_exposure

        with self._locked():
            public_ref = self.event_id(session, message_id, "user")
            public = self._source(public_ref, binding_only=True)
            if public is None or public.get("role") != "user":
                raise ValueError("V13_5_TOOL_DELIVERY_INPUT_REQUIRED")
            for ref in source_refs:
                source = self.source(ref)
                if source is None or source.get("role") != "tool":
                    raise ValueError("FUNCTIONAL_VISIBLE_TOOL_SOURCE_REQUIRED")
            note_exposure(self, public_ref, source_refs)

    def forgotten_source_refs(self) -> list[str]:
        if self.functional_contract != "functional_v1":
            return []
        from milai_lab.memory.functional_state import visibility

        return list(visibility(self)["sources"])

    @property
    def forget_epoch(self) -> int:
        if self.functional_contract != "functional_v1":
            return 0
        from milai_lab.memory.functional_state import visibility

        return int(visibility(self)["epoch"])

    def forget(
        self,
        session: str,
        operation_id: str,
        candidate_handle: str | None = None,
        *,
        scope: str = "record_and_sources",
        fragment_handles: list[str] | None = None,
        additional_fragment_handles: list[str] | None = None,
    ) -> dict[str, Any]:
        """Revoke declared runtime visibility, never claim physical evidence erasure."""
        if self.functional_contract != "functional_v1":
            raise ValueError("V13_5_FUNCTIONAL_CONTRACT_REQUIRED")
        if not session or not operation_id or scope not in {"record", "record_and_sources"}:
            raise FunctionalRejection("V13_5_FORGET_ARGUMENTS_INVALID")
        from milai_lab.memory.functional_state import fragment_support, namespace, visibility

        key = reference_key([session, operation_id])
        request = {
            "candidate_handle": candidate_handle,
            "scope": scope,
            "fragment_handles": fragment_handles,
            "additional_fragment_handles": additional_fragment_handles,
        }
        with self._locked():
            state = visibility(self)
            previous = state["operations"].get(key)
            if previous is not None:
                if previous["request"] != request:
                    raise FunctionalRejection("V13_5_FORGET_OPERATION_CHANGED")
                return {**previous["receipt"], "replayed": True}
            if (candidate_handle is None) == (fragment_handles is None):
                raise FunctionalRejection("V13_5_FORGET_EXACTLY_ONE_SELECTION_REQUIRED")
            if candidate_handle is not None:
                bound = self.candidate(candidate_handle)
                if bound is None:
                    return {"ok": False, "status": "rejected", "reason": "read_handle_invalid"}
                item = self.store.get(self.namespace, bound["record_id"])
                metadata = item.value["_v13_1"] if item is not None else None
                if metadata is None or metadata["revision"] != bound["revision"]:
                    return {"ok": False, "status": "rejected", "reason": "revision_conflict"}
                refs = list(
                    dict.fromkeys(
                        ref
                        for version in metadata["history"]
                        for ref in self._version_source_refs(version)
                    )
                )
                record_ids = [bound["record_id"]]
            else:
                if scope != "record_and_sources":
                    raise FunctionalRejection("V13_5_SOURCE_FORGET_REQUIRES_SOURCE_SCOPE")
                assert fragment_handles is not None
                refs = fragment_support(self, fragment_handles)["source_refs"]
                record_ids = [
                    row["id"]
                    for row in self._rows(self.namespace)
                    if any(
                        set(refs).intersection(self._version_source_refs(version))
                        for version in row["value"].get("_v13_1", {}).get("history", [])
                    )
                ]
            if additional_fragment_handles is not None:
                if candidate_handle is None or scope != "record_and_sources":
                    raise FunctionalRejection(
                        "V13_5_ADDITIONAL_SOURCE_SCOPE_REQUIRES_RECORD_AND_SOURCES"
                    )
                refs = list(
                    dict.fromkeys(
                        [*refs, *fragment_support(self, additional_fragment_handles)["source_refs"]]
                    )
                )
            revoked = refs if scope == "record_and_sources" else []
            assistant_refs: list[str] = []
            if scope == "record_and_sources":
                trigger = self.public_turn(session)
                revoked = list(
                    dict.fromkeys(
                        [*revoked, *([trigger["source_ref"]] if trigger is not None else [])]
                    )
                )
                # User inputs precede retrieval. Prefetch must never imply that
                # an independent user statement derives from the delivered memory.
                # Generated assistant outputs can actually contain delivered material.
                exposures = [
                    row["value"]
                    for row in self._rows(namespace(self))
                    if row["id"].startswith("exposure:")
                    and row["value"].get("edge_kind") == "assistant_output"
                ]
                changed = True
                while changed:
                    prior_count = len(revoked)
                    assistant_refs = [
                        entry["public_source"]
                        for entry in exposures
                        if set(entry["source_refs"]).intersection(revoked)
                    ]
                    revoked = list(dict.fromkeys([*revoked, *assistant_refs]))
                    changed = len(revoked) != prior_count
            receipt = {
                "ok": True,
                "status": "visibility_revoked",
                "effect": "visibility_only",
                "scope": scope,
                "revoked_ids": record_ids,
                "revoked_source_refs": revoked,
                "forget_epoch": state["epoch"] + 1,
                "source_visibility_scope": "selected_support_trigger_and_assistant_outputs",
                "exposure_semantics": "assistant_output_only_not_user_prefetch",
                "scope_counts": {
                    "selected_records": len(record_ids),
                    "explicit_support_sources": len(refs),
                    "derived_assistant_sources": len(assistant_refs),
                    "revoked_sources": len(revoked),
                },
                "independent_input_copies": "require_explicit_fragment_selection",
                "physical_erasure": False,
                "raw_audit_retained": True,
            }
            state = {
                **state,
                "epoch": receipt["forget_epoch"],
                "records": list(dict.fromkeys([*state["records"], *record_ids])),
                "sources": list(dict.fromkeys([*state["sources"], *revoked])),
                "operations": {
                    **state["operations"],
                    key: {"request": request, "receipt": receipt},
                },
            }
            try:
                self.store.put(namespace(self), "visibility", state, index=False)
            except Exception as error:
                raise FunctionalOperationError("visibility_commit", error) from error
            return receipt

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
                    row["id"] in self._version_source_refs(version)
                    for record in records
                    for version in record["value"].get("_v13_1", {}).get("history", [])
                )
                result.append({**event, "formation_status": "formed" if formed else "pending"})
            return sorted(result, key=lambda event: (event["observed_at"], event["event_id"]))

    def episodes(
        self,
        *,
        episode_ids: list[str] | None = None,
        pending_only: bool = False,
        limit: int | None = 20,
    ) -> list[dict[str, Any]]:
        """Visible source-backed episodes in this same owner's Store."""
        from milai_lab.memory.episodes import EpisodeIndex

        return EpisodeIndex(self).select(
            episode_ids=episode_ids, pending_only=pending_only, limit=limit
        )

    def index_source_episodes(self) -> dict[str, Any]:
        """Add episode indices for visible older sources without recapturing them."""
        from milai_lab.memory.episodes import EpisodeIndex

        index = EpisodeIndex(self)
        results = []
        for source in self.sources():
            episode_id = source.get("episode_id") or reference_key(
                [source["session"], source["capture_key"], source["role"]]
            )
            results.append(index.register(episode_id, [source["event_id"]]))
        return {
            "indexed": len(results),
            "episode_ids": [row["episode_id"] for row in results],
            "new_sources": 0,
            "semantic_records_changed": 0,
        }

    def export_snapshot(self) -> dict[str, Any]:
        """Export this owner's currently visible sources, records and history.

        This is a portable observation of memory, never a business authorization
        or a promise to erase external backups. Execution journals stay separate.
        """
        records = [row for row in self.records() if row["ok"]]
        history = []
        for row in self._rows(self.namespace):
            metadata = row["value"].get("_v13_1")
            if metadata is None or metadata["owner"] != self.owner:
                continue
            versions = [
                self.read(row["id"], version["revision"]) for version in metadata["history"]
            ]
            history.append({"id": row["id"], "versions": [v for v in versions if v["ok"]]})
        return {
            "owner": self.owner,
            "namespace": list(self.namespace),
            "memory_profile": self.memory_profile,
            "sources": self.sources(),
            "records": records,
            "history": history,
            "episodes": self.episodes(limit=None) if self.memory_profile == "unified_v1" else [],
            "visibility_scope": "currently permitted memory only",
            "business_effects": "not established by this export",
        }

    def _uses_explicit_receipt(self, proposal: dict[str, Any], source: dict[str, Any]) -> bool:
        ref = source.get("object_ref")
        return (
            self.receipt_contract == "explicit_receipt_v1"
            and proposal["basis"] == "tool_observation"
            and ref is not None
            and ref.get("application") == RECEIPT_PROFILES[self.receipt_profile]["application"]
        )

    def _receipt_claims(self, proposal: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
        required = set(self.receipt_fields)
        fields = proposal["fields"]
        if not required <= fields.keys():
            return "receipt_fields_required", None
        if fields.keys() != required:
            return "unsupported_operational_field", None
        if not all(self._field_type(key, value) for key, value in fields.items()):
            return "invalid_receipt_fields", None
        if proposal.get("content_format") != "receipt_json_v1":
            return "receipt_content_format_required", None
        try:
            body = _receipt_json(proposal["content"])
        except ValueError:
            return "receipt_body_invalid_json", None
        if (
            not isinstance(body, dict)
            or not required <= body.keys()
            or not body.keys() <= required | {"notes"}
            or not all(self._field_type(key, body[key]) for key in required)
            or ("notes" in body and not isinstance(body["notes"], str))
        ):
            return "receipt_body_invalid_schema", None
        return None, body

    def _field_type(self, key: str, value: Any) -> bool:
        return (
            type(value) is int if self.receipt_fields[key] == "integer" else isinstance(value, str)
        )

    def _validate(self, proposal: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
        if self.mutation_contract == "event_bound_v1" and proposal.get("action") not in {
            "create",
            "update",
        }:
            return "invalid_proposal", None
        if (
            not isinstance(proposal.get("content"), str)
            or proposal.get("kind") not in {"semantic", "episodic"}
            or not isinstance(proposal.get("scope"), dict)
            or proposal.get("basis")
            not in {"user_statement", "tool_observation", "plan", "inference"}
            or not isinstance(proposal.get("fields"), dict)
        ):
            return "invalid_proposal", None
        if proposal.get("edit_state") is not None:
            from milai_lab.memory.edit_units import validate_state

            try:
                validate_state(proposal["edit_state"], self)
            except FunctionalRejection as error:
                return str(error), None
        if proposal.get("target_resolution_error"):
            return "target_not_unique", None
        if proposal.get("binding_error"):
            return str(proposal["binding_error"]), None
        if proposal.get("action") == "update" and not proposal.get("id"):
            return "update_target_required", None
        if proposal.get("action") == "create" and proposal.get("id") is not None:
            return "create_must_omit_id", None
        source = self.source(proposal.get("source_ref", ""))
        if source is None:
            return "source_not_found_or_not_owned", None
        if self.mutation_contract == "event_bound_v1":
            refs = proposal.get("source_refs")
            if (
                not isinstance(refs, list)
                or not refs
                or not all(isinstance(r, str) for r in refs)
                or len(refs) != len(set(refs))
                or proposal["source_ref"] not in refs
            ):
                return "source_selection_required", source
            sources = [self.source(ref) for ref in refs]
            if any(event is None for event in sources):
                return "source_not_found_or_not_owned", source
            role = {"user_statement": "user", "tool_observation": "tool"}.get(proposal["basis"])
            if role is not None and any(event["role"] != role for event in sources if event):
                return "source_role_mismatch", source
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
        body = None
        if self._uses_explicit_receipt(proposal, source):
            reason, body = self._receipt_claims(proposal)
            if reason is not None:
                return reason, source
        if self.mode == "field_grounded" and proposal["fields"]:
            assert ref is not None
            for field, value in proposal["fields"].items():
                if field not in self.receipt_fields:
                    return "unsupported_operational_field", source
                if not self._field_type(field, value) or ref["fields"].get(field) != value:
                    return "field_conflict:" + field, source
            if body is not None:
                for field in self.receipt_fields:
                    if body[field] != proposal["fields"][field]:
                        return "receipt_body_conflict:" + field, source
        return None, source

    def operation_receipt(self, session: str, operation_id: str) -> dict[str, Any] | None:
        """Observe the saved outcome of an old semantic operation without repeating it."""
        identity = reference_key([session, operation_id])
        with self._locked():
            attempt = self.store.get(self.attempts_namespace, identity)
            for row in self._rows(self.namespace):
                metadata = row["value"].get("_v13_1", {})
                if metadata.get("owner") != self.owner:
                    continue
                proposal = metadata.get("proposals", {}).get(identity)
                if proposal is not None:
                    return cast(dict[str, Any], json.loads(_json(proposal["receipt"])))
            if attempt is not None:
                return cast(dict[str, Any], json.loads(_json(attempt.value["receipt"])))
        return None

    def replay_requested(
        self, session: str, proposal_id: str, requested: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Opt-in replay before automatic source/target/revision binding.

        Compare the exact original tool request, not newly resolved state. A changed
        request is preserved as a conflicting attempt. The stored proposal and its
        historical receipt remain intact; this does not execute a second commit.
        """
        if not session or not proposal_id:
            raise ValueError("V13_PROPOSAL_IDENTITY_REQUIRED")
        requested = json.loads(_json(requested))
        identity = reference_key([session, proposal_id])
        with self._locked():
            attempt = self.store.get(self.attempts_namespace, identity)
            previous = next(
                (
                    row["value"].get("_v13_1", {}).get("proposals", {})[identity]
                    for row in self._rows(self.namespace)
                    if row["value"].get("_v13_1", {}).get("owner") == self.owner
                    and identity in row["value"].get("_v13_1", {}).get("proposals", {})
                ),
                attempt.value if attempt is not None else None,
            )
            if previous is None:
                return None
            if previous["raw"].get("requested") != requested:
                raw = {"requested": requested}
                return self._reject(
                    identity + ":conflict:" + str(uuid.uuid4()),
                    raw,
                    previous["receipt"]["id"],
                    "proposal_id_conflict",
                    None,
                )
            receipt = previous["receipt"]
            return {
                **receipt,
                "status": "no_change" if receipt["ok"] else "rejected",
                "replayed": True,
                "original_status": receipt["status"],
            }

    def prepare_proposal(
        self,
        session: str,
        proposal_id: str,
        proposal: dict[str, Any],
    ) -> str:
        """Persist an immutable precommit proposal before optional model review."""
        if not session or not proposal_id:
            raise ValueError("V13_PROPOSAL_IDENTITY_REQUIRED")
        key = reference_key([session, proposal_id])
        ns = (*self.namespace, "prepared_proposals")
        value = {
            "owner": self.owner,
            "session": session,
            "proposal_id": proposal_id,
            "proposal": json.loads(_json(proposal)),
        }
        with self._locked():
            prior = self.store.get(ns, key)
            if prior is not None and prior.value != value:
                raise FunctionalRejection("V13_PROPOSAL_ID_CONFLICT")
            if prior is None:
                self.store.put(ns, key, value, index=False)
        return proposal_id

    def record_no_change(
        self,
        session: str,
        proposal_id: str,
        requested: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a maintenance decision that makes no assertion or record write."""
        replay = self.replay_requested(session, proposal_id, requested)
        if replay is not None:
            return replay
        with self._locked():
            return self._save_attempt(
                reference_key([session, proposal_id]),
                {"requested": json.loads(_json(requested))},
                {
                    "ok": True,
                    "status": "no_change",
                    "id": None,
                    "revision": None,
                    "effect": "none",
                    "content_verification": "unchecked",
                },
            )

    def commit(self, session: str, proposal_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
        """Commit a raw Host proposal; no semantic repair or fabricated result projection."""
        raw = json.loads(_json(proposal))
        if self.support_contract == "direct_support_v1" and "trigger_binding" not in raw:
            raw["trigger_binding"] = self.public_turn(session)
        if not session or not proposal_id:
            raise ValueError("V13_PROPOSAL_IDENTITY_REQUIRED")
        identity = reference_key([session, proposal_id])
        target = raw.get("id") or str(
            uuid.uuid5(uuid.NAMESPACE_URL, _json([self.namespace, session, proposal_id]))
        )
        with self._locked():
            if (
                self.mutation_contract == "event_bound_v1"
                and raw.get("action") == "update"
                and self.candidate_contract != "legacy_query_v1"
            ):
                try:
                    bound = self.candidate(raw.get("candidate_handle"))
                except ValueError:
                    if self.support_contract != "direct_support_v1":
                        raise
                    bound = None
                if bound is None:
                    raw["binding_error"] = "candidate_handle_required_or_invalid"
                elif (raw.get("id") is not None and raw["id"] != bound["record_id"]) or (
                    raw.get("expected_revision") is not None
                    and raw["expected_revision"] != bound["revision"]
                ):
                    raw["binding_error"] = "candidate_binding_mismatch"
                else:
                    raw["id"], raw["expected_revision"] = bound["record_id"], bound["revision"]
                    target = bound["record_id"]
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
                    identity + ":conflict:" + str(uuid.uuid4()),
                    raw,
                    target,
                    "proposal_id_conflict",
                    None,
                )
            lineage: dict[str, Any] = {}
            if (
                self.functional_contract == "functional_v1"
                and metadata is not None
                and raw.get("action") == "update"
                and not raw.get("binding_error")
                and raw.get("expected_revision") != metadata["revision"]
            ):
                assert prior is not None
                return self._reject(identity, raw, target, "revision_conflict", prior.value)
            try:
                reason, source = self._validate(raw)
                if reason is None and self.support_contract == "direct_support_v1":
                    trigger = self.public_turn(session)
                    if trigger is None or raw.get("trigger_binding") != trigger:
                        reason = "public_turn_required_or_mismatched"
                    elif raw.get("patch_operation") != "no_change":
                        reason, lineage = self._field_lineage(raw, metadata)
            except ValueError:
                if self.support_contract != "direct_support_v1":
                    raise
                reason, source = "source_integrity_failed", None
            if (
                reason is None
                and self.mutation_contract == "event_bound_v1"
                and self.support_contract == "legacy"
                and raw.get("action") in {"create", "update"}
                and raw.get("patch_operation") != "no_change"
                and not set(raw["source_refs"]).intersection(
                    self._source_boundaries.get(session, ("", []))[1]
                )
            ):
                reason = "current_boundary_source_required"
            if reason is None and raw.get("id") is not None and prior is None:
                reason = "record_not_found"
            if reason is None and self._functional_hidden(record_id=target):
                reason = "record_visibility_revoked"
            if reason is None and prior is not None and metadata is None:
                reason = "legacy_record_requires_explicit_migration"
            if reason is None and metadata is not None and metadata["owner"] != self.owner:
                reason = "record_not_found"
            functional_support = None
            if (
                reason is None
                and self.functional_contract == "functional_v1"
                and "functional_support" in raw
            ):
                from milai_lab.memory.functional_state import fragment_support, scope_leaves

                requested_support = raw["functional_support"]
                paths = {"content", "kind", "basis", *scope_leaves(raw["scope"])}
                if not isinstance(requested_support, dict) or set(requested_support) != paths:
                    reason = "functional_field_support_invalid"
                else:
                    try:
                        functional_support = {
                            path: fragment_support(self, handles)
                            for path, handles in requested_support.items()
                        }
                        if any(
                            not set(entry["source_refs"]) <= set(raw["source_refs"])
                            for entry in functional_support.values()
                        ):
                            reason = "functional_field_support_unselected"
                    except ValueError:
                        reason = "functional_fragment_invalid"
            revision = (metadata or {}).get("revision", 0)
            expected = raw.get("expected_revision")
            if reason is None and (type(expected) is not int or expected != revision):
                reason = "revision_conflict"
            if (
                reason is None
                and self.functional_contract == "functional_v1"
                and raw.get("action") == "create"
                and isinstance(raw.get("requested"), dict)
                and raw["requested"].get("operation") == "save"
            ):
                # The Agent may repeat an identical save with a new tool-call ID.
                # Under the same public-turn binding this is the same request,
                # not a second fact. Compare exact values/evidence, never similarity.
                for row in self._rows(self.namespace):
                    saved = row["value"].get("_v13_1", {})
                    if saved.get("owner") != self.owner:
                        continue
                    for accepted_id, accepted in saved.get("proposals", {}).items():
                        old = accepted["raw"]
                        if (
                            accepted["receipt"].get("status") != "committed"
                            or not accepted["receipt"].get("ok")
                            or old.get("action") != "create"
                            or _json(old.get("requested")) != _json(raw["requested"])
                            or old.get("trigger_binding") != raw.get("trigger_binding")
                        ):
                            continue
                        if (
                            self._functional_hidden(record_id=row["id"])
                            or saved["revision"] != accepted["receipt"]["revision"]
                        ):
                            return self._reject(
                                identity,
                                raw,
                                target,
                                "duplicate_save_target_changed_or_hidden",
                                None,
                            )
                        receipt = {
                            **accepted["receipt"],
                            "status": "no_change",
                            "effect": "none",
                            "duplicate_request": True,
                            "existing_record": True,
                            "duplicate_of_operation": accepted_id,
                            "original_status": "committed",
                        }
                        return self._save_attempt(identity, raw, receipt)
            # One tool receipt may support one record projection. Repeated consumption
            # cannot create a second fact or revise an old record again.
            if reason is None and source is not None and source["role"] == "tool":
                for row in self._rows(self.namespace):
                    for accepted in row["value"].get("_v13_1", {}).get("proposals", {}).values():
                        old = accepted["raw"]
                        if accepted["receipt"]["ok"] and old["source_ref"] == raw["source_ref"]:
                            comparable: tuple[str, ...] = (
                                "content",
                                "kind",
                                "scope",
                                "basis",
                                "object_ref",
                                "fields",
                            )
                            if self._uses_explicit_receipt(raw, source):
                                comparable += ("content_format",)
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
            if raw.get("patch_operation") == "no_change":
                return self._save_attempt(
                    identity,
                    raw,
                    {
                        "ok": True,
                        "status": "no_change",
                        "id": target,
                        "revision": revision,
                        "effect": "none",
                        "content_verification": "unchecked",
                    },
                )
            if (
                self.functional_contract == "functional_v1"
                and metadata is not None
                and raw.get("patch_operation") != "retract"
                and all(
                    _json(raw.get(field)) == _json(metadata["current"].get(field))
                    for field in ("content", "kind", "scope", "basis", "fields", "object_ref")
                )
                and (
                    "edit_state" not in raw
                    or raw["edit_state"] == metadata["current"].get("edit_state")
                )
            ):
                return self._save_attempt(
                    identity,
                    raw,
                    {
                        "ok": True,
                        "status": "no_change",
                        "id": target,
                        "revision": revision,
                        "effect": "none",
                        "content_verification": "unchecked",
                        "support_preserved": True,
                    },
                )
            if (
                metadata is not None
                and raw.get("edit_state") is not None
                and raw.get("edit_state") == metadata["current"].get("edit_state")
                and raw.get("content") == metadata["current"].get("content")
                and raw.get("patch_operation") != "retract"
            ):
                return self._save_attempt(
                    identity,
                    raw,
                    {
                        "ok": True,
                        "status": "no_change",
                        "id": target,
                        "revision": revision,
                        "effect": "none",
                        "content_verification": "unchecked",
                    },
                )
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
                "committed_at": self.clock().isoformat(),
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
            if self.functional_contract == "functional_v1":
                version["retracted"] = raw.get("patch_operation") == "retract"
                if "removed_field_support" in raw:
                    from milai_lab.memory.functional_state import fragment_support

                    version["removed_field_support"] = {
                        path: fragment_support(self, handles)
                        for path, handles in raw["removed_field_support"].items()
                    }
            if raw.get("edit_state") is not None:
                version.update(
                    edit_state=raw["edit_state"],
                    edit_operations=raw.get("edit_operations", []),
                    method_version=raw.get("method_version"),
                    method_arm=raw.get("method_arm"),
                )
                if "revision_evidence" in raw:
                    version["revision_evidence"] = raw["revision_evidence"]
                version["retracted"] = raw.get("patch_operation") == "retract"
            if functional_support is not None:
                version["functional_support"] = functional_support
                receipt["fragment_provenance_verified"] = True
            if self.mutation_contract == "event_bound_v1":
                bindings = self._source_bindings(raw["source_refs"])
                version.update(
                    source_refs=raw["source_refs"],
                    source_bindings=bindings,
                    mutation_contract=self.mutation_contract,
                )
                if raw.get("patch_operation") == "supersede":
                    version["supersedes_revision"] = revision
                receipt.update(
                    source_refs=raw["source_refs"],
                    source_bindings=bindings,
                    mutation_contract=self.mutation_contract,
                )
            if self.support_contract == "direct_support_v1":
                for value in (version, receipt):
                    value.update(
                        support_contract=self.support_contract,
                        trigger_binding=raw["trigger_binding"],
                        field_support=lineage,
                    )
            if self._uses_explicit_receipt(raw, source):
                # This verifies only two literal claims against a historical
                # observation. Notes, quotations and general prose are unchecked;
                # it does not assert current applicability of the old receipt.
                finite_claims = {
                    "receipt_contract": self.receipt_contract,
                    "content_format": raw["content_format"],
                    "receipt_claim_fields": list(self.receipt_fields),
                    "body_fields_verification": "matches_proposed_fields"
                    if self.mode == "field_grounded"
                    else "unchecked",
                    "notes_verification": "unchecked",
                }
                version.update(finite_claims)
                receipt.update(finite_claims)
            if self.operational_projection == "disabled" and source["role"] == "tool":
                # Identical proposal validation and semantic body/revision commit.
                # Keep claims in raw diagnostics, but persist no verified field view.
                version["fields"] = {}
                for value in (version, receipt):
                    value["fields_verification"] = "checked_proposal_no_projection"
                    value["operational_projection"] = "disabled"
                    if "body_fields_verification" in value:
                        value["body_fields_verification"] = "checked_proposal_no_projection"
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
        if self.mutation_contract == "event_bound_v1":
            receipt.update(formation_status="pending", raw_preserved=True)
        if prior is None:
            return self._save_attempt(identity, raw, receipt)
        prior["_v13_1"]["proposals"][identity] = {"raw": raw, "receipt": receipt}
        self.store.put(self.namespace, target, prior, index=False)
        return receipt

    def read(self, memory_id: str, revision: int | None = None) -> dict[str, Any]:
        if self._functional_hidden(record_id=memory_id):
            return {"ok": False, "status": "visibility_revoked", "id": memory_id}
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
        if (
            version is not None
            and self.functional_contract == "functional_v1"
            and any(
                self._functional_hidden(source_ref=ref)
                for ref in self._version_source_refs(version)
            )
        ):
            return {"ok": False, "status": "support_visibility_revoked", "id": memory_id}
        if (
            self.functional_contract == "functional_v1"
            and revision is None
            and version is not None
            and version.get("retracted")
        ):
            return {
                "ok": False,
                "status": "retracted",
                "id": memory_id,
                "revision": version["revision"],
                "history_available": True,
            }
        result = {
            "ok": version is not None,
            "status": "found" if version else "revision_not_found",
            "id": memory_id,
            "value": version,
            "observation_only": True,
        }
        if self.mutation_contract == "event_bound_v1" and version is not None:
            with self._locked():
                result["candidate_handle"] = self._issue_candidate(memory_id, version)
        return result

    def records(self) -> list[dict[str, Any]]:
        """Current material only; capture/attempt subnamespaces are not memory records."""
        return [self.read(row["id"]) for row in self._rows(self.namespace)]

    def search(
        self, query: str, limit: int = 10, *, dense: bool = False, include_raw: bool = True
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("V13_SEARCH_LIMIT_INVALID")
        degradation = None
        if dense and self.semantic_retriever is None:
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
        if self.functional_contract == "functional_v1":
            raw = [event for event in raw if event["role"] != "assistant"]
        linked_text: dict[str, str] = {}
        relation: dict[str, Any] = {}

        def searchable(row: dict[str, Any]) -> str:
            # Readable provenance IDs may contain public event keys or bank names.
            # Those keys are identities, never additional semantic search terms.
            value = row.get("value", row)
            if self.semantic_retriever is not None:
                return semantic_text(value)
            keys = (
                ("content", "kind", "scope", "basis", "fields")
                if "value" in row
                else ("content", "role", "origin", "observed_at")
            )
            text = _json({key: value[key] for key in keys if key in value})
            if self.functional_contract == "functional_v1":
                text += " " + str(value.get("content", ""))
            return text

        if self.source_backlinks == "enabled" and tokens:
            all_sources = raw if include_raw else self.sources()
            matching_sources = [
                event
                for event in all_sources
                if any(
                    token
                    in set(
                        _lexical_tokens(
                            searchable(event),
                            include_cjk_unigrams=True,
                        )
                    )
                    for token in tokens
                )
            ]
            for event in matching_sources:
                for record in self.backlink_candidates([event["event_id"]], limit=100):
                    linked_text[record["id"]] = (
                        linked_text.get(record["id"], "") + " " + searchable(event)
                    )
        if self.receipt_contract == "explicit_receipt_v1" and tokens:
            started_wall, started_cpu = time.monotonic_ns(), time.process_time_ns()
            # Reuse sources already loaded for raw search. Internal target discovery
            # excludes raw output and needs one exact Store get per distinct source.
            source_cache: dict[str, dict[str, Any] | None] = {
                event["event_id"]: event for event in raw
            }
            lookups: list[dict[str, Any]] = []
            links: list[dict[str, str]] = []

            def observe_relation() -> dict[str, Any]:
                cost = {
                    "kind": "captured_public_tool",
                    "joined_records": len(links),
                    "store_get_calls": len(lookups),
                    "wall_ns": time.monotonic_ns() - started_wall,
                    "cpu_ns": time.process_time_ns() - started_cpu,
                    "io_accounting": "captured_source_gets_only",
                }
                if self.observer is not None:
                    self.observer(
                        {
                            "event": "v13_memory_source_relation",
                            "owner": self.owner,
                            "query": query,
                            **cost,
                            "links": links,
                            "lookups": lookups,
                        }
                    )
                return cost

            for row in records:
                version = row.get("value") or {}
                if (
                    not row["ok"]
                    or version.get("receipt_contract") != "explicit_receipt_v1"
                    or version.get("content_format") != "receipt_json_v1"
                ):
                    continue
                source_ref = version["source_ref"]
                if not include_raw and source_ref not in source_cache:
                    lookup: dict[str, Any] = {"source_ref": source_ref}
                    lookups.append(lookup)
                    try:
                        receipt_event = self.source(source_ref)
                    except Exception as error:
                        lookup.update(error_type=type(error).__name__, error=str(error))
                        observe_relation()
                        raise
                    source_cache[source_ref] = receipt_event
                    lookup["original_result"] = receipt_event
                receipt_event = source_cache.get(source_ref)
                if receipt_event is None or not self._uses_explicit_receipt(version, receipt_event):
                    continue
                ref = receipt_event["object_ref"]
                if (
                    receipt_event["role"] != "tool"
                    or receipt_event["event_id"] != source_ref
                    or ref["id"] != version["object_ref"]
                    or ref["owner"] != self.owner
                    or ref["source_ref"] != source_ref
                ):
                    continue
                linked_text[row["id"]] = _json(
                    {"origin": receipt_event["origin"], "content": receipt_event["content"]}
                )
                links.append({"id": row["id"], "source_ref": source_ref})
            relation = observe_relation()

        def rank(row: dict[str, Any]) -> int:
            text = searchable(row)
            if row.get("id") in linked_text:
                text += " " + linked_text[row["id"]]
            text_tokens = set(_lexical_tokens(text, include_cjk_unigrams=True))
            return sum(token in text_tokens for token in tokens)

        withdrawals = []
        if self.functional_contract == "functional_v1":
            for row in records:
                if row.get("status") != "retracted":
                    continue
                historical = self.read(row["id"], row["revision"])
                if historical["ok"] and (enumerate_bank or rank(historical)):
                    version = historical["value"]
                    withdrawals.append(
                        {
                            "record_id": row["id"],
                            "revision": row["revision"],
                            "state": "withdrawn_not_current_fact",
                            "source_refs": self._version_source_refs(version),
                            "history_available": True,
                            "body_visibility": "notice_only",
                        }
                    )
        visible_records = [row for row in records if row["ok"]]
        if self.semantic_retriever is not None and not enumerate_bank:
            records = self.semantic_retriever.rank(query, visible_records, limit)
        else:
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
            "retrieval": (
                "dense_cosine" if self.semantic_retriever is not None else "raw_keyword"
            ),
            "degraded": degradation is not None,
            "degradation_reason": degradation,
            "records": records,
            "raw_events": raw,
            **({"withdrawals": withdrawals} if self.functional_contract == "functional_v1" else {}),
            **({"source_relation": relation} if relation else {}),
        }
