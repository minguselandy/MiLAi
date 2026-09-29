"""Data views of existing journal effects, operation identity and native targets."""

from __future__ import annotations

from typing import Literal, TypedDict

EffectStatus = Literal["confirmed", "partial", "none", "observed", "unknown"]


class OperationIdentity(TypedDict):
    """The ordered identity fields already used by the application journal."""

    run_id: str
    arm_id: str
    owner: str
    task_id: str
    operation_id: str


class ApplicationTarget(TypedDict, total=False):
    """Known native target fields; tool-specific completeness remains with its owner."""

    item_key: str
    quantity: int
    destination: str
    packing: str
    resolved: bool
