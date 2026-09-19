"""Context preparation components.

``context_preparation`` remains the compatibility entry point for the service;
this package owns the smaller, deterministic contracts used by that service.
Keeping these seams separate makes route, binding and serialization changes
reviewable without changing the HTTP/API import surface.
"""

from .contracts import ExecutionRoute, PrepareContextExecution

__all__ = ["ExecutionRoute", "PrepareContextExecution"]
