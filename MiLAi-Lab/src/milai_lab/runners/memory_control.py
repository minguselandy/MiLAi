"""Configure policies and charge local work to the existing Host budget."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from milai_lab.harness.contextual_artifacts import RunBudget
from milai_lab.memory.retrieval import SemanticRetriever
from milai_lab.methods.evidence_reading import project_pack
from milai_lab.methods.laya_memory_policy import GenerativeMemoryPolicy, LayaMemoryPolicy
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    FixedMemoryPolicy,
    MemoryPolicy,
    RulesMemoryPolicy,
)
from milai_lab.providers.laya_local import NativeDecision


def dense_control_pool(
    query: str, materials: list[dict[str, Any]], *, retriever: SemanticRetriever,
    record: Callable[[dict[str, Any]], None],
) -> list[dict[str, Any]]:
    """Rank full actual packs with the existing metered embedder, retaining bound indices."""
    rows = [{"id": str(i), "value": {"content": json.dumps(
        {k: v for k, v in project_pack(item, i).items() if k != "label"},
        ensure_ascii=False)}} for i, item in enumerate(materials)]
    ranked = retriever.rank(query, rows, len(rows), include_scores=True)
    record({"event": "memory_control_dense_pool", "ranking": [
        {"pool_index": int(r["id"]), "score": r["dense_score"]} for r in ranked],
        "body_count": len(rows), "embedding_cost": "original metered embedding client"})
    ranks = {int(r["id"]): (position, r["dense_score"]) for position, r in enumerate(ranked)}
    return [{**item, "control_pool_rank": ranks[i][0], "control_dense_score": ranks[i][1]}
            for i, item in enumerate(materials)]


def memory_policy(
    config: dict[str, Any], budget: RunBudget, *,
    call: Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]],
    admit: Callable[[], None], record: Callable[[dict[str, Any]], None],
) -> MemoryPolicy:
    kind = config["policy"]
    if kind == "fixed":
        return FixedMemoryPolicy(config.get("reads", 4))
    if kind == "fixed_context":
        return FixedContextMemoryPolicy(config.get("reads", 4))
    if kind == "rules":
        return RulesMemoryPolicy(config.get("reads", 4))
    if kind == "generative":
        return GenerativeMemoryPolicy(call)
    if kind != "laya":
        raise ValueError(f"Unknown memory control policy: {kind}")
    model: NativeDecision | None = None

    def predict(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal model
        admit()
        if model is None:
            import torch  # type: ignore[import-not-found]

            torch.set_num_threads(config.get("threads", 4))
            started, cpu = time.perf_counter(), time.process_time()
            try:
                model = NativeDecision(Path(config["checkpoint"]), config.get("max_len", 8192),
                                       config.get("head_max_len", 2048))
            finally:
                loading = {"wall_seconds": time.perf_counter() - started,
                           "cpu_seconds": time.process_time() - cpu, "loads": 1}
                record({"event": "memory_control_model_load", "checkpoint": config["checkpoint"],
                        "device": "cpu", "loaded": model is not None, **loading})
                budget.record_compute("dynamic_memory_laya_load", loading)
        started, cpu = time.perf_counter(), time.process_time()
        before = dict(model.counters)
        try:
            result = model.predict(payload)
            record({"event": "memory_control_model_result", "input": payload, "result": result})
            return result
        finally:
            budget.record_compute("dynamic_memory_laya", {
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu,
                **{k: v - before[k] for k, v in model.counters.items()}})

    return LayaMemoryPolicy(predict)
