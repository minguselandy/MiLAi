from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.benchmark import dg11_retrieval
from scripts import dg11_state

DEFAULT_RUN = ROOT / "var/dg10/runs/lme-confirmation-20260823-003"
DEFAULT_DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
DEFAULT_MODEL = ROOT / "runtime/var/models/all-MiniLM-L6-v2"


class OnnxBatchEncoder:
    def __init__(self, model_path: Path) -> None:
        onnxruntime = importlib.import_module("onnxruntime")
        tokenizers = importlib.import_module("tokenizers")
        self.numpy = importlib.import_module("numpy")
        tokenizer_path = model_path / "tokenizer.json"
        model_file = model_path / "onnx/model.onnx"
        if not tokenizer_path.is_file() or not model_file.is_file():
            raise ValueError("local MiniLM ONNX model is incomplete")
        self.tokenizer = tokenizers.Tokenizer.from_file(str(tokenizer_path))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self.session = onnxruntime.InferenceSession(
            str(model_file), providers=["CPUExecutionProvider"]
        )
        self.batch_calls = 0

    def encode(self, texts: list[str], *, batch_size: int = 32) -> Any:
        rows: list[Any] = []
        for start in range(0, len(texts), batch_size):
            encodings = self.tokenizer.encode_batch(texts[start : start + batch_size])
            input_ids = self.numpy.asarray(
                [item.ids for item in encodings], dtype="int64"
            )
            attention = self.numpy.asarray(
                [item.attention_mask for item in encodings], dtype="int64"
            )
            token_types = self.numpy.asarray(
                [item.type_ids for item in encodings], dtype="int64"
            )
            hidden = self.session.run(
                ["last_hidden_state"],
                {
                    "input_ids": input_ids,
                    "attention_mask": attention,
                    "token_type_ids": token_types,
                },
            )[0]
            mask = attention.astype("float32")[:, :, None]
            pooled = (hidden * mask).sum(axis=1) / self.numpy.maximum(
                mask.sum(axis=1), 1.0
            )
            norms = self.numpy.linalg.norm(pooled, axis=1, keepdims=True)
            rows.append(pooled / self.numpy.maximum(norms, 1e-12))
            self.batch_calls += 1
        return self.numpy.concatenate(rows, axis=0)


def _selected_rows(dataset: Path, selected: set[str]) -> dict[str, dict[str, Any]]:
    source = json.loads(dataset.read_text(encoding="utf-8"))
    result = {
        str(row["question_id"]): row
        for row in source
        if isinstance(row, dict) and row.get("question_id") in selected
    }
    if set(result) != selected:
        raise ValueError("DEV source rows are incomplete")
    return result


def _scored_record(
    *,
    case_id: str,
    category: str,
    relevant: list[str],
    retrieval: dict[str, Any],
) -> dict[str, Any]:
    retrieved = [str(value) for value in retrieval["session_ids"]]
    overlap = set(relevant).intersection(retrieved)
    return {
        "case_id": case_id,
        "category": category,
        "relevant_session_count": len(relevant),
        "retrieved_session_ids": retrieved,
        "hit_at_3": int(bool(overlap)),
        "relevant_coverage_at_3": round(len(overlap) / len(relevant), 6),
        "retrieval": retrieval,
    }


def _frozen_a0(
    records: list[dict[str, Any]], rows: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    scored = []
    for record in records:
        source_id = str(record["case_id"]).removeprefix("longmemeval:")
        trace = record["milai_trace"]
        items = trace["retrieved_items"]
        scored.append(
            _scored_record(
                case_id=str(record["case_id"]),
                category=str(record["category"]),
                relevant=[
                    str(value) for value in rows[source_id]["answer_session_ids"]
                ],
                retrieval={
                    "session_ids": [
                        str(value) for value in record["retrieved_session_ids"]
                    ],
                    "items": items,
                    "score_margin_top1_top2": round(
                        float(items[0]["relevance_score"])
                        - float(items[1]["relevance_score"]),
                        8,
                    ),
                    "intents": sorted(
                        dg11_retrieval.classify_intent(str(record["question"]))
                    ),
                    "candidate_limit": None,
                    "recent_lane_enabled": any(
                        "recent" in item["matched_by"] for item in items
                    ),
                    "trace_source": "DG10_FROZEN_RUNTIME_RAW_RECORD",
                },
            )
        )
    summary = dg11_retrieval.summarize_records(scored)
    return {
        "configuration": "current session + 16d",
        "projection_identity": records[0]["milai_trace"]["embedding"],
        "summary": summary,
        "gates": dg11_retrieval.metric_gates(summary),
        "records": scored,
    }


def _window_variants(
    records: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    encoder: OnnxBatchEncoder,
) -> dict[str, dict[str, Any]]:
    accumulated: dict[str, list[dict[str, Any]]] = {"A1": [], "A2": [], "A3": []}
    dimensions = {"A1": 16, "A2": 128, "A3": 384}
    for record in records:
        source_id = str(record["case_id"]).removeprefix("longmemeval:")
        row = rows[source_id]
        documents = dg11_retrieval.build_window_documents(
            [str(value) for value in row["haystack_session_ids"]],
            row["haystack_sessions"],
            [str(value) for value in row["haystack_dates"]],
        )
        question = str(record["question"])
        source_vectors = encoder.encode(
            [question, *[document.text for document in documents]]
        )
        for arm, dimension in dimensions.items():
            projected = dg11_retrieval.project_source(
                source_vectors, dimension, numpy_module=encoder.numpy
            )
            vector_scores = projected[1:] @ projected[0]
            retrieval = dg11_retrieval.retrieve_parents(
                question, documents, vector_scores.tolist(), k=3
            )
            accumulated[arm].append(
                _scored_record(
                    case_id=str(record["case_id"]),
                    category=str(record["category"]),
                    relevant=[str(value) for value in row["answer_session_ids"]],
                    retrieval=retrieval,
                )
            )
    result: dict[str, dict[str, Any]] = {}
    for arm, records_for_arm in accumulated.items():
        summary = dg11_retrieval.summarize_records(records_for_arm)
        result[arm] = {
            "configuration": f"turn/window + {dimensions[arm]}d",
            "projection_identity": dg11_retrieval.projection_identity(
                dimensions[arm]
            ).as_dict(),
            "summary": summary,
            "gates": dg11_retrieval.metric_gates(summary),
            "records": records_for_arm,
        }
    return result


def run(
    run_id: str, source_run: Path, dataset: Path, model_path: Path
) -> dict[str, Any]:
    started = perf_counter()
    raw_path = source_run / "raw-records.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    records = [record for record in raw["records"] if record["arm"] == "MILAI_T3A"]
    if len(records) != 50:
        raise ValueError("retrieval matrix requires 50 frozen MiLAi DEV records")
    selected = {
        str(record["case_id"]).removeprefix("longmemeval:") for record in records
    }
    rows = _selected_rows(dataset, selected)
    encoder = OnnxBatchEncoder(model_path)
    variants = {"A0": _frozen_a0(records, rows)}
    variants.update(_window_variants(records, rows, encoder))
    winner = dg11_retrieval.choose_winner(
        {name: value for name, value in variants.items() if name != "A0"}
    )
    result = {
        "schema": "milai.dg11.retrieval-matrix.v1",
        "run_id": run_id,
        "work_package": "DG11-02",
        "status": "PASS" if winner is not None else "REVISE",
        "decision": f"IMPLEMENT_{winner}" if winner is not None else "REVISE_RETRIEVAL",
        "winner": winner,
        "source_run_id": raw["run_id"],
        "source_raw_sha256": dg11_state.sha256(raw_path),
        "dataset_sha256": dg11_state.sha256(dataset),
        "model_sha256": dg11_state.sha256(model_path / "onnx/model.onnx"),
        "tokenizer_sha256": dg11_state.sha256(model_path / "tokenizer.json"),
        "case_denominator": len(records),
        "variants": variants,
        "summary": {
            name: value["summary"]["overall"] for name, value in variants.items()
        },
        "answer_provider_requests": 0,
        "provider_requests": 0,
        "local_embedding_batch_calls": encoder.batch_calls,
        "development_ai_reviews": 0,
        "elapsed_ms": round((perf_counter() - started) * 1_000, 3),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.record_result(
        result,
        phase="RETRIEVAL_OFFLINE_READY" if winner is not None else "BASELINE_READY",
        work_package="DG11-02",
        state_status="IN_PROGRESS",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DG-11 offline retrieval matrix")
    parser.add_argument("--run-id", default="dg11-retrieval-offline-001")
    parser.add_argument("--source-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    result = run(
        args.run_id,
        args.source_run.resolve(),
        args.dataset.resolve(),
        args.model_path.resolve(),
    )
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "decision": result["decision"],
                "winner": result["winner"],
                "summary": result["summary"],
                "provider_requests": result["provider_requests"],
                "elapsed_ms": result["elapsed_ms"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
