"""Frozen LongMemEval flat-Contriever context worker."""

from __future__ import annotations

import argparse
import importlib
import json
import platform
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from tokenizers import Tokenizer

from evals.paper.adapters import DenseAdapter
from evals.paper.contracts import ContextRecord, write_context_archive
from evals.paper.datasets.longmemeval import load_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file
from evals.paper.parallelism import DENSE_CONTEXT_PROCESS_LANE
from evals.paper.runners.longmemeval import (
    memory_events,
    require_unfrozen_smoke_inputs,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
CONTRIEVER_SNAPSHOT = Path(
    "/root/.cache/huggingface/hub/models--facebook--contriever/"
    "snapshots/2bd46a25019aeea091fd42d1f0fd4801675cf699"
)
MODEL_ID = "facebook/contriever@2bd46a25019aeea091fd42d1f0fd4801675cf699"
EXPECTED_WEIGHTS_SHA256 = (
    "d0b6e2516913f812360475154323f50e2b1e1da0ce6a435175e08f218784c6fb"
)
EXPECTED_TOKENIZER_SHA256 = (
    "5fd1c882abbd30517dced455a2c9768945ec726b96727927e4959348d9de550b"
)
EXPECTED_TRANSFORMERS = "4.43.3"
EXPECTED_TORCH = "2.7.0+cu126"


class ContrieverContextError(RuntimeError):
    pass


def _select_shard(cases: tuple[Any, ...], *, index: int, count: int) -> tuple[Any, ...]:
    DENSE_CONTEXT_PROCESS_LANE.validate(count)
    if not 0 <= index < count:
        raise ContrieverContextError(
            "Contriever shard index is outside the shard count"
        )
    return tuple(case for ordinal, case in enumerate(cases) if ordinal % count == index)


class FrozenContrieverEmbedder:
    """Faithful official mean-pooling and raw-dot-product embedding worker."""

    def __init__(self, *, device: str, batch_size: int = 128) -> None:
        if batch_size != 128:
            raise ContrieverContextError(
                "official Contriever batch size must remain 128"
            )
        weights = CONTRIEVER_SNAPSHOT / "pytorch_model.bin"
        tokenizer_json = CONTRIEVER_SNAPSHOT / "tokenizer.json"
        if (
            sha256_file(weights) != EXPECTED_WEIGHTS_SHA256
            or sha256_file(tokenizer_json) != EXPECTED_TOKENIZER_SHA256
        ):
            raise ContrieverContextError("Contriever snapshot identity drifted")
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
        if (
            str(torch.__version__) != EXPECTED_TORCH
            or str(transformers.__version__) != EXPECTED_TRANSFORMERS
        ):
            raise ContrieverContextError(
                "Contriever runtime must use the preregistered Torch/Transformers pair"
            )
        if not bool(torch.cuda.is_available()):
            raise ContrieverContextError("Contriever requires the frozen CUDA runtime")
        self._torch: Any = torch
        self._device = device
        self._batch_size = batch_size
        self._tokenizer: Any = transformers.AutoTokenizer.from_pretrained(
            str(CONTRIEVER_SNAPSHOT), local_files_only=True
        )
        self._model: Any = transformers.AutoModel.from_pretrained(
            str(CONTRIEVER_SNAPSHOT), local_files_only=True
        ).to(device)
        self._model.eval()
        self.embedding_calls = 0
        self.embedding_items = 0

    def _batch(self, values: Sequence[str]) -> np.ndarray:
        inputs = self._tokenizer(
            list(values), padding=True, truncation=True, return_tensors="pt"
        )
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with self._torch.no_grad():
            token_embeddings = self._model(**inputs)[0]
            mask = inputs["attention_mask"]
            token_embeddings = token_embeddings.masked_fill(
                ~mask[..., None].bool(), 0.0
            )
            pooled = token_embeddings.sum(dim=1) / mask.sum(dim=1)[..., None]
        return np.asarray(pooled.detach().cpu(), dtype=np.float32)

    def __call__(self, values: Sequence[str]) -> np.ndarray:
        if not values or any(not isinstance(value, str) for value in values):
            raise ContrieverContextError("Contriever received an invalid text batch")
        # The official implementation embeds the query alone, then documents in
        # batches of 128. Preserve that padding boundary exactly.
        vectors = [self._batch(values[:1])]
        documents = values[1:]
        for offset in range(0, len(documents), self._batch_size):
            vectors.append(self._batch(documents[offset : offset + self._batch_size]))
        self.embedding_calls += 1 + (
            (len(documents) + self._batch_size - 1) // self._batch_size
        )
        self.embedding_items += len(values)
        return np.concatenate(vectors, axis=0)

    def identity(self) -> dict[str, Any]:
        return {
            "batch_size": self._batch_size,
            "device": self._device,
            "model_id": MODEL_ID,
            "pooling": "attention-mask-mean",
            "python": platform.python_version(),
            "similarity": "unnormalized-dot-product",
            "tokenizer_sha256": EXPECTED_TOKENIZER_SHA256,
            "torch": EXPECTED_TORCH,
            "transformers": EXPECTED_TRANSFORMERS,
            "weights_sha256": EXPECTED_WEIGHTS_SHA256,
        }


def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    token_budget: int,
    tokenizer_path: Path,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
    device: str,
    shard_index: int = 0,
    shard_count: int = 1,
) -> dict[str, Any]:
    if device not in {"cuda:2", "cuda:3"}:
        raise ContrieverContextError(
            "Contriever worker is restricted to isolated GPU 2/3"
        )
    DENSE_CONTEXT_PROCESS_LANE.validate(shard_count)
    if shard_count == 2 and device != f"cuda:{2 + shard_index}":
        raise ContrieverContextError(
            "two-way Contriever shards must bind shard 0/1 to cuda:2/3"
        )
    if allow_unfrozen_smoke:
        require_unfrozen_smoke_inputs(input_path)
    else:
        require_paper_evaluation_ready(freeze_manifest)
    partition, all_cases = load_inputs(input_path)
    cases = _select_shard(all_cases, index=shard_index, count=shard_count)
    answer_tokenizer = Tokenizer.from_file(str(tokenizer_path))
    token_counter = lambda text: len(answer_tokenizer.encode(text).ids)
    embedder = FrozenContrieverEmbedder(device=device)
    records: list[ContextRecord] = []
    for case in cases:
        calls_before = embedder.embedding_calls
        items_before = embedder.embedding_items
        adapter = DenseAdapter(
            embedder,
            granularity="session",
            top_k=3,
            token_counter=token_counter,
            model_id=MODEL_ID,
        )
        adapter.reset(run_id, case.source_id)
        try:
            for event in memory_events(case):
                adapter.ingest(event)
            adapter.finalize()
            result = adapter.query(
                case.question, case.question_at, token_budget, "CONTROLLED"
            )
            stats = adapter.stats()
            records.append(
                ContextRecord(
                    case_id=case.source_id,
                    method_id="LME-DENSE",
                    track="CONTROLLED",
                    context=result.context,
                    source_ids=result.source_ids,
                    trace=result.trace,
                    declared_tokens=result.declared_tokens,
                    latency_ms=result.latency_ms,
                    usage={
                        **dict(result.usage),
                        "adapter_storage_bytes": stats.storage_bytes,
                        "embedding_calls": embedder.embedding_calls - calls_before,
                        "embedding_items": embedder.embedding_items - items_before,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001 - every case keeps a terminal record
            records.append(
                ContextRecord(
                    case_id=case.source_id,
                    method_id="LME-DENSE",
                    track="CONTROLLED",
                    context="",
                    source_ids=(),
                    trace=(),
                    declared_tokens=0,
                    latency_ms=0.0,
                    usage={
                        "embedding_calls": embedder.embedding_calls - calls_before,
                        "embedding_items": embedder.embedding_items - items_before,
                        "failure_class": type(exc).__name__,
                        "retriever_calls": 1,
                    },
                    terminal_status="INFRASTRUCTURE_FAILURE",
                )
            )
        finally:
            adapter.close()
    failures = sum(record.terminal_status != "SUCCEEDED" for record in records)
    identity = embedder.identity()
    return write_context_archive(
        output,
        run_id=run_id,
        benchmark_id=partition,
        records=records,
        metadata={
            "embedder_identity": identity,
            "embedding_calls": embedder.embedding_calls,
            "embedding_items": embedder.embedding_items,
            "failure_count": failures,
            "labels_accessed": False,
            "paper_labels_opened": False,
            "process_shard_count": shard_count,
            "process_shard_index": shard_index,
            "status": "PASS" if failures == 0 else "FAIL",
            "worker_count": 1,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--token-budget", type=int, default=512)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    parser.add_argument("--device", default="cuda:2")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1, choices=(1, 2))
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        input_path=args.inputs.resolve(),
        output=args.output.resolve(),
        token_budget=args.token_budget,
        tokenizer_path=args.tokenizer.resolve(),
        freeze_manifest=args.freeze_manifest.resolve(),
        allow_unfrozen_smoke=args.allow_unfrozen_smoke,
        device=args.device,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
    )
    print(
        json.dumps(
            {
                "failure_count": result["failure_count"],
                "record_count": result["record_count"],
                "run_id": result["run_id"],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
