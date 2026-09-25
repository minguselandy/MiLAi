"""Per-user deletion markers and recoverable managed effects outside checkpoints."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from milai_lab.methods.contextual_memory.operations import TaskEnvelope


@dataclass(frozen=True)
class DeletionOperation:
    operation_id: str
    task_id: str
    phase: str
    purpose: str
    scope_id: str
    retained_input_sha256: str
    requested: tuple[str, ...]
    roots: tuple[str, ...]
    affected: tuple[str, ...]
    effects: tuple[str, ...]
    completed_effects: tuple[str, ...] = ()
    committed: bool = False

    @property
    def pending_effects(self) -> tuple[str, ...]:
        return tuple(effect for effect in self.effects if effect not in self.completed_effects)


@dataclass(frozen=True)
class DeletionState:
    refs: frozenset[str] = frozenset()
    generation: int = 0
    next_card: int = 1
    operations: dict[str, DeletionOperation] = field(default_factory=dict)


@dataclass(frozen=True)
class DeletionLedger:
    """One user workflow owns the file; no source or derived body is retained."""

    path: Path
    user_id: str

    def read(self) -> DeletionState:
        if not self.path.exists():
            return DeletionState()
        value = json.loads(self.path.read_text())
        if value["user_id"] != self.user_id or value["format"] not in {
            "contextual-deletions-v1", "contextual-deletions-v2",
        }:
            raise ValueError("DELETION_LEDGER_USER_OR_VERSION_MISMATCH")
        operations = {
            key: DeletionOperation(
                operation_id=key, task_id=item["task_id"],
                phase=item["phase"], purpose=item["purpose"],
                scope_id=item["scope_id"],
                retained_input_sha256=item["retained_input_sha256"],
                requested=tuple(item["requested"]),
                roots=tuple(item["roots"]), affected=tuple(item["affected"]),
                effects=tuple(item["effects"]),
                completed_effects=tuple(item.get("completed_effects", [])),
                committed=item["committed"],
            )
            for key, item in value.get("operations", {}).items()
        }
        return DeletionState(
            frozenset(value["refs"]), value["generation"], value["next_card"], operations,
        )

    def _write(self, state: DeletionState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({
            "format": "contextual-deletions-v2", "user_id": self.user_id,
            "refs": sorted(state.refs), "generation": state.generation,
            "next_card": state.next_card,
            "operations": {key: asdict(item) for key, item in state.operations.items()},
        }, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(self.path)

    def _check_refs(self, refs: set[str]) -> None:
        prefix = hashlib.sha256(self.user_id.encode()).hexdigest()[:16] + "/"
        if any(not ref.startswith(prefix) for ref in refs):
            raise ValueError("DELETION_REFERENCE_BELONGS_TO_ANOTHER_USER")

    def record(self, refs: set[str], next_card: int) -> DeletionState:
        """Import inherited markers; ordinary authorized deletes use begin/commit."""
        self._check_refs(refs)
        previous = self.read()
        current = DeletionState(
            previous.refs | refs, previous.generation + int(not refs <= previous.refs),
            max(previous.next_card, next_card), previous.operations,
        )
        if current != previous:
            self._write(current)
        return current

    def begin(
        self, envelope: TaskEnvelope, requested: list[str], affected: set[str],
        effects: tuple[str, ...],
    ) -> DeletionOperation:
        if envelope.scope_id != str(self.path.parent.resolve()):
            raise ValueError("DELETE_MANAGED_SCOPE_MISMATCH")
        self._check_refs(affected)
        state = self.read()
        original = state.operations.get(envelope.operation_id)
        roots = tuple(sorted(envelope.authorized_roots))
        retained_hash = hashlib.sha256(envelope.retained_input.encode()).hexdigest()
        if original is not None:
            if (original.task_id, original.phase, original.purpose, original.scope_id,
                original.retained_input_sha256,
                original.requested, original.roots, original.effects) != (
                envelope.task_id, envelope.phase, envelope.purpose, envelope.scope_id,
                retained_hash,
                tuple(sorted(requested)), roots, effects,
            ) or original.affected != tuple(sorted(affected)):
                raise ValueError("DELETE_OPERATION_ID_SCOPE_MISMATCH")
            return original
        operation = DeletionOperation(
            envelope.operation_id, envelope.task_id, envelope.phase, envelope.purpose,
            envelope.scope_id, retained_hash,
            tuple(sorted(requested)), roots, tuple(sorted(affected)), effects,
        )
        self._write(DeletionState(
            state.refs, state.generation, state.next_card,
            {**state.operations, envelope.operation_id: operation},
        ))
        return operation

    def commit(self, operation_id: str, next_card: int) -> DeletionState:
        state = self.read()
        operation = state.operations[operation_id]
        if operation.committed:
            return state
        affected = set(operation.affected)
        committed = DeletionOperation(
            operation.operation_id, operation.task_id, operation.phase,
            operation.purpose, operation.scope_id, operation.retained_input_sha256,
            operation.requested, operation.roots,
            operation.affected, operation.effects, operation.completed_effects, True,
        )
        current = DeletionState(
            state.refs | affected,
            state.generation + int(not affected <= state.refs),
            max(state.next_card, next_card),
            {**state.operations, operation_id: committed},
        )
        # The marker and committed flag cross one atomic file-replacement boundary.
        self._write(current)
        return current

    def complete_effect(self, operation_id: str, effect: str) -> DeletionOperation:
        state = self.read()
        operation = state.operations[operation_id]
        if not operation.committed or effect not in operation.effects:
            raise ValueError("UNKNOWN_DELETE_CLEANUP_EFFECT")
        if effect in operation.completed_effects:
            return operation
        completed = DeletionOperation(
            operation.operation_id, operation.task_id, operation.phase,
            operation.purpose, operation.scope_id, operation.retained_input_sha256,
            operation.requested, operation.roots,
            operation.affected, operation.effects,
            (*operation.completed_effects, effect), True,
        )
        self._write(DeletionState(
            state.refs, state.generation, state.next_card,
            {**state.operations, operation_id: completed},
        ))
        return completed
