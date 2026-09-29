"""Compatibility exports for canonical request contracts and memory presentation."""

from milai_lab.contracts.request import (
    MemoryPlacement as MemoryPlacement,
)
from milai_lab.contracts.request import (
    ModelView as ModelView,
)
from milai_lab.contracts.request import (
    RequestContext as RequestContext,
)
from milai_lab.memory.presentation import (
    json_action_calls as json_action_calls,
)
from milai_lab.memory.presentation import (
    record_material as record_material,
)
from milai_lab.memory.presentation import (
    render_request as render_request,
)
from milai_lab.memory.presentation import (
    render_system as render_system,
)

__all__ = [
    "MemoryPlacement",
    "ModelView",
    "RequestContext",
    "json_action_calls",
    "record_material",
    "render_request",
    "render_system",
]
