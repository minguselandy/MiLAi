from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import time
from pathlib import Path
from typing import Any

from milai.adapters.embedding import (
    DeterministicHashEmbedding,
    EmbeddingProvider,
    OnnxSentenceTransformerEmbedding,
)


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        math.sqrt(sum(value * value for value in left))
        * math.sqrt(sum(value * value for value in right))
        or 1.0
    )


def evaluate(
    provider: EmbeddingProvider, fixtures: list[dict[str, Any]]
) -> dict[str, Any]:
    started = time.perf_counter()
    correct = 0
    durations_ms: list[float] = []
    failures = 0

    def measured_embed(text: str) -> list[float]:
        nonlocal failures
        call_started = time.perf_counter()
        try:
            return provider.embed(text)
        except Exception:
            failures += 1
            raise
        finally:
            durations_ms.append((time.perf_counter() - call_started) * 1000)

    for fixture in fixtures:
        query = measured_embed(str(fixture["query"]))
        scored = [
            (cosine(query, measured_embed(str(candidate))), index)
            for index, candidate in enumerate(fixture["candidates"])
        ]
        predicted = max(scored)[1]
        correct += predicted == int(fixture["relevant_index"])
    elapsed = time.perf_counter() - started
    warm = durations_ms[1:] or durations_ms
    return {
        "provider_identity": provider.identity.key,
        "cases": len(fixtures),
        "embedding_calls": len(durations_ms),
        "top1_accuracy": correct / len(fixtures),
        "elapsed_ms": round(elapsed * 1000, 3),
        "cold_start_ms": round(durations_ms[0], 3),
        "warm_latency_ms": {
            "p50": round(_percentile(warm, 0.50), 3),
            "p95": round(_percentile(warm, 0.95), 3),
            "p99": round(_percentile(warm, 0.99), 3),
        },
        "throughput_calls_per_second": round(len(durations_ms) / elapsed, 3),
        "failure_rate": failures / len(durations_ms),
        "external_model_cost_usd": 0,
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * quantile) - 1))
    return ordered[index]


def _device_manifest() -> dict[str, Any]:
    memory_bytes: int | None = None
    try:
        memory_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        pass
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "memory_bytes": memory_bytes,
        "accelerator": "CPU_ONLY",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixtures", type=Path, default=Path(__file__).with_name("fixtures.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--model-id", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--source-dimensions", type=int, default=384)
    args = parser.parse_args()
    fixture_bytes = args.fixtures.read_bytes()
    fixtures = json.loads(fixture_bytes)
    result: dict[str, Any] = {
        "benchmark_format": "milai-embedding-quality-v2",
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "workload": {
            "concurrency": 1,
            "state": "cold-first-call-then-warm",
            "database_rows": 0,
            "index_bytes": 0,
            "projection_lag": "NOT_APPLICABLE_ISOLATED_PROVIDER",
        },
        "device": _device_manifest(),
        "gate": "NOT_PROMOTED_WITHOUT_REAL_PROVIDER_RESULT",
        "baseline": evaluate(DeterministicHashEmbedding(), fixtures),
        "required_gain": {"top1_accuracy_absolute": 0.1},
    }
    if args.model_path is not None:
        real = evaluate(
            OnnxSentenceTransformerEmbedding(
                args.model_path,
                model_id=args.model_id,
                source_dimensions=args.source_dimensions,
            ),
            fixtures,
        )
        result["real_provider"] = real
        gain = real["top1_accuracy"] - result["baseline"]["top1_accuracy"]
        result["observed_gain"] = gain
        result["gate"] = "PASS" if gain >= 0.1 else "NOT_PROMOTED_QUALITY_GATE_FAILED"
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
