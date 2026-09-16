from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Any, Literal

DocumentKind = Literal["session", "turn", "window"]

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = frozenset(
    {
        "a",
        "am",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)
_RECENCY = re.compile(
    r"\b(?:latest|last|recent|recently|newest|since|before|after|ago|started|changed)\b",
    re.IGNORECASE,
)
_PREFERENCE = re.compile(
    r"\b(?:prefer|preference|favorite|favourite|like|dislike|avoid|usually|"
    r"dietary|allerg|constraint)\w*\b",
    re.IGNORECASE,
)
_ASSISTANT = re.compile(
    r"\b(?:you|your)\b.*\b(?:recommend|suggest|tell|told|answer|advice|said)\w*\b|"
    r"\b(?:recommend|suggest|advice)\w*\b.*\b(?:you|your)\b",
    re.IGNORECASE,
)
_MULTI = re.compile(
    r"\b(?:how many|total|combined|all|both|between|compare|since|before|after)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ProjectionIdentity:
    provider: str
    model_id: str
    source_dimensions: int
    projection_dimensions: int
    normalization: str
    code_version: str

    @property
    def key(self) -> str:
        canonical = "|".join(
            (
                self.provider,
                self.model_id,
                str(self.source_dimensions),
                str(self.projection_dimensions),
                self.normalization,
                self.code_version,
            )
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def as_dict(self) -> dict[str, str | int]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "source_dimensions": self.source_dimensions,
            "projection_dimensions": self.projection_dimensions,
            "normalization": self.normalization,
            "code_version": self.code_version,
            "key": self.key,
        }


@dataclass(frozen=True, slots=True)
class RetrievalDocument:
    document_id: str
    parent_session_id: str
    kind: DocumentKind
    text: str
    observed_at: str
    roles: tuple[str, ...]
    turn_start: int
    turn_end: int


@dataclass(frozen=True, slots=True)
class LaneCandidate:
    parent_session_id: str
    document_id: str
    raw_score: float
    lane: Literal["fts", "vector", "recent"]
    rank: int


def projection_identity(dimensions: int) -> ProjectionIdentity:
    if dimensions not in {16, 128, 384}:
        raise ValueError("DG11 projection dimensions must be 16, 128, or 384")
    if dimensions == 384:
        return ProjectionIdentity(
            provider="onnx_sentence_transformer",
            model_id="sentence-transformers/all-MiniLM-L6-v2",
            source_dimensions=384,
            projection_dimensions=384,
            normalization="mean-pool-l2",
            code_version="1",
        )
    return ProjectionIdentity(
        provider="onnx_sentence_transformer",
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        source_dimensions=384,
        projection_dimensions=dimensions,
        normalization="mean-pool-l2+dense-projection-l2",
        code_version="1" if dimensions == 16 else "dg11-experimental-1",
    )


def _terms(value: str) -> list[str]:
    raw = [match.group(0).casefold() for match in _WORD.finditer(value)]
    selected = [token for token in raw if len(token) > 1 and token not in _STOPWORDS]
    return selected or [token for token in raw if token]


def _bounded_words(value: str, *, size: int = 140, overlap: int = 24) -> list[str]:
    words = value.split()
    if not words:
        return []
    if len(words) <= size:
        return [value.strip()]
    chunks: list[str] = []
    step = size - overlap
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + size]).strip()
        if chunk:
            chunks.append(chunk)
        if start + size >= len(words):
            break
    return chunks


def build_session_documents(
    session_ids: Sequence[str],
    sessions: Sequence[Sequence[Mapping[str, Any]]],
    dates: Sequence[str],
) -> list[RetrievalDocument]:
    if not (len(session_ids) == len(sessions) == len(dates)):
        raise ValueError("session IDs, payloads, and dates must align")
    documents: list[RetrievalDocument] = []
    for source_index, (session_id, messages, observed_at) in enumerate(
        zip(session_ids, sessions, dates, strict=True)
    ):
        rendered: list[str] = []
        roles: list[str] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if (
                not isinstance(role, str)
                or not isinstance(content, str)
                or not content.strip()
            ):
                raise ValueError("LongMemEval message contract failed")
            roles.append(role.casefold())
            rendered.append(f"{role}: {content.strip()}")
        documents.append(
            RetrievalDocument(
                document_id=f"{session_id}:source:{source_index}:session",
                parent_session_id=str(session_id),
                kind="session",
                text="\n".join(rendered),
                observed_at=str(observed_at),
                roles=tuple(roles),
                turn_start=0,
                turn_end=len(rendered) - 1,
            )
        )
    return documents


def build_window_documents(
    session_ids: Sequence[str],
    sessions: Sequence[Sequence[Mapping[str, Any]]],
    dates: Sequence[str],
) -> list[RetrievalDocument]:
    """Build bounded turn chunks and adjacent message windows with parent pointers."""
    if not (len(session_ids) == len(sessions) == len(dates)):
        raise ValueError("session IDs, payloads, and dates must align")
    documents: list[RetrievalDocument] = []
    for source_index, (session_id, messages, observed_at) in enumerate(
        zip(session_ids, sessions, dates, strict=True)
    ):
        normalized: list[tuple[str, str]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if (
                not isinstance(role, str)
                or not isinstance(content, str)
                or not content.strip()
            ):
                raise ValueError("LongMemEval message contract failed")
            normalized.append((role.casefold(), content.strip()))
        for turn_index, (role, content) in enumerate(normalized):
            for chunk_index, chunk in enumerate(_bounded_words(content)):
                documents.append(
                    RetrievalDocument(
                        document_id=(
                            f"{session_id}:source:{source_index}:"
                            f"turn:{turn_index}:{chunk_index}"
                        ),
                        parent_session_id=str(session_id),
                        kind="turn",
                        text=f"{role}: {chunk}",
                        observed_at=str(observed_at),
                        roles=(role,),
                        turn_start=turn_index,
                        turn_end=turn_index,
                    )
                )
        for turn_index in range(len(normalized) - 1):
            left_role, left_content = normalized[turn_index]
            right_role, right_content = normalized[turn_index + 1]
            left = " ".join(left_content.split()[-72:])
            right = " ".join(right_content.split()[:96])
            documents.append(
                RetrievalDocument(
                    document_id=(
                        f"{session_id}:source:{source_index}:"
                        f"window:{turn_index}:{turn_index + 1}"
                    ),
                    parent_session_id=str(session_id),
                    kind="window",
                    text=f"{left_role}: {left}\n{right_role}: {right}",
                    observed_at=str(observed_at),
                    roles=(left_role, right_role),
                    turn_start=turn_index,
                    turn_end=turn_index + 1,
                )
            )
    if len({document.document_id for document in documents}) != len(documents):
        raise ValueError("derived document identities must be unique")
    return documents


def classify_intent(query: str) -> frozenset[str]:
    intents = {"semantic"}
    if _RECENCY.search(query):
        intents.add("recency")
    if _PREFERENCE.search(query):
        intents.add("preference")
    if _ASSISTANT.search(query):
        intents.add("assistant")
    if _MULTI.search(query):
        intents.add("multi")
    return frozenset(intents)


def bm25_scores(query: str, documents: Sequence[RetrievalDocument]) -> list[float]:
    if not documents:
        return []
    query_terms = list(dict.fromkeys(_terms(query)))
    frequencies = [Counter(_terms(document.text)) for document in documents]
    lengths = [sum(values.values()) for values in frequencies]
    average_length = max(mean(lengths), 1.0)
    document_frequency = {
        token: sum(token in values for values in frequencies) for token in query_terms
    }
    scores: list[float] = []
    for counts, length in zip(frequencies, lengths, strict=True):
        score = 0.0
        for token in query_terms:
            frequency = counts.get(token, 0)
            if not frequency:
                continue
            inverse_frequency = math.log(
                1
                + (len(documents) - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )
            denominator = frequency + 1.2 * (0.25 + 0.75 * length / average_length)
            score += inverse_frequency * (frequency * 2.2) / denominator
        scores.append(score)
    return scores


def _parent_lane(
    scores: Sequence[float],
    documents: Sequence[RetrievalDocument],
    lane: Literal["fts", "vector"],
    *,
    intents: frozenset[str],
    limit: int,
) -> list[LaneCandidate]:
    if len(scores) != len(documents):
        raise ValueError("lane score/document alignment failed")
    adjusted: list[tuple[float, RetrievalDocument]] = []
    for score, document in zip(scores, documents, strict=True):
        value = float(score)
        if lane == "fts" and value <= 0:
            continue
        if "assistant" in intents and "assistant" in document.roles:
            value += 0.035 if lane == "vector" else value * 0.08
        if "preference" in intents and "user" in document.roles:
            value += 0.025 if lane == "vector" else value * 0.06
        adjusted.append((value, document))
    adjusted.sort(key=lambda item: (-item[0], item[1].document_id))
    parents: list[tuple[float, RetrievalDocument]] = []
    seen: set[str] = set()
    for score, document in adjusted:
        if document.parent_session_id in seen:
            continue
        seen.add(document.parent_session_id)
        parents.append((score, document))
        if len(parents) >= limit:
            break
    return [
        LaneCandidate(
            parent_session_id=document.parent_session_id,
            document_id=document.document_id,
            raw_score=round(score, 8),
            lane=lane,
            rank=rank,
        )
        for rank, (score, document) in enumerate(parents, start=1)
    ]


def _recent_lane(
    lexical: Sequence[LaneCandidate],
    documents: Sequence[RetrievalDocument],
    *,
    limit: int,
) -> list[LaneCandidate]:
    by_id = {document.document_id: document for document in documents}

    def timestamp(candidate: LaneCandidate) -> float:
        value = by_id[candidate.document_id].observed_at
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return float("-inf")

    ordered = sorted(
        lexical,
        key=lambda candidate: (
            -timestamp(candidate),
            -candidate.raw_score,
            candidate.document_id,
        ),
    )[:limit]
    return [
        LaneCandidate(
            parent_session_id=candidate.parent_session_id,
            document_id=candidate.document_id,
            raw_score=timestamp(candidate),
            lane="recent",
            rank=rank,
        )
        for rank, candidate in enumerate(ordered, start=1)
    ]


def retrieve_parents(
    query: str,
    documents: Sequence[RetrievalDocument],
    vector_scores: Sequence[float],
    *,
    k: int = 3,
) -> dict[str, Any]:
    if k <= 0:
        raise ValueError("retrieval k must be positive")
    intents = classify_intent(query)
    candidate_limit = 30 if "multi" in intents else 12
    lexical = _parent_lane(
        bm25_scores(query, documents),
        documents,
        "fts",
        intents=intents,
        limit=candidate_limit,
    )
    semantic = _parent_lane(
        vector_scores,
        documents,
        "vector",
        intents=intents,
        limit=candidate_limit,
    )
    groups: list[list[LaneCandidate]] = [lexical, semantic]
    weights = {"fts": 1.0, "vector": 0.4, "recent": 0.7}
    if "preference" in intents:
        weights["vector"] = 1.0
    elif "assistant" in intents:
        weights["vector"] = 0.8
    if "recency" in intents:
        groups.append(_recent_lane(lexical, documents, limit=candidate_limit))

    scores: dict[str, float] = {}
    evidence: dict[str, list[LaneCandidate]] = {}
    for group in groups:
        for candidate in group:
            scores[candidate.parent_session_id] = scores.get(
                candidate.parent_session_id, 0.0
            ) + (weights[candidate.lane] / (10 + candidate.rank))
            evidence.setdefault(candidate.parent_session_id, []).append(candidate)
    ranked = sorted(scores, key=lambda parent: (-scores[parent], parent))
    selected = ranked[:k]
    result_items: list[dict[str, Any]] = []
    for parent in selected:
        lanes = sorted(evidence[parent], key=lambda candidate: candidate.lane)
        result_items.append(
            {
                "parent_session_id": parent,
                "score": round(scores[parent], 8),
                "matched_by": [candidate.lane for candidate in lanes],
                "lane_evidence": [
                    {
                        "lane": candidate.lane,
                        "rank": candidate.rank,
                        "raw_score": round(candidate.raw_score, 8),
                        "document_id": candidate.document_id,
                    }
                    for candidate in lanes
                ],
            }
        )
    margin = scores[selected[0]] - scores[selected[1]] if len(selected) > 1 else None
    return {
        "session_ids": selected,
        "items": result_items,
        "score_margin_top1_top2": round(margin, 8) if margin is not None else None,
        "intents": sorted(intents),
        "candidate_limit": candidate_limit,
        "recent_lane_enabled": "recency" in intents,
    }


def project_source(source: Any, dimensions: int, *, numpy_module: Any) -> Any:
    """Project normalized 384d rows; the 16d path matches the Runtime byte algorithm."""
    identity = projection_identity(dimensions)
    matrix = numpy_module.asarray(source, dtype="float32")
    if matrix.ndim != 2 or matrix.shape[1] != identity.source_dimensions:
        raise ValueError("source embedding matrix must be N x 384")
    if dimensions == identity.source_dimensions:
        return matrix
    weights = numpy_module.empty(
        (identity.source_dimensions, dimensions), dtype="float32"
    )
    seed = identity.key.encode()
    for source_index in range(identity.source_dimensions):
        base = seed + source_index.to_bytes(4, "big")
        for block_start in range(0, dimensions, 32):
            digest = hashlib.sha256(
                base + (b"" if block_start == 0 else block_start.to_bytes(2, "big"))
            ).digest()
            width = min(32, dimensions - block_start)
            weights[source_index, block_start : block_start + width] = [
                (digest[index] - 127.5) / 127.5 for index in range(width)
            ]
    projected = matrix @ weights
    norms = numpy_module.linalg.norm(projected, axis=1, keepdims=True)
    return projected / numpy_module.maximum(norms, 1e-12)


def summarize_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise ValueError("retrieval records cannot be empty")
    categories = sorted({str(record["category"]) for record in records})

    def aggregate(group: Sequence[Mapping[str, Any]]) -> dict[str, float | int]:
        return {
            "case_count": len(group),
            "hit_at_3": round(mean(float(record["hit_at_3"]) for record in group), 6),
            "relevant_coverage_at_3": round(
                mean(float(record["relevant_coverage_at_3"]) for record in group), 6
            ),
        }

    return {
        "overall": aggregate(records),
        "category": {
            category: aggregate(
                [record for record in records if str(record["category"]) == category]
            )
            for category in categories
        },
    }


def metric_gates(summary: Mapping[str, Any]) -> dict[str, bool]:
    overall = summary["overall"]
    categories = summary["category"]
    return {
        "overall_hit_at_3_gte_090": float(overall["hit_at_3"]) >= 0.90,
        "overall_coverage_at_3_gte_085": float(overall["relevant_coverage_at_3"])
        >= 0.85,
        "preference_hit_at_3_gte_075": (
            float(categories["single-session-preference"]["hit_at_3"]) >= 0.75
        ),
        "assistant_hit_at_3_gte_090": (
            float(categories["single-session-assistant"]["hit_at_3"]) >= 0.90
        ),
    }


def choose_winner(variants: Mapping[str, Mapping[str, Any]]) -> str | None:
    passing = [name for name, value in variants.items() if all(value["gates"].values())]
    if not passing:
        return None
    if "A1" in passing:
        baseline = variants["A1"]["summary"]
        for name in ("A2", "A3"):
            if name not in passing:
                continue
            candidate = variants[name]["summary"]
            stable_gain = (
                float(candidate["overall"]["hit_at_3"])
                >= float(baseline["overall"]["hit_at_3"]) + 0.02
                and float(candidate["overall"]["relevant_coverage_at_3"])
                >= float(baseline["overall"]["relevant_coverage_at_3"]) + 0.03
                and float(
                    candidate["category"]["single-session-preference"]["hit_at_3"]
                )
                >= float(baseline["category"]["single-session-preference"]["hit_at_3"])
                and float(candidate["category"]["single-session-assistant"]["hit_at_3"])
                >= float(baseline["category"]["single-session-assistant"]["hit_at_3"])
            )
            if stable_gain:
                return name
        return "A1"
    return min(passing, key=lambda name: {"A2": 128, "A3": 384}.get(name, 10_000))
