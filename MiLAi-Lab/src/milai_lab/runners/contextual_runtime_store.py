"""One local writer's crash-safe bank, live session, and business action journal."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from milai_lab.harness.contextual_artifacts import digest
from milai_lab.methods.contextual_memory.decision_basis import DECISION_PROTOCOL
from milai_lab.methods.contextual_memory.deletion import DeletionLedger
from milai_lab.methods.contextual_memory.material_view import (
    VIEW_PROTOCOL,
    MaterialBinding,
)
from milai_lab.methods.contextual_memory.operations import OPERATION_CONTRACT_VERSION
from milai_lab.methods.contextual_memory.write_contract import WRITE_CONTRACT_VERSION
from milai_lab.methods.contextual_user_memory import METHOD_VERSION, ContextualMemory
from milai_lab.runners.contextual_host import ACTION_PROTOCOL
from milai_lab.runners.contextual_session import HostSession

STORE_PROTOCOL = "contextual-runtime-store-v1"


@dataclass(frozen=True)
class RuntimeIdentity:
    owner_id: str
    config_sha256: str
    host_model: str
    host_identity: str
    embedding_model: str
    embedding_dimension: int
    embedding_identity: str
    state_policy: str
    decision_policy: str
    decision_feedback: bool
    decision_gap_focus: bool
    decision_protocol: str
    action_protocol: str
    method_version: str
    write_contract: str
    material_view_protocol: str
    operation_contract: str
    source_protocol: str
    actor_protocol: str
    maintenance_protocol: str

    @classmethod
    def from_config(cls, owner_id: str, config: Mapping[str, Any]) -> RuntimeIdentity:
        """Use the same embedding fingerprint as CachedEmbedding, without a model call."""
        embedding_identity = digest(
            {
                "model": config["embedding"]["model"],
                "dimension": config["embedding_dimension"],
                "weights": config["model_identity"]["embedding"],
                "window": config["embedding_window"],
            }
        )
        return cls(
            owner_id=owner_id,
            config_sha256=digest(config),
            host_model=config["host"]["model"],
            host_identity=digest([config["host"], config["model_identity"]["host"]]),
            embedding_model=config["embedding"]["model"],
            embedding_dimension=config["embedding_dimension"],
            embedding_identity=embedding_identity,
            state_policy=config["state_policy"],
            decision_policy=config.get("decision_policy", "off"),
            decision_feedback=config.get("decision_feedback",
                                         config.get("decision_policy") == "basis"),
            decision_gap_focus=config.get("decision_gap_focus",
                                          config.get("decision_policy") == "basis"),
            decision_protocol=DECISION_PROTOCOL,
            action_protocol=ACTION_PROTOCOL,
            method_version=METHOD_VERSION,
            write_contract=WRITE_CONTRACT_VERSION,
            material_view_protocol=VIEW_PROTOCOL,
            operation_contract=OPERATION_CONTRACT_VERSION,
            source_protocol=config["source_protocol"],
            actor_protocol=config["actor_protocol"],
            maintenance_protocol=config.get("maintenance_protocol", "turn-maintenance-v2"),
        )


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".runtime-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _payload(message: dict[str, Any]) -> dict[str, Any] | None:
    """Recover only a projected result that is literally present in one transcript item."""
    content = message.get("content")
    if not isinstance(content, str):
        return None
    for start, character in enumerate(content):
        if character != "{":
            continue
        try:
            parsed = json.loads(content[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        projected = parsed.get("result", parsed)
        if isinstance(projected, dict) and projected.get("view") == VIEW_PROTOCOL:
            return projected
    return None


def _binding(value: dict[str, Any]) -> MaterialBinding:
    spans = value.get("spans", [])
    if not isinstance(spans, list) or any(
        not isinstance(span, list)
        or len(span) != 2
        or type(span[0]) is not int
        or type(span[1]) is not int
        or span[0] < 0
        or span[1] < span[0]
        for span in spans
    ):
        raise ValueError("RUNTIME_SESSION_BINDING_INVALID")
    if not all(isinstance(value.get(key), str) for key in ("exact_ref", "kind", "content_sha256")):
        raise ValueError("RUNTIME_SESSION_BINDING_INVALID")
    return MaterialBinding(
        value["exact_ref"],
        value["kind"],
        tuple((part[0], part[1]) for part in spans),
        value["content_sha256"],
    )


def _result_dict(result: Any) -> dict[str, Any]:
    if is_dataclass(result) and not isinstance(result, type):
        return copy.deepcopy(asdict(result))
    if isinstance(result, Mapping):
        return copy.deepcopy(dict(result))
    raise TypeError("RUNTIME_RESULT_MUST_BE_MAPPING")


def _session_snapshot(session: HostSession) -> dict[str, Any]:
    session.refresh_visibility()
    view = session.material_view
    if view is None:
        raise ValueError("RUNTIME_SESSION_REQUIRES_MEMORY")
    transcript = copy.deepcopy(session.transcript)
    deliveries = []
    for message, content, bindings in session.deliveries:
        index = next(
            (index for index, candidate in enumerate(session.transcript) if candidate is message),
            None,
        )
        if index is None or message.get("content") != content:
            raise ValueError("RUNTIME_DELIVERY_NOT_RESIDENT")
        projected = _payload(message)
        if projected is None and not bindings:
            # A control receipt can be recorded by the Host but grants no material
            # visibility. Keep its transcript item without inventing a delivery.
            continue
        if projected is None or view.visible_bindings(projected) != bindings:
            raise ValueError("RUNTIME_DELIVERY_NOT_IN_TRANSCRIPT")
        deliveries.append(
            {
                "message_index": index,
                "content": content,
                "projected": copy.deepcopy(projected),
                "bindings": {alias: asdict(binding) for alias, binding in bindings.items()},
            }
        )
    aliases = {alias: asdict(binding) for alias, binding in session.visible_bindings.items()}
    return {
        "session_id": session.session_id,
        "task_id": session.task_id,
        "turn_index": session.turn_index,
        "turn_id": session.turn_id,
        "transcript": transcript,
        "next_alias": view._next,
        "aliases": aliases,
        "deliveries": deliveries,
        "observations": copy.deepcopy(session.observations),
        "maintenance": copy.deepcopy(getattr(session, "maintenance", {})),
    }


def _restore_session(value: dict[str, Any], memory: ContextualMemory) -> HostSession:
    if value["task_id"] != memory.state.task_id or not value["session_id"]:
        raise ValueError("RUNTIME_SESSION_TASK_MISMATCH")
    session = HostSession(value["session_id"], memory)
    if not isinstance(value["transcript"], list):
        raise ValueError("RUNTIME_TRANSCRIPT_INVALID")
    session.transcript = copy.deepcopy(value["transcript"])
    session.turn_index = value["turn_index"]
    session.turn_id = value["turn_id"]
    session.observations = copy.deepcopy(value["observations"])
    session.maintenance = copy.deepcopy(value.get("maintenance", {}))
    session.read_cache.clear()
    view = session.material_view
    assert view is not None
    view._next = value["next_alias"]
    view._bindings = {"unknown": MaterialBinding("unresolved", "subject")}
    view._bindings.update({alias: _binding(binding) for alias, binding in value["aliases"].items()})
    for delivery in value["deliveries"]:
        index = delivery["message_index"]
        if type(index) is not int or index < 0 or index >= len(session.transcript):
            raise ValueError("RUNTIME_DELIVERY_NOT_RESIDENT")
        message = session.transcript[index]
        projected = _payload(message)
        if message.get("content") != delivery["content"] or projected != delivery["projected"]:
            raise ValueError("RUNTIME_DELIVERY_NOT_IN_TRANSCRIPT")
        assert projected is not None
        expected = {alias: _binding(binding) for alias, binding in delivery["bindings"].items()}
        if view.visible_bindings(projected) != expected:
            raise ValueError("RUNTIME_DELIVERY_BINDING_MISMATCH")
        session.record_delivery(message, projected)
    expected_visible = {alias: _binding(binding) for alias, binding in value["aliases"].items()}
    if session.visible_bindings != expected_visible:
        raise ValueError("RUNTIME_SESSION_VISIBILITY_MISMATCH")
    return session


class RuntimeStore:
    """Exact-identity, single-writer local store; never replays external effects."""

    def __init__(self, path: Path, identity: RuntimeIdentity) -> None:
        self.path, self.identity = path, identity
        self._lock_fd: int | None = None
        self._state: dict[str, Any] | None = None

    def __enter__(self) -> RuntimeStore:
        self.path.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path / ".writer.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(descriptor)
            raise ValueError("RUNTIME_WRITER_ALREADY_ACTIVE") from error
        self._lock_fd = descriptor
        try:
            state_path = self.path / "state.json"
            if state_path.exists():
                state = json.loads(state_path.read_text())
                if state.get("format") != STORE_PROTOCOL:
                    raise ValueError("RUNTIME_STORE_PROTOCOL_MISMATCH")
                recorded = state.get("identity", {})
                if recorded.get("owner_id") != self.identity.owner_id:
                    raise ValueError("RUNTIME_OWNER_MISMATCH")
                if recorded != asdict(self.identity):
                    raise ValueError("RUNTIME_IDENTITY_MISMATCH")
            else:
                state = {
                    "format": STORE_PROTOCOL,
                    "identity": asdict(self.identity),
                    "checkpoint": None,
                    "session": None,
                    "extra": {},
                    "actions": {},
                    "turns": {},
                }
                _atomic_json(state_path, state)
            self._state = state
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_: Any) -> None:
        if self._lock_fd is not None:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None
        self._state = None

    def _current(self) -> dict[str, Any]:
        if self._state is None or self._lock_fd is None:
            raise ValueError("RUNTIME_STORE_NOT_OPEN")
        return self._state

    def _commit(self, state: dict[str, Any]) -> None:
        self._current()
        _atomic_json(self.path / "state.json", state)
        self._state = state

    def _check_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        expected = self.identity
        if checkpoint.get("user_id") != expected.owner_id:
            raise ValueError("RUNTIME_OWNER_MISMATCH")
        if (
            checkpoint.get("format") != expected.method_version
            or checkpoint.get("host_id") != expected.host_model
            or checkpoint.get("embedding_model") != expected.embedding_model
            or checkpoint.get("embedding_dimension") != expected.embedding_dimension
            or checkpoint.get("embedding_identity") != expected.embedding_identity
            or checkpoint.get("state_policy") != expected.state_policy
            or checkpoint.get("decision_policy") != expected.decision_policy
            or checkpoint.get("decision_feedback") != expected.decision_feedback
            or checkpoint.get("decision_gap_focus") != expected.decision_gap_focus
        ):
            raise ValueError("RUNTIME_CHECKPOINT_IDENTITY_MISMATCH")

    def _snapshot(
        self,
        memory: ContextualMemory,
        session: HostSession | None,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if session is not None and session.memory is not memory:
            raise ValueError("RUNTIME_SESSION_MEMORY_MISMATCH")
        active = session is not None and not session.closed
        checkpoint = memory.checkpoint(include_task=active)
        self._check_checkpoint(checkpoint)
        state = copy.deepcopy(self._current())
        state["checkpoint"] = checkpoint
        state["session"] = _session_snapshot(session) if active and session is not None else None
        state["extra"] = (
            copy.deepcopy(dict(extra))
            if active and extra is not None
            else (state["extra"] if active else {})
        )
        return state

    def persist(
        self,
        memory: ContextualMemory,
        session: HostSession | None = None,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        self._commit(self._snapshot(memory, session, extra))

    def restore_memory(
        self,
        embed: Callable[[list[str]], list[list[float]]],
        *,
        deletion_ledger: DeletionLedger | None = None,
    ) -> ContextualMemory | None:
        checkpoint = self._current()["checkpoint"]
        if checkpoint is None:
            return None
        self._check_checkpoint(checkpoint)
        return ContextualMemory.restore(
            checkpoint,
            user_id=self.identity.owner_id,
            embed=embed,
            embedding_identity=self.identity.embedding_identity,
            embedding_model=self.identity.embedding_model,
            embedding_dimension=self.identity.embedding_dimension,
            state_policy=self.identity.state_policy,
            decision_policy=self.identity.decision_policy,
            decision_feedback=self.identity.decision_feedback,
            decision_gap_focus=self.identity.decision_gap_focus,
            deletion_ledger=deletion_ledger,
        )

    def restore_session(self, memory: ContextualMemory) -> HostSession | None:
        value = self._current()["session"]
        if value is None:
            return None
        self._check_checkpoint(self._current()["checkpoint"])
        if memory.user_id != self.identity.owner_id:
            raise ValueError("RUNTIME_OWNER_MISMATCH")
        return _restore_session(value, memory)

    def restore_extra(self) -> dict[str, Any]:
        return copy.deepcopy(self._current()["extra"])

    @staticmethod
    def call_id(session_id: str, turn_id: str, ordinal: int) -> str:
        if not session_id or not turn_id or type(ordinal) is not int or ordinal < 0:
            raise ValueError("RUNTIME_CALL_ID_INVALID")
        key = json.dumps([session_id, turn_id, ordinal], ensure_ascii=False)
        return "call:" + hashlib.sha256(key.encode()).hexdigest()[:32]

    @staticmethod
    def _turn_key(session_id: str, turn_id: str) -> str:
        if not session_id or not turn_id:
            raise ValueError("RUNTIME_TURN_ID_INVALID")
        return json.dumps([session_id, turn_id], ensure_ascii=False)

    def reserve_turn(
        self,
        session_id: str,
        turn_id: str,
        *,
        input_sha256: str,
        memory: ContextualMemory,
        session: HostSession,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", input_sha256):
            raise ValueError("RUNTIME_TURN_INPUT_DIGEST_INVALID")
        if session.session_id != session_id:
            raise ValueError("RUNTIME_SESSION_ID_MISMATCH")
        key = self._turn_key(session_id, turn_id)
        turns = self._current()["turns"]
        existing = turns.get(key)
        if existing is not None:
            if existing["input_sha256"] != input_sha256:
                raise ValueError("RUNTIME_TURN_INPUT_CHANGED")
            return copy.deepcopy(
                {
                    "status": existing["status"],
                    "turn_index": existing["turn_index"],
                    "result": existing.get("result"),
                }
            )
        state = self._snapshot(memory, session)
        index = 1 + max(
            (item["turn_index"] for item in turns.values() if item["session_id"] == session_id),
            default=0,
        )
        state["turns"][key] = {
            "session_id": session_id,
            "turn_id": turn_id,
            "turn_index": index,
            "input_sha256": input_sha256,
            "status": "in_progress",
            "result": None,
        }
        self._commit(state)
        return {"status": "new", "turn_index": index, "result": None}

    def completed_turn(self, session_id: str, turn_id: str) -> dict[str, Any] | None:
        item = self._current()["turns"].get(self._turn_key(session_id, turn_id))
        if item is None or item["status"] != "complete":
            return None
        result = copy.deepcopy(item["result"])
        if not isinstance(result, dict):
            raise ValueError("RUNTIME_TURN_RESULT_INVALID")
        return result

    def complete_turn(
        self,
        session_id: str,
        turn_id: str,
        result: Mapping[str, Any] | Any,
        *,
        memory: ContextualMemory,
        session: HostSession,
    ) -> None:
        key = self._turn_key(session_id, turn_id)
        item = self._current()["turns"].get(key)
        if item is None:
            raise ValueError("RUNTIME_TURN_NOT_RESERVED")
        serialized = _result_dict(result)
        if item["status"] == "complete":
            if item["result"] != serialized:
                raise ValueError("RUNTIME_TURN_RESULT_CHANGED")
            return
        state = self._snapshot(memory, session)
        state["turns"][key]["status"] = "complete"
        state["turns"][key]["result"] = serialized
        self._commit(state)

    def begin_action(
        self,
        call_id: str,
        name: str,
        arguments: Mapping[str, Any],
        *,
        memory: ContextualMemory,
        session: HostSession,
    ) -> dict[str, Any]:
        if not call_id or not name:
            raise ValueError("RUNTIME_ACTION_ID_INVALID")
        existing = self._current()["actions"].get(call_id)
        canonical = copy.deepcopy(dict(arguments))
        if existing is not None:
            if existing["name"] != name or existing["arguments"] != canonical:
                raise ValueError("RUNTIME_ACTION_ID_REUSED")
            return {
                "status": "unknown" if existing["state"] == "intent" else "settled",
                "may_execute": False,
                "result": copy.deepcopy(existing["result"]),
            }
        state = self._snapshot(memory, session)
        state["actions"][call_id] = {
            "call_id": call_id,
            "name": name,
            "arguments": canonical,
            "session_id": session.session_id,
            "turn_id": session.turn_id,
            "state": "intent",
            "result": None,
            "reconciliation": None,
        }
        self._commit(state)
        return {"status": "new", "may_execute": True, "result": None}

    def finish_action(
        self,
        call_id: str,
        result: Mapping[str, Any] | Any,
        *,
        memory: ContextualMemory,
        session: HostSession,
    ) -> None:
        existing = self._current()["actions"].get(call_id)
        if existing is None:
            raise ValueError("RUNTIME_ACTION_NOT_REGISTERED")
        serialized = _result_dict(result)
        if existing["state"] == "settled":
            if existing["result"] != serialized:
                raise ValueError("RUNTIME_ACTION_RESULT_CHANGED")
            return
        if existing["state"] == "reconciled":
            raise ValueError("RUNTIME_ACTION_ALREADY_RECONCILED")
        state = self._snapshot(memory, session)
        state["actions"][call_id]["state"] = "settled"
        state["actions"][call_id]["result"] = serialized
        self._commit(state)

    def reconcile_action(
        self,
        call_id: str,
        result: Mapping[str, Any] | Any,
        *,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Record an application's independent check of an uncertain external effect."""
        existing = self._current()["actions"].get(call_id)
        if existing is None:
            raise ValueError("RUNTIME_ACTION_NOT_REGISTERED")
        if not evidence:
            raise ValueError("RUNTIME_RECONCILIATION_EVIDENCE_REQUIRED")
        verified = {"result": _result_dict(result), "evidence": copy.deepcopy(dict(evidence))}
        if (verified["result"].get("status") not in {"succeeded", "failed"}
                or verified["result"].get("call_id", call_id) != call_id):
            raise ValueError("RUNTIME_RECONCILIATION_NOT_DETERMINATE")
        if existing["state"] == "reconciled":
            if existing["reconciliation"] != verified:
                raise ValueError("RUNTIME_RECONCILIATION_CHANGED")
            return copy.deepcopy(existing)
        if existing["state"] == "settled" and existing["result"].get("status") != "unknown":
            raise ValueError("RUNTIME_ACTION_RESULT_ALREADY_KNOWN")
        state = copy.deepcopy(self._current())
        state["actions"][call_id]["state"] = "reconciled"
        state["actions"][call_id]["reconciliation"] = verified
        self._commit(state)
        return copy.deepcopy(state["actions"][call_id])

    def actions_for_turn(self, session_id: str, turn_id: str) -> list[dict[str, Any]]:
        """Return journaled intents and full results for receipt recovery, without replay."""
        return [
            copy.deepcopy(item)
            for item in self._current()["actions"].values()
            if item["session_id"] == session_id and item["turn_id"] == turn_id
        ]

    def pending_actions(self) -> list[dict[str, Any]]:
        """Only genuinely unknown effects require an application-level check."""
        return [
            {
                "call_id": call_id,
                "name": item["name"],
                "arguments": copy.deepcopy(item["arguments"]),
                "session_id": item["session_id"],
                "turn_id": item["turn_id"],
                "status": "unknown",
                "state": item["state"],
                "result": copy.deepcopy(item["result"]),
            }
            for call_id, item in self._current()["actions"].items()
            if item["state"] == "intent"
            or (item["state"] == "settled" and item["result"].get("status") == "unknown")
        ]
