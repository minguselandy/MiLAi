"""Common shuffled pools with honest BM25 and same-pool dense controls.

Preparation uses explicitly supplied split files. Dense selection reads the answer-free
case file and uses the existing metered embedding provider and original ledger.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def prepare(decisions: Path, source_records: Path, budget_path: Path,
            output: Path, scope: str) -> None:
    from prepare_musique_decisions import ranked_pool

    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    states = read_rows(decisions)
    initial = {r["metadata"]["row"]: r for r in states if not r["state"]["read_evidence"]}
    sources = {
        r["metadata"]["row"]: r["source"]
        for r in read_rows(source_records)
    }
    cases, labels, costs = [], [], []
    for index, row in sorted(initial.items()):
        source, meta = sources[index], row["metadata"]
        candidates = row["state"]["candidates"]
        case_id = f"row-{index}"
        mapping = dict(zip((p["id"] for p in candidates), meta["pool_source_indices"], strict=True))
        before, before_cpu = time.perf_counter(), time.process_time()
        lexical = ranked_pool(
            {
                "question": source["question"],
                "paragraphs": [
                    {k: p[k] for k in ("title", "paragraph_text")} for p in source["paragraphs"]
                ],
            },
            len(source["paragraphs"]),
        )
        costs.append(
            {
                "case_id": case_id,
                "wall_seconds": time.perf_counter() - before,
                "cpu_seconds": time.process_time() - before_cpu,
                "source_paragraphs": len(source["paragraphs"]),
                "selected": len(candidates),
            }
        )
        if lexical != meta["bm25_source_indices"]:
            raise ValueError("Lexical control differs from the frozen question-only ranking")
        lexical_ids = [next(alias for alias, idx in mapping.items() if idx == i) for i in lexical]
        for policy, count in (("k2", 2), ("k4", 4), ("full_pool", len(candidates)),
                              (f"k{len(candidates)}", len(candidates))):
            write_json(
                output / "selections/bm25" / case_id / f"{policy}.json",
                {
                    "case_id": case_id,
                    "selected_ids": lexical_ids[:count],
                    "policy": policy,
                    "stop_reason": "fixed_k",
                    "decision_calls": 0,
                    "ranking_scope": "BM25 order mapped to shared shuffled candidate IDs",
                },
            )
        cases.append({"case_id": case_id, "question": source["question"], "candidates": candidates})
        labels.append(
            {
                "case_id": case_id,
                "family": meta["family"],
                "source_row": index,
                "source": {**source, "answer_aliases": source.get("answer_aliases", [])},
                "candidate_source_indices": mapping,
                "dataset": meta.get("dataset", "musique"),
            }
        )
    for name, rows in (("cases", cases), ("labels", labels)):
        (output / f"{name}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        )
    write_json(output / "common-retrieval-costs.json", costs)
    measures = {
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "preparations": 1,
        "cases": len(cases),
    }
    write_json(
        output / "preparation.json",
        {
            **measures,
            "families": len({r["family"] for r in labels}),
            "source_semantics_not_in_runtime": True,
            "exact_exported_empty_payloads": True,
            "reference_state_input": str(decisions.resolve()),
            "source_record_input": str(source_records.resolve()),
            "new_model_calls": 0,
            "scope": scope,
        },
    )
    with budget_path.with_name("budget.json.http-owner.lock").open("a+b") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        budget = RunBudget(RunLimits(**read_json(budget_path)["limits"]), budget_path)
        budget.record_compute("global_reader_qa_v1_preparation", measures)


def dense(protocol_path: Path, output: Path) -> None:
    from milai_lab.runners.edit_benchmarks import BenchmarkRun

    protocol = read_json(protocol_path)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    cases = read_rows(Path(protocol["cases"]))
    inputs = {
        case["case_id"]: [
            case["question"],
            *[p["title"] + "\n" + p["text"] for p in case["candidates"]],
        ]
        for case in cases
    }
    texts = list(dict.fromkeys(text for values in inputs.values() for text in values))
    write_json(output / "embedding-inputs.json", texts)
    settings = {
        **protocol["reader"],
        **protocol["dense_embedding"],
        "experiment_name": protocol["name"] + "-dense",
    }
    execution = BenchmarkRun(settings, output)
    run: dict[str, Any] = {
        "status": "RUNNING",
        "pid": os.getpid(),
        "planned_cases": len(cases),
        "unique_embedding_inputs": len(texts),
        "completed_cases": 0,
        "new_generation_calls": 0,
        "automatic_retry": False,
    }
    write_json(output / "run.json", run)
    try:
        embedder = execution.retrieval_embeddings
        assert embedder is not None
        tokens = embedder.capacity.check(texts)
        vectors = embedder.embed_documents(texts)
        write_json(output / "embedding-vectors.json", vectors)
        by_text = dict(zip(texts, vectors, strict=True))
        token_by_text = dict(zip(texts, tokens, strict=True))
        for case in cases:
            query, *documents = inputs[case["case_id"]]
            query_vector = by_text[query]
            scores = [
                sum(a * b for a, b in zip(query_vector, by_text[text], strict=True))
                for text in documents
            ]
            ranked = sorted(range(len(documents)), key=lambda i: (-scores[i], i))
            write_json(
                output / case["case_id"] / "k4.json",
                {
                    "case_id": case["case_id"],
                    "policy": "k4",
                    "stop_reason": "fixed_k",
                    "selected_ids": [case["candidates"][i]["id"] for i in ranked[:4]],
                    "scores": {
                        p["id"]: score for p, score in zip(case["candidates"], scores, strict=True)
                    },
                    "decision_calls": 0,
                    "embedding_tokens_if_no_cross_case_reuse": sum(
                        token_by_text[t] for t in inputs[case["case_id"]]
                    ),
                    "ranking_scope": "Normalized BGE-M3 dot product; ties by candidate position",
                },
            )
            run["completed_cases"] += 1
            write_json(output / "run.json", run)
        run.update(status="COMPLETED", actual_embedding_input_tokens_with_specials=sum(tokens))
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        measures: dict[str, int | float] = {
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "runs": 1,
            "completed_cases": run["completed_cases"],
        }
        execution.budget.record_compute(
            protocol.get("dense_compute_phase", "global_reader_dense_control_v1"), measures)
        execution.close()
        write_json(
            output / "compute.json",
            {
                **measures,
                "embedding_http_receipts": str(output / "http/embedding"),
                "scope": "Actual unique text embeddings across the cohort plus ranking. "
                "Do not multiply shared batch/index costs by question or policy count.",
            },
        )
        write_json(output / "run.json", run)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("decisions", type=Path)
    prep.add_argument("sources", type=Path)
    prep.add_argument("output", type=Path)
    prep.add_argument("--budget", type=Path, required=True)
    prep.add_argument("--scope", required=True)
    select = sub.add_parser("dense")
    select.add_argument("protocol", type=Path)
    select.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare(args.decisions, args.sources, args.budget, args.output, args.scope)
    else:
        dense(args.protocol, args.output)


if __name__ == "__main__":
    main()
