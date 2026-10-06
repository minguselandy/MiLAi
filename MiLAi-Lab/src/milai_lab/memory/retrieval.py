"""Ordinary dense retrieval over visible current memory records."""

from __future__ import annotations

from typing import Any

from langchain_core.embeddings import Embeddings

from milai_lab.memory.embeddings import normalized


def semantic_text(value: dict[str, Any]) -> str:
    """Match literal matter/clauses, not rendered IDs or collection timestamps."""
    state = value.get("edit_state")
    if isinstance(state, dict):
        return "\n".join(
            [state.get("matter_description", ""), *[unit["text"] for unit in state["units"]]]
        )
    return str(value.get("content", ""))


class SemanticRetriever:
    """A disposable vector cache; the service remains the only memory authority.

    Rank literal current bodies by cosine. The fixed-state development comparison
    found no added necessary evidence from lexical interleaving. No threshold,
    weights, query rewrite or source/gold lookup. Each service owns its cache.
    """

    def __init__(self, embeddings: Embeddings, dimension: int) -> None:
        self.embeddings, self.dimension = embeddings, dimension
        self._vectors: dict[str, tuple[str, list[float]]] = {}

    def rank(
        self,
        query: str,
        records: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not records:
            return []
        bodies = {row["id"]: semantic_text(row["value"]) for row in records}
        self._vectors = {key: value for key, value in self._vectors.items() if key in bodies}
        changed = [
            key for key, body in bodies.items() if self._vectors.get(key, (None,))[0] != body
        ]
        if changed:
            vectors = self.embeddings.embed_documents([bodies[key] for key in changed])
            if len(vectors) != len(changed):
                raise ValueError("EMBEDDING_VECTOR_COUNT_MISMATCH")
            for key, vector in zip(changed, vectors, strict=True):
                self._vectors[key] = (bodies[key], normalized(vector, self.dimension))
        query_vector = normalized(self.embeddings.embed_query(query), self.dimension)
        return sorted(
            records,
            key=lambda row: (
                -sum(a * b for a, b in zip(query_vector, self._vectors[row["id"]][1], strict=True)),
                row["id"],
            ),
        )[:limit]
