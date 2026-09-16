"""Memory adapters used by the DG-11 paper evaluation plane."""

from .baselines import (
    CustomLexicalTop1Adapter,
    DenseAdapter,
    FullHistoryAdapter,
    NoMemoryAdapter,
    OfficialBM25Adapter,
    OracleAdapter,
)

__all__ = [
    "CustomLexicalTop1Adapter",
    "DenseAdapter",
    "FullHistoryAdapter",
    "NoMemoryAdapter",
    "OfficialBM25Adapter",
    "OracleAdapter",
]
