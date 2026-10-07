"""Ordinary dense retrieval over visible current memory records."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal

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


def merge_candidates(
    groups: Sequence[Sequence[dict[str, Any]]], *, limit: int | None = None
) -> list[dict[str, Any]]:
    """Interleave actual ranked pools once per target, without synthesizing records.

    A single pool retains its exact order. Independent candidate queries may use
    this interface without giving every topic a separate editor for one target.
    """
    if limit is not None and limit < 1:
        return []
    selected: dict[str, dict[str, Any]] = {}
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index < len(group):
                row = group[index]
                selected.setdefault(row["id"], row)
                if limit is not None and len(selected) >= limit:
                    return list(selected.values())
    return list(selected.values())


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
        *,
        ranking: Literal["dense", "dense_activation"] = "dense",
        activation_score: Callable[[dict[str, Any]], float] | None = None,
        include_scores: bool = False,
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
        if ranking not in {"dense", "dense_activation"}:
            raise ValueError("RETRIEVAL_RANKING_INVALID")
        if ranking == "dense_activation" and activation_score is None:
            raise ValueError("RETRIEVAL_ACTIVATION_CALLBACK_REQUIRED")

        cosine_scores = {
            row["id"]: sum(
                a * b for a, b in zip(query_vector, self._vectors[row["id"]][1], strict=True)
            ) for row in records
        }

        def order(row: dict[str, Any]) -> tuple[Any, ...]:
            cosine = cosine_scores[row["id"]]
            if ranking == "dense_activation" and activation_score is not None:
                return (-cosine, -activation_score(row), row["id"])
            return (-cosine, row["id"])

        selected = sorted(records, key=order)[:limit]
        return (
            [{**row, "dense_score": cosine_scores[row["id"]]} for row in selected]
            if include_scores else selected
        )
