"""Read completed raw-source scale runs, original first labels and exact costs."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from summarize_innovation_structure_delivery import costs, ledger_delta, read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--author-review", type=Path, required=True)
    args = parser.parse_args()
    driver = read(args.run / "driver.json")
    assert driver["status"] == "COMPLETED"
    sizes = {}
    for size in (100, 1000, 5000):
        root = args.run / str(size) / "MiLAi-memory-only"
        official = read(root / "halumem-official-results.json")["question_answering_records"]
        labels = {
            (r["ssession_id"], r["question"]): r.get("result_type") or "invalid" for r in official
        }
        rows = []
        for session in (size - 1, size, size + 1):
            for index in range(16 if session == size - 1 else 4):
                key = f"halumem/innovation-scale-aster-{size}/{session}/qa/{index}"
                prediction = read(root / "predictions" / key / "complete.json")
                view = read(root / "http" / key / "memory-view.json")
                native = read(root / "native" / key / "retrieval.json")
                request = read(root / "http" / key / "view/pack-0/request.json")
                receipts = [
                    read(p)["usage"]
                    for p in (root / "http" / key).rglob("response.json")
                    if "judge" not in p.relative_to(root / "http" / key).parts
                ]
                row = {
                    "session": session,
                    "question_index": index,
                    "question": prediction["question"],
                    "answer": prediction["hypothesis"],
                    "first_label": labels[session, prediction["question"]],
                    "reader_calls": len(receipts),
                    "reading_tokens": sum(u["total_tokens"] for u in receipts),
                    "first_input_tokens": request["prompt_tokens"],
                    "opened_indices": view["opened_indices"],
                    "source_retrieval": native["native_return"]["source_retrieval"],
                    "first_input_contains_orientation_completion": (
                        "Mira has completed orientation" in json.dumps(request["messages"])
                    ),
                }
                rows.append(row)
        stages = costs(root)
        sizes[str(size)] = {
            "initial_sources": size,
            "total_sources": size + 2,
            "terminal_predict": read(root / "terminal-predict.json"),
            "terminal_score": read(root / "terminal-score.json")["status"],
            "first_labels": dict(Counter(row["first_label"] for row in rows)),
            "stages": stages,
            "prediction_tokens": sum(v["total_tokens"] for k, v in stages.items() if k != "judge"),
            "reuse_prefixes_before_updates": {
                str(n): {
                    "queries": n,
                    "reading_tokens": sum(r["reading_tokens"] for r in rows[:n]),
                    "construction_model_tokens": 0,
                }
                for n in (1, 4, 16)
            },
            "source_retrieval_seconds": sum(
                r["source_retrieval"]["timings"]["total_seconds"] for r in rows
            ),
            "queries": rows,
        }
    ledger = ledger_delta(args.run)
    total_tokens = sum(
        s["total_tokens"] for size in sizes.values() for s in size["stages"].values()
    )
    responses = sum(s["responses"] for size in sizes.values() for s in size["stages"].values())
    result = {
        "status": "COMPLETED",
        "source_version": driver["source_version"],
        "independent_target_scenarios": 1,
        "scope": "One Aster target history with different amounts of unrelated depot history. "
        "Same frozen implementation across all sizes. Not three independent histories, "
        "not an external benchmark, and not a learned selector result.",
        "sizes": sizes,
        "ledger_delta": ledger,
        "receipt_minus_ledger_tokens": total_tokens - ledger["generation"]["known_tokens"],
        "response_minus_generation_requests": responses - ledger["generation_requests"],
        "cli_stage_wall_seconds": {
            f"{s['phase']}/{s['size']}": s["finished_at"] - s["started_at"] for s in driver["steps"]
        },
        "latency_limit": "Shared machine; CPU training overlaps the later scale run. Whole CLI "
        "time includes capture, database, serialization/tokenization, generation "
        "and IO. Frozen version predates the later Source-identity lookup fix. "
        "No exclusive-GPU speed or asymptotic claim.",
        "author_review": read(args.author_review),
        "decision": "Raw retrieval remains a strong simple control. Larger distractor pools "
        "do not by themselves demonstrate structural-memory benefit. Observed "
        "failures distinguish stopping before an available complementary Source "
        "from failure to use already delivered facts; value learning must test both.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "sizes": {
                    k: {
                        f: v[f]
                        for f in (
                            "first_labels",
                            "prediction_tokens",
                            "reuse_prefixes_before_updates",
                        )
                    }
                    for k, v in sizes.items()
                },
                "ledger": ledger,
                "receipt_difference": result["receipt_minus_ledger_tokens"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
