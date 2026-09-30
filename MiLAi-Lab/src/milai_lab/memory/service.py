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
from milai_lab.memory.observation import (
    PROJECTOR_VERSION,
    ObservationError,
    derive_observations,
    profile_identity,
)
from milai_lab.memory.observation import (
    observation_view as field_observation_view,
)


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _body_hash(value: Any) -> str:
    return hashlib.sha256((value if isinstance(value, str) else _json(value)).encode()).hexdigest()


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
        observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if not isinstance(store, SqliteStore):
            raise TypeError("V13_MEMORY_REQUIRES_SQLITE_STORE")
        if mode not in {"ref_only", "field_grounded"} or not owner or not namespace:
            raise ValueError("V13_MEMORY_CONFIGURATION_INVALID")
        if namespace[-1] != owner:
            raise ValueError("V13_MEMORY_OWNER_NAMESPACE_MISMATCH")
        self.store, self.namespace, self.owner = store, namespace, owner
        self.mode, self.lock_path = mode, lock_path.resolve()
        self.receipt_contract = self.validate_receipt_contract(receipt_contract)
        self.mutation_contract = self.validate_mutation_contract(mutation_contract)
        if type(source_backlinks) is not str or source_backlinks not in {"disabled", "enabled"}:
            raise ValueError("V13_SOURCE_BACKLINKS_INVALID")
        self.source_backlinks = source_backlinks
        if candidate_contract is None:
            candidate_contract = (
                "read_handle_v1"
                if self.mutation_contract == "event_bound_v1" else "legacy_query_v1"
            )
        if type(candidate_contract) is not str or candidate_contract not in {
            "legacy_query_v1", "id_revision_v1", "read_handle_v1"
        }:
            raise ValueError("V13_CANDIDATE_CONTRACT_INVALID")
        self.candidate_contract = candidate_contract
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
                if event is None or event["session"] != session:
                    raise ValueError("V13_SOURCE_BOUNDARY_SCOPE_MISMATCH")
            prior_id, prior_refs = self._source_boundaries.get(session, ("", []))
            refs = prior_refs if append and prior_id == boundary_id else []
            self._source_boundaries[session] = (
                boundary_id, list(dict.fromkeys([*refs, *source_refs]))
            )

    def boundary_sources(self, session: str) -> list[str]:
        """Only explicitly bound current events; history cannot fill a missing binding."""
        with self._locked():
            return list(self._source_boundaries.get(session, ("", []))[1])

    @staticmethod
    def _version_source_refs(version: dict[str, Any]) -> list[str]:
        return cast(list[str], version.get("source_refs", [version["source_ref"]]))

    def _source_bindings(self, source_refs: list[str]) -> list[dict[str, Any]] | None:
        bindings = []
        for source_ref in source_refs:
            event = self.source(source_ref)
            if event is None:
                return None
            bindings.append({"source_ref": source_ref, "role": event["role"],
                             "content_sha256": event["content_sha256"]})
        return bindings

    def _issue_candidate(self, record_id: str, version: dict[str, Any]) -> str:
        bindings = self._source_bindings(self._version_source_refs(version))
        if bindings is None:
            raise ValueError("V13_CANDIDATE_SUPPORT_UNAVAILABLE")
        if "source_bindings" in version and bindings != version["source_bindings"]:
            raise ValueError("V13_CANDIDATE_SUPPORT_CHANGED")
        bound = {"owner": self.owner, "namespace": list(self.namespace),
                 "record_id": record_id, "revision": version["revision"],
                 "support_sources": bindings, "version_sha256": _hash(version)}
        handle = "cand-" + _hash(bound)[:24]
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
        if (bound.get("owner") != self.owner or bound.get("namespace") != list(self.namespace)
                or handle != "cand-" + _hash(bound)[:24]):
            return None
        bindings = self._source_bindings([row["source_ref"] for row in bound["support_sources"]])
        if bindings is None or bindings != bound["support_sources"]:
            return None
        item = self.store.get(self.namespace, bound["record_id"])
        metadata = item.value.get("_v13_1", {}) if item is not None else {}
        version = next((row for row in metadata.get("history", [])
                        if row["revision"] == bound["revision"]), None)
        if (metadata.get("owner") != self.owner or version is None
                or self._version_source_refs(version) != [row["source_ref"] for row in bindings]
                or _hash(version) != bound["version_sha256"]):
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
        """Rebuildable source→record index; association does not choose a semantic target.

        Validate the current bank fingerprint before using the index. This initial
        implementation scans primary record identities for invalidation; it makes
        no unmeasured scale or speed claim. Supporting histories remain authority.
        """
        if self.source_backlinks != "enabled":
            return []
        if not 1 <= limit <= 100:
            raise ValueError("V13_SEARCH_LIMIT_INVALID")
        with self._locked():
            rows = self._rows(self.namespace)
            bank_revision = _hash([(row["id"], row["value"].get("_v13_1", {}).get("revision"))
                                   for row in sorted(rows, key=lambda row: row["id"])])
            matched: set[str] = set()
            for source_ref in source_refs:
                source = self.source(source_ref)
                if source is None:
                    continue
                old = self.store.get(self.backlinks_namespace, source_ref)
                if (old is None or old.value.get("bank_revision") != bank_revision
                        or old.value.get("source_hash") != source["content_sha256"]):
                    links = {}
                    for row in rows:
                        metadata = row["value"].get("_v13_1", {})
                        if metadata.get("owner") != self.owner:
                            continue
                        versions = [version["revision"] for version in metadata["history"]
                                    if source_ref in self._version_source_refs(version)]
                        if versions:
                            links[row["id"]] = versions
                    value = {"owner": self.owner, "source_ref": source_ref,
                             "source_hash": source["content_sha256"],
                             "bank_revision": bank_revision,
                             "records": links}
                    self.store.put(self.backlinks_namespace, source_ref, value, index=False)
                else:
                    value = old.value
                matched.update(value["records"])
        # read() issues a handle under its own lock. Do not hold a second flock.
        return [self.read(memory_id) for memory_id in sorted(matched)[:limit]]

    def revise(
        self, session: str, proposal_id: str, candidate_handle: str,
        semantic_patch: dict[str, Any], source_refs: list[str] | None = None, *,
        operation: str = "revise",
    ) -> dict[str, Any]:
        """Small semantic patch over the version actually read; observed literals are immutable."""
        requested = {"candidate_handle": candidate_handle, "semantic_patch": semantic_patch,
                     "source_refs": source_refs, "operation": operation}

        def rejected(reason: str) -> dict[str, Any]:
            identity = _hash([session, proposal_id])
            with self._locked():
                return self._save_attempt(identity, {"requested": requested}, {
                    "ok": False, "status": "rejected", "reason": reason, "effect": "none",
                    "formation_status": "pending", "raw_preserved": True,
                    "content_verification": "unchecked", "id": None, "revision": None,
                })

        if source_refs is None:
            source_refs = self.boundary_sources(session)
            if len(source_refs) != 1:
                return rejected("source_selection_required")

        bound = self.candidate(candidate_handle)
        if bound is None:
            return rejected("candidate_handle_required_or_invalid")
        if (operation not in {"revise", "supersede", "no_change"}
                or not isinstance(semantic_patch, dict)
                or not semantic_patch.keys() <= {"content", "scope", "basis", "kind"}
                or not source_refs):
            return rejected("invalid_semantic_patch")
        version = self.read(bound["record_id"], bound["revision"])["value"]
        scope = semantic_patch.get("scope", {})
        if not isinstance(scope, dict):
            return rejected("invalid_semantic_patch")
        proposal = {"action": "update", "id": bound["record_id"],
                    "expected_revision": bound["revision"], "candidate_handle": candidate_handle,
                    "source_ref": source_refs[0], "source_refs": source_refs,
                    "content": semantic_patch.get("content", version["content"]),
                    "kind": semantic_patch.get("kind", version["kind"]),
                    "scope": {**version["scope"], **scope},
                    "basis": semantic_patch.get("basis", version["basis"]),
                    "fields": {}, "object_ref": None, "patch_operation": operation,
                    "requested": requested}
        return self.commit(session, proposal_id, proposal)

    def semantic_receipts(self, source_ref: str) -> list[dict[str, Any]]:
        """Successful semantic submissions citing one owner-checked actual source."""
        if self.source(source_ref) is None:
            return []
        return [entry["receipt"] for row in self._rows(self.namespace)
                if row["value"].get("_v13_1", {}).get("owner") == self.owner
                for entry in row["value"].get("_v13_1", {}).get("proposals", {}).values()
                if entry["receipt"]["ok"] and source_ref in entry["raw"].get(
                    "source_refs", [entry["raw"].get("source_ref")])]

    @staticmethod
    def _projection_id(source_ref: str, profile: ObservationProfile) -> str:
        return "projection-" + _hash([source_ref, profile.profile_id,
                                     profile.adapter_version, PROJECTOR_VERSION])

    def observe(self, source_ref: str, profile: ObservationProfile) -> dict[str, Any]:
        """Derive only real source literals, with detectable pending and idempotent replay.

        The public Store has no multi-item transaction here. A complete marker
        follows verified fact writes; partial writes remain invisible in the
        complete view and can be replayed without repeating any business tool.
        """
        if self.mutation_contract != "event_bound_v1":
            raise ValueError("V13_OBSERVATION_REQUIRES_EVENT_BOUND")
        profile_hash = profile_identity(profile)
        projection_id = self._projection_id(source_ref, profile)
        initial_source = self.source(source_ref)
        if initial_source is None:
            return {"ok": False, "status": "rejected",
                    "reason": "source_not_found_or_not_owned", "effect": "none"}
        initial_binding = {"owner": self.owner, "source_event_id": source_ref,
                           "source_hash": initial_source["content_sha256"],
                           "adapter_id": profile.profile_id,
                           "adapter_version": profile.adapter_version,
                           "adapter_sha256": profile_hash, "projector_version": PROJECTOR_VERSION}
        with self._locked():
            initial_projection = self.store.get(self.projections_namespace, projection_id)
            if (initial_projection is not None and any(
                    initial_projection.value.get(key) != value
                    for key, value in initial_binding.items())):
                return {"ok": False, "status": "rejected", "reason": "projection_binding_changed",
                        "projection_id": projection_id, "effect": "none"}
            if initial_projection is None:
                # A real kill at W2 must leave a public, profile-bound dirty witness.
                witness = {**initial_binding, "status": "pending", "receipt": {
                    "ok": False, "status": "pending", "projection_id": projection_id,
                    "source_ref": source_ref, "source_hash": initial_source["content_sha256"],
                    "projector_version": PROJECTOR_VERSION, "raw_preserved": True,
                    "effect": "memory_projection_only", "current_verified": False,
                    "reason": "projection_not_started",
                }}
                self.store.put(self.projections_namespace, projection_id, witness, index=False)
                persisted = self.store.get(self.projections_namespace, projection_id)
                if persisted is None or persisted.value != witness:
                    raise RuntimeError("V13_PROJECTION_PENDING_NOT_VISIBLE")
        if self.observer is not None and (initial_projection is None
                                         or initial_projection.value["status"] != "complete"):
            # Driver evidence can read the service; callbacks run outside its lock.
            self.observer({"event": "v13_observation_boundary", "phase": "source_persisted",
                           "source_ref": source_ref, "projection_id": projection_id})
        with self._locked():
            source = self.source(source_ref)
            if source is None:
                return {"ok": False, "status": "rejected",
                        "reason": "source_not_found_or_not_owned", "effect": "none"}
            item = self.store.get(self.projections_namespace, projection_id)
            prior = item.value if item is not None else None
            binding = {"owner": self.owner, "source_event_id": source_ref,
                       "source_hash": source["content_sha256"], "adapter_id": profile.profile_id,
                       "adapter_version": profile.adapter_version, "adapter_sha256": profile_hash,
                       "projector_version": PROJECTOR_VERSION}
            if prior is not None and any(prior.get(key) != value for key, value in binding.items()):
                return {"ok": False, "status": "rejected", "reason": "projection_binding_changed",
                        "projection_id": projection_id, "effect": "none"}
            receipt: dict[str, Any] = {
                "ok": False, "status": "pending", "projection_id": projection_id,
                "source_ref": source_ref, "source_hash": source["content_sha256"],
                "projector_version": PROJECTOR_VERSION, "raw_preserved": True,
                "effect": "memory_projection_only", "current_verified": False,
            }
            try:
                facts, outcome = derive_observations(source, profile)
            except ObservationError as error:
                receipt.update(reason=str(error), observation_count=0)
                if prior is None or prior.get("status") != "complete":
                    self.store.put(self.projections_namespace, projection_id,
                                   {**binding, "status": "pending", "receipt": receipt},
                                   index=False)
                return receipt
            facts = [{**fact, "projection_id": projection_id} for fact in facts]
            hashes = {fact["observation_id"]: _hash(fact) for fact in facts}
            receipt["expected_observation_count"] = len(facts)
            if prior is not None and prior.get("status") == "complete":
                consistent = prior.get("fact_sha256") == hashes
                for fact_id, expected_hash in hashes.items():
                    fact_item = self.store.get(self.observations_namespace, fact_id)
                    consistent = (consistent and fact_item is not None
                                  and _hash(fact_item.value) == expected_hash)
                if consistent:
                    return {**prior["receipt"], "status": "no_change", "replayed": True,
                            "original_status": prior["receipt"]["status"]}
            pending = {**binding, "status": "pending", "fact_sha256": hashes, "receipt": receipt,
                       "outcome": outcome}
            # Persist the recovery witness before any independent fact writes.
            self.store.put(self.projections_namespace, projection_id, pending, index=False)
            try:
                for fact in facts:
                    existing = self.store.get(self.observations_namespace, fact["observation_id"])
                    if existing is not None and existing.value != fact:
                        raise ValueError("V13_OBSERVATION_IDENTITY_CHANGED")
                    if existing is None:
                        self.store.put(self.observations_namespace, fact["observation_id"], fact,
                                       index=False)
                    written = self.store.get(self.observations_namespace, fact["observation_id"])
                    if written is None or written.value != fact:
                        raise RuntimeError("V13_OBSERVATION_WRITE_NOT_VISIBLE")
                receipt.update(ok=True,
                               status="observed_unknown" if outcome == "unknown" else "projected",
                               observation_count=len(facts), outcome=outcome)
                complete = {**pending, "status": "complete", "fact_sha256": hashes,
                            "receipt": receipt}
                self.store.put(self.projections_namespace, projection_id, complete, index=False)
                readback = self.store.get(self.projections_namespace, projection_id)
                if readback is None or readback.value != complete:
                    raise RuntimeError("V13_PROJECTION_COMMIT_NOT_VISIBLE")
            except Exception as error:
                receipt.pop("observation_count", None)
                receipt.update(ok=False, status="pending", reason="projection_write_incomplete",
                               error_type=type(error).__name__, error=str(error))
                pending = {**pending, "fact_sha256": hashes, "receipt": receipt}
                self.store.put(self.projections_namespace, projection_id, pending, index=False)
                pending_witness = self.store.get(self.projections_namespace, projection_id)
                if pending_witness is None or pending_witness.value != pending:
                    raise RuntimeError("V13_PROJECTION_PENDING_NOT_VISIBLE") from error
                return receipt
        if self.observer is not None:
            self.observer({"event": "v13_observation_boundary", "phase": "projection_committed",
                           "source_ref": source_ref, "projection_id": projection_id,
                           "receipt": receipt})
        return receipt

    def projection_receipt(
        self, source_ref: str, profile: ObservationProfile
    ) -> dict[str, Any] | None:
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
                source = self.source(state["source_event_id"])
                if source is None or source["content_sha256"] != state["source_hash"]:
                    raise ValueError("V13_OBSERVATION_SOURCE_CHANGED")
                if state["status"] != "complete":
                    pending.append(state["receipt"])
                    continue
                collected = []
                for fact_id, expected_hash in state["fact_sha256"].items():
                    item = self.store.get(self.observations_namespace, fact_id)
                    if item is None or _hash(item.value) != expected_hash:
                        raise ValueError("V13_OBSERVATION_COMMIT_INCOMPLETE")
                    collected.append(item.value)
                facts.extend(collected)
                if state["outcome"] == "unknown":
                    unknown.append(state["receipt"])
            return {"ok": True,
                    "observations": sorted(facts, key=lambda row: row["observation_id"]),
                    "objects": field_observation_view(facts),
                    "pending": pending, "unknown": unknown,
                    "current_verified": False}

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

    def capture_assistant(self, session: str, event_key: str, content: Any) -> dict[str, Any]:
        """Trusted actual assistant message; proposals/packets are never original messages."""
        if self.mutation_contract != "event_bound_v1":
            raise ValueError("V13_ASSISTANT_CAPTURE_REQUIRES_EVENT_BOUND")
        return self._capture(
            session, event_key, "assistant", "public_assistant_message", content, None
        )

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
                    event_id in self._version_source_refs(version)
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
                    row["id"] in self._version_source_refs(version)
                    for record in records
                    for version in record["value"].get("_v13_1", {}).get("history", [])
                )
                result.append({**event, "formation_status": "formed" if formed else "pending"})
            return sorted(result, key=lambda event: (event["observed_at"], event["event_id"]))

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
        if (self.mutation_contract == "event_bound_v1"
                and proposal.get("action") not in {"create", "update"}):
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
            if (not isinstance(refs, list) or not refs or not all(isinstance(r, str) for r in refs)
                    or len(refs) != len(set(refs)) or proposal["source_ref"] not in refs):
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
        identity = _hash([session, proposal_id])
        with self._locked():
            attempt = self.store.get(self.attempts_namespace, identity)
            previous = next(
                (row["value"].get("_v13_1", {}).get("proposals", {})[identity]
                 for row in self._rows(self.namespace)
                 if row["value"].get("_v13_1", {}).get("owner") == self.owner
                 and identity in row["value"].get("_v13_1", {}).get("proposals", {})),
                attempt.value if attempt is not None else None,
            )
            if previous is None:
                return None
            if previous["raw"].get("requested") != requested:
                raw = {"requested": requested}
                return self._reject(identity + ":" + _hash(raw), raw,
                                    previous["receipt"]["id"], "proposal_id_conflict", None)
            receipt = previous["receipt"]
            return {**receipt, "status": "no_change" if receipt["ok"] else "rejected",
                    "replayed": True, "original_status": receipt["status"]}

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
            if (self.mutation_contract == "event_bound_v1" and raw.get("action") == "update"
                    and self.candidate_contract != "legacy_query_v1"):
                bound = self.candidate(raw.get("candidate_handle"))
                if bound is None:
                    raw["binding_error"] = "candidate_handle_required_or_invalid"
                elif ((raw.get("id") is not None and raw["id"] != bound["record_id"])
                      or (raw.get("expected_revision") is not None
                          and raw["expected_revision"] != bound["revision"])):
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
                return self._save_attempt(identity, raw, {
                    "ok": True, "status": "no_change", "id": target, "revision": revision,
                    "effect": "none", "content_verification": "unchecked",
                })
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
            if self.mutation_contract == "event_bound_v1":
                bindings = self._source_bindings(raw["source_refs"])
                version.update(source_refs=raw["source_refs"], source_bindings=bindings,
                               mutation_contract=self.mutation_contract)
                if raw.get("patch_operation") == "supersede":
                    version["supersedes_revision"] = revision
                receipt.update(source_refs=raw["source_refs"], source_bindings=bindings,
                               mutation_contract=self.mutation_contract)
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
        linked_text: dict[str, str] = {}
        relation: dict[str, Any] = {}
        if self.source_backlinks == "enabled" and tokens:
            all_sources = raw if include_raw else self.sources()
            matching_sources = [event for event in all_sources
                                if any(token in set(_lexical_tokens(_json(event),
                                     include_cjk_unigrams=True)) for token in tokens)]
            for event in matching_sources:
                for record in self.backlink_candidates([event["event_id"]], limit=100):
                    linked_text[record["id"]] = (linked_text.get(record["id"], "")
                                                 + " " + _json(event))
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
                    self.observer({
                        "event": "v13_memory_source_relation", "owner": self.owner,
                        "query": query, **cost, "links": links, "lookups": lookups,
                    })
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
            text = _json(row)
            if row.get("id") in linked_text:
                text += " " + linked_text[row["id"]]
            text_tokens = set(_lexical_tokens(text, include_cjk_unigrams=True))
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
            **({"source_relation": relation} if relation else {}),
        }
