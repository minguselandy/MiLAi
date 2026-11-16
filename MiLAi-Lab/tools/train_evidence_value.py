"""Fit independent and conditional lexical controls on reviewed subset outcomes.

Both fit the same labels. Per-query weighting prevents alias/subset multiplicity
from giving a question more total weight. Reports are training-fit diagnostics,
never held-out results or actual selector/Reader evaluations.
"""

from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter
from pathlib import Path

import numpy as np

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.learned_evidence_value import LearnedValue, ValueFeatures, ridge_fit


def training_examples(prepared):
    examples = {"immediate": [], "two_open": [], "answer_return": []}
    for data in prepared:
        qid = data["question_id"]
        for edge in data["transitions"]:
            for head, key in (
                ("immediate", "observed_gain"),
                ("two_open", "observed_two_open_return_gain"),
            ):
                if edge[key] is not None:
                    examples[head].append(
                        {
                            "question_id": qid,
                            "example_id": (
                                f"{qid}:{edge['before_condition']}->{edge['after_condition']}"
                            ),
                            "input": edge["model_input"],
                            "target": float(edge[key]),
                        }
                    )
        for state in data["states"]:
            if state["observed_return"] is not None:
                examples["answer_return"].append(
                    {
                        "question_id": qid,
                        "example_id": f"{qid}:{state['condition']}",
                        "input": state["model_input"],
                        "target": float(state["observed_return"]),
                    }
                )
    return examples


def fit(examples, *, regularization, max_vocabulary):
    features = ValueFeatures.fit(
        (row["input"] for rows in examples.values() for row in rows), max_vocabulary=max_vocabulary
    )
    models, diagnostics = {}, {}
    for name, conditional in (("independent", False), ("conditional", True)):
        started, cpu_started = time.perf_counter(), time.process_time()
        heads, observations = {}, {}
        for head, rows in examples.items():
            matrix = np.stack(
                [features.encode(row["input"], conditional=conditional) for row in rows]
            )
            targets = np.asarray([row["target"] for row in rows])
            counts = Counter(row["question_id"] for row in rows)
            weights = np.asarray([1 / counts[row["question_id"]] for row in rows])
            weights *= len(rows) / weights.sum()
            root_weight = np.sqrt(weights)
            heads[head] = ridge_fit(
                matrix * root_weight[:, None], targets * root_weight, regularization
            )
            predictions = matrix @ heads[head]
            observations[head] = {
                "examples": len(rows),
                "questions": len(counts),
                "weighted_training_mse": float(
                    np.average((predictions - targets) ** 2, weights=weights)
                ),
                "weighted_zero_predictor_mse": float(np.average(targets**2, weights=weights)),
                "weight_l2": float(np.linalg.norm(heads[head])),
                "predictions": [
                    {
                        "example_id": row["example_id"],
                        "target": row["target"],
                        "prediction": float(prediction),
                    }
                    for row, prediction in zip(rows, predictions, strict=True)
                ],
            }
        models[name] = LearnedValue(features, conditional, heads)
        diagnostics[name] = {
            "heads": observations,
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu_started,
            "fitted_coefficients": sum(len(v) for v in heads.values()),
        }
    return models, diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--regularization", type=float, default=0.1)
    parser.add_argument("--max-vocabulary", type=int, default=2048)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    started, cpu_started = time.perf_counter(), time.process_time()
    prepared = [read_json(path) for path in args.inputs]
    examples = training_examples(prepared)
    models, diagnostics = fit(
        examples, regularization=args.regularization, max_vocabulary=args.max_vocabulary
    )
    for name, model in models.items():
        write_json(args.output / f"{name}.json", model.to_json())
    result = {
        "status": "COMPLETED_TRAINING_FIT_ONLY",
        "source_version": args.source_version,
        "input_artifacts": [str(p) for p in args.inputs],
        "question_ids": [d["question_id"] for d in prepared],
        "regularization": args.regularization,
        "vocabulary_size": len(models["conditional"].features.vocabulary),
        "label_policy": "Only non-null reviewed labels. Equal total weight per question per head; "
        "aliases and multiple subsets are dependent, not independent samples.",
        "input_policy": "Explicit lexical vocabulary fitted to training inputs; question/date, "
        "delivered content/report times and ordinary candidate excerpt/date. "
        "No condition names, item IDs, gold answers or review/outcome labels.",
        "matching": "Identical labels, vocabulary, dimensions, fitting method and regularization; "
        "independent arm masks state features after common input construction.",
        "diagnostics": diagnostics,
        "model_http_calls": 0,
        "source_mutations": 0,
        "linear_head_fits": 6,
        "numpy_version": np.__version__,
        "total_wall_seconds": time.perf_counter() - started,
        "total_cpu_seconds": time.process_time() - cpu_started,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "scope": "Small lexical control on exposed development outcomes. Training fit does not "
        "establish semantic generalization, calibrated utility, valid stopping, "
        "or an actual selected-subset quality/cost improvement.",
    }
    write_json(args.output / "training.json", result)
    print(
        json.dumps(
            {
                name: {head: d["weighted_training_mse"] for head, d in arm["heads"].items()}
                for name, arm in diagnostics.items()
            }
        )
    )


if __name__ == "__main__":
    main()
