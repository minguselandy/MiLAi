"""Versioned, user-scoped Lab memory over the existing Workspace primitives.

Acquisition publishes immutable observations. The Host authors interpretations;
semantic judgments (subject, applicability, uncertainty and forgetting) remain
explicit Host actions. Checkpoints contain only retained user memory.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from jsonschema import ValidationError, validate  # type: ignore[import-untyped]

from milai_lab.methods.contextual_memory.decision_basis import (
    DecisionBasis,
)
from milai_lab.methods.contextual_memory.decision_basis import (
    mark_change as mark_decision_change,
)
from milai_lab.methods.contextual_memory.decision_basis import (
    restored as restored_decision,
)
from milai_lab.methods.contextual_memory.deletion import DeletionLedger
from milai_lab.methods.contextual_memory.material_view import MaterialView
from milai_lab.methods.contextual_memory.materials import base_material, linked_packet
from milai_lab.methods.contextual_memory.models import (
    Interpretation,
    Observation,
    TaskState,
)
from milai_lab.methods.contextual_memory.models import (
    ReceiptOutcome as ReceiptOutcome,
)
from milai_lab.methods.contextual_memory.models import (
    receipt_outcome as receipt_outcome,
)
from milai_lab.methods.contextual_memory.operations import TaskEnvelope, new_save_operation_id
from milai_lab.methods.contextual_memory.query_context import (
    accept_evidence,
    project_query,
    scope_result,
    task_context,
)
from milai_lab.methods.contextual_memory.retrieval import (
    Ranked,
    index_entries,
    rank,
)
from milai_lab.methods.contextual_memory.revision import (
    apply_changeset,
    mark_affected,
    now,
    support_view,
)
from milai_lab.methods.contextual_memory.store import RevisionStore
from milai_lab.methods.contextual_memory.write_contract import (
    CONDITION_DEFINITIONS,
    WRITE_RULES,
    apply_content_patch,
    normalize_basis_delta,
    validate_changeset_fields,
    validate_conditions,
    validate_date,
)
from milai_lab.methods.controlled_workspace import (
    FocusFrame,
    MemoryCard,
    WorkspaceSnapshot,
    apply_workspace_patch,
)
from milai_lab.methods.state_attention import (
    AttentionLimits,
    AttentionState,
    CoverageReview,
    StateField,
    decide_attention,
    question_digest,
)
from milai_lab.methods.state_focus import SourceSnapshot, SourceUnit

METHOD_VERSION = "contextual-user-memory-v16"
INDEX_POLICY = "source-range-2048-overlap256-bm25-vector-rrf60-v2"


def _known_cutoff(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("INVALID_KNOWN_AT") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _schema(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
            },
        },
    }


_STRING = {"type": "string"}
_DATE_VALUE = {"type": "string", "pattern": "^([0-9]{4}-[0-9]{2}-[0-9]{2})?$"}
_REFS = {"type": "array", "items": _STRING, "uniqueItems": True}
_CONDITIONS_SCHEMA = {
    "type": "object", "properties": {
        key: {"type": "string",
              "description": f"{definition.meaning}. Comparison: {definition.comparison}."}
        for key, definition in CONDITION_DEFINITIONS.items()
    },
    "additionalProperties": False,
}
_CONDITION_EVIDENCE = {"type": "array", "items": {
    "type": "object", "properties": {
        "key": {"enum": list(CONDITION_DEFINITIONS)}, "value": _STRING,
        "basis": {"enum": ["visible_question", "visible_source", "inference"]},
        "basis_ref": _STRING, "quote": _STRING, "reason": _STRING,
    }, "required": ["key", "value", "basis"], "additionalProperties": False,
}}
_SUPPORT_ITEM_SCHEMA = {
    "type": "object", "properties": {
        "ref": _STRING,
        "start": {"type": "integer", "minimum": 0},
        "end": {"type": "integer", "minimum": 1},
    }, "required": ["ref"], "additionalProperties": False,
}
_CLAIM_OPERATION = {
    "type": "object",
    "properties": {
        "op": {"const": "claim"}, "alias": {"type": "string", "pattern": "^new:[A-Za-z0-9_-]+$"},
        "content": _STRING, "target_ref": _STRING, "source_refs": _REFS,
        "subject": _STRING, "context": _STRING,
        "certainty": {"enum": ["explicit", "inferred", "uncertain"]},
        "persistence": {"enum": ["durable", "task"]},
        "conditions": _CONDITIONS_SCHEMA,
        "valid_from": _DATE_VALUE, "valid_until": _DATE_VALUE,
        "uncertain_start": {"type": "boolean"},
        "uncertain_end": {"type": "boolean"},
    },
    "required": ["op", "content"], "additionalProperties": False,
}
_JUSTIFICATION_OPERATION = {
    "type": "object",
    "properties": {
        "op": {"const": "justification"}, "target_ref": _STRING,
        "polarity": {"enum": ["support", "oppose"]},
        "items": {"type": "array", "minItems": 1, "items": _SUPPORT_ITEM_SCHEMA},
        "conditions": _CONDITIONS_SCHEMA,
        "valid_from": _DATE_VALUE, "valid_until": _DATE_VALUE,
    },
    "required": ["op", "target_ref", "polarity", "items"], "additionalProperties": False,
}
_RETRACT_OPERATION = {
    "type": "object", "properties": {
        "op": {"const": "retract_justification"}, "group_id": _STRING,
    }, "required": ["op", "group_id"], "additionalProperties": False,
}
_STATE_CHANGE_OPERATION = {
    "type": "object", "properties": {
        "op": {"const": "state_change"}, "old_ref": _STRING,
        "valid_from": _DATE_VALUE, "content": _STRING,
        "alias": {"type": "string", "pattern": "^new:[A-Za-z0-9_-]+$"},
        "source_refs": _REFS, "subject": _STRING, "context": _STRING,
        "certainty": {"enum": ["explicit", "inferred", "uncertain"]},
        "conditions": _CONDITIONS_SCHEMA,
    }, "required": ["op", "old_ref", "content"],
    "additionalProperties": False,
}
_TASK_OVERRIDE_OPERATION = {
    "type": "object", "properties": {
        "op": {"const": "task_override"}, "target_ref": _STRING, "content": _STRING,
    }, "required": ["op", "target_ref", "content"], "additionalProperties": False,
}
_REINTERPRET_OPERATION = {
    "type": "object", "properties": {
        "op": {"const": "reinterpret"}, "target_ref": _STRING,
        "group_ids": _REFS,
        "alias": {"type": "string", "pattern": "^new:[A-Za-z0-9_-]+$"},
        "content": _STRING, "source_refs": _REFS, "subject": _STRING,
        "context": _STRING, "certainty": {"enum": ["explicit", "inferred", "uncertain"]},
        "conditions": _CONDITIONS_SCHEMA,
        "valid_from": _DATE_VALUE, "valid_until": _DATE_VALUE,
    }, "required": ["op", "target_ref", "group_ids"], "additionalProperties": False,
}
_REVIEW_OPERATION = {
    "type": "object", "properties": {
        "op": {"const": "review"}, "target_ref": _STRING,
        "decision": {"enum": ["keep", "unresolved"]},
    }, "required": ["op", "target_ref", "decision"], "additionalProperties": False,
}
CHANGESET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "groups": {"type": "array", "maxItems": 12, "items": {
            "type": "object", "properties": {
                "reason_refs": _REFS,
                "operations": {"type": "array", "minItems": 1, "maxItems": 16,
                               "items": {"oneOf": [
                                   _CLAIM_OPERATION, _JUSTIFICATION_OPERATION, _RETRACT_OPERATION,
                                   _STATE_CHANGE_OPERATION, _TASK_OVERRIDE_OPERATION,
                                   _REINTERPRET_OPERATION, _REVIEW_OPERATION,
                               ]}},
            }, "required": ["operations"], "additionalProperties": False,
        }},
    }, "required": ["groups"], "additionalProperties": False,
}
TOOLS = [
    _schema(
        "memory_search",
        "Discover current sources and interpretations; whole units only.",
        {
            "query": _STRING,
            "focus": {"type": "string", "enum": ["default", "critical_gap"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 32},
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": 65536},
            "valid_at": _STRING,
            "known_at": _STRING,
            "date_from": _STRING,
            "date_to": _STRING,
            "session_id": _STRING,
            "neighbor_window": {"type": "integer", "minimum": 0, "maximum": 8},
            "condition_evidence": _CONDITION_EVIDENCE,
        },
    ),
    _schema(
        "memory_read",
        "Read an exact reference, its sources, and dependency versions.",
        {
            "ref": _STRING,
            "include_sources": {"type": "boolean"},
            "start": {"type": "integer", "minimum": 0},
            "length": {"type": "integer", "minimum": 1, "maximum": 16000},
            "valid_at": _STRING,
            "known_at": _STRING,
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": 65536},
            "neighbor_window": {"type": "integer", "minimum": 0, "maximum": 8},
            "condition_evidence": _CONDITION_EVIDENCE,
        },
    ),
    _schema(
        "memory_save",
        WRITE_RULES,
        {
            "content": _STRING,
            "content_patch": {"type": "array", "minItems": 1, "maxItems": 8,
                "items": {"type": "object", "properties": {
                    "old": {"type": "string", "minLength": 1}, "new": _STRING,
                }, "required": ["old", "new"], "additionalProperties": False}},
            "literal_uses": {"type": "array", "items": {"type": "object", "properties": {
                "token": {"type": "string", "minLength": 1},
                "source_ref": {"type": "string", "minLength": 1},
            }, "required": ["token", "source_ref"], "additionalProperties": False},
                "description": "Optional literal use of an issued material handle as actual "
                "source text. source_ref must be delivered and support this write; the "
                "new prose must use token literally, never to point at material."},
            "op": {"enum": ["CREATE", "REVISE", "RETAIN_SOURCE", "NO_CHANGE"]},
            "source_ref": {
                "type": "string",
                "minLength": 1,
                "description": "Copy an actual published source_ref. Omit if absent.",
            },
            "source_refs": _REFS,
            "basis_mode": {"enum": ["delta"]},
            "source_delta": {"type": "object", "properties": {
                "add": _REFS, "remove": _REFS,
            }, "required": ["add", "remove"], "additionalProperties": False},
            "dependency_delta": {"type": "object", "properties": {
                "add": _REFS, "remove": _REFS,
            }, "required": ["add", "remove"], "additionalProperties": False},
            "about_ref": {
                "type": "string",
                "description": "Bound subject identity: current user, trusted actor, a delivered "
                "source speaker, or unresolved. current_user/u0 means the actual memory owner, "
                "not every person or entity mentioned in a user message. Use unresolved/unknown "
                "for an entity without a justified person binding and name it in the content. "
                "subject describes the matter, not person identity.",
            },
            "target_ref": {
                "type": "string",
                "minLength": 1,
                "description": "Update an existing record only: copy its exact ref from "
                "memory_read. Omit for new records. Never invent a record name.",
            },
            "subject": _STRING,
            "context": _STRING,
            "certainty": {"enum": ["explicit", "inferred", "uncertain"]},
            "persistence": {
                "enum": ["durable", "task"],
                "description": "durable survives new Host sessions; use it for information needed "
                "in later work, including pending or time-limited matters. It does not mean "
                "permanent truth. task expires at this session's end; it does not mean a record "
                "about a business task. Use task only for disposable working notes.",
            },
            "conditions": _CONDITIONS_SCHEMA,
            "dependencies": _REFS,
            "valid_from": _DATE_VALUE,
            "valid_until": _DATE_VALUE,
            "uncertain_start": {"type": "boolean"},
            "uncertain_end": {"type": "boolean"},
            "changeset": CHANGESET_SCHEMA,
        },
    ),
    _schema(
        "memory_state",
        "Optional current-task understanding; free text does not alter an explicit query. "
        "With UNKNOWN "
        "coverage, Attention keeps its baseline selection even when intentions are set. "
        "A coverage review applies only to the last returned memory_search selection; "
        "set coverage in a separate call after reviewing that result. It resets on "
        "changed state, memory, query, or task. Never "
        "silently promotes a temporary exception to a lasting preference. "
        "Put narrative intentions and conflicts in context; reference fields "
        "accept only exact refs copied from tool results.",
        {
            "context": _STRING,
            "subject": _STRING,
            "uncertainty": _STRING,
            "intentions": {
                **_REFS,
                "description": "Exact refs from memory tool results only; put prose in context.",
            },
            "conflicts": {
                **_REFS,
                "description": "Exact refs from memory tool results only; put prose in context.",
            },
            "coverage": {
                "enum": ["SUFFICIENT", "GAP", "UNKNOWN"],
                "description": "Review the last returned memory_search selection only; "
                "set alone after inspecting it. UNKNOWN makes no coverage claim.",
            },
            "conditions": _CONDITIONS_SCHEMA,
            "valid_at": _DATE_VALUE,
            "known_at": _STRING,
        },
    ),
]

TOOLS[1]["function"]["parameters"]["required"] = ["ref"]


class ContextualMemory:
    """One user's bank and one task's Workspace; storage is owned by the runner."""

    def __init__(
        self,
        user_id: str,
        *,
        host_id: str,
        embed: Callable[[list[str]], list[list[float]]],
        embedding_model: str = "bge-m3",
        embedding_dimension: int = 1024,
        embedding_identity: str | None = None,
        state_policy: str = "off",
        decision_policy: str = "off",
        decision_feedback: bool | None = None,
        decision_gap_focus: bool | None = None,
        profile: str = "ordinary",
        material_mode: str = "plain",
        maintenance_mode: str = "eager",
        deletion_ledger: DeletionLedger | None = None,
    ) -> None:
        self.user_id, self.host_id, self.embed = user_id, host_id, embed
        self.scope = hashlib.sha256(user_id.encode()).hexdigest()[:16]
        self.embedding_model, self.embedding_dimension = embedding_model, embedding_dimension
        self.embedding_identity = embedding_identity
        if state_policy not in {"off", "optional", "forced_legacy"}:
            raise ValueError("UNKNOWN_STATE_POLICY")
        self.state_policy = state_policy
        if decision_policy not in {"off", "notes", "basis"} or (
            decision_policy != "off" and state_policy != "off"
        ):
            raise ValueError("UNKNOWN_OR_INCOMPATIBLE_DECISION_POLICY")
        decision_feedback = (decision_policy == "basis" if decision_feedback is None
                             else decision_feedback)
        decision_gap_focus = (decision_policy == "basis" if decision_gap_focus is None
                              else decision_gap_focus)
        if (type(decision_feedback) is not bool or type(decision_gap_focus) is not bool
                or (decision_policy != "basis" and
                    (decision_feedback or decision_gap_focus))):
            raise ValueError("INVALID_DECISION_CONTROL")
        self.decision_policy = decision_policy
        self.decision_feedback = decision_feedback
        self.decision_gap_focus = decision_gap_focus
        self.state_used = False
        if profile not in {"ordinary", "support"}:
            raise ValueError("UNKNOWN_MEMORY_PROFILE")
        self.profile = profile
        if material_mode not in {"plain", "linked"}:
            raise ValueError("UNKNOWN_MATERIAL_MODE")
        if maintenance_mode not in {"eager", "pending"}:
            raise ValueError("UNKNOWN_MAINTENANCE_MODE")
        self.material_mode = material_mode
        self.maintenance_mode = maintenance_mode
        self.workspace = WorkspaceSnapshot()
        self.state = TaskState("", query_context=task_context("", ""))
        self.execution_context = TaskEnvelope(user_id, "", "answer")
        self.sources: dict[str, Observation] = {}
        self.source_replacements: dict[str, str] = {}
        self.source_known_at: dict[str, str] = {}
        self.source_replacement_at: dict[str, str] = {}
        self.source_sequence: dict[str, int] = {}
        self.next_source_sequence = 1
        self.last_known_at = ""
        self.retained: set[str] = set()
        self.task_sources: set[str] = set()
        self.forgotten: set[str] = set()
        self.forget_generation = 0
        self.details: dict[str, Interpretation] = {}
        self.history: dict[str, dict[str, Any]] = {}
        self.vectors: dict[str, list[float]] = {}
        self.seen: set[str] = set()
        self.visible_source_ranges: dict[str, set[tuple[int, int]]] = {}
        self.next_card = 1
        self.expansion: dict[str, Any] = {}
        self.latest_search: dict[str, Any] | None = None
        self.coverage_binding: dict[str, Any] | None = None
        self.revisions = RevisionStore()
        self.local_timings = {"retrieval_seconds": 0.0, "material_seconds": 0.0}
        if deletion_ledger is not None and deletion_ledger.user_id != user_id:
            raise ValueError("DELETION_LEDGER_USER_MISMATCH")
        self.deletion_ledger = deletion_ledger
        self._apply_deletions()

    @property
    def contextual(self) -> bool:
        """Read-only compatibility for existing Host tool selection."""
        return self.state_policy != "off"

    def _apply_deletions(self) -> None:
        if self.deletion_ledger is None:
            return
        deletion = self.deletion_ledger.read()
        for operation in deletion.operations.values():
            if not operation.committed:
                self.deletion_ledger.commit(operation.operation_id, self.next_card)
        deletion = self.deletion_ledger.read()
        present = deletion.refs & (self._known_refs() | self.history.keys())
        if present:
            self._erase_deletion(set(present))
        elif deletion.generation > self.forget_generation:
            # An old task overlay may contain copied body even if its source was absent.
            self.state = TaskState(
                self.state.task_id,
                query_context=task_context(self.state.task_id, ""),
            )
            self.workspace.working_note = ""
            self.workspace.frame = FocusFrame()
            self.expansion = {}
            self.latest_search = None
            self.coverage_binding = None
        self.forgotten.update(deletion.refs)
        self.forget_generation = max(self.forget_generation, deletion.generation)
        self.next_card = max(self.next_card, deletion.next_card)

    def _invalidate_coverage(self) -> None:
        self.state.coverage = "UNKNOWN"
        self.latest_search = None
        self.coverage_binding = None

    def _state_signature(self) -> str:
        return hashlib.sha256(
            json.dumps(
                [
                    self.state.task_id,
                    self.state.context,
                    self.state.subject,
                    self.state.uncertainty,
                    self.state.intentions,
                    self.state.conflicts,
                    self.state.conditions,
                    self.state.query_context,
                    self.state.valid_at,
                    self.state.known_at,
                    self.state.overrides,
                ],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()

    def _ref(self, card: MemoryCard) -> str:
        return f"{self.scope}/{card.handle}@{card.revision}"

    def _handle(self, ref: str) -> str:
        prefix = f"{self.scope}/"
        if not ref.startswith(prefix):
            raise ValueError("REFERENCE_BELONGS_TO_ANOTHER_USER")
        return ref.removeprefix(prefix).split("@", 1)[0]

    def _known_now(self) -> str:
        candidate = now()
        if self.last_known_at and candidate <= self.last_known_at:
            candidate = (
                datetime.fromisoformat(self.last_known_at) + timedelta(microseconds=1)
            ).isoformat(timespec="microseconds")
        self.last_known_at = candidate
        return candidate

    def publish(self, observation: Observation, *, sequence: int | None = None) -> str:
        """Only an input adapter may publish; never exposed as a model tool."""
        self._apply_deletions()
        identity = json.dumps([observation.artifact, observation.session_id, observation.event_id])
        ref = f"{self.scope}/source:{hashlib.sha256(identity.encode()).hexdigest()[:24]}"
        if ref in self.forgotten:
            return ref
        if observation.supersedes in self.forgotten:
            self.forgotten.add(ref)
            if self.deletion_ledger is not None:
                deletion = self.deletion_ledger.record({ref}, self.next_card)
                self.forget_generation = max(self.forget_generation, deletion.generation)
            return ref
        old = self.sources.get(ref)
        if old is not None and old != observation:
            raise ValueError("SOURCE_IDENTITY_REUSED_WITH_DIFFERENT_OBSERVATION")
        if old is not None:
            return ref
        source_time = self._known_now()
        if observation.supersedes:
            self.sources[observation.supersedes]
            if self.resolve(observation.supersedes) != observation.supersedes:
                raise ValueError("SOURCE_REPLACEMENT_REQUIRES_CURRENT_REF")
            self.source_replacements[observation.supersedes] = ref
            self.source_replacement_at[observation.supersedes] = source_time
            if observation.supersedes in self.retained:
                self.retained.add(ref)
            elif observation.supersedes in self.task_sources:
                self.task_sources.add(ref)
            self._drop_vectors(observation.supersedes)
        self.sources[ref] = observation
        self.source_known_at[ref] = source_time
        self.source_sequence[ref] = self.next_source_sequence if sequence is None else sequence
        self.next_source_sequence = max(self.next_source_sequence, self.source_sequence[ref] + 1)
        if observation.supersedes:
            mark_affected(self, {observation.supersedes}, reviewed=set())
            self._scan_decision_changes()
        self._invalidate_coverage()
        return ref

    def source_subject(self, ref: str) -> str:
        """A trusted actor is stable; an unknown speaker is scoped to one exact source."""
        source = self.sources[ref]
        if source.actor_ref == "current_user":
            return "current_user"
        if source.actor_ref:
            return f"actor:{source.actor_ref}"
        return f"speaker:{ref}"

    def start_task(
        self, task_id: str, question: str, *, handoff: dict[str, Any] | None = None,
        task_conditions: dict[str, str] | None = None, task_valid_at: str = "",
    ) -> None:
        fresh_context = task_context(task_id, question, task_conditions, task_valid_at)
        self._apply_deletions()
        self.execution_context = TaskEnvelope(
            self.user_id, task_id, "history" if task_id == "history" else "answer",
        )
        if handoff is not None:
            if handoff["user_id"] != self.user_id:
                raise ValueError("HANDOFF_USER_MISMATCH")
            if handoff.get("forget_generation", 0) != self.forget_generation:
                raise ValueError("HANDOFF_PRECEDES_FORGET")
        removed_refs = set(self.task_sources - self.retained)
        for handle in list(self.workspace.cards):
            if self.details[handle].persistence == "task":
                removed_refs.add(self._ref(self.workspace.cards[handle]))
                removed_refs.update(ref for ref in self.history if self._handle(ref) == handle)
                self._drop_card(handle)
        for ref in self.sources.keys() - self.retained:
            self.sources.pop(ref, None)
            self.source_known_at.pop(ref, None)
            self.source_sequence.pop(ref, None)
            self._drop_vectors(ref)
        self.task_sources.clear()
        self.revisions.prune_refs(removed_refs)
        self.revisions.changesets = [
            entry for entry in self.revisions.changesets
            if not any(
                operation["op"] == "task_override"
                for operation in entry["outcome"]["operations"]
            )
        ]
        self.source_replacements = {
            old: new
            for old, new in self.source_replacements.items()
            if old in self.sources and new in self.sources
        }
        self.source_replacement_at = {
            old: timestamp for old, timestamp in self.source_replacement_at.items()
            if old in self.source_replacements
        }
        self.state = TaskState(task_id, valid_at=task_valid_at, query_context=fresh_context)
        self.state_used = False
        self.workspace.frame = FocusFrame(question=question)
        self.workspace.working_note = ""
        self.seen.clear()
        self.visible_source_ranges.clear()
        self.expansion = {}
        self.latest_search = None
        self.coverage_binding = None
        if handoff is not None:
            self._restore_overlay(handoff["overlay"])
            transferred = copy.deepcopy(handoff["state"])
            same_task = (
                transferred["task_id"] == task_id
                and transferred.get("query_context", {}).get("question") == question
            )
            transferred["task_id"] = task_id
            transferred["coverage"] = "UNKNOWN"
            if not same_task:
                transferred["overrides"] = {}
                transferred["conditions"] = {}
                transferred["query_context"] = fresh_context
                transferred["valid_at"] = task_valid_at
                transferred["known_at"] = ""
            for key in ("intentions", "conflicts", "recent_refs"):
                transferred[key] = [self.resolve(ref) for ref in transferred[key]]
            transferred["active_decision"] = restored_decision(
                transferred.get("active_decision")
            ) if same_task else None
            transferred["work_note"] = transferred.get("work_note", "") if same_task else ""
            self.state = TaskState(**transferred)
            self.state_used = bool(handoff.get("state_used", False))
            self.workspace.working_note = self.state.context
            self.workspace.frame.intent = self.state.context
            self.workspace.frame.selected_refs = list(self.state.intentions)

    def advance_turn(
        self, question: str, *, conditions: dict[str, str] | None = None,
        valid_at: str = "",
    ) -> None:
        """Move the current request forward without dropping session sources or State."""
        fresh = task_context(self.state.task_id, question, conditions, valid_at)
        previous_conditions = {
            (item["key"], item["value"])
            for item in self.state.query_context.get("condition_evidence", [])
            if item.get("basis") == "task_input"
        }
        next_conditions = {
            (item["key"], item["value"])
            for item in fresh.get("condition_evidence", [])
            if item.get("basis") == "task_input"
        }
        changed = self.state.valid_at != valid_at or previous_conditions != next_conditions
        self.state.query_context = fresh
        self.state.valid_at = valid_at
        self.state.conditions = {}
        self.state.known_at = ""
        self.workspace.frame.question = question
        self.expansion = {}
        self._invalidate_coverage()
        if changed and self.decision_feedback and self.state.active_decision is not None:
            for adopted in self.state.active_decision.adopted:
                mark_decision_change(self.state.active_decision, exact_ref=adopted.exact_ref,
                                     current_ref=adopted.observed_ref,
                                     reason="task_scope_changed")

    def apply_decision(self, value: DecisionBasis | None) -> None:
        if self.decision_policy != "basis":
            raise ValueError("DECISION_POLICY_NOT_BASIS")
        if value is not None and value.task_id != self.state.task_id:
            raise ValueError("DECISION_TASK_MISMATCH")
        old_focus = (
            self.state.active_decision.critical_gap,
            self.state.active_decision.scope.get("item", ""),
            self.state.active_decision.status,
        ) if self.state.active_decision is not None else ("", "", "")
        self.state.active_decision = value
        new_focus = (
            value.critical_gap, value.scope.get("item", ""), value.status,
        ) if value else ("", "", "")
        if old_focus != new_focus:
            self.expansion = {}
            self.latest_search = None
        self._scan_decision_changes()

    def _scan_decision_changes(self) -> None:
        decision = self.state.active_decision
        if decision is None or not self.decision_feedback:
            return
        for row in decision.adopted:
            try:
                current = self.resolve(row.exact_ref)
            except (KeyError, ValueError):
                current = "unavailable"
            if current != row.observed_ref:
                mark_decision_change(decision, exact_ref=row.exact_ref,
                                     current_ref=current, reason="adopted_version_changed")

    def bind_envelope(self, envelope: TaskEnvelope) -> None:
        if envelope.user_id != self.user_id or envelope.task_id != self.state.task_id:
            raise ValueError("TASK_ENVELOPE_SCOPE_MISMATCH")
        self.execution_context = envelope

    def _accept_condition_evidence(self, proposed: list[dict[str, str]] | None) -> None:
        if not proposed:
            return
        keys = set(self.state.conditions)
        keys.update(item["key"] for item in self.state.query_context["condition_evidence"])
        keys.update(
            key for detail in self.details.values() for key in detail.conditions
        )
        keys.update(key for record in self.history.values() for key in record["conditions"])
        keys.update(
            key for group in self.revisions.groups.values() for key in group.conditions
        )
        sources = {
            ref: [self.sources[ref].content[start:end] for start, end in ranges]
            for ref, ranges in self.visible_source_ranges.items()
        }
        next_context = accept_evidence(
            self.state.query_context, proposed, known_keys=keys,
            source_text=sources, seen=self.seen,
        )
        if next_context != self.state.query_context:
            self.state.query_context = next_context
            self._invalidate_coverage()

    def _note_source_visibility(self, material: Any) -> None:
        """Track only source pages actually returned, including associated excerpts."""
        if isinstance(material, list):
            for item in material:
                self._note_source_visibility(item)
        elif isinstance(material, dict):
            ref = material.get("ref")
            if ref in self.sources:
                pages = ([material] if "content" in material else []) + material.get("excerpts", [])
                for page in pages:
                    span = page.get("page")
                    if span is not None:
                        self.visible_source_ranges.setdefault(ref, set()).add(
                            (span["start"], span["end"])
                        )
                        self.seen.add(ref)
            for value in material.values():
                if isinstance(value, (dict, list)):
                    self._note_source_visibility(value)

    def resolve(self, ref: str) -> str:
        return self.resolve_at(ref, "")

    def resolve_at(self, ref: str, known_at: str = "") -> str:
        known_at = _known_cutoff(known_at)
        if ref in self.sources:
            if known_at and self.source_known_at[ref] > known_at:
                raise ValueError("REFERENCE_NOT_YET_KNOWN")
            while ref in self.source_replacements and (
                not known_at or self.source_replacement_at[ref] <= known_at
            ):
                ref = self.source_replacements[ref]
            return ref
        handle = self._handle(ref)
        card = self.workspace.cards[handle]
        if not known_at:
            return self._ref(card)
        versions = [
            historical for historical in self.history
            if self._handle(historical) == handle
            and self.history[historical]["known_at"] <= known_at
        ]
        current = self._ref(card)
        if self.details[handle].known_at <= known_at:
            versions.append(current)
        if not versions:
            raise ValueError("REFERENCE_NOT_YET_KNOWN")
        return max(versions, key=lambda version: int(version.rsplit("@", 1)[1]))

    def _dependency_status(
        self, details: Interpretation, known_at: str = ""
    ) -> list[dict[str, str]]:
        result = []
        for ref in details.dependencies:
            try:
                current = self.resolve_at(ref, known_at)
            except (KeyError, ValueError):
                current = "UNAVAILABLE"
            result.append(
                {
                    "observed_ref": ref,
                    "current_ref": current,
                    "status": "CURRENT" if current == ref else "NEEDS_REVISION",
                }
            )
        return result

    def read(
        self, ref: str, include_sources: bool = True, start: int = 0, length: int = 16000,
        valid_at: str = "", known_at: str = "", max_bytes: int = 16000,
        neighbor_window: int = 0,
        condition_evidence: list[dict[str, str]] | None = None,
        _visible: bool = True,
    ) -> dict[str, Any]:
        started = time.monotonic()
        self._accept_condition_evidence(condition_evidence)
        projected = project_query(
            "", task_context=self.state.query_context, state=self.state,
            explicit_filters={"valid_at": valid_at, "known_at": known_at},
        )
        effective_known = _known_cutoff(projected["filters"]["known_at"])
        effective_date = projected["filters"]["valid_at"]
        result = self._view(ref, False, valid_at=effective_date, known_at=effective_known)
        field_name = "content" if result["kind"] == "source" else "text"
        original = result[field_name]
        result[field_name] = original[start : start + length]
        result["page"] = {
            "start": start,
            "end": min(start + length, len(original)),
            "total_chars": len(original),
            "complete": start == 0 and length >= len(original),
            "content_sha256": hashlib.sha256(original.encode()).hexdigest(),
        }
        if _visible:
            self.seen.add(ref)
        if include_sources and result["kind"] == "interpretation":
            remaining = max(0, length - len(result[field_name]))
            pages = []
            source_refs = list(
                dict.fromkeys(
                    expanded
                    for source_ref in result["source_refs"]
                    for expanded in (self.resolve_at(source_ref, effective_known), source_ref)
                )
            )
            for source_ref in source_refs:
                if remaining <= 0:
                    break
                page = self.read(
                    source_ref, False, length=remaining, valid_at=effective_date,
                    known_at=effective_known, max_bytes=0,
                    _visible=False,
                )
                pages.append(page)
                remaining -= len(page["content"])
            result["sources"] = pages
            result["unexpanded_sources"] = source_refs[len(pages) :]
        if (self.material_mode == "linked" or result["kind"] == "source") and max_bytes > 0:
            result = linked_packet(
                self, ref, valid_at=effective_date, known_at=effective_known,
                max_bytes=max_bytes, neighbor_window=neighbor_window,
                base_override=result,
                correction_only=self.material_mode != "linked",
            )
        self.local_timings["material_seconds"] += time.monotonic() - started
        if _visible:
            self._note_source_visibility(result)
        return result

    def claim_applicability(
        self, ref: str, *, valid_at: str = "", known_at: str = ""
    ) -> str:
        status: str = self.claim_applicability_view(
            ref, valid_at=valid_at, known_at=known_at,
        )["status"]
        return status

    def claim_applicability_view(
        self, ref: str, *, valid_at: str = "", known_at: str = "",
    ) -> dict[str, Any]:
        handle = self._handle(ref)
        details = (
            self.history[ref] if ref != self._ref(self.workspace.cards[handle])
            else asdict(self.details[handle])
        )
        if known_at and details["known_at"] > known_at:
            return {"status": "UNUSABLE", "reasons": [{"kind": "known_at", "verdict": "MISMATCH"}]}
        result = scope_result(
            details.get("conditions", {}), details.get("valid_from", ""),
            details.get("valid_until", ""),
            self.state.query_context, self.state.conditions, valid_at,
        )
        if details.get("uncertain_end", False) and not valid_at:
            result["status"] = "UNUSABLE"
            result["reasons"].append({"kind": "world_boundary", "verdict": "ENDED_UNKNOWN_DATE"})
        elif (details.get("uncertain_start", False)
              or details.get("uncertain_end", False)) and valid_at:
            if result["status"] != "UNUSABLE":
                result["status"] = "PENDING"
            result["reasons"].append({"kind": "world_boundary", "verdict": "UNKNOWN_DATE"})
        return result

    def _view(
        self, ref: str, include_sources: bool = True, *, valid_at: str = "",
        known_at: str = "",
    ) -> dict[str, Any]:
        effective_date = valid_at
        effective_known = _known_cutoff(known_at)
        if ref in self.sources:
            if effective_known and self.source_known_at[ref] > effective_known:
                raise ValueError("REFERENCE_NOT_YET_KNOWN")
            source = self.sources[ref]
            current_ref = self.resolve_at(ref, effective_known)
            return {
                "ref": ref,
                "kind": "source",
                **asdict(source),
                "retained": ref in self.retained,
                **({"known_at": self.source_known_at[ref]} if self.profile == "support" else {}),
                "current_ref": current_ref,
                "status": "SUPERSEDED" if ref != current_ref else "CURRENT",
                "provenance": "acquired_observation_not_verified_truth",
            }
        handle = self._handle(ref)
        card = self.workspace.cards[handle]
        current_ref = self.resolve_at(ref, effective_known)
        exact_current = self._ref(card)
        if ref != exact_current:
            old = copy.deepcopy(self.history[ref])
            if effective_known and old["known_at"] > effective_known:
                raise ValueError("REFERENCE_NOT_YET_KNOWN")
            old["dependency_status"] = self._dependency_status(
                Interpretation(old["author"], dependencies=old["dependencies"]),
                effective_known,
            ) + [
                {
                    "observed_ref": source,
                    "current_ref": self.resolve_at(source, effective_known),
                    "status": "NEEDS_REVISION",
                }
                for source in old["source_refs"]
                if source in self.source_replacements
                and self.resolve_at(source, effective_known) != source
            ]
            result = {**old, "current_ref": current_ref}
        else:
            details = self.details[handle]
            if effective_known and details.known_at > effective_known:
                raise ValueError("REFERENCE_NOT_YET_KNOWN")
            detail_view = asdict(details)
            if self.profile == "ordinary":
                for key in (
                    "valid_from", "valid_until", "known_at",
                    "uncertain_start", "uncertain_end",
                ):
                    detail_view.pop(key)
            result = {
                "ref": ref, "kind": "interpretation", **asdict(card), **detail_view,
                "dependency_status": self._dependency_status(details, effective_known) + [
                {
                    "observed_ref": source,
                    "current_ref": self.resolve_at(source, effective_known),
                    "status": "NEEDS_REVISION",
                }
                for source in card.source_refs
                if source in self.source_replacements
                and self.resolve_at(source, effective_known) != source
                ],
                "current_ref": current_ref,
            }
        if self.profile == "ordinary":
            for key in (
                "valid_from", "valid_until", "known_at", "uncertain_start", "uncertain_end",
            ):
                result.pop(key, None)
        result["about_ref"] = result.get("about_ref", "unresolved")
        result["about"] = self._about_view(result["about_ref"], result["source_refs"])
        result["status"] = "CURRENT" if ref == current_ref else "SUPERSEDED"
        applicability = self.claim_applicability_view(
            ref, valid_at=effective_date, known_at=effective_known,
        )
        result["structured_scope"] = applicability.get("structured_scope", "UNDECLARED")
        if self.profile == "support" or applicability["reasons"]:
            result["applicability"] = applicability["status"]
            result["applicability_reasons"] = applicability["reasons"]
        if self.profile == "support":
            result.update(support_view(
                self, ref, valid_at=effective_date, known_at=effective_known,
            ))
            override = self.state.overrides.get(ref)
            if override and (not effective_known or override["known_at"] <= effective_known):
                result["task_override"] = override
        pending = self.revisions.pending.get(ref)
        if pending and (not effective_known or pending["known_at"] <= effective_known):
            result["pending_review"] = copy.deepcopy(pending)
        if include_sources:
            result["sources"] = [
                self._view(source, False, valid_at=effective_date, known_at=effective_known)
                for source in result["source_refs"]
            ]
        return result

    def _retain(self, ref: str) -> None:
        self.retained.add(ref)
        while ref in self.source_replacements:
            ref = self.source_replacements[ref]
            self.retained.add(ref)

    def _about_view(self, about_ref: str, source_refs: list[str]) -> dict[str, str]:
        """Validate a bound subject once and explain it from trusted source identity."""
        if not isinstance(about_ref, str):
            raise ValueError("INVALID_ABOUT_REF")
        if about_ref == "current_user":
            return {"kind": "current_user", "user_id": self.user_id}
        if about_ref == "unresolved":
            return {"kind": "unresolved"}
        if about_ref.startswith("actor:"):
            actor_ref = about_ref.removeprefix("actor:")
            if not actor_ref or not any(
                self.sources[ref].actor_ref == actor_ref for ref in source_refs
            ):
                raise ValueError("ABOUT_ACTOR_NOT_CITED")
            return {"kind": "actor", "actor_ref": actor_ref}
        if about_ref.startswith("speaker:"):
            source_ref = about_ref.removeprefix("speaker:")
            if source_ref not in self.sources:
                raise ValueError("ABOUT_SOURCE_NOT_PUBLISHED")
            if source_ref not in source_refs:
                raise ValueError("ABOUT_SOURCE_NOT_CITED")
            return {
                "kind": "source_speaker", "source_ref": source_ref,
                "source_role": self.sources[source_ref].role,
            }
        raise ValueError("INVALID_ABOUT_REF")

    def save(
        self,
        *,
        op: str | None = None,
        content: str | None = None,
        content_patch: list[dict[str, str]] | None = None,
        basis_mode: str | None = None,
        source_delta: dict[str, list[str]] | None = None,
        dependency_delta: dict[str, list[str]] | None = None,
        source_ref: str | None = None,
        source_refs: list[str] | None = None,
        about_ref: str | None = None,
        target_ref: str | None = None,
        subject: str | None = None,
        context: str | None = None,
        certainty: str | None = None,
        persistence: str | None = None,
        conditions: dict[str, str] | None = None,
        dependencies: list[str] | None = None,
        forget_refs: list[str] | None = None,
        changeset: dict[str, Any] | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        uncertain_start: bool | None = None,
        uncertain_end: bool | None = None,
    ) -> dict[str, Any]:
        if basis_mode not in {None, "delta"}:
            raise ValueError("UNKNOWN_BASIS_MODE")
        delta_mode = basis_mode == "delta"
        if delta_mode:
            if (op != "REVISE" or target_ref is None or content_patch is None
                    or source_delta is None or any(value is not None for value in (
                        content, source_ref, source_refs, about_ref, subject, context,
                        certainty, persistence, conditions, dependencies, forget_refs,
                        changeset, valid_from, valid_until, uncertain_start, uncertain_end,
                    ))):
                raise ValueError("DELTA_REQUIRES_PATCH_AND_RELATION_CHANGES_ONLY")
        elif source_delta is not None or dependency_delta is not None:
            raise ValueError("DELTA_FIELDS_REQUIRE_BASIS_MODE")
        if forget_refs is not None:
            if any(value is not None for value in (
                content, content_patch, source_ref, source_refs, about_ref, target_ref,
                subject, context,
                certainty,
                persistence, conditions, dependencies, changeset, valid_from, valid_until,
                uncertain_start, uncertain_end, op,
            )):
                raise ValueError("SAVE_AND_DELETE_CANNOT_MIX")
            if not forget_refs:
                return {"status": "NO_CHANGE", "decision": "NO_CHANGE",
                        "memory_changes": [], "cleanup_effects": [], "completion": "complete"}
            raise ValueError("DELETE_REQUIRES_TRUSTED_EXECUTOR")
        if op == "NO_CHANGE":
            if any(value is not None for value in (
                content, content_patch, source_ref, source_refs, about_ref, target_ref,
                subject, context,
                certainty,
                persistence, conditions, dependencies, changeset, valid_from, valid_until,
                uncertain_start, uncertain_end,
            )):
                raise ValueError("NO_CHANGE_CANNOT_MIX_WRITE")
            return {"status": "NO_CHANGE", "decision": "NO_CHANGE",
                    "memory_changes": [], "cleanup_effects": [], "completion": "complete"}
        if op not in {None, "CREATE", "REVISE", "RETAIN_SOURCE"}:
            raise ValueError("UNKNOWN_WRITE_OPERATION")
        if content_patch is not None and (op != "REVISE" or content is not None):
            raise ValueError("CONTENT_PATCH_REQUIRES_REVISE_WITHOUT_CONTENT")
        if op == "CREATE" and (content is None or target_ref is not None):
            raise ValueError("CREATE_REQUIRES_NEW_CONTENT")
        if op == "REVISE" and ((content is None and content_patch is None)
                               or target_ref is None):
            raise ValueError("REVISE_REQUIRES_TARGET_AND_CONTENT")
        if op in {"CREATE", "REVISE"} and not delta_mode:
            if about_ref is None or source_refs is None or source_ref is not None:
                raise ValueError("WRITE_REQUIRES_EXPLICIT_ABOUT_AND_SOURCES")
            if certainty is None:
                raise ValueError("WRITE_REQUIRES_EXPLICIT_CERTAINTY")
            if op == "REVISE" and dependencies is None:
                raise ValueError("REVISION_REQUIRES_EXPLICIT_DEPENDENCIES")
        if op == "RETAIN_SOURCE" and (
            source_ref is None or any(value is not None for value in (
                content, content_patch, source_refs, about_ref, target_ref, subject,
                context, certainty,
                conditions, dependencies, changeset, valid_from, valid_until,
                uncertain_start, uncertain_end,
            ))
        ):
            raise ValueError("RETAIN_SOURCE_REQUIRES_SOURCE_ONLY")
        if changeset is not None and any(value is not None for value in (
            op, content, content_patch, source_ref, source_refs, about_ref, target_ref,
            subject, context,
            certainty, persistence, conditions, dependencies, valid_from, valid_until,
            uncertain_start, uncertain_end,
        )):
            raise ValueError("CHANGESET_CANNOT_MIX_LEGACY_RECORD")
        validate_conditions(conditions)
        validate_date(valid_from, "valid_from")
        validate_date(valid_until, "valid_until")
        if certainty is not None and certainty not in {"explicit", "inferred", "uncertain"}:
            raise ValueError("INVALID_CERTAINTY")
        results: dict[str, Any] = {}
        if source_ref is not None:
            self.sources[source_ref]  # Acquisition owns identity and role.
        if changeset is not None:
            validate_changeset_fields(changeset)
            if changeset.get("groups") == []:
                return {"status": "NO_CHANGE", "decision": "NO_CHANGE",
                        "memory_changes": [], "cleanup_effects": [], "completion": "complete"}
            results["changeset"] = apply_changeset(self, changeset)
            statuses = [group["status"] for group in results["changeset"]["groups"]]
            if any(status != "APPLIED" for status in statuses):
                results["status"] = (
                    "PARTIAL" if any(status == "APPLIED" for status in statuses) else "ERROR"
                )
            return results
        if content is None and target_ref is not None and content_patch is None:
            content = self.workspace.cards[self._handle(target_ref)].text
        if content is None and content_patch is None:
            if source_ref is None:
                raise ValueError("SAVE_REQUIRES_CONTENT_SOURCE_OR_FORGET")
            source_changed = (
                source_ref not in self.retained if persistence != "task" else
                source_ref not in self.retained | self.task_sources
            )
            if persistence != "task":
                self._retain(source_ref)
            elif source_ref not in self.retained:
                self.task_sources.add(source_ref)
            results["source"] = {
                "status": "RETAINED" if source_ref in self.retained else "TASK_ONLY",
                "ref": source_ref,
            }
            results["memory_changes"] = [source_ref] if source_changed else []
            results["decision"] = "COMMITTED" if source_changed else "NO_CHANGE"
            return results
        old: MemoryCard | None = None
        basis_change: dict[str, Any] = {}
        if target_ref is not None:
            handle = self._handle(target_ref)
            old = self.workspace.cards[handle]
            if target_ref != self._ref(old):
                return {
                    **results,
                    "record": {
                        "status": "VERSION_CONFLICT",
                        "target_ref": target_ref,
                        "current_ref": self._ref(old),
                    },
                }
            if target_ref not in self.seen:
                raise ValueError("REVISION_REQUIRES_READ_TARGET")
            if delta_mode:
                assert source_delta is not None
                source_refs, source_change = normalize_basis_delta(
                    old.source_refs, source_delta, kind="source",
                )
                dependencies, dependency_change = normalize_basis_delta(
                    self.details[handle].dependencies,
                    dependency_delta or {"add": [], "remove": []}, kind="dependency",
                )
                for ref in source_change["inherited"]:
                    if ref not in self.sources or ref in self.forgotten:
                        raise ValueError("INHERITED_SOURCE_UNAVAILABLE")
                    if self.resolve(ref) != ref:
                        raise ValueError("INHERITED_SOURCE_SUPERSEDED")
                for ref in source_change["added"]:
                    if ref not in self.sources or ref in self.forgotten:
                        raise ValueError("SOURCE_DELTA_ADD_UNAVAILABLE")
                    if self.resolve(ref) != ref:
                        raise ValueError("SOURCE_DELTA_ADD_SUPERSEDED")
                    if not self.visible_source_ranges.get(ref):
                        raise ValueError("SOURCE_DELTA_ADD_REQUIRES_READ")
                for ref in dependency_change["inherited"]:
                    if ref in self.sources:
                        raise ValueError("DEPENDENCY_REQUIRES_INTERPRETATION")
                    try:
                        current = self.resolve(ref)
                    except (KeyError, ValueError) as error:
                        raise ValueError("INHERITED_DEPENDENCY_UNAVAILABLE") from error
                    if current != ref:
                        raise ValueError("INHERITED_DEPENDENCY_SUPERSEDED")
                    if self.claim_applicability_view(ref)["status"] == "UNUSABLE":
                        raise ValueError("INHERITED_DEPENDENCY_UNUSABLE")
                reviewed = {
                    ref: [list(span) for span in sorted(self.visible_source_ranges[ref])]
                    for ref in dict.fromkeys([*old.source_refs, *source_change["added"]])
                    if self.visible_source_ranges.get(ref)
                }
                basis_change = {
                    "mode": "delta", "target_ref": target_ref,
                    "sources": source_change, "dependencies": dependency_change,
                    "reviewed_source_ranges": reviewed,
                }
                about_ref = self.details[handle].about_ref
                certainty = self.details[handle].certainty
            if content_patch is not None:
                content = apply_content_patch(old.text, content_patch)
            metadata = copy.deepcopy(self.details[handle])
        else:
            metadata = Interpretation(self.host_id)
        assert content is not None
        metadata.author = self.host_id
        metadata.basis_change = basis_change
        for key, value in (
            ("about_ref", about_ref),
            ("subject", subject),
            ("context", context),
            ("certainty", certainty),
            ("persistence", persistence),
            ("conditions", conditions),
            ("dependencies", dependencies),
            ("valid_from", valid_from),
            ("valid_until", valid_until),
            ("uncertain_start", uncertain_start),
            ("uncertain_end", uncertain_end),
        ):
            if value is not None:
                setattr(metadata, key, value)
        refs = list(source_refs if source_refs is not None else old.source_refs if old else [])
        if source_ref is not None and source_ref not in refs:
            refs.append(source_ref)
        if not set(refs) <= self.sources.keys():
            raise ValueError("SOURCE_NOT_PUBLISHED")
        self._about_view(metadata.about_ref, refs)
        if metadata.about_ref == "current_user" and metadata.persistence == "durable":
            if not refs:
                raise ValueError("DURABLE_USER_FACT_REQUIRES_SOURCE")
            if all(self.sources[ref].role == "assistant" for ref in refs):
                raise ValueError("DURABLE_USER_FACT_REQUIRES_NON_ASSISTANT_SOURCE")
        source_changed = source_ref is not None and (
            source_ref not in self.retained if metadata.persistence == "durable" else
            source_ref not in self.retained | self.task_sources
        )
        for dependency in metadata.dependencies:
            if dependency in self.sources:
                raise ValueError("DEPENDENCY_REQUIRES_INTERPRETATION")
            if old is not None and self._handle(dependency) == old.handle:
                raise ValueError("REVISION_CANNOT_DEPEND_ON_OWN_VERSION")
            if dependency not in self.seen and not (
                delta_mode and dependency in basis_change["dependencies"]["inherited"]
            ):
                raise ValueError("DEPENDENCY_REQUIRES_READ_VERSION")
        if (old is not None and old.text == content and old.source_refs == refs
                and replace(metadata, basis_change=self.details[old.handle].basis_change)
                == self.details[old.handle]):
            return {
                "status": "NO_CHANGE", "decision": "NO_CHANGE",
                "memory_changes": [],
                "record": {**self.read(self._ref(old), False), "status": "REUSED"},
            }
        if old is None:
            for existing in self.workspace.cards.values():
                if (existing.text, existing.source_refs, self.details[existing.handle]) == (
                    content,
                    refs,
                    replace(metadata, known_at=self.details[existing.handle].known_at),
                ):
                    if source_ref is not None:
                        if metadata.persistence == "task" and source_ref not in self.retained:
                            self.task_sources.add(source_ref)
                        else:
                            self._retain(source_ref)
                        results["source"] = {
                            "status": "RETAINED" if source_ref in self.retained else "TASK_ONLY",
                            "ref": source_ref,
                        }
                    results["memory_changes"] = [source_ref] if source_changed else []
                    results["decision"] = "COMMITTED" if source_changed else "NO_CHANGE"
                    return {
                        **results,
                        "record": {**self.read(self._ref(existing), False), "status": "REUSED"},
                    }
        if (
            old is None or old.text != content or old.source_refs != refs
            or metadata != self.details[old.handle]
        ):
            metadata.known_at = self._known_now()
        put: dict[str, Any] = {"text": content, "source_refs": refs}
        if old is not None:
            put["handle"] = old.handle
        patch = apply_workspace_patch(
            json.dumps({"workspace_update": {"put_cards": [put]}}),
            self.workspace,
            evidence_refs=set(self.sources),
            known_refs=self._known_refs() | self.history.keys(),
            next_card=self.next_card,
            max_cards=10000,
        )
        handle = old.handle if old else patch.created[0]
        updated_workspace = patch.workspace
        card = updated_workspace.cards[handle]
        if old is not None and metadata != self.details[handle] and card.revision == old.revision:
            card = replace(card, revision=old.revision + 1)
            updated_workspace = replace(
                updated_workspace,
                cards={**updated_workspace.cards, handle: card},
                revision=updated_workspace.revision + 1,
            )
        if old is not None and card != old:
            old_view = self._view(self._ref(old), False)
            old_view.pop("task_override", None)
            old_view.update(asdict(self.details[old.handle]))
            self.history[self._ref(old)] = old_view
            self.vectors.pop(self._ref(old), None)
        self.workspace, self.next_card = updated_workspace, patch.next_card
        self.details[handle] = metadata
        self._invalidate_coverage()
        retained_before, task_sources_before = set(self.retained), set(self.task_sources)
        if metadata.persistence == "durable":
            for ref in refs:
                self._retain(ref)
        else:
            self.task_sources.update(set(refs) - self.retained)
        if source_ref is not None:
            results["source"] = {
                "status": "RETAINED" if source_ref in self.retained else "TASK_ONLY",
                "ref": source_ref,
            }
        results["record"] = {**self.read(self._ref(card), False), "status": "SAVED"}
        if basis_change:
            results["basis_change"] = copy.deepcopy(basis_change)
        results["memory_changes"] = [
            *sorted((self.retained - retained_before) |
                    (self.task_sources - task_sources_before)),
            self._ref(card),
        ]
        results["decision"] = "COMMITTED"
        return results

    def _known_refs(self) -> set[str]:
        return set(self.sources) | {self._ref(card) for card in self.workspace.cards.values()}

    def update_state(self, **changes: Any) -> dict[str, Any]:
        if "conditions" in changes:
            validate_conditions(changes["conditions"])
        if "valid_at" in changes:
            validate_date(changes["valid_at"], "valid_at")
        if "known_at" in changes:
            changes["known_at"] = _known_cutoff(changes["known_at"])
        requested_coverage = changes.get("coverage")
        if requested_coverage in {"SUFFICIENT", "GAP"}:
            if set(changes) != {"coverage"} or self.latest_search is None:
                raise ValueError("COVERAGE_REQUIRES_LAST_SEARCH_WITH_UNCHANGED_STATE")
            if self.latest_search["state_signature"] != self._state_signature():
                raise ValueError("COVERAGE_REQUIRES_LAST_SEARCH_WITH_UNCHANGED_STATE")
        elif "coverage" in changes and requested_coverage != "UNKNOWN":
            raise ValueError("INVALID_COVERAGE")
        next_state = copy.deepcopy(self.state)
        for key in ("intentions", "conflicts"):
            if key in changes:
                changes[key] = [self.resolve(ref) for ref in changes[key]]
        for key, value in changes.items():
            setattr(next_state, key, value)
        patch = apply_workspace_patch(
            json.dumps(
                {
                    "workspace_update": {"working_note": next_state.context},
                    "frame": {"intent": next_state.context, "selected_refs": next_state.intentions},
                }
            ),
            self.workspace,
            evidence_refs=set(self.sources),
            known_refs=self._known_refs() | self.history.keys(),
            next_card=self.next_card,
            max_cards=10000,
        )
        self.workspace = patch.workspace
        self.state = next_state
        if changes:
            self.state_used = True
        if requested_coverage in {"SUFFICIENT", "GAP"}:
            self.coverage_binding = copy.deepcopy(self.latest_search)
        elif changes:
            self._invalidate_coverage()
        return {"status": "UPDATED", "state": asdict(self.state)}

    def _text(self, ref: str) -> str:
        if ref in self.sources:
            source = self.sources[ref]
            return f"{source.role} {source.date}\n{source.content}"
        if ref in self.history:
            old = self.history[ref]
            return f"{old['subject']} {old['context']} {old['certainty']}\n{old['text']}"
        card = self.workspace.cards[self._handle(ref)]
        details = self.details[card.handle]
        return f"{details.subject} {details.context} {details.certainty}\n{card.text}"

    def _drop_vectors(self, ref: str) -> None:
        for key in [key for key in self.vectors if key == ref or key.startswith(f"{ref}#")]:
            del self.vectors[key]

    def _index_entries(
        self, *, sources: bool = True, records: bool = True,
        valid_at: str = "", known_at: str = "", date_from: str = "",
        date_to: str = "", session_id: str = "",
    ) -> list[tuple[str, str, str, tuple[int, int] | None]]:
        entries, _ = index_entries(
            self, sources=sources, records=records, valid_at=valid_at,
            known_at=known_at, date_from=date_from, date_to=date_to,
            session_id=session_id,
        )
        return [(entry.key, entry.ref, entry.text, entry.span) for entry in entries]

    def _rank(
        self, query: str, *, sources: bool = True, records: bool = True,
        valid_at: str = "", known_at: str = "", date_from: str = "",
        date_to: str = "", session_id: str = "",
    ) -> Ranked:
        started = time.monotonic()
        result = rank(
            self, query, sources=sources, records=records, valid_at=valid_at,
            known_at=known_at, date_from=date_from, date_to=date_to,
            session_id=session_id,
        )
        self.local_timings["retrieval_seconds"] += time.monotonic() - started
        return result

    def _material(
        self, ref: str, spans: dict[str, list[tuple[int, int]]], *,
        valid_at: str = "", known_at: str = "", max_bytes: int = 16000,
        date_pending: bool = False, neighbor_window: int = 0,
        date_from: str = "", date_to: str = "",
    ) -> dict[str, Any]:
        started = time.monotonic()
        if self.material_mode == "linked" or ref in self.sources:
            item = linked_packet(
                self, ref, spans=spans.get(ref), max_bytes=max_bytes,
                neighbor_window=neighbor_window, date_from=date_from,
                date_to=date_to, valid_at=valid_at, known_at=known_at,
                date_pending=date_pending,
                correction_only=self.material_mode != "linked",
            )
        else:
            item = base_material(
                self, ref, spans.get(ref), valid_at=valid_at, known_at=known_at,
                date_pending=date_pending,
            )
            if item["kind"] == "interpretation":
                item.pop("page", None)
        self.local_timings["material_seconds"] += time.monotonic() - started
        return item

    def suggest_existing_records(
        self, query: str, limit: int = 8, max_bytes: int = 12000
    ) -> list[dict[str, Any]]:
        """Current, read-marked records for a Host's next history proposal."""
        ranking = self._rank(
            query, sources=False, valid_at=self.state.valid_at,
            known_at=self.state.known_at,
        )
        result: list[dict[str, Any]] = []
        used = 0
        for ref in ranking.refs:
            was_seen = ref in self.seen
            item = self.read(ref, include_sources=False, length=len(self._text(ref)))
            item["status"] = "CURRENT"
            size = len(json.dumps(item, ensure_ascii=False).encode())
            if used + size > max_bytes:
                if not was_seen:
                    self.seen.discard(ref)
                continue
            result.append(item)
            used += size
            if len(result) == limit:
                break
        return result

    def search(
        self, query: str = "", limit: int = 8, max_bytes: int = 16000,
        focus: str = "default",
        valid_at: str = "", known_at: str = "", date_from: str = "",
        date_to: str = "", session_id: str = "", neighbor_window: int = 0,
        condition_evidence: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        self._accept_condition_evidence(condition_evidence)
        projection = project_query(
            query, task_context=self.state.query_context, state=self.state,
            focus=focus,
            gap=(self.state.active_decision.critical_gap
                 if self.state.active_decision is not None else "")
                if self.decision_policy == "basis" else "",
            anchor=(self.state.active_decision.scope
                    if self.state.active_decision is not None else {}),
            host_intent=(self.state.active_decision.status
                         if self.state.active_decision is not None else "active"),
            auto_gap_enabled=self.decision_policy == "basis" and self.decision_gap_focus,
            explicit_filters={
                "valid_at": valid_at, "known_at": known_at,
                "date_from": date_from, "date_to": date_to,
                "session_id": session_id,
            },
        )
        effective_query = projection["effective_query"]
        filters = projection["filters"]
        effective_date = filters["valid_at"]
        effective_known = _known_cutoff(filters["known_at"])
        date_from, date_to = filters["date_from"], filters["date_to"]
        session_id = filters["session_id"]
        self.state.intentions = [self.resolve(ref) for ref in self.state.intentions]
        self.state.conflicts = [self.resolve(ref) for ref in self.state.conflicts]
        state_active = self.state_policy == "forced_legacy" or (
            self.state_policy == "optional" and self.state_used
        )
        ranking = self._rank(
            effective_query, valid_at=effective_date, known_at=effective_known,
            date_from=date_from, date_to=date_to, session_id=session_id,
        )
        ranked, spans = ranking.refs, ranking.spans

        def material_for(ref: str, budget: int = max_bytes) -> dict[str, Any]:
            return self._material(
                ref, spans, valid_at=effective_date, known_at=effective_known,
                max_bytes=budget, date_pending=ref in ranking.date_pending,
                neighbor_window=neighbor_window, date_from=date_from,
                date_to=date_to,
            )
        priorities = []
        for ref in self.state.intentions + self.state.conflicts:
            try:
                candidate = self.resolve_at(ref, effective_known)
            except ValueError:
                continue
            if candidate in ranked:
                priorities.append(candidate)
        pool = list(dict.fromkeys((priorities if state_active else []) + ranked[:limit]))[:28]
        # Attention budgets the same compact units that the Host can receive.
        preview = MaterialView("attention-preview", self)
        units: list[SourceUnit] = []
        over_budget: list[str] = []
        for ref in pool:
            text = json.dumps(
                preview.preview(
                    {"materials": [material_for(ref)]}, max_bytes=max_bytes,
                    linked=self.material_mode == "linked",
                ),
                ensure_ascii=False,
            )
            if sum(len(unit.content.encode()) for unit in units) + len(text.encode()) > 65536:
                over_budget.append(ref)
                continue
            units.append(SourceUnit(ref, ref, self.scope, text))
        snapshot = SourceSnapshot(self.scope, tuple(units))
        available = {unit.source_id: unit for unit in units}
        baseline = tuple(ref for ref in ranked if ref in available)[:limit]

        def attention_for(
            current_snapshot: SourceSnapshot, current_units: dict[str, SourceUnit]
        ) -> AttentionState | None:
            if not state_active:
                return None
            fields = tuple(
                StateField(
                    name,
                    "HOST",
                    0,
                    1,
                    f"task:{self.state.task_id}",
                    tuple(current_units[ref] for ref in wanted if ref in current_units),
                )
                for name, wanted in (
                    ("memory_intentions", priorities or list(baseline)),
                    ("open_conflicts", self.state.conflicts),
                )
            )
            return AttentionState(
                self.state.task_id,
                self.scope,
                question_digest(effective_query[:1024]),
                current_snapshot.sha256,
                fields,
            )

        attention = attention_for(snapshot, available)
        coverage: CoverageReview | None = None
        binding = self.coverage_binding
        if binding is not None and attention is not None:
            if (
                binding["query"] == effective_query
                and binding["snapshot_sha256"] == snapshot.sha256
                and binding["attention_sha256"] == attention.sha256
                and binding["state_signature"] == self._state_signature()
            ):
                coverage = CoverageReview(
                    attention.sha256,
                    snapshot.sha256,
                    tuple(binding["selected_ids"]),
                    self.state.coverage,
                    f"task:{self.state.task_id}",
                    0,
                    1,
                )
            else:
                self._invalidate_coverage()
        decision = decide_attention(
            task_id=self.state.task_id or "default",
            question=effective_query[:1024],
            sequence=1,
            snapshot=snapshot,
            baseline_ids=baseline,
            state=attention,
            coverage=coverage,
            expansion_attempts=0,
            check_source=lambda _: "ELIGIBLE",
            limits=AttentionLimits(limit, max_bytes, min(4, limit)),
        )
        if coverage is not None and decision["coverage"] == "UNKNOWN":
            self._invalidate_coverage()
        expanded_refs: list[str] = []
        if decision["action"] == "RETRIEVE_ONCE":
            key = hashlib.sha256(
                json.dumps([effective_query, priorities, snapshot.sha256]).encode()
            ).hexdigest()
            if self.expansion.get("key") != key:
                self.expansion = {"key": key, "attempts": 1, "status": "STARTED", "refs": []}
                expanded = [ref for ref in ranked if ref not in available][: min(4, limit)]
                self.expansion.update(status="RETRIEVED", refs=expanded)
            expanded_refs = list(self.expansion["refs"])
            merged_units = list(units)
            merged_bytes = sum(len(unit.content.encode()) for unit in merged_units)
            admitted_refs: list[str] = []
            for ref in expanded_refs:
                item = material_for(self.resolve_at(ref, effective_known))
                body = json.dumps(
                    preview.preview(
                        {"materials": [item]}, max_bytes=max_bytes,
                        linked=self.material_mode == "linked",
                    ), ensure_ascii=False,
                )
                size = len(body.encode())
                if len(merged_units) < 32 and merged_bytes + size <= 65536:
                    merged_units.append(SourceUnit(item["ref"], item["ref"], self.scope, body))
                    admitted_refs.append(item["ref"])
                    merged_bytes += size
                else:
                    over_budget.append(ref)
            expanded_refs = admitted_refs
            snapshot = SourceSnapshot(self.scope, tuple(merged_units))
            available = {unit.source_id: unit for unit in merged_units}
            attention = attention_for(snapshot, available)
            decision = decide_attention(
                task_id=self.state.task_id or "default",
                question=effective_query[:1024],
                sequence=1,
                snapshot=snapshot,
                baseline_ids=baseline,
                state=attention,
                coverage=None,
                expansion_attempts=1,
                check_source=lambda _: "ELIGIBLE",
                limits=AttentionLimits(limit, max_bytes, min(4, limit)),
            )
            decision["expansion_result"] = copy.deepcopy(self.expansion)
            self._invalidate_coverage()
        selected_refs = [str(item["source_id"]) for item in decision["selected_sources"]]
        self.state.recent_refs = selected_refs
        # Include each observation once even when multiple interpretations cite it.
        materials: list[dict[str, Any]] = []
        for ref in selected_refs:
            item = material_for(ref)
            materials.append(item)
        self.seen.update(selected_refs)
        source_refs = list(
            dict.fromkeys(
                expanded
                for ref in selected_refs
                if ref not in self.sources
                for source in self._view(
                    ref, False, valid_at=effective_date, known_at=effective_known,
                )["source_refs"]
                for expanded in (self.resolve_at(source, effective_known), source)
            )
        )
        uncovered: list[str] = []
        for ref in source_refs:
            if ref in selected_refs:
                continue
            item = material_for(ref)
            if len(materials) < 32:
                materials.append(item)
                self.seen.add(ref)
            else:
                uncovered.append(ref)
        expansion_materials: list[dict[str, Any]] = []
        shown = {item["ref"] for item in materials}
        for ref in expanded_refs:
            current = self.resolve_at(ref, effective_known)
            if current in shown:
                continue
            item = material_for(current)
            if len(materials) + len(expansion_materials) < 32:
                expansion_materials.append(item)
                self.seen.add(current)
                shown.add(current)
            else:
                over_budget.append(current)
        if not expanded_refs:
            self.latest_search = {
                "query": effective_query,
                "snapshot_sha256": snapshot.sha256,
                "attention_sha256": attention.sha256 if attention else None,
                "selected_ids": selected_refs,
                "state_signature": self._state_signature(),
            }
        self._note_source_visibility(materials + expansion_materials)
        return {
            "materials": materials,
            "expanded_materials": expansion_materials,
            "attention": decision,
            "query": effective_query,
            "query_projection": projection,
            "unexpanded_sources": uncovered,
            "oversized_units": over_budget,
            "independent_source_refs": list(
                dict.fromkeys(
                    self.resolve_at(ref, effective_known)
                    for ref in [ref for ref in selected_refs if ref in self.sources]
                    + source_refs
                    + [ref for ref in expanded_refs if ref in self.sources and ref in shown]
                )
            ),
            "state": asdict(self.state),
        }

    def _drop_card(self, handle: str) -> None:
        card = self.workspace.cards.pop(handle)
        self.details.pop(handle)
        prefix = f"{self.scope}/{handle}@"
        self.history = {
            ref: value for ref, value in self.history.items() if not ref.startswith(prefix)
        }
        self._drop_vectors(self._ref(card))

    def forget(
        self, refs: list[str], *, envelope: TaskEnvelope | None = None,
        cleanup_effects: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Execute a trusted lifecycle deletion with a frozen, recoverable plan."""
        if not refs:
            return {"status": "NO_CHANGE", "decision": "NO_CHANGE",
                    "memory_changes": [], "cleanup_effects": [], "completion": "complete"}
        if envelope is None or self.deletion_ledger is None:
            raise ValueError("DELETE_REQUIRES_TRUSTED_EXECUTOR")
        if envelope.user_id != self.user_id or envelope.task_id != self.state.task_id:
            raise ValueError("DELETE_TASK_SCOPE_MISMATCH")
        if envelope != self.execution_context:
            raise ValueError("DELETE_TASK_ENVELOPE_MISMATCH")
        envelope.authorize_delete(refs)
        existing = self.deletion_ledger.read().operations.get(envelope.operation_id)
        if existing is not None:
            # The original plan is authoritative after a partial or completed commit.
            operation = self.deletion_ledger.begin(
                envelope, refs, set(existing.affected), cleanup_effects,
            )
            deletion = self.deletion_ledger.commit(operation.operation_id, self.next_card)
            self._apply_deletions()
            return self._deletion_receipt(operation.operation_id, deletion)
        for ref in refs:
            self._view(ref, False)
        affected = set(refs)
        affected.update(self.resolve(ref) for ref in refs)
        while True:
            family = {
                ref
                for old, new in self.source_replacements.items()
                if {old, new} & affected
                for ref in (old, new)
            }
            if family <= affected:
                break
            affected.update(family)
        handles: set[str] = set()
        while True:
            unsupported_handles: set[str] = set()
            for target, group_ids in self.revisions.by_target.items():
                if target in self.sources:
                    continue
                supporting = [
                    self.revisions.groups[key] for key in group_ids
                    if self.revisions.groups[key].polarity == "support"
                    and not self.revisions.groups[key].withdrawn_at
                ]
                if supporting and not any(
                    all(item.ref not in affected for item in group.items)
                    for group in supporting
                ):
                    unsupported_handles.add(self._handle(target))
            added = {
                handle
                for handle, card in self.workspace.cards.items()
                if self._ref(card) in affected
                or set(card.source_refs) & affected
                or set(self.details[handle].dependencies) & affected
                or any(
                    self._handle(ref) == handle
                    and (set(old["source_refs"]) | set(old["dependencies"])) & affected
                    for ref, old in self.history.items()
                )
            } | unsupported_handles
            if added <= handles:
                break
            handles.update(added)
            affected.update(self._ref(self.workspace.cards[handle]) for handle in added)
            affected.update(ref for ref in self.history if self._handle(ref) in added)
        operation = self.deletion_ledger.begin(envelope, refs, affected, cleanup_effects)
        deletion = self.deletion_ledger.commit(operation.operation_id, self.next_card)
        self._erase_deletion(affected)
        self.forget_generation = max(self.forget_generation, deletion.generation)
        return self._deletion_receipt(operation.operation_id, deletion)

    def _deletion_receipt(self, operation_id: str, deletion: Any) -> dict[str, Any]:
        operation = deletion.operations[operation_id]
        return {
            "status": "FORGOTTEN", "operation_id": operation_id,
            "decision": "COMMITTED", "refs": list(operation.affected),
            "memory_changes": list(operation.affected),
            "cleanup_effects": list(operation.pending_effects),
            "completion": "pending" if operation.pending_effects else "complete",
        }

    def _erase_deletion(self, affected: set[str]) -> None:
        """Idempotently replay committed markers; never create a user operation."""
        handles = {
            handle for handle, card in self.workspace.cards.items()
            if self._ref(card) in affected
            or any(ref in affected for ref in self.history if self._handle(ref) == handle)
        }
        self.forgotten.update(affected)
        for ref in affected:
            self._drop_vectors(ref)
        for ref in affected & self.sources.keys():
            self.sources.pop(ref)
            self.source_known_at.pop(ref, None)
            self.source_sequence.pop(ref, None)
            self.retained.discard(ref)
            self.task_sources.discard(ref)
            self.forgotten.add(ref)
            self.source_replacements = {
                old: new
                for old, new in self.source_replacements.items()
                if old != ref and new != ref
            }
            self.source_replacement_at = {
                old: timestamp for old, timestamp in self.source_replacement_at.items()
                if old in self.source_replacements
            }
            self._drop_vectors(ref)
        for handle in handles:
            self._drop_card(handle)
        self.revisions.prune_refs(affected)
        self.seen.difference_update(affected)
        for ref in affected:
            self.visible_source_ranges.pop(ref, None)
        # Free-text task understanding can restate the forgotten material.
        self.state = TaskState(
            self.state.task_id,
            query_context=task_context(self.state.task_id, ""),
        )
        self.workspace.working_note = ""
        self.workspace.frame = FocusFrame()
        self.expansion = {}
        self.latest_search = None
        self.coverage_binding = None

    def _task_overlay(self) -> dict[str, Any]:
        handles = {h for h, detail in self.details.items() if detail.persistence == "task"}
        refs = (self.task_sources - self.retained) | {
            self._ref(self.workspace.cards[handle]) for handle in handles
        }
        refs.update(ref for ref in self.history if self._handle(ref) in handles)
        all_refs = set(self.sources) | self._known_refs() | set(self.history)
        task_revision = self.revisions.dump(all_refs, include_task=True)
        task_revision["groups"] = {
            key: group for key, group in task_revision["groups"].items()
            if group["target_ref"] in refs
        }
        task_revision["changesets"] = [
            entry for entry in task_revision["changesets"]
            if any(
                operation["op"] == "task_override"
                for operation in entry["outcome"]["operations"]
            )
            or any(
                operation.get(key) in refs
                for operation in entry["outcome"]["operations"]
                for key in ("ref", "target_ref", "old_ref", "closed_ref", "new_ref")
            )
        ]
        task_revision["pending"] = {
            ref: item for ref, item in task_revision["pending"].items() if ref in refs
        }
        return {
            "sources": {
                ref: asdict(self.sources[ref]) for ref in self.task_sources - self.retained
            },
            "source_replacements": {
                old: new
                for old, new in self.source_replacements.items()
                if old in refs and new in refs
            },
            "source_known_at": {
                ref: self.source_known_at[ref] for ref in self.task_sources - self.retained
            },
            "source_sequence": {
                ref: self.source_sequence[ref] for ref in self.task_sources - self.retained
            },
            "next_source_sequence": self.next_source_sequence,
            "source_replacement_at": {
                old: self.source_replacement_at[old]
                for old in self.source_replacement_at if old in refs
            },
            "cards": {h: asdict(self.workspace.cards[h]) for h in handles},
            "details": {h: asdict(self.details[h]) for h in handles},
            "history": {
                ref: value for ref, value in self.history.items() if self._handle(ref) in handles
            },
            "vectors": {
                key: vector
                for key, vector in self.vectors.items()
                if key.split("#", 1)[0] in refs
            },
            "embedding_identity": self.embedding_identity,
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "index_policy": INDEX_POLICY,
            "next_card": self.next_card,
            "revisions": task_revision,
        }

    def _restore_overlay(self, overlay: dict[str, Any]) -> None:
        if set(overlay["cards"]) & self.workspace.cards.keys():
            raise ValueError("HANDOFF_CARD_IDENTITY_CONFLICT")
        self.sources.update(
            {ref: Observation(**value) for ref, value in overlay["sources"].items()}
        )
        self.source_replacements.update(overlay.get("source_replacements", {}))
        self.source_known_at.update(overlay["source_known_at"])
        self.source_sequence.update(overlay["source_sequence"])
        self.next_source_sequence = max(
            self.next_source_sequence, overlay["next_source_sequence"],
        )
        self.source_replacement_at.update(overlay["source_replacement_at"])
        self.task_sources.update(overlay["sources"])
        self.workspace.cards.update(
            {h: MemoryCard(**value) for h, value in overlay["cards"].items()}
        )
        self.details.update({h: Interpretation(**value) for h, value in overlay["details"].items()})
        self.history.update(copy.deepcopy(overlay["history"]))
        task_revision = RevisionStore.load(overlay["revisions"])
        for group in task_revision.groups.values():
            self.revisions.add(group)
        self.revisions.changesets.extend(task_revision.changesets)
        self.revisions.pending.update(task_revision.pending)
        self.revisions.next_group = max(self.revisions.next_group, task_revision.next_group)
        if (
            self.embedding_identity is not None
            and overlay.get("embedding_identity") == self.embedding_identity
            and overlay.get("embedding_model") == self.embedding_model
            and overlay.get("embedding_dimension") == self.embedding_dimension
            and overlay.get("index_policy") == INDEX_POLICY
        ):
            self.vectors.update(copy.deepcopy(overlay["vectors"]))
        self.next_card = max(self.next_card, overlay["next_card"])

    def _saved_state(self, available: set[str]) -> dict[str, Any]:
        state = asdict(self.state)
        for key in ("intentions", "conflicts", "recent_refs"):
            current = [self.resolve(ref) for ref in state[key]]
            state["unavailable_refs"].extend(ref for ref in current if ref not in available)
            state[key] = [ref for ref in current if ref in available]
        state["unavailable_refs"] = list(dict.fromkeys(state["unavailable_refs"]))
        return state

    def handoff(self) -> dict[str, Any]:
        requested = set(self.state.intentions + self.state.conflicts + self.state.recent_refs)
        pending = list(requested)
        while pending:
            ref = pending.pop()
            item = self._view(ref, False)
            if item["kind"] == "interpretation":
                dependencies = set(item["source_refs"] + item["dependencies"]) - requested
                requested.update(dependencies)
                pending.extend(dependencies)
            elif item["current_ref"] != ref:
                replacement = self.source_replacements[ref]
                if replacement not in requested:
                    requested.add(replacement)
                    pending.append(replacement)
        overlay = self._task_overlay()
        handles = {self._handle(ref) for ref in requested if ref not in self.sources}
        overlay["sources"] = {
            ref: item for ref, item in overlay["sources"].items() if ref in requested
        }
        overlay["source_replacements"] = {
            old: new
            for old, new in overlay["source_replacements"].items()
            if old in overlay["sources"] and new in overlay["sources"]
        }
        overlay["source_sequence"] = {
            ref: sequence for ref, sequence in overlay["source_sequence"].items()
            if ref in overlay["sources"]
        }
        for key in ("cards", "details"):
            overlay[key] = {
                handle: item for handle, item in overlay[key].items() if handle in handles
            }
        overlay["history"] = {
            ref: item for ref, item in overlay["history"].items() if self._handle(ref) in handles
        }
        overlay["revisions"]["pending"] = {
            ref: item for ref, item in overlay["revisions"]["pending"].items()
            if ref in requested
        }
        overlay["vectors"] = {
            key: item
            for key, item in overlay["vectors"].items()
            if key.split("#", 1)[0] in requested
        }
        overlay.update(
            embedding_identity=self.embedding_identity,
            embedding_model=self.embedding_model,
            embedding_dimension=self.embedding_dimension,
            index_policy=INDEX_POLICY,
        )
        available = (
            self.retained
            | set(overlay["sources"])
            | {self._ref(card) for card in self.workspace.cards.values()}
        )
        return {
            "user_id": self.user_id,
            "forget_generation": self.forget_generation,
            "state": {**self._saved_state(available), "coverage": "UNKNOWN"},
            "state_used": self.state_used,
            "overlay": overlay,
        }

    def checkpoint(self, *, include_task: bool = True) -> dict[str, Any]:
        self._apply_deletions()
        handles = {
            handle
            for handle in self.workspace.cards
            if self.details[handle].persistence == "durable"
        }
        refs = self.retained | {self._ref(self.workspace.cards[handle]) for handle in handles}
        refs.update(ref for ref in self.history if self._handle(ref) in handles)
        overlay = self._task_overlay()
        available = (
            refs
            | set(overlay["sources"])
            | {self._ref(self.workspace.cards[handle]) for handle in overlay["cards"]}
        )
        state = self._saved_state(available)
        frame = asdict(self.workspace.frame)
        frame["selected_refs"] = list(state["intentions"])
        return {
            "format": METHOD_VERSION,
            "user_id": self.user_id,
            "host_id": self.host_id,
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "embedding_identity": self.embedding_identity,
            "index_policy": INDEX_POLICY,
            "state_policy": self.state_policy,
            "decision_policy": self.decision_policy,
            "decision_feedback": self.decision_feedback,
            "decision_gap_focus": self.decision_gap_focus,
            "profile": self.profile,
            "material_mode": self.material_mode,
            "maintenance_mode": self.maintenance_mode,
            "next_card": self.next_card,
            "next_source_sequence": self.next_source_sequence,
            "last_known_at": self.last_known_at,
            "sources": {ref: asdict(self.sources[ref]) for ref in self.retained},
            "forgotten": sorted(self.forgotten),
            "forget_generation": self.forget_generation,
            "source_replacements": {
                old: new
                for old, new in self.source_replacements.items()
                if old in available and new in available
            },
            "source_known_at": {
                ref: self.source_known_at[ref] for ref in self.retained
            },
            "source_sequence": {
                ref: self.source_sequence[ref] for ref in self.retained
            },
            "source_replacement_at": {
                old: self.source_replacement_at[old]
                for old in self.source_replacement_at
                if old in available and self.source_replacements[old] in available
            },
            "cards": {handle: asdict(self.workspace.cards[handle]) for handle in handles},
            "details": {handle: asdict(self.details[handle]) for handle in handles},
            "history": {
                ref: value for ref, value in self.history.items() if self._handle(ref) in handles
            },
            "revisions": self.revisions.dump(refs),
            "vectors": {
                key: vector
                for key, vector in self.vectors.items()
                if key.split("#", 1)[0] in refs
            },
            "task": {
                "state": state,
                "state_used": self.state_used,
                "frame": frame,
                "overlay": overlay,
                "expansion": copy.deepcopy(self.expansion),
                "latest_search": copy.deepcopy(self.latest_search),
                "coverage_binding": copy.deepcopy(self.coverage_binding),
            }
            if include_task
            else None,
        }

    @classmethod
    def restore(
        cls,
        value: dict[str, Any],
        *,
        user_id: str,
        embed: Callable[[list[str]], list[list[float]]],
        embedding_identity: str | None = None,
        embedding_model: str | None = None,
        embedding_dimension: int | None = None,
        material_mode: str | None = None,
        state_policy: str | None = None,
        decision_policy: str | None = None,
        decision_feedback: bool | None = None,
        decision_gap_focus: bool | None = None,
        deletion_ledger: DeletionLedger | None = None,
    ) -> ContextualMemory:
        if value["format"] != METHOD_VERSION or value["user_id"] != user_id:
            raise ValueError("CHECKPOINT_USER_OR_VERSION_MISMATCH")
        effective_policy = state_policy or value["state_policy"]
        if (effective_policy != value["state_policy"] and value["task"] is not None):
            raise ValueError("CHECKPOINT_TASK_POLICY_MISMATCH")
        effective_decision = decision_policy or value["decision_policy"]
        effective_feedback = (value["decision_feedback"] if decision_feedback is None
                              else decision_feedback)
        effective_gap_focus = (value["decision_gap_focus"] if decision_gap_focus is None
                               else decision_gap_focus)
        if value["task"] is not None and (
            effective_decision != value["decision_policy"]
            or effective_feedback != value["decision_feedback"]
            or effective_gap_focus != value["decision_gap_focus"]
        ):
            raise ValueError("CHECKPOINT_TASK_DECISION_POLICY_MISMATCH")
        actual_model = embedding_model if embedding_model is not None else value["embedding_model"]
        actual_dimension = (
            embedding_dimension if embedding_dimension is not None else value["embedding_dimension"]
        )
        same_index = (
            embedding_identity is not None
            and embedding_identity == value.get("embedding_identity")
            and actual_model == value["embedding_model"]
            and actual_dimension == value["embedding_dimension"]
            and value.get("index_policy") == INDEX_POLICY
        )
        memory = cls(
            user_id,
            host_id=value["host_id"],
            embed=embed,
            embedding_model=actual_model,
            embedding_dimension=actual_dimension,
            embedding_identity=embedding_identity,
            state_policy=effective_policy,
            decision_policy=effective_decision,
            decision_feedback=effective_feedback,
            decision_gap_focus=effective_gap_focus,
            profile=value["profile"],
            material_mode=material_mode or value["material_mode"],
            maintenance_mode=value["maintenance_mode"],
            deletion_ledger=deletion_ledger,
        )
        memory.sources = {ref: Observation(**item) for ref, item in value["sources"].items()}
        memory.retained = set(memory.sources)
        memory.forgotten = set(value["forgotten"])
        memory.forget_generation = value.get("forget_generation", 0)
        memory.source_replacements = dict(value["source_replacements"])
        memory.source_known_at = dict(value["source_known_at"])
        memory.source_sequence = dict(value["source_sequence"])
        memory.next_source_sequence = value["next_source_sequence"]
        memory.source_replacement_at = dict(value["source_replacement_at"])
        memory.last_known_at = value["last_known_at"]
        memory.workspace.cards = {
            handle: MemoryCard(**item) for handle, item in value["cards"].items()
        }
        memory.details = {
            handle: Interpretation(**item) for handle, item in value["details"].items()
        }
        memory.history = copy.deepcopy(value["history"])
        memory.revisions = RevisionStore.load(value["revisions"])
        if same_index:
            memory.vectors = copy.deepcopy(value["vectors"])
        memory.next_card = value["next_card"]
        if value["task"] is not None:
            memory._restore_overlay(value["task"]["overlay"])
            if same_index:
                memory.expansion = copy.deepcopy(value["task"]["expansion"])
            state_data = dict(value["task"]["state"])
            state_data["active_decision"] = restored_decision(
                state_data.get("active_decision")
            )
            memory.state = TaskState(**state_data)
            memory.state_used = bool(value["task"].get("state_used", False))
            if same_index:
                memory.latest_search = copy.deepcopy(value["task"]["latest_search"])
                memory.coverage_binding = copy.deepcopy(value["task"]["coverage_binding"])
            else:
                memory._invalidate_coverage()
            memory.workspace.frame = FocusFrame(**value["task"]["frame"])
            memory.workspace.working_note = memory.state.context
            memory.state.intentions = [memory.resolve(ref) for ref in memory.state.intentions]
        for handle, card in memory.workspace.cards.items():
            if not set(card.source_refs) <= memory.sources.keys():
                raise ValueError("CHECKPOINT_SOURCE_MISSING")
            memory._dependency_status(memory.details[handle])
        memory._apply_deletions()
        memory._scan_decision_changes()
        memory.execution_context = TaskEnvelope(
            user_id, memory.state.task_id,
            "history" if memory.state.task_id == "history" else "answer",
        )
        return memory

    def dispatch(
        self, name: str, arguments: dict[str, Any], *, operation_id: str | None = None,
    ) -> dict[str, Any]:
        if name != "memory_save":
            return self._dispatch(name, arguments)
        if operation_id is not None and not operation_id:
            raise ValueError("EMPTY_OPERATION_ID")
        actual_id = operation_id if operation_id is not None else new_save_operation_id()
        result = self._dispatch(name, arguments)
        result["operation_id"] = actual_id
        if result.get("decision") in {"COMMITTED", "PARTIAL"}:
            self._scan_decision_changes()
        return result

    def _dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "memory_save" and (
            "forget_refs" in arguments or arguments.get("op") == "NO_CHANGE"
            or arguments == {"changeset": {"groups": []}}
        ):
            try:
                return self.save(**arguments)
            except (TypeError, ValueError) as error:
                return {"status": "ERROR", "decision": "REJECTED", "error": str(error)}
        envelope = self.execution_context
        if envelope.user_id != self.user_id or envelope.task_id != self.state.task_id:
            return {"status": "ERROR", "decision": "REJECTED",
                    "error": "TASK_ENVELOPE_SCOPE_MISMATCH"}
        capability = "read" if name in {"memory_search", "memory_read"} else "maintain"
        if capability not in envelope.allowed_operations:
            return {"status": "ERROR", "decision": "REJECTED",
                    "error": "OPERATION_NOT_ALLOWED_IN_TASK"}
        if (name == "memory_save" and "changeset" not in arguments
                and "op" not in arguments):
            return {"status": "ERROR", "decision": "REJECTED",
                    "error": "WRITE_OPERATION_REQUIRED"}
        self._apply_deletions()
        functions: dict[str, Callable[..., dict[str, Any]]] = {
            "memory_search": self.search,
            "memory_read": self.read,
            "memory_save": self.save,
            "memory_state": self.update_state,
        }
        schema = next(
            (tool["function"]["parameters"] for tool in TOOLS if tool["function"]["name"] == name),
            None,
        )
        if schema is None:
            return {"status": "ERROR", "error": "UNKNOWN_MEMORY_TOOL"}
        try:
            validate(arguments, schema)
            return functions[name](**arguments)
        except (ValidationError, ValueError, KeyError) as error:
            result: dict[str, Any] = {"status": "ERROR", "error": str(error)}
            if name == "memory_save":
                result.update(decision="REJECTED", memory_changes=[], cleanup_effects=[])
            return result
