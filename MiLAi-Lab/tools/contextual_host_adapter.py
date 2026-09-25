"""Compatibility exports for the contextual Host and vLLM transport."""

from milai_lab.providers.contextual_vllm import Emit, VLLMClient, VLLMConfig
from milai_lab.runners.contextual_host import (
    FINAL_ANSWER_RESPONSE_FORMAT,
    ContextualHost,
    HostResult,
    InvalidToolCall,
)

__all__ = [
    "FINAL_ANSWER_RESPONSE_FORMAT", "ContextualHost", "Emit", "HostResult",
    "InvalidToolCall", "VLLMClient", "VLLMConfig",
]
