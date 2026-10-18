"""Configure policies and charge local work to the existing Host budget."""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from milai_lab.harness.contextual_artifacts import RunBudget
from milai_lab.methods.laya_memory_policy import GenerativeMemoryPolicy, LayaMemoryPolicy
from milai_lab.methods.memory_control import FixedMemoryPolicy, MemoryPolicy, RulesMemoryPolicy
from milai_lab.providers.laya_local import NativeDecision


def memory_policy(
    config: dict[str, Any], budget: RunBudget, *,
    call: Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]],
    admit: Callable[[], None], record: Callable[[dict[str, Any]], None],
) -> MemoryPolicy:
    kind = config["policy"]
    if kind == "fixed":
        return FixedMemoryPolicy(config.get("reads", 4))
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
                budget.record_compute("dynamic_memory_laya_load", loading)
                record({"event": "memory_control_model_load", "checkpoint": config["checkpoint"],
                        "device": "cpu", **loading})
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
