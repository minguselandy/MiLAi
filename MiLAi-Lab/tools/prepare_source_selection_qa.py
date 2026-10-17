"""Materialize the frozen mixed-corpus fixed4 QA matrix without model calls."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from build_source_selection_states import derive, write_rows
from global_reader_controls import prepare
from milai_lab.harness.artifact_io import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("training_protocol", type=Path)
    parser.add_argument("prior_qa_protocol", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    lab = Path.cwd()
    source = lab / "artifacts/jev-reader/selection-v2"
    training = read_json(args.training_protocol)
    prior = read_json(args.prior_qa_protocol)
    root = args.output.absolute()
    root.mkdir(parents=True, exist_ok=False)
    models: list[dict[str, Any]] = []
    for condition in training["conditions"]:
        for seed in training["seeds"]:
            models.append({"name": f"{condition}_seed{seed}", "condition": condition,
                "seed": seed, "checkpoint": str(source / "training-v1/runs" / condition
                                                  / str(seed) / "checkpoint"),
                "selection_only": True, "probe": True})
    models.append({"name": "base_zero", "checkpoint": training["base_checkpoint"],
                   "selection_only": True, "probe": False})
    for seed in training["seeds"]:
        models.append({"name": f"prior128_seed{seed}", "seed": seed,
            "checkpoint": str(lab / "artifacts/jev-reader/global-reader-reference-v1/runs"
                              / "families128" / str(seed) / "native/checkpoint"),
            "selection_only": False, "probe": False})
    reserved_root = source / "reserved-source-review"
    reserved = [json.loads(line) for line in
                (reserved_root / "selected-sources.jsonl").read_text().splitlines()]
    reviews = {r["source_row"]: r for r in read_json(
        reserved_root / "all28-before-reference.json")["cases"]}
    states = [state for record in reserved
              for state in derive(record, reviews[record["metadata"]["row"]], 20261017)]
    write_rows(root / "reserved-prefixes.jsonl", states)
    cohorts = []
    for cohort in ("dev", "reserved"):
        folder = root / cohort
        decisions = (Path(training["common_dev"]) if cohort == "dev"
                     else root / "reserved-prefixes.jsonl")
        records = (source / "admission/cohort-sources.jsonl" if cohort == "dev"
                   else reserved_root / "selected-sources.jsonl")
        prepare(decisions, records, Path(training["budget"]), folder,
                f"Frozen source-selection-v2 {cohort}; source annotations kept offline")
        reader = copy.deepcopy(prior["reader"])
        reader["experiment_name"] = f"milai-source-selection-v2-{cohort}"
        arms = {m["name"]: {"selection_root": str(folder / "selections" / m["name"]),
                            "policy": "k4"} for m in models}
        arms.update(bm25_k4={"selection_root": str(folder / "selections/bm25"), "policy": "k4"},
                    dense_k4={"selection_root": str(folder / "selections/dense"), "policy": "k4"},
                    full_pool={"selection_root": str(folder / "selections/bm25"),
                               "policy": "full_pool"})
        source_review = (source / "states-v2/effective-reviews.json" if cohort == "dev"
                         else reserved_root / "all28-before-reference.json")
        protocol = {"name": reader["experiment_name"], "cohort": cohort,
            "cases": str(folder / "cases.jsonl"), "labels": str(folder / "labels.jsonl"),
            "reader": reader, "dense_embedding": prior["dense_embedding"],
            "dense_compute_phase": f"source_selection_v2_{cohort}_dense",
            "official_scorer": prior["official_scorer"], "source_review": str(source_review),
            "common_retrieval_costs": str(folder / "common-retrieval-costs.json"),
            "arms": arms, "reuse_identical_reader_inputs": True, "arm_order_seed": 20261017,
            "native_metric_scope": "Original answers unchanged. MuSiQue answer EM/F1 "
                "normalization applied to both corpora; 2Wiki values are reference-compatible "
                "adapted scores, not official 2Wiki leaderboard metrics. Official MuSiQue "
                "paired score only for complete natural positive/negative MuSiQue pairs. "
                "Missing outputs score zero; source semantics separately reviewed.",
            "stage_receipts_root": str(root), "local_stages": [],
            "no_automatic_retry": True, "sha_checks": False}
        for model in models:
            name = f"select-{cohort}-{model['name']}"
            protocol["local_stages"].append({"name": name,
                "phase": f"source_selection_v2_{name}",
                "root": str(folder / "selections" / model["name"])})
            if cohort == "dev" and model["probe"]:
                for kind in ("presentation", "evidence"):
                    name = f"{kind}-{model['name']}"
                    protocol["local_stages"].append({"name": name,
                        "phase": f"source_selection_v2_{name}",
                        "root": str(root / "probes" / kind / model["name"])})
        write_json(folder / "protocol.json", protocol)
        cohorts.append({"name": cohort, "root": str(folder),
                        "protocol": str(folder / "protocol.json")})
    write_json(root / "protocol.json", {"status": "PREPARED_FROM_FROZEN_TRAINING_PROTOCOL",
        "training_root": str(source / "training-v1"), "budget": training["budget"],
        "models": models, "cohorts": cohorts, "robustness": training["robustness"],
        "common_dev": training["common_dev"], "reference_dev": training["reference_dev"],
        "max_len": training["max_len"], "head_max_len": training["head_max_len"],
        "training_protocol": str(args.training_protocol.absolute()),
        "cuda_python": str(lab / "artifacts/jev-reader/cuda-env/bin/python"),
        "http_python": str(lab / "artifacts/jev-reader/http-env/bin/python"),
        "planned_arms_per_cohort": 13, "planned_reader_positions": 923,
        "automatic_retry": False, "sha_checks": False})
    print(json.dumps({"root": str(root), "models": len(models), "cohorts": cohorts,
                      "new_model_calls": 0}))


if __name__ == "__main__":
    main()
