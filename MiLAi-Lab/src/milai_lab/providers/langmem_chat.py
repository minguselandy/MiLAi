"""Compatibility imports for the canonical generic chat bridge."""

from milai_lab.providers.chat_bridge import (
    IncompleteChatResponse as IncompleteChatResponse,
)
from milai_lab.providers.chat_bridge import (
    VLLMChatModel as VLLMChatModel,
)
from milai_lab.providers.chat_bridge import (
    _action_prompt as _action_prompt,
)
from milai_lab.providers.chat_bridge import (
    _action_schema as _action_schema,
)
from milai_lab.providers.chat_bridge import (
    _json_action_history as _json_action_history,
)

__all__ = [
    "IncompleteChatResponse",
    "VLLMChatModel",
    "_action_prompt",
    "_action_schema",
    "_json_action_history",
]
