"""Prepare 512 real TRAIN rows for a complete 32-update CUDA profile.

Preserve whole conditional groups and include the actual longest encoder inputs,
heads, largest menus and known change pairs. No labels or visible fields change.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from conditional_training import conditional_training_groups
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("lengths", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    started = time.process_time()
    from laya.common import build_head
    from laya.train import to_internal
    from transformers import AutoTokenizer

    rows = [r for r in read_jsonl(args.data / "train.jsonl") if r["gold"]]
    pairs = read_jsonl(args.data / "selected-pairs.jsonl")
    groups = conditional_training_groups(rows, pairs, args.seed)
    if any(len(group) != 2 for group in groups):
        raise ValueError("The 512-row profile requires complete two-row groups")
    lengths = {r["event_id"]: r["sequence_tokens"]
               for r in read_json(args.lengths)["train"]}
    tokenizer = AutoTokenizer.from_pretrained(args.checkpoint / "tokenizer", local_files_only=True)
    head_lengths, menu_sizes = [], []
    for row in rows:
        ((qid, question),) = row["questions"].items()
        head_lengths.append(len(build_head(tokenizer, to_internal(qid, question), 100000)[0]))
        menu_sizes.append(len(question["criteria"]))
    group_lengths = [max(lengths[rows[i]["metadata"]["event_id"]] for i in group)
                     for group in groups]
    group_heads = [max(head_lengths[i] for i in group) for group in groups]
    group_menus = [max(menu_sizes[i] for i in group) for group in groups]
    changes = {p["left_event"] for p in pairs if p["kind"] == "change"}
    selected = {i for i, group in enumerate(groups)
                if any(rows[j]["metadata"]["event_id"] in changes for j in group)}
    for values in (group_lengths, group_heads, group_menus):
        selected.update(sorted(range(len(groups)), key=lambda i: (values[i], i))[-16:])
    remaining = sorted(set(range(len(groups))) - selected, key=lambda i: (group_lengths[i], i))
    needed = 256 - len(selected)
    selected.update(remaining[k * len(remaining) // needed] for k in range(needed))
    indices = sorted(j for i in selected for j in groups[i])
    chosen = [rows[i] for i in indices]
    identities = {r["metadata"]["event_id"] for r in chosen}
    chosen_pairs = [p for p in pairs if all(p[side + "_event"] in identities
                                          for side in ("left", "right"))]
    args.output.mkdir(parents=True, exist_ok=False)
    dev = read_jsonl(args.data / "dev.jsonl")
    for name, records in [("train", chosen), ("selected-pairs", chosen_pairs),
                          ("dev", dev[:16] + dev[-16:])]:
        with (args.output / f"{name}.jsonl").open("w", encoding="utf-8") as stream:
            for row in records:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    (args.output / "mixture.json").write_bytes((args.data / "mixture.json").read_bytes())
    write_json(args.output / "preparation.json", {
        "source": str(args.data.resolve()), "source_lengths": str(args.lengths.resolve()),
        "checkpoint": str(args.checkpoint.resolve()), "rows": len(chosen), "updates": 32,
        "source_positions": indices, "complete_pairs": len(chosen_pairs),
        "components": dict(Counter(r["metadata"]["component"] for r in chosen)),
        "source_max_sequence_tokens": max(group_lengths),
        "selected_max_sequence_tokens": max(group_lengths[i] for i in selected),
        "source_max_head_tokens": max(head_lengths),
        "selected_max_head_tokens": max(head_lengths[i] for i in indices),
        "source_max_options": max(menu_sizes),
        "selected_max_options": max(menu_sizes[i] for i in indices),
        "selection": "All change groups, top16 by each of sequence/head/menu sizes; "
                     "remaining groups at evenly spaced sequence-length ranks. TRAIN only.",
        "cpu_seconds_pending": time.process_time() - started,
        "profile_only": True, "model_calls": 0, "no_sha_validation": True,
    })
    print(f"Prepared {len(chosen)} TRAIN rows, {len(chosen_pairs)} complete conditional pairs")


if __name__ == "__main__":
    main()
