"""Stable recollection boundary for Runtime consumers.

The package is intentionally small: facade types live here while retrieval
strategy and orchestration remain behind the boundary.  The package preserves
the historical ``milai.application.recollection`` import path.
"""

from .facade import (
    MatchedReplayInvariantError,
    MatchedReplayPolicy,
    MatchedRetrievalReplay,
    RecollectionFacade,
    RetrievalExecution,
)

__all__ = [
    "MatchedReplayInvariantError",
    "MatchedReplayPolicy",
    "MatchedRetrievalReplay",
    "RecollectionFacade",
    "RetrievalExecution",
]
