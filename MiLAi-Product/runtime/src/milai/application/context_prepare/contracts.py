"""Stable contracts shared by context-preparation components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ExecutionRoute = Literal["NONE", "CACHE", "L0", "L1"]


@dataclass(frozen=True, slots=True)
class PrepareContextExecution:
    """Result envelope returned by the context preparation service."""

    body: dict[str, Any]
    status_code: int = 200


__all__ = ["ExecutionRoute", "PrepareContextExecution"]
