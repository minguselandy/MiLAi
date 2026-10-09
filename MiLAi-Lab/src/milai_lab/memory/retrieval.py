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


def _semantic_entries(
    value: dict[str, Any], *, granularity: Literal["record", "record_units"] = "record"
) -> tuple[tuple[str, dict[str, Any] | None], ...]:
    """Keep each unchanged key's actual unit, with no unit for the whole key."""
    whole = semantic_text(value)
    state = value.get("edit_state")
    if granularity == "record" or not isinstance(state, dict):
        return ((whole, None),)

    units = state["units"]
    texts: dict[str, str] = {
        unit["unit_id"]: unit["text"] for unit in units if "unit_id" in unit
    }
    linked: dict[str, list[str]] = {}
    for relation in state.get("relations", []):
        source, target = relation.get("source_unit"), relation.get("target_unit")
        if source not in texts or target not in texts:
            continue
        # Preserve actual type/direction and both literal ends, without asserting
        # that a stored qualification is currently applicable or independently true.
        link = f"{relation['relation_type']}: {texts[source]} -> {texts[target]}"
        linked.setdefault(source, []).append(link)
        if target != source:
            linked.setdefault(target, []).append(link)

    entries: dict[str, dict[str, Any] | None] = {whole: None}
    for unit in units:
        text = (
            "\n".join(
                [state.get("matter_description", ""), unit["text"],
                 *linked.get(unit.get("unit_id", ""), [])]
            )
        )
        entries.setdefault(text, unit)
    return tuple(entries.items())


def semantic_keys(
    value: dict[str, Any], *, granularity: Literal["record", "record_units"] = "record"
) -> tuple[str, ...]:
    """Disposable search keys; none becomes a record, source or Reader material."""
    return tuple(text for text, _ in _semantic_entries(value, granularity=granularity))


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

    Rank literal current bodies by cosine, optionally also their existing units.
    Each record takes its maximum key cosine and still returns its complete row.
    No threshold, weights, query rewrite or source/gold lookup. Each service owns
    its cache; the default retains the original whole-record embedding path.
    """

    def __init__(
        self,
        embeddings: Embeddings,
        dimension: int,
        *,
        granularity: Literal["record", "record_units"] = "record",
    ) -> None:
        if granularity not in {"record", "record_units"}:
            raise ValueError("RETRIEVAL_GRANULARITY_INVALID")
        self.embeddings, self.dimension = embeddings, dimension
        self.granularity = granularity
        self._vectors: dict[str, tuple[str, list[float]]] = {}
        self._unit_vectors: dict[tuple[str, str], list[float]] = {}

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
        entries = {
            row["id"]: _semantic_entries(row["value"], granularity=self.granularity)
            for row in records
        }
        keys = {key: tuple(text for text, _ in items) for key, items in entries.items()}
        bodies = {key: texts[0] for key, texts in keys.items()}
        unit_keys = dict.fromkeys(
            (key, text) for key, texts in keys.items() for text in texts[1:]
        )
        self._vectors = {key: value for key, value in self._vectors.items() if key in bodies}
        self._unit_vectors = {
            key: vector for key, vector in self._unit_vectors.items() if key in unit_keys
        }
        changed = [
            key for key, body in bodies.items() if self._vectors.get(key, (None,))[0] != body
        ]
        changed_units = [key for key in unit_keys if key not in self._unit_vectors]
        if changed or changed_units:
            vectors = self.embeddings.embed_documents(
                [bodies[key] for key in changed] + [text for _, text in changed_units]
            )
            if len(vectors) != len(changed) + len(changed_units):
                raise ValueError("EMBEDDING_VECTOR_COUNT_MISMATCH")
            for key, vector in zip(changed, vectors[:len(changed)], strict=True):
                self._vectors[key] = (bodies[key], normalized(vector, self.dimension))
            for unit_key, vector in zip(changed_units, vectors[len(changed):], strict=True):
                self._unit_vectors[unit_key] = normalized(vector, self.dimension)
        query_vector = normalized(self.embeddings.embed_query(query), self.dimension)
        if ranking not in {"dense", "dense_activation"}:
            raise ValueError("RETRIEVAL_RANKING_INVALID")
        if ranking == "dense_activation" and activation_score is None:
            raise ValueError("RETRIEVAL_ACTIVATION_CALLBACK_REQUIRED")

        cosine_scores: dict[str, float] = {}
        navigation: dict[str, dict[str, Any]] = {}
        for key, texts in keys.items():
            scores = [
                sum(a * b for a, b in zip(query_vector, vector, strict=True))
                for vector in [
                    self._vectors[key][1],
                    *[self._unit_vectors[(key, text)] for text in texts[1:]],
                ]
            ]
            winner = max(range(len(scores)), key=scores.__getitem__)
            cosine_scores[key] = scores[winner]
            unit = entries[key][winner][1]
            if self.granularity == "record_units":
                # Navigation only, outside the stored value/support. The first
                # maximum wins, so a whole-key tie never invents a unit hit.
                text = texts[winner] if unit is None else unit["text"]
                navigation[key] = {
                    "key_kind": "whole" if unit is None else "unit",
                    **({"unit_id": unit["unit_id"]}
                       if unit is not None and "unit_id" in unit else {}),
                    "excerpt": text[:240], "truncated": len(text) > 240,
                }

        def order(row: dict[str, Any]) -> tuple[Any, ...]:
            cosine = cosine_scores[row["id"]]
            if ranking == "dense_activation" and activation_score is not None:
                return (-cosine, -activation_score(row), row["id"])
            return (-cosine, row["id"])

        candidates = (
            records if self.granularity == "record"
            else list({row["id"]: row for row in records}.values())
        )
        selected = sorted(candidates, key=order)[:limit]
        if navigation:
            selected = [
                {**row, "retrieval_navigation": navigation[row["id"]]}
                if row["id"] in navigation else row for row in selected
            ]
        return (
            [{**row, "dense_score": cosine_scores[row["id"]]} for row in selected]
            if include_scores else selected
        )
