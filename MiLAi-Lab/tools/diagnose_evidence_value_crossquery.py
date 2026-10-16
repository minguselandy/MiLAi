"""Leave one exposed development question out of feature fitting and training.

Evaluates observed-return prediction on nominated subsets, not actual selection
from a full pool. The held-out fold is not a globally unseen benchmark split.
"""

from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

import numpy as np

from milai_lab.harness.artifact_io import read_json, write_json
from train_evidence_value import fit, training_examples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--regularization", type=float, default=0.1)
    parser.add_argument("--max-vocabulary", type=int, default=2048)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    started, cpu_started = time.perf_counter(), time.process_time()
    data = [read_json(path) for path in args.inputs]
    folds = []
    for held_out in data:
        training = [d for d in data if d["question_id"] != held_out["question_id"]]
        models, fit_diagnostics = fit(
            training_examples(training),
            regularization=args.regularization,
            max_vocabulary=args.max_vocabulary,
        )
        evaluation = training_examples([held_out])
        scores = {}
        for arm, model in models.items():
            write_json(args.output / held_out["question_id"] / f"{arm}.json", model.to_json())
            scores[arm] = {}
            for head, rows in evaluation.items():
                predictions = [model.predict(row["input"])[head] for row in rows]
                scores[arm][head] = {
                    "examples": len(rows),
                    "mse": float(
                        np.mean(
                            [
                                (prediction - row["target"]) ** 2
                                for row, prediction in zip(rows, predictions, strict=True)
                            ]
                        )
                    ),
                    "predictions": [
                        {
                            "example_id": row["example_id"],
                            "target": row["target"],
                            "prediction": prediction,
                        }
                        for row, prediction in zip(rows, predictions, strict=True)
                    ],
                }
        folds.append(
            {
                "excluded_question_id": held_out["question_id"],
                "training_question_ids": [d["question_id"] for d in training],
                "vocabulary_size": len(models["conditional"].features.vocabulary),
                "training": fit_diagnostics,
                "evaluation": scores,
            }
        )
    mean_mse = {
        arm: {
            head: float(np.mean([fold["evaluation"][arm][head]["mse"] for fold in folds]))
            for head in ("immediate", "two_open", "answer_return")
        }
        for arm in ("independent", "conditional")
    }
    result = {
        "status": "COMPLETED_EXPOSED_CROSS_QUERY_DIAGNOSTIC",
        "source_version": args.source_version,
        "regularization": args.regularization,
        "inputs": [str(p) for p in args.inputs],
        "folds": folds,
        "per_question_mean_mse": mean_mse,
        "model_http_calls": 0,
        "source_mutations": 0,
        "linear_head_fits": 6 * len(folds),
        "numpy_version": np.__version__,
        "total_wall_seconds": time.perf_counter() - started,
        "total_cpu_seconds": time.process_time() - cpu_started,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "scope": "Vocabulary and all coefficient heads fit only other questions within each "
        "fold. Questions were already exposed in development; these are dependent "
        "nominated-subset outcomes, not selected-pool task accuracy or formal holdout. "
        "Raw uncalibrated scores are evaluated without clipping or retuning.",
    }
    write_json(args.output / "results.json", result)
    print(json.dumps(mean_mse))


if __name__ == "__main__":
    main()
