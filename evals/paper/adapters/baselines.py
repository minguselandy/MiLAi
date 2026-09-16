"""Controlled baseline adapters for LongMemEval-style histories."""

from __future__ import annotations

import math
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from evals.paper.contracts import (
    AdapterCapabilities,
    AdapterStats,
    CapabilityStatus,
    MemoryEvent,
    MemoryQueryResult,
)

TokenCounter = Callable[[str], int]
Embedder = Callable[[Sequence[str]], np.ndarray]


def _whitespace_tokens(value: str) -> list[str]:
    """Match LongMemEval's official flat-bm25 split-on-literal-space protocol."""

    return value.split(" ")


def _default_token_counter(value: str) -> int:
    return len(value.split())


@dataclass(frozen=True)
class _Document:
    source_id: str
    parent_session_id: str
    index_text: str
    content: str
    observed_at: str


def _render_document(document: _Document) -> str:
    return f"Session Date: {document.observed_at}\nSession Content:\n{document.content}"


def _render_chronological(documents: Sequence[_Document]) -> str:
    ordered = sorted(
        documents,
        key=lambda item: (item.observed_at, item.parent_session_id, item.source_id),
    )
    return "\n\n".join(_render_document(document) for document in ordered)


def _fit_prefix(
    value: str, token_budget: int, token_counter: TokenCounter
) -> tuple[str, bool]:
    """Match official retrieval-context prefix truncation with an exact counter."""

    if token_budget <= 0:
        raise ValueError("token budget must be positive")
    if token_counter(value) <= token_budget:
        return value, False
    low = 0
    high = len(value)
    best = ""
    while low <= high:
        midpoint = (low + high) // 2
        candidate = value[:midpoint].rstrip()
        if token_counter(candidate) <= token_budget:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best, True


class _StatefulAdapter:
    method_id = "BASE"
    capabilities = AdapterCapabilities(
        revoke=CapabilityStatus.SUPPORTED,
        update=CapabilityStatus.SUPPORTED,
        native_provider_calls=False,
    )

    def __init__(self, *, token_counter: TokenCounter | None = None) -> None:
        self._token_counter = token_counter or _default_token_counter
        self._run_id: str | None = None
        self._case_id: str | None = None
        self._events: list[MemoryEvent] = []
        self._revoked: set[str] = set()
        self._finalized = False
        self._queries = 0

    def reset(self, run_id: str, case_id: str) -> None:
        if not run_id or not case_id:
            raise ValueError("run_id and case_id are required")
        self._run_id = run_id
        self._case_id = case_id
        self._events = []
        self._revoked = set()
        self._finalized = False
        self._queries = 0

    def ingest(self, event: MemoryEvent) -> None:
        self._require_reset()
        if self._finalized:
            raise RuntimeError("cannot ingest after finalize")
        if any(item.event_id == event.event_id for item in self._events):
            raise ValueError(f"duplicate event_id: {event.event_id}")
        self._events.append(event)

    def finalize(self) -> None:
        self._require_reset()
        self._finalized = True

    def revoke(self, event_id: str) -> CapabilityStatus:
        self._require_reset()
        if not any(item.event_id == event_id for item in self._events):
            raise KeyError(event_id)
        self._revoked.add(event_id)
        return CapabilityStatus.SUPPORTED

    def stats(self) -> AdapterStats:
        storage = sum(len(item.content.encode("utf-8")) for item in self._events)
        return AdapterStats(
            method_id=self.method_id,
            ingested_events=len(self._events),
            query_count=self._queries,
            revoked_events=len(self._revoked),
            provider_calls={
                "ingest_extraction": 0,
                "reflection_consolidation": 0,
                "memory_query_model": 0,
                "answer": 0,
                "judge": 0,
            },
            storage_bytes=storage,
        )

    def close(self) -> None:
        self._run_id = None
        self._case_id = None
        self._events = []
        self._revoked = set()
        self._finalized = False

    def _active_events(self) -> list[MemoryEvent]:
        return [event for event in self._events if event.event_id not in self._revoked]

    def _require_query_ready(self) -> None:
        self._require_reset()
        if not self._finalized:
            raise RuntimeError("adapter must be finalized before query")

    def _require_reset(self) -> None:
        if self._run_id is None or self._case_id is None:
            raise RuntimeError("adapter must be reset before use")


class NoMemoryAdapter(_StatefulAdapter):
    method_id = "CTRL-NONE"

    def query(
        self,
        question: str,
        question_at: str,
        token_budget: int,
        mode: str,
    ) -> MemoryQueryResult:
        del question, question_at, mode
        self._require_query_ready()
        if token_budget < 0:
            raise ValueError("token budget cannot be negative")
        self._queries += 1
        return MemoryQueryResult("", (), (), 0, 0.0, {"retriever_calls": 0})


class CustomLexicalTop1Adapter(_StatefulAdapter):
    """DG-10 continuity baseline; explicitly not an official retriever."""

    method_id = "CTRL-CUSTOM-LEX1"

    def query(
        self,
        question: str,
        question_at: str,
        token_budget: int,
        mode: str,
    ) -> MemoryQueryResult:
        del question_at, mode
        self._require_query_ready()
        if token_budget <= 0:
            raise ValueError("token budget must be positive")
        started = time.perf_counter()
        documents = OfficialBM25Adapter(
            granularity="session", token_counter=self._token_counter
        )
        documents._events = list(self._events)
        documents._revoked = set(self._revoked)
        source = documents._documents()
        terms = Counter(
            token.casefold() for token in question.split() if len(token.strip()) > 1
        )
        scored: list[tuple[int, str, _Document]] = []
        for document in source:
            document_terms = Counter(
                token.casefold()
                for token in document.index_text.split()
                if len(token.strip()) > 1
            )
            overlap = sum(
                min(count, document_terms.get(token, 0))
                for token, count in terms.items()
            )
            scored.append((-overlap, document.source_id, document))
        scored.sort(key=lambda item: (item[0], item[1]))
        selected = scored[0][2] if scored else None
        full_context = _render_document(selected) if selected is not None else ""
        context, truncated = _fit_prefix(
            full_context, token_budget, self._token_counter
        )
        self._queries += 1
        trace = (
            (
                {
                    "rank": 1,
                    "score": -scored[0][0],
                    "session_id": selected.parent_session_id,
                    "source_id": selected.source_id,
                },
            )
            if selected is not None
            else ()
        )
        return MemoryQueryResult(
            context,
            (selected.source_id,) if selected is not None else (),
            trace,
            self._token_counter(context),
            (time.perf_counter() - started) * 1000,
            {
                "context_truncated": truncated,
                "documents_scored": len(source),
                "retriever_calls": 1,
            },
        )


class OfficialBM25Adapter(_StatefulAdapter):
    """Rank-BM25 compatible Okapi adapter using the official LME tokenization."""

    def __init__(
        self,
        *,
        granularity: str,
        top_k: int = 3,
        token_counter: TokenCounter | None = None,
        method_id: str | None = None,
    ) -> None:
        super().__init__(token_counter=token_counter)
        if granularity not in {"session", "turn"}:
            raise ValueError("BM25 granularity must be session or turn")
        if top_k <= 0:
            raise ValueError("BM25 top_k must be positive")
        self.granularity = granularity
        self.top_k = top_k
        self.method_id = method_id or (
            "LME-BM25-S" if granularity == "session" else "LME-BM25-T"
        )

    def _documents(self) -> list[_Document]:
        grouped: dict[str, list[MemoryEvent]] = defaultdict(list)
        for event in self._active_events():
            session_id = str(event.metadata.get("session_id", event.event_id))
            grouped[session_id].append(event)
        documents: list[_Document] = []
        for session_id, events in grouped.items():
            events.sort(
                key=lambda item: (
                    int(item.metadata.get("turn_index", 0)),
                    item.event_id,
                )
            )
            if self.granularity == "session":
                user_text = " ".join(
                    event.content for event in events if event.actor == "user"
                )
                if user_text:
                    documents.append(
                        _Document(
                            session_id,
                            session_id,
                            user_text,
                            "\n\n".join(
                                f"{event.actor}: {event.content}" for event in events
                            ),
                            events[-1].observed_at,
                        )
                    )
                continue
            for index, event in enumerate(events):
                if event.actor != "user":
                    continue
                round_events = [event]
                if index + 1 < len(events) and events[index + 1].actor == "assistant":
                    round_events.append(events[index + 1])
                documents.append(
                    _Document(
                        event.event_id,
                        session_id,
                        event.content,
                        "\n\n".join(
                            f"{item.actor}: {item.content}" for item in round_events
                        ),
                        event.observed_at,
                    )
                )
        return documents

    def query(
        self,
        question: str,
        question_at: str,
        token_budget: int,
        mode: str,
    ) -> MemoryQueryResult:
        del question_at, mode
        self._require_query_ready()
        if token_budget <= 0:
            raise ValueError("token budget must be positive")
        started = time.perf_counter()
        documents = self._documents()
        scores = _bm25_scores(
            [_whitespace_tokens(document.index_text) for document in documents],
            _whitespace_tokens(question),
        )
        ranked = sorted(
            range(len(documents)),
            key=lambda index: (scores[index], index),
            reverse=True,
        )
        selected = [documents[index] for index in ranked[: self.top_k]]
        trace = [
            {
                "rank": rank,
                "session_id": documents[index].parent_session_id,
                "score": round(float(scores[index]), 9),
                "source_id": documents[index].source_id,
            }
            for rank, index in enumerate(ranked[: self.top_k], start=1)
        ]
        context, truncated = _fit_prefix(
            _render_chronological(selected), token_budget, self._token_counter
        )
        self._queries += 1
        return MemoryQueryResult(
            context=context,
            source_ids=tuple(document.source_id for document in selected),
            trace=tuple(trace),
            declared_tokens=self._token_counter(context),
            latency_ms=(time.perf_counter() - started) * 1000,
            usage={
                "context_truncated": truncated,
                "retriever_calls": 1,
                "documents_scored": len(documents),
            },
        )


class DenseAdapter(_StatefulAdapter):
    """Dense controlled-track adapter with an explicitly frozen embedder."""

    method_id = "LME-DENSE"

    def __init__(
        self,
        embedder: Embedder,
        *,
        granularity: str = "session",
        top_k: int = 3,
        token_counter: TokenCounter | None = None,
        model_id: str,
    ) -> None:
        super().__init__(token_counter=token_counter)
        if granularity not in {"session", "turn"}:
            raise ValueError("dense granularity must be session or turn")
        if top_k <= 0 or not model_id:
            raise ValueError("dense adapter requires positive top_k and model_id")
        self._embedder = embedder
        self.granularity = granularity
        self.top_k = top_k
        self.model_id = model_id

    def query(
        self,
        question: str,
        question_at: str,
        token_budget: int,
        mode: str,
    ) -> MemoryQueryResult:
        del question_at, mode
        self._require_query_ready()
        started = time.perf_counter()
        source = OfficialBM25Adapter(
            granularity=self.granularity,
            top_k=self.top_k,
            token_counter=self._token_counter,
        )
        source._events = list(self._events)
        source._revoked = set(self._revoked)
        documents = source._documents()
        if not documents:
            vectors = np.empty((0, 0), dtype=np.float32)
            scores = np.empty((0,), dtype=np.float32)
        else:
            vectors = np.asarray(
                self._embedder([question, *[item.index_text for item in documents]])
            )
            if vectors.ndim != 2 or vectors.shape[0] != len(documents) + 1:
                raise ValueError("dense embedder returned an invalid shape")
            if not np.isfinite(vectors).all():
                raise ValueError("dense embedder returned non-finite values")
            # Match LongMemEval's official flat-contriever implementation: mean
            # pooling followed by an unnormalized query/document dot product.
            scores = vectors[1:] @ vectors[0]
        ranked = sorted(
            range(len(documents)),
            key=lambda index: (scores[index], index),
            reverse=True,
        )
        selected = [documents[index] for index in ranked[: self.top_k]]
        trace = [
            {
                "rank": rank,
                "session_id": documents[index].parent_session_id,
                "score": round(float(scores[index]), 9),
                "source_id": documents[index].source_id,
            }
            for rank, index in enumerate(ranked[: self.top_k], start=1)
        ]
        context, truncated = _fit_prefix(
            _render_chronological(selected), token_budget, self._token_counter
        )
        self._queries += 1
        return MemoryQueryResult(
            context,
            tuple(item.source_id for item in selected),
            tuple(trace),
            self._token_counter(context),
            (time.perf_counter() - started) * 1000,
            {
                "context_truncated": truncated,
                "embedding_calls": 1,
                "embedding_items": len(documents) + 1,
                "model_id": self.model_id,
            },
        )


class FullHistoryAdapter(_StatefulAdapter):
    def __init__(
        self,
        *,
        truncate: bool,
        token_counter: TokenCounter | None = None,
    ) -> None:
        super().__init__(token_counter=token_counter)
        self.truncate = truncate
        self.method_id = "CTRL-TRUNC-FULL" if truncate else "CTRL-FULL"

    def query(
        self,
        question: str,
        question_at: str,
        token_budget: int,
        mode: str,
    ) -> MemoryQueryResult:
        del question, question_at, mode
        self._require_query_ready()
        started = time.perf_counter()
        events = sorted(
            self._active_events(), key=lambda item: (item.observed_at, item.event_id)
        )
        rendered = [
            f"[{event.observed_at}] {event.actor}: {event.content}" for event in events
        ]
        full_context = "\n".join(rendered)
        if not self.truncate:
            if self._token_counter(full_context) > token_budget:
                raise ValueError("full history exceeds the controlled memory budget")
            selected = events
            context = full_context
        else:
            selected = []
            selected_rendered: list[str] = []
            for event, line in reversed(list(zip(events, rendered, strict=True))):
                proposed = "\n".join([line, *selected_rendered])
                if self._token_counter(proposed) > token_budget:
                    continue
                selected.insert(0, event)
                selected_rendered.insert(0, line)
            context = "\n".join(selected_rendered)
        self._queries += 1
        return MemoryQueryResult(
            context,
            tuple(event.event_id for event in selected),
            tuple(
                {"rank": index + 1, "source_id": event.event_id}
                for index, event in enumerate(selected)
            ),
            self._token_counter(context),
            (time.perf_counter() - started) * 1000,
            {"history_events": len(events), "selected_events": len(selected)},
        )


class OracleAdapter(_StatefulAdapter):
    """Explicit retrieval upper bound; ordinary ingest remains label-free."""

    method_id = "LME-ORACLE"

    def __init__(self, *, token_counter: TokenCounter | None = None) -> None:
        super().__init__(token_counter=token_counter)
        self._oracle_ids: set[str] = set()

    def reset(self, run_id: str, case_id: str) -> None:
        super().reset(run_id, case_id)
        self._oracle_ids = set()

    def set_oracle_source_ids(self, source_ids: Iterable[str]) -> None:
        self._require_reset()
        if self._events:
            raise RuntimeError("oracle labels must be bound before ingest")
        self._oracle_ids = set(source_ids)

    def query(
        self,
        question: str,
        question_at: str,
        token_budget: int,
        mode: str,
    ) -> MemoryQueryResult:
        del question, question_at
        self._require_query_ready()
        if mode != "ORACLE_UPPER_BOUND":
            raise ValueError("oracle adapter is restricted to the upper-bound track")
        started = time.perf_counter()
        grouped: dict[str, list[MemoryEvent]] = defaultdict(list)
        for event in self._active_events():
            session_id = str(event.metadata.get("session_id", event.event_id))
            if session_id in self._oracle_ids or event.event_id in self._oracle_ids:
                grouped[session_id].append(event)
        documents: list[_Document] = []
        for session_id, events in grouped.items():
            events.sort(
                key=lambda item: (
                    int(item.metadata.get("turn_index", 0)),
                    item.event_id,
                )
            )
            documents.append(
                _Document(
                    (
                        session_id
                        if session_id in self._oracle_ids
                        else next(
                            event.event_id
                            for event in events
                            if event.event_id in self._oracle_ids
                        )
                    ),
                    session_id,
                    " ".join(
                        event.content for event in events if event.actor == "user"
                    ),
                    "\n\n".join(f"{event.actor}: {event.content}" for event in events),
                    events[-1].observed_at,
                )
            )
        context, truncated = _fit_prefix(
            _render_chronological(documents), token_budget, self._token_counter
        )
        self._queries += 1
        return MemoryQueryResult(
            context,
            tuple(document.source_id for document in documents),
            tuple(
                {
                    "rank": index + 1,
                    "score": 1.0,
                    "session_id": document.parent_session_id,
                    "source_id": document.source_id,
                }
                for index, document in enumerate(documents)
            ),
            self._token_counter(context),
            (time.perf_counter() - started) * 1000,
            {
                "context_truncated": truncated,
                "oracle_labels_used": len(self._oracle_ids),
            },
        )


def _bm25_scores(corpus: Sequence[Sequence[str]], query: Sequence[str]) -> list[float]:
    """BM25Okapi 0.2.2 scoring with its default k1/b/epsilon parameters."""

    if not corpus:
        return []
    k1 = 1.5
    b = 0.75
    epsilon = 0.25
    document_frequencies: Counter[str] = Counter()
    frequencies: list[Counter[str]] = []
    lengths: list[int] = []
    for document in corpus:
        frequency = Counter(document)
        frequencies.append(frequency)
        lengths.append(len(document))
        document_frequencies.update(frequency.keys())
    corpus_size = len(corpus)
    average_length = sum(lengths) / corpus_size
    idf: dict[str, float] = {}
    negative: list[str] = []
    for word, document_count in document_frequencies.items():
        value = math.log(corpus_size - document_count + 0.5) - math.log(
            document_count + 0.5
        )
        idf[word] = value
        if value < 0:
            negative.append(word)
    average_idf = sum(idf.values()) / len(idf) if idf else 0.0
    for word in negative:
        idf[word] = epsilon * average_idf
    scores = [0.0] * corpus_size
    for word in query:
        word_idf = idf.get(word, 0.0)
        for index, frequency in enumerate(frequencies):
            count = frequency.get(word, 0)
            denominator = count + k1 * (1 - b + b * lengths[index] / average_length)
            if denominator:
                scores[index] += word_idf * count * (k1 + 1) / denominator
    return scores
