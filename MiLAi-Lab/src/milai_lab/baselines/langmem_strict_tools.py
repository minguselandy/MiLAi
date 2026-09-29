"""Compatibility exports for canonical memory.strict_tools."""

from milai_lab.memory.strict_tools import Annotated as Annotated
from milai_lab.memory.strict_tools import BaseStore as BaseStore
from milai_lab.memory.strict_tools import InjectedToolCallId as InjectedToolCallId
from milai_lab.memory.strict_tools import Literal as Literal
from milai_lab.memory.strict_tools import NamespaceTemplate as NamespaceTemplate
from milai_lab.memory.strict_tools import StructuredTool as StructuredTool
from milai_lab.memory.strict_tools import ToolMessage as ToolMessage
from milai_lab.memory.strict_tools import _invalid_receipt as _invalid_receipt
from milai_lab.memory.strict_tools import _receipt as _receipt
from milai_lab.memory.strict_tools import cast as cast
from milai_lab.memory.strict_tools import create_manage_memory_tool as create_manage_memory_tool
from milai_lab.memory.strict_tools import (
    create_strict_manage_memory_tool as create_strict_manage_memory_tool,
)
from milai_lab.memory.strict_tools import get_store as get_store
from milai_lab.memory.strict_tools import json as json
from milai_lab.memory.strict_tools import uuid as uuid

__all__ = [
    "Annotated",
    "BaseStore",
    "InjectedToolCallId",
    "Literal",
    "NamespaceTemplate",
    "StructuredTool",
    "ToolMessage",
    "cast",
    "create_manage_memory_tool",
    "create_strict_manage_memory_tool",
    "get_store",
    "json",
    "uuid",
]
