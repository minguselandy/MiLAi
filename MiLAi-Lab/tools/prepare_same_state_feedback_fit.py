"""Prepare feedback versus continued SFT on identical new inputs and shared old replay."""

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
from milai_lab.methods.laya_memory_policy import project_operation_payload
from prepare_feedback_training import matched_old_rows
from retrieval_feedback import validate_feedback
from retrieval_mixture import mixture_event_weights
from train_laya_matched import audit


def prepare(
    feedback: list[dict[str, Any]],
    sft: list[dict[str, Any]],
    old: list[dict[str, Any]],
    dev: list[dict[str, Any]],
    old_lengths: dict[str, int],
    new_lengths: dict[str, int],
    seed: int,
    replay_mass: float = 0.25,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not feedback or len(feedback) != len(sft):
        raise ValueError("Matched objective comparison needs nonempty shared directional support")
    pairs, control = copy.deepcopy(feedback), copy.deepcopy(sft)
    dev_families = {r["metadata"]["family"] for r in dev}
    all_rows = [*pairs, *control, *old]
    if any(r["metadata"]["split"] != "train" for r in all_rows) or dev_families & {
        r["metadata"]["family"] for r in all_rows
    }:
        raise ValueError("Preserve TRAIN/development source roles")
    seen, rollouts = set(), []
    for a, b in zip(pairs, control, strict=True):
        validate_feedback(a)
        if (
            not b["gold"]
            or any(a[key] != b[key] for key in ("state", "questions"))
            or any(
                a["metadata"][key] != b["metadata"][key]
                for key in ("event_id", "family", "training_event", "action_parameters")
            )
        ):
            raise ValueError("Matched SFT must retain the actual state, full menu and source/event")
        identity = a["metadata"]["event_id"]
        if identity in seen:
            raise ValueError("Do not count the same reached state twice")
        seen.add(identity)
        rollouts.append(a["metadata"]["feedback_rollout"])
    if any(r != rollouts[0] for r in rollouts):
        raise ValueError("Keep different continuation/terminal feedback conditions separate")
    first_id = max(r["metadata"]["state_id"] for r in [*old, *dev]) + 1
    for i, (a, b) in enumerate(zip(pairs, control, strict=True)):
        for row, component in ((a, "feedback"), (b, "new_operation_sft")):
            row["metadata"].update(
                feedback_source_state_id=row["metadata"]["state_id"],
                state_id=first_id + i,
                component=component,
            )
    pool = [copy.deepcopy(r) for r in old if r["gold"]]
    for row in pool:
        row["metadata"].update(
            original_component=row["metadata"].get("component"), component="operation_replay"
        )
    targets = [new_lengths[r["metadata"]["event_id"]] for r in pairs]
    rng = random.Random(seed)  # noqa: S311 -- declared outcome-blind replay sampling
    replay = matched_old_rows(
        pool, old_lengths, targets, {"operation_replay": 1.0}, rng, set(), Counter()
    )
    feedback_rows, sft_rows = [*pairs, *replay], [*control, *copy.deepcopy(replay)]
    pair_weights = mixture_event_weights(
        feedback_rows, {"feedback": 1, "operation_replay": replay_mass}
    )
    sft_mixture = {"new_operation_sft": 1, "operation_replay": replay_mass}
    sft_weights = mixture_event_weights(sft_rows, sft_mixture)
    if pair_weights != sft_weights:
        raise ValueError("Objective arms changed component/source/event loss mass")
    for a, b in zip(feedback_rows, sft_rows, strict=True):
        if (
            any(a[k] != b[k] for k in ("state", "questions"))
            or a["metadata"]["state_id"] != b["metadata"]["state_id"]
        ):
            raise ValueError("Objective arms changed model inputs or option-permutation seed IDs")
    return {"feedback": feedback_rows, "continued-sft": sft_rows, "sft_mixture": sft_mixture}, {
        "new_matched_states": len(pairs),
        "shared_replay_states": len(replay),
        "rows_each_arm": len(feedback_rows),
        "new_source_families": len({r["metadata"]["family"] for r in pairs}),
        "rollout": rollouts[0],
        "feedback_event_ids": [r["metadata"]["event_id"] for r in pairs],
        "shared_replay_event_ids": [r["metadata"]["event_id"] for r in replay],
        "new_family_overlap_with_old_pool": sorted(
            {r["metadata"]["family"] for r in pairs} & {r["metadata"]["family"] for r in old}
        ),
        "replay_selection": "Seeded old TRAIN pool; least-used family, then nearest token length",
        "replay_relative_loss_mass": replay_mass,
        "normalized_new_mass": 1 / (1 + replay_mass),
        "weights_both_arms": pair_weights,
        "complete_model_inputs_and_sampling_ids_equal": True,
        "length_matching": [
            {
                "new_event": a["metadata"]["event_id"],
                "new_tokens": length,
                "replay_tokens": old_lengths[b["metadata"]["event_id"]],
            }
            for a, b, length in zip(pairs, replay, targets, strict=True)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_data", type=Path)
    parser.add_argument("old_lengths", type=Path)
    parser.add_argument("tokenizer", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--feedback-directories", type=Path, nargs="+", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-rows", type=int, default=32)
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_rows < 1:
        parser.error("Positive epochs and effective batch rows required")
    from transformers import AutoTokenizer

    started, cpu = time.perf_counter(), time.process_time()
    feedback, sft = [], []
    for directory in args.feedback_directories:
        feedback.extend(read_jsonl(directory / "matched-feedback.jsonl"))
        sft.extend(read_jsonl(directory / "matched-sft.jsonl"))
    old, dev = read_jsonl(args.old_data / "train.jsonl"), read_jsonl(args.old_data / "dev.jsonl")
    old_lengths = {
        r["event_id"]: r["sequence_tokens"]
        for r in read_json(args.old_lengths)["train"]
        if r["question"] == "next"
    }
    tok = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    lengths = audit(
        [project_operation_payload(r, "shared_actions") for r in feedback], tok, 16384, 2048
    )
    if any(r["state_tokens_dropped"] or r["head_tokens_dropped"] for r in lengths):
        raise ValueError("Matched feedback inputs must fit the declared complete-input capacity")
    data, report = prepare(
        feedback,
        sft,
        old,
        dev,
        old_lengths,
        {r["event_id"]: r["sequence_tokens"] for r in lengths},
        args.seed,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    for name in ("feedback", "continued-sft"):
        folder = args.output / name
        folder.mkdir()
        with (folder / "train.jsonl").open("w") as stream:
            for row in data[name]:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        (folder / "dev.jsonl").symlink_to((args.old_data / "dev.jsonl").resolve())
    write_json(args.output / "continued-sft/mixture.json", data["sft_mixture"])
    write_json(
        args.output / "manifest.json",
        {
            "status": "MATCHED_OBJECTIVE_DATA_PREPARED_NOT_FITTED",
            **report,
            "inputs": list(map(str, args.feedback_directories)),
            "old_data": str(args.old_data.resolve()),
            "seed": args.seed,
            "epochs": args.epochs,
            "effective_batch_rows": args.batch_rows,
            "full_pass_optimizer_updates": math.ceil(report["rows_each_arm"] / args.batch_rows)
            * args.epochs,
            "full_pass_draws_each_arm": report["rows_each_arm"] * args.epochs,
            "training_conditions": {
                "feedback": "objective pair, legacy-direction, delivery, replay set, "
                "replay weight0.25; normalized total component mass",
                "continued-sft": "task mixed_retrieval (all row tasks memory_operation); "
                "objective set; supplied mixture.json; loss scale1",
            },
            "new_model_calls": 0,
            "no_sha_validation": True,
            "scope": "Identical state/menu/source/option-shuffle and replay. Targets differ: "
            "reviewed branch pairs versus reference-witness SFT. Restricted common support and "
            "upstream unknowns stay explicit. "
            "A small prefix is data preparation, not a full S2 study.",
            "compute": {
                "cpu_seconds": time.process_time() - cpu,
                "wall_seconds": time.perf_counter() - started,
            },
        },
    )


if __name__ == "__main__":
    main()
