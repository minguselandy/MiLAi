"""Freeze nested feedback source cohorts using only inherited split/component metadata."""
from __future__ import annotations

import argparse
import copy
import random
import time
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from prepare_host_intent_t2 import source_registry


def nested_order(registry: dict[str, dict[str, str]], anchors: list[str], seed: int) -> list[str]:
    """Keep earlier feedback groups, then cycle shuffled component queues without replacement."""
    if len(anchors) != len(set(anchors)) or any(registry[g]["split"] != "train" for g in anchors):
        raise ValueError("Feedback anchors must be distinct registered training groups")
    components: dict[str, list[str]] = defaultdict(list)
    for family, entry in sorted(registry.items()):
        if entry["split"] == "train" and family not in anchors:
            components[entry["component"]].append(family)
    rng = random.Random(seed)  # noqa: S311 -- preregistered metadata-only source selection
    queues = {}
    for component in sorted(components):
        rng.shuffle(components[component])
        queues[component] = deque(components[component])
    result = list(anchors)
    while any(queues.values()):
        for queue in queues.values():
            if queue:
                result.append(queue.popleft())
    return result


def prepare_cohorts(
    data: dict[str, list[dict[str, Any]]], fixtures: list[dict[str, Any]],
    anchors: list[str], sizes: list[int], seed: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    registry = source_registry(data)
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    identities = set()
    for fixture in fixtures:
        for history in fixture["histories"]:
            if history["id"] in identities:
                raise ValueError("A public history was included twice")
            identities.add(history["id"])
            family = history["source_group"]
            if family not in registry or history["split"] != registry[family]["split"]:
                raise ValueError("Public source identity or split differs from inherited registry")
            by_group[family].append(history)
    if set(by_group) != set(registry):
        raise ValueError("Public histories must cover the complete inherited source registry")
    order = nested_order(registry, anchors, seed)
    if any(size < len(anchors) or size > len(order) for size in sizes):
        raise ValueError("Requested cohorts must contain the anchors and fit the registered pool")
    outputs, cohorts = {}, {}
    for size in sizes:
        selected = order[:size]
        histories = [copy.deepcopy(history) for family in selected
                     for history in sorted(by_group[family], key=lambda h: h["id"])]
        outputs[size] = {"schema": "nested_feedback_histories_v1",
            "scope": "Admitted training Sources; new actual collector trajectories required.",
            "histories": histories}
        cohorts[str(size)] = {"selected_groups": selected,
            "component_groups": dict(Counter(registry[g]["component"] for g in selected)),
            "histories": len(histories), "request_positions_per_collector": sum(
                len(h["requests"]) for h in histories)}
    return outputs, {"status": "SELECTED_NOT_COLLECTED", "seed": seed, "anchors": anchors,
        "registered_train_groups": len(order), "registered_dev_groups": sum(
            e["split"] == "dev" for e in registry.values()), "source_order": order,
        "cohorts": cohorts, "selection": "Anchors first; sort groups within component, shuffle "
            "with declared seed,then round-robin sorted components until each queue is empty. "
            "Prefix cohorts keep every original history/request/source in selected groups. "
            "No gold,answerability,action score or task outcome is used.",
        "no_new_independent_sources_claimed": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("histories", nargs="+", type=Path)
    parser.add_argument("--anchors", nargs="+", required=True)
    parser.add_argument("--sizes", nargs="+", type=int, default=[32, 64, 128])
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    data = {split: read_jsonl(args.data / f"{split}.jsonl") for split in ("train", "dev")}
    cohorts, report = prepare_cohorts(data, [read_json(p) for p in args.histories],
                                      args.anchors, args.sizes, args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    for size, fixture in cohorts.items():
        directory = args.output / f"sources-{size}"
        directory.mkdir()
        write_json(directory / "histories.json", fixture)
        write_json(directory / "selection.json", report["cohorts"][str(size)])
    report.update(data=str(args.data), source_fixtures=[str(p) for p in args.histories],
                  model_calls=0, ledger_recorded=False,
                  compute={"cpu_seconds": time.process_time() - cpu,
                           "wall_seconds": time.perf_counter() - started})
    write_json(args.output / "selection.json", report)
    print({size: {k: v for k, v in details.items() if k != "selected_groups"}
           for size, details in report["cohorts"].items()})


if __name__ == "__main__":
    main()
