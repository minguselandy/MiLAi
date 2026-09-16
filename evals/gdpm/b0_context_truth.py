"""Typed B0 context-only preflight boundary.

This module intentionally has no answer-provider or Judge dependency. A
semantic abstention is a valid retrieval disposition; an exception is always
an infrastructure or protocol/implementation failure.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from evals.dg14.contracts import (
    DG14ContextBudgetError,
    DG14ContractError,
    DG14LifecycleError,
    DG14ReadinessError,
    DG14TransportError,
)


class PreflightFailureClass(StrEnum):
    INFRASTRUCTURE = "INFRASTRUCTURE"
    PROTOCOL_IMPLEMENTATION = "PROTOCOL_IMPLEMENTATION"
    SEMANTIC_ABSTENTION = "SEMANTIC_ABSTENTION"


@dataclass(frozen=True, slots=True)
class ContextPreflightReceipt:
    disposition: str
    failure_class: PreflightFailureClass | None
    failure_type: str | None
    semantic_abstention: bool
    reader_calls: int
    result: Mapping[str, object] | None = None


def run_context_preflight(
    operation: Callable[[], Mapping[str, object]],
) -> ContextPreflightReceipt:
    """Execute one context-only operation without converting failures to abstain."""

    try:
        result = operation()
    except (DG14TransportError, DG14ReadinessError, TimeoutError, OSError) as exc:
        return _failure(PreflightFailureClass.INFRASTRUCTURE, exc)
    except (
        DG14ContextBudgetError,
        DG14ContractError,
        DG14LifecycleError,
        TypeError,
        ValueError,
    ) as exc:
        return _failure(PreflightFailureClass.PROTOCOL_IMPLEMENTATION, exc)
    except (MemoryError, RuntimeError) as exc:
        return _failure(PreflightFailureClass.INFRASTRUCTURE, exc)
    status = result.get("status")
    if status in {"ABSENT", "ABSTAINED"}:
        return ContextPreflightReceipt(
            disposition="SEMANTIC_ABSTENTION",
            failure_class=PreflightFailureClass.SEMANTIC_ABSTENTION,
            failure_type=None,
            semantic_abstention=True,
            reader_calls=0,
            result=result,
        )
    return ContextPreflightReceipt(
        disposition="CONTEXT_READY",
        failure_class=None,
        failure_type=None,
        semantic_abstention=False,
        reader_calls=0,
        result=result,
    )


def _failure(
    failure_class: PreflightFailureClass,
    error: Exception,
) -> ContextPreflightReceipt:
    return ContextPreflightReceipt(
        disposition="FAILED",
        failure_class=failure_class,
        failure_type=type(error).__name__,
        semantic_abstention=False,
        reader_calls=0,
    )


__all__ = [
    "ContextPreflightReceipt",
    "PreflightFailureClass",
    "run_context_preflight",
]
