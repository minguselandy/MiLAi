"""Adapter to the upstream standalone MemPursuit selector, not its Mem0 pipeline."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from langchain_core.embeddings import Embeddings

from milai_lab.harness.contextual_artifacts import RunBudget
from milai_lab.methods.evidence_reading import project_pack


class MemPursuitPool:
    """Embed actual complete candidates and retain their original indices/availability."""

    def __init__(self, embeddings: Embeddings, budget: RunBudget, *, selected_limit: int,
                 adaptive: bool, record: Callable[[dict[str, Any]], None]) -> None:
        self.embeddings, self.budget, self.record = embeddings, budget, record
        self.selected_limit, self.adaptive = selected_limit, adaptive
        self.vectors: dict[str, list[float]] = {}

    def __call__(self, query: str, materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not materials:
            return []
        from mempursuit import select

        started, cpu = time.perf_counter(), time.process_time()
        texts = [json.dumps({key: value for key, value in project_pack(item, i).items()
                            if key != "label"}, ensure_ascii=False)
                 for i, item in enumerate(materials)]
        missing = list(dict.fromkeys(text for text in texts if text not in self.vectors))
        try:
            if missing:
                self.vectors.update(zip(missing, self.embeddings.embed_documents(missing),
                                        strict=True))
            result = select(self.embeddings.embed_query(query),
                [self.vectors[text] for text in texts], min(self.selected_limit, len(materials)),
                adaptive=self.adaptive, backend="numpy")
            selected = result.selected_indices.tolist()
            ranks = {index: rank for rank, index in enumerate(selected)}
            self.record({"event": "memory_control_mempursuit_pool", "query": query,
                "candidate_texts": texts, "selected_indices": selected,
                "weights": result.weights.tolist(), "stop_reason": result.stop_reason,
                "steps": [{"candidate_index": s.candidate_index,
                           "squared_error": s.squared_error,
                           "relative_improvement": s.relative_improvement} for s in result.steps],
                "scope": "Original candidate pool; upstream NumPy selection/refit. "
                         "Embeddings and acquisition costs are charged separately from quality."})
            return [{**item, "control_pool_selected": i in ranks,
                     "control_pool_rank": ranks.get(i, len(selected) + i)}
                    for i, item in enumerate(materials)]
        finally:
            self.budget.record_compute("memory_control_mempursuit_pool", {
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu, "pools": 1,
                "candidates": len(materials), "candidate_embedding_cache_misses": len(missing)})
