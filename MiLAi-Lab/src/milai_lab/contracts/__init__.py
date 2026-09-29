"""Stable Lab-side experiment contracts."""

from milai_lab.contracts.arms import ExperimentArmKind, ExperimentArmSpec
from milai_lab.contracts.memory import (
    MemoryMutationReceipt,
    MemoryObjectRef,
    MemoryReadResult,
    MemoryRecord,
    MemorySourceRef,
)
from milai_lab.contracts.operations import ApplicationTarget, EffectStatus, OperationIdentity
from milai_lab.contracts.records import HistoryItem, ResultRecord, WorkloadHistory
from milai_lab.contracts.request import MemoryPlacement, ModelView, RequestContext
from milai_lab.contracts.scope import FoundationScope

__all__ = [
    "ApplicationTarget",
    "EffectStatus",
    "ExperimentArmKind",
    "ExperimentArmSpec",
    "FoundationScope",
    "HistoryItem",
    "MemoryMutationReceipt",
    "MemoryObjectRef",
    "MemoryPlacement",
    "MemoryReadResult",
    "MemoryRecord",
    "MemorySourceRef",
    "ModelView",
    "OperationIdentity",
    "RequestContext",
    "ResultRecord",
    "WorkloadHistory",
]
