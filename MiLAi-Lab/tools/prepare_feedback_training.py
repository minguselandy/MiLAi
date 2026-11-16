"""Match a shared reviewed-feedback pool to old-operation replay and continued CE."""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from retrieval_feedback import feedback_counts, feedback_dev_report, validate_feedback
from retrieval_mixture import normalized_mixture


def read_rows(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path)


def matched_old_rows(
    pool: list[dict[str, Any]], lengths: dict[str, int], targets: list[int],
    masses: dict[str, float], rng: random.Random, used: set[str], family_counts: Counter[str],
) -> list[dict[str, Any]]:
    """Length matching uses no labels beyond eligibility, predictions or task outcomes."""
    masses = normalized_mixture(masses)
    exact = {key: len(targets) * value for key, value in masses.items()}
    quotas = {key: int(value) for key, value in exact.items()}
    for key in sorted(exact, key=lambda k: (-(exact[k] - quotas[k]), k))[
            :len(targets) - sum(quotas.values())]:
        quotas[key] += 1
    schedule = [key for key, count in quotas.items() for _ in range(count)]
    rng.shuffle(schedule)
    candidates = list(pool)
    rng.shuffle(candidates)
    selected = []
    for target, component in zip(targets, schedule, strict=True):
        available = [row for row in candidates if row["metadata"]["component"] == component
                     and row["metadata"]["event_id"] not in used]
        row = min(available, key=lambda r: (
            family_counts[r["metadata"]["family"]],
            abs(lengths[r["metadata"]["event_id"]] - target)))
        used.add(row["metadata"]["event_id"])
        family_counts[row["metadata"]["family"]] += 1
        selected.append(copy.deepcopy(row))
    return selected


def prepare(
    old_train: list[dict[str, Any]], old_dev: list[dict[str, Any]],
    feedback: list[dict[str, Any]], old_lengths: dict[str, int], new_lengths: dict[str, int],
    masses: dict[str, float], seed: int,
    *, feedback_dev: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    feedback_dev = [] if feedback_dev is None else feedback_dev
    dev_report = feedback_dev_report(feedback_dev, [*old_train, *feedback], old_dev)
    pool = [row for row in old_train
            if row["metadata"]["task"] == "memory_operation" and row["gold"]]
    dev = [copy.deepcopy(row) for row in old_dev if row["metadata"]["task"] == "memory_operation"]
    if not feedback or any(r["metadata"]["split"] != "train" for r in [*pool, *feedback]):
        raise ValueError("Feedback training requires nonempty reviewed training-source states")
    if {r["metadata"]["family"] for r in feedback} & {r["metadata"]["family"] for r in old_dev}:
        raise ValueError("Feedback source family overlaps development")
    for row in feedback:
        validate_feedback(row)
    own = copy.deepcopy(feedback)
    first_id = max(r["metadata"]["state_id"] for r in [*old_train, *old_dev]) + 1
    for i, row in enumerate(own):
        row["metadata"].update(state_id=first_id + i, task="memory_operation",
                               component="reviewed_feedback")
    targets = [new_lengths[row["metadata"]["event_id"]] for row in own]
    components = {row["metadata"]["component"] for row in pool}
    operation_masses = {key: value for key, value in masses.items() if key in components}
    rng = random.Random(seed)  # noqa: S311 -- declared outcome-blind sampling
    used: set[str] = set()
    families: Counter[str] = Counter()
    replay = matched_old_rows(pool, old_lengths, targets, operation_masses, rng, used, families)
    replacement = matched_old_rows(
        pool, old_lengths, targets, operation_masses, rng, used, families)
    shared = [*own, *replay]
    control = [*replacement, *copy.deepcopy(replay)]
    updates = math.ceil(2 * len(shared) / 16)
    report = {
        "status": "MATCHED_DATA_PREPARED_NOT_FITTED", "seed": seed,
        "feedback_states": len(own), "old_replay_states": len(replay),
        "continued_ce_states": len(control), "shared_states": len(shared),
        "dev_states": len(dev), "optimizer_updates": updates, "row_draws_each_arm": updates * 16,
        "feedback_dev": dev_report,
        "effective_batch": 16, "feedback": {
            target: feedback_counts(shared, target) for target in ("answer", "delivery")},
        "old_sampling": "Component quotas from original operation masses; prefer least-used source "
                        "families, then nearest native sequence length; seed resolves ties.",
        "old_rows_unchanged": True, "feedback_inputs_unchanged": True,
        "shared_replay_event_ids": [r["metadata"]["event_id"] for r in replay],
        "additional_control_event_ids": [r["metadata"]["event_id"] for r in replacement],
        "length_matching": [{"feedback_event": own[i]["metadata"]["event_id"],
                             "feedback_tokens": target,
                             "replay_tokens": old_lengths[replay[i]["metadata"]["event_id"]],
                             "control_replacement_tokens": old_lengths[
                                 replacement[i]["metadata"]["event_id"]]}
                            for i, target in enumerate(targets)],
        "scope": "Small single-seed matched operation budget; answer/delivery use one shared file. "
                 "Continued CE uses old states; its comparison includes state coverage "
                 "differences. "
                 "Original full T1 train/dev files are retained, not rewritten.",
    }
    return {"feedback": shared, "continued-ce": control, "dev": dev,
            "feedback-dev": copy.deepcopy(feedback_dev)}, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_data", type=Path)
    parser.add_argument("feedback", type=Path)
    parser.add_argument("old_lengths", type=Path)
    parser.add_argument("new_lengths", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--feedback-dev", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    old_lengths = {x["event_id"]: x["sequence_tokens"]
                   for x in read_json(args.old_lengths)["train"] if x["question"] == "next"}
    new_lengths = {x["event_id"]: x["sequence_tokens"] for x in read_json(args.new_lengths)}
    data, report = prepare(read_rows(args.old_data / "train.jsonl"),
        read_rows(args.old_data / "dev.jsonl"), read_rows(args.feedback), old_lengths, new_lengths,
        read_json(args.old_data / "mixture.json"), args.seed,
        feedback_dev=read_rows(args.feedback_dev) if args.feedback_dev is not None else None)
    args.output.mkdir(parents=True, exist_ok=False)
    for arm in ("feedback", "continued-ce"):
        directory = args.output / arm
        directory.mkdir()
        splits = [("train", data[arm]), ("dev", data["dev"])]
        if args.feedback_dev is not None:
            splits.append(("feedback-dev", data["feedback-dev"]))
        for split, rows in splits:
            (directory / f"{split}.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    report.update(old_data=str(args.old_data), feedback_file=str(args.feedback),
        feedback_dev_file=str(args.feedback_dev) if args.feedback_dev is not None else None,
        old_length_audit=str(args.old_lengths), new_length_audit=str(args.new_lengths),
        compute={"wall_seconds": time.perf_counter() - started,
                 "cpu_seconds": time.process_time() - cpu}, ledger_recorded=False)
    write_json(args.output / "preparation.json", report)


if __name__ == "__main__":
    main()
