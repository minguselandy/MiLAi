"""Trusted operation scope supplied by the runner, never by model arguments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

OPERATION_CONTRACT_VERSION = "contextual-operation-contract-v2"


def new_save_operation_id() -> str:
    """Name one local write attempt before its result is known."""
    return f"save:{uuid4().hex}"


@dataclass(frozen=True)
class TaskEnvelope:
    user_id: str
    task_id: str
    phase: Literal["history", "answer", "lifecycle"]
    allowed_operations: frozenset[str] = frozenset({"read", "maintain"})
    authorized_roots: tuple[str, ...] = ()
    operation_id: str = ""
    purpose: Literal["maintain", "answer", "delete_only", "delete_then_answer"] = "answer"
    retained_input: str = ""
    scope_id: str = ""

    def authorize_delete(self, refs: list[str]) -> None:
        if (
            self.phase != "lifecycle"
            or "delete" not in self.allowed_operations
            or not self.operation_id
            or not self.scope_id
            or self.purpose not in {"delete_only", "delete_then_answer"}
            or not set(refs) <= set(self.authorized_roots)
        ):
            raise ValueError("DELETE_NOT_AUTHORIZED_FOR_TASK")
