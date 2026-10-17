"""Probe identifier and ordering sensitivity on the same bounded decision states.

Transforms preserve source content and the action set. A title-frame variant
adds a neutral prefix without paraphrasing facts. This diagnoses presentation
sensitivity, not policy QA or evidence removal. Source labels never enter payloads.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import random
import time
from pathlib import Path
from typing import Any

from evaluate_bounded_laya import NativeDecision, score_predictions
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits


def transform(
    payload: dict[str, Any], variant: str, seed: int,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return equivalent visible input and a transformed-to-original action map."""
    result = copy.deepcopy(payload)
    state = result["state"]
    criteria = result["questions"]["next"]["criteria"]
    original_keys = list(criteria)
    mapping = {key: key for key in original_keys}
    if variant == "aliases":
        items = state["read_evidence"] + state["candidates"]
        ids = list(dict.fromkeys(item["id"] for item in items))
        aliases = [f"item{i}" for i in range(len(ids))]
        random.Random(seed).shuffle(aliases)  # noqa: S311 -- fixed diagnostic
        rename = dict(zip(ids, aliases, strict=True))
        for item in items:
            item["id"] = rename[item["id"]]
        rewritten = {}
        mapping = {}
        for action, description in criteria.items():
            if action.startswith("open_"):
                old_id = action.removeprefix("open_")
                new_action = f"open_{rename[old_id]}"
                rewritten[new_action] = f"Read candidate {rename[old_id]} next."
                mapping[new_action] = action
            else:
                rewritten[action] = description
                mapping[action] = action
        result["questions"]["next"]["criteria"] = rewritten
    elif variant == "candidate_order":
        state["candidates"].reverse()
    elif variant == "option_order":
        result["questions"]["next"]["criteria"] = dict(reversed(list(criteria.items())))
    elif variant == "title_frame":
        for item in state["read_evidence"] + state["candidates"]:
            item["title"] = f"Passage titled: {item['title']}"
    elif variant != "original":
        raise ValueError(f"Unknown probe variant: {variant}")
    return result, mapping


def canonical_prediction(
    prediction: dict[str, Any], mapping: dict[str, str],
) -> dict[str, Any]:
    return {**prediction, "choice": mapping[prediction["choice"]],
            **{field: {mapping[key]: value for key, value in prediction[field].items()}
               for field in ("logits", "probabilities")}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--budget", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=20261017)
    parser.add_argument("--max-len", type=int, default=8192)
    parser.add_argument("--head-max-len", type=int, default=512)
    parser.add_argument("--backend", choices=("native", "linear"), default="native")
    parser.add_argument("--variants", nargs="+", choices=(
        "original", "aliases", "candidate_order", "option_order", "title_frame"),
        default=("original", "aliases", "candidate_order", "option_order", "title_frame"),
        help="Omit original when exact frozen baseline predictions already exist")
    args = parser.parse_args()
    import json
    import os

    import torch

    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2":
        raise ValueError("This local probe is allocated only physical GPU2")
    torch.set_num_threads(4)
    args.output.mkdir(parents=True, exist_ok=False)
    rows = [json.loads(line) for line in args.data.read_text().splitlines()]
    variants = args.variants
    run = {"status": "RUNNING", "pid": os.getpid(), "completed": 0,
           "planned": len(rows) * len(variants), "data": str(args.data.resolve()),
           "checkpoint": str(args.checkpoint.resolve()), "physical_gpu": 2,
           "seed": args.seed, "http_requests": 0, "backend": args.backend,
           "variants": variants}
    write_json(args.output / "run.json", run)
    started, cpu = time.perf_counter(), time.process_time()
    decision: NativeDecision | None = None
    try:
        if args.backend == "linear":
            from linear_reader_classifier import LinearDecision

            decision = LinearDecision.load(args.checkpoint, args.max_len, args.head_max_len)
        else:
            decision = NativeDecision(args.checkpoint, args.max_len, args.head_max_len)
        decision.model.encoder.config.reference_compile = False
        decision.device = torch.device("cuda:0")
        decision.model.to(decision.device)
        all_predictions: dict[str, list[dict[str, Any]]] = {variant: [] for variant in variants}
        for index, row in enumerate(rows):
            payload = {key: row[key] for key in ("state", "questions")}
            for variant in variants:
                modified, mapping = transform(payload, variant, args.seed + index)
                path = args.output / "calls" / str(index) / variant
                write_json(path / "input.json", modified)
                write_json(path / "action-map.json", mapping)
                prediction = decision.predict(modified)
                write_json(path / "output.json", prediction)
                all_predictions[variant].append(canonical_prediction(prediction, mapping))
                run["completed"] += 1
                write_json(args.output / "run.json", run)
        write_json(args.output / "scores.json", {
            variant: score_predictions(rows, predictions)
            for variant, predictions in all_predictions.items()})
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        measures = {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu, "runs": 1,
                    **(decision.counters if decision is not None else {})}
        write_json(args.output / "compute.json", measures)
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(args.budget)["limits"]), args.budget)
            budget.record_compute("reader_invariance_probe_v1", measures)
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
