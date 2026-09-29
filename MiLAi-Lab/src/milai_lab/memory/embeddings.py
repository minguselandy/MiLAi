"""Generic finite vector normalization used by memory embeddings."""

import math


def normalized(vector: list[float], dimension: int) -> list[float]:
    if len(vector) != dimension or any(not math.isfinite(x) for x in vector):
        raise ValueError("EMBEDDING_CONTRACT_MISMATCH")
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise ValueError("ZERO_EMBEDDING")
    return [x / norm for x in vector]
