"""Analyze fixed-budget learning and saved-checkpoint semantic probes, without forwards."""

from __future__ import annotations

import argparse
import fcntl
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from probe_bounded_invariance import canonical_prediction, transform
from review_global_reader_results import local_ledger_audit


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def target(row: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = row["gold"].get("next", {}).get("probabilities", {})
    return result


def accepted(row: dict[str, Any], prediction: dict[str, Any]) -> bool:
    return target(row).get(prediction["choice"], 0) > 0


def metrics(data: list[dict[str, Any]], predictions: list[dict[str, Any]],
            reviews: dict[int, dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter(states=len(data))
    strata: dict[str, Counter[str]] = defaultdict(Counter)
    groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    uniform = []
    for row, prediction in zip(data, predictions, strict=True):
        meta, gold = row["metadata"], target(row)
        if set(prediction["probabilities"]) != set(row["questions"]["next"]["criteria"]):
            raise ValueError("Prediction does not match the frozen offered action set")
        if not gold:
            counts["masked"] += 1
            continue
        hit = int(accepted(row, prediction))
        counts["labelled"] += 1
        counts["accepted"] += hit
        review = reviews[meta["row"]]
        dimensions = [f"dataset/{meta['dataset']}", f"status/{meta['label_status']}",
            f"source/{review['disposition']}", f"qualified/{review.get('qualified', False)}",
            f"reads/{len(meta['opened_source_indices'])}",
            *[f"origin/{origin}" for origin in meta["prefix_origins"]]]
        if review["complete_proofs"]:
            dimensions.append(f"minimum_proof/{min(map(len, review['complete_proofs']))}")
        for dimension in dimensions:
            strata[dimension].update(labelled=1, accepted=hit)
        groups[meta["family"]][meta["question_id"]].append(hit)
        uniform.append(len(gold) / len(prediction["probabilities"]))
        available = set(prediction["probabilities"])
        lexical = next(f"open_p{meta['pool_source_indices'].index(i)}"
                       for i in meta["bm25_source_indices"]
                       if f"open_p{meta['pool_source_indices'].index(i)}" in available
                       and i not in meta["opened_source_indices"])
        counts["bm25_next_accepted"] += int(gold.get(lexical, 0) > 0)
    return {"counts": dict(counts), "strata": {k: dict(v) for k, v in strata.items()},
        "families": len(groups), "family_question_macro": mean(
            mean(mean(values) for values in questions.values()) for questions in groups.values()),
        "family_results": {family: {q: {"states": len(v), "accepted": sum(v)}
                                     for q, v in questions.items()}
                           for family, questions in groups.items()},
        "uniform_action_expected_acceptance": mean(uniform),
        "scope": "Labelled prefix decisions, with masks explicit; not on-policy QA. "
                 "Origins overlap. Qualified source cases retain their frozen interpretation."}


def pair_metrics(data: list[dict[str, Any]], left: list[dict[str, Any]],
                 right: list[dict[str, Any]], changed: list[bool]) -> dict[str, int]:
    result: Counter[str] = Counter(states=len(data))
    for row, a, b, change in zip(data, left, right, changed, strict=True):
        result["canonical_choice_equal"] += a["choice"] == b["choice"]
        result["input_changed"] += change
        if not target(row):
            result["masked"] += 1
            continue
        ah, bh = accepted(row, a), accepted(row, b)
        result["labelled"] += 1
        result["both_accepted"] += ah and bh
        result["left_only_accepted"] += ah and not bh
        result["right_only_accepted"] += bh and not ah
        if change:
            result["changed_input_labelled"] += 1
            result["changed_input_both_accepted"] += ah and bh
    return dict(result)


def evidence_metrics(data: list[dict[str, Any]], predictions: list[dict[str, Any]],
                     pairs: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    observations = []
    for pair in pairs:
        left, right = pair["left"], pair["right"]
        a, b = data[left], data[right]
        if (a["state"]["candidates"] != b["state"]["candidates"]
                or a["state"]["question"] != b["state"]["question"]
                or a["questions"] != b["questions"]):
            raise ValueError("Controlled evidence pair changed the offered actions/candidates")
        disjoint = not (set(target(a)) & set(target(b)))
        if not target(a) or not target(b) or disjoint != pair["requires_choice_change"]:
            raise ValueError("Evidence pair target scope differs from its frozen definition")
        both = accepted(a, predictions[left]) and accepted(b, predictions[right])
        switched = predictions[left]["choice"] != predictions[right]["choice"]
        counts["pairs"] += 1
        counts["both_accepted"] += both
        counts["choice_changed"] += switched
        if disjoint:
            counts["requires_choice_change"] += 1
            counts["required_change_and_both_accepted"] += both and switched
            counts["changed_but_not_both_accepted"] += switched and not both
        observations.append({**pair, "both_accepted": both, "choice_changed": switched})
    return {"counts": dict(counts), "pairs": observations,
        "scope": "Authored observed-premise changes with all actions retained; a switch alone "
                 "is not correctness. Natural question variants are evaluated separately in QA."}


def learning(root: Path) -> dict[str, Any]:
    protocol = read_json(root / "protocol.json")
    driver = read_json(root / "driver.json")
    if driver["status"] != "COMPLETED" or len(driver["jobs"]) != 6:
        raise ValueError("Learning matrix must contain all six terminal jobs")
    data_root = Path(protocol["data"])
    reviews = {r["source_row"]: r for r in read_json(data_root / "effective-reviews.json")["cases"]}
    dev = {condition: rows(data_root / condition / "dev.jsonl")
           for condition in protocol["conditions"]}
    results = []
    for job in driver["jobs"]:
        folder = Path(job["output"])
        run = read_json(folder / "run.json")
        if run["status"] != "COMPLETED" or run["optimizer_updates"] != 188:
            raise ValueError("A fixed training job did not finish its frozen update budget")
        train = [r for r in rows(data_root / job["condition"] / "train.jsonl") if target(r)]
        checkpoints = {}
        for step in protocol["evaluation_steps"]:
            predictions = [read_json(folder / "dev" / str(step) / f"{i}.json")
                           for i in range(len(dev["source"]))]
            checkpoints[str(step)] = {name: metrics(items, predictions, reviews)
                                      for name, items in dev.items()}
        train_predictions = [read_json(folder / "train/188" / f"{i}.json")
                             for i in range(len(train))]
        compute = read_json(folder / "compute.json")
        name = f"{job['condition']}-seed{job['seed']}"
        phase = f"source_selection_v2_train_{job['condition']}_seed{job['seed']}"
        results.append({"condition": job["condition"], "seed": job["seed"],
            "run": run, "compute": compute,
            "ledger_audit": local_ledger_audit(root, name, phase, compute),
            "history": read_json(folder / "history.json"),
            "parameter_probes": read_json(folder / "parameter-probes.json"),
            "dev": checkpoints, "train_own_recipe": metrics(train, train_predictions, reviews)})
    return {"status": "ALL_SIX_FIXED_UPDATE_LEARNING_DIAGNOSTICS_CLOSED", "jobs": results,
        "scope": "Pre-save FP32 diagnostics, not reloaded checkpoint predictions. Equal188updates "
                 "and3008examples, differing masks/eligible families/tokens; no equal-FLOPs claim. "
                 "Intermediate94 diagnostics retained; checkpoint_latest is overwritten by188."}


def probes(root: Path) -> dict[str, Any]:
    protocol = read_json(root / "protocol.json")
    training = read_json(Path(protocol["training_protocol"]))
    reviews = {r["source_row"]: r for r in read_json(
        Path(training["data"]) / "effective-reviews.json")["cases"]}
    data = rows(Path(protocol["common_dev"]))
    reference = rows(Path(protocol["reference_dev"]))
    contrast = rows(Path(protocol["robustness"]["evidence_contrasts"]))
    pairs = read_json(Path(protocol["robustness"]["evidence_pairs"]))
    models = []
    for model in protocol["models"]:
        if not model["probe"]:
            continue
        for kind in ("presentation", "evidence"):
            run = read_json(root / "probes" / kind / model["name"] / "run.json")
            if run["status"] != "COMPLETED" or run["completed"] != run["planned"]:
                raise ValueError("Every frozen probe must be terminal before analysis")
        predicted: dict[str, list[dict[str, Any]]] = {}
        changed_inputs: dict[str, list[bool]] = {}
        for variant in protocol["robustness"]["presentation_variants"]:
            predicted[variant], changed_inputs[variant] = [], []
            for index, row in enumerate(data):
                folder = (root / "probes/presentation" / model["name"] / "calls"
                          / str(index) / variant)
                original_payload = {k: row[k] for k in ("state", "questions")}
                expected, mapping = transform(original_payload, variant, 20261017 + index)
                actual = read_json(folder / "input.json")
                if json.dumps(expected) != json.dumps(actual):
                    raise ValueError("Saved presentation input differs, including option order")
                if read_json(folder / "action-map.json") != mapping:
                    raise ValueError("Saved action alias map differs")
                predicted[variant].append(canonical_prediction(read_json(folder / "output.json"),
                                                               mapping))
                changed_inputs[variant].append(json.dumps(actual) != json.dumps(original_payload))
        original = predicted["original"]
        contrasts = []
        for index, row in enumerate(contrast):
            folder = root / "probes/evidence" / model["name"] / "calls" / str(index) / "original"
            payload = {k: row[k] for k in ("state", "questions")}
            if json.dumps(read_json(folder / "input.json")) != json.dumps(payload):
                raise ValueError("Evidence contrast input differs from the frozen source view")
            contrasts.append(read_json(folder / "output.json"))
        pre_save = [read_json(Path(protocol["training_root"]) / "runs" / model["condition"]
                    / str(model["seed"]) / "dev/188" / f"{i}.json") for i in range(len(data))]
        models.append({"model": model["name"],
            "presentation_source": {v: metrics(data, p, reviews) for v, p in predicted.items()},
            "original_reference": metrics(reference, original, reviews),
            "presentation_pairs": {v: pair_metrics(data, original, p, changed_inputs[v])
                                   for v, p in predicted.items() if v != "original"},
            "pre_save_vs_reload": pair_metrics(data, pre_save, original, [False] * len(data)),
            "evidence_contexts": metrics(contrast, contrasts, reviews),
            "evidence_pairs": evidence_metrics(contrast, contrasts, pairs)})
    return {"status": "ALL_SIX_SAVED_CHECKPOINT_PROBES_ANALYZED", "models": models,
        "scope": "SavedFP16 weights reloadedFP32. Two-view acceptance primary; exactchoice "
                 "invariance secondary. Unchanged transformations have a separate denominator."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("learning", "probes"))
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    result = learning(args.root) if args.phase == "learning" else probes(args.root)
    write_json(args.output / "report.json", result)
    measures = {"wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu, "analyses": 1}
    budget_path = Path(read_json(args.root / "protocol.json")["budget"])
    with budget_path.with_name("budget.json.http-owner.lock").open("a+b") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        budget = RunBudget(RunLimits(**read_json(budget_path)["limits"]), budget_path)
        budget.record_compute(f"source_selection_v2_{args.phase}_analysis", measures)
    write_json(args.output / "compute.json", measures)
    print(result["status"])


if __name__ == "__main__":
    main()
