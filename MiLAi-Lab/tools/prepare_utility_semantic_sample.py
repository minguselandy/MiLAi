"""Select a declared subset of executed utility states for actual Reader/semantic feedback."""
from __future__ import annotations

import argparse
import copy
import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from feedback_choices import parameter_stratum
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.runners.given_host_readout import separate_answer_fields


def select_semantic_states(cases: list[dict[str, Any]], scores: list[dict[str, Any]],
                           count: int, seed: int) -> list[tuple[dict[str, Any], str]]:
    """50% source-stratified random, 25% Teacher/learner disagreement, rest undercovered.

    This selects costly offline annotations, not online actions. All candidate bindings
    were fixed and executed before Teacher scoring. Shortfalls use the remaining pool.
    """
    if count < 1 or count > len(cases):
        raise ValueError("Semantic sample size must fit the actual state pool")
    rng = random.Random(seed)  # noqa: S311 -- recorded sampling seed
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_family[case["family"]].append(case)
    families = list(by_family)
    rng.shuffle(families)
    for group in by_family.values():
        rng.shuffle(group)
    stratified = []
    for offset in range(max(map(len, by_family.values()))):
        stratified.extend(by_family[family][offset] for family in families
                          if offset < len(by_family[family]))
    selected = [(c, "source_stratified_random") for c in stratified[:count // 2]]
    used = {c["event_id"] for c, _ in selected}
    utilities: dict[str, dict[str, float]] = defaultdict(dict)
    for score in scores:
        if score["score_known"]:
            utilities[score["event_id"]][score["action"]["id"]] = score["mean_logprob"]
    disagreements = []
    for case in stratified:
        values = utilities[case["event_id"]]
        learner = case["choices"]["learner"]
        if learner in values and max(values.values()) > values[learner] + 1e-6:
            disagreements.append(case)
    for case in disagreements:
        if len(selected) >= count // 2 + count // 4:
            break
        if case["event_id"] not in used:
            selected.append((case, "teacher_learner_disagreement"))
            used.add(case["event_id"])
    coverage: Counter[str] = Counter()
    for case, _ in selected:
        coverage.update(parameter_stratum(b["action"]) for b in case["branches"])
    remaining = [c for c in stratified if c["event_id"] not in used]
    while len(selected) < count:
        candidate = min(remaining, key=lambda c: min(
            coverage[parameter_stratum(b["action"])] for b in c["branches"]))
        remaining.remove(candidate)
        selected.append((candidate, "undercovered_binding_stratum_or_quota_shortfall"))
        coverage.update(parameter_stratum(b["action"]) for b in candidate["branches"])
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("scores", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--states", type=int, required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    original = read_json(args.prepared / "run.json")
    score_run = read_json(args.scores.parent / "run.json")
    if original["status"] != "COMPLETED" or score_run["status"] not in {
            "COMPLETED", "COMPLETED_WITH_FAILURES"}:
        raise ValueError("Select only closed executed and scored versions")
    cases, scores = read_json(args.prepared / "cases.json"), read_jsonl(args.scores)
    expected_events = {c["event_id"] for c in cases}
    if {s["event_id"] for s in scores} != expected_events or any(
            Path(s["packet_ref"]["path"]).resolve() != (args.prepared / "cases.json").resolve()
            for s in scores):
        raise ValueError("Sampling scores must belong to these executed packet records")
    selected = select_semantic_states(cases, scores, args.states, args.seed)
    output = []
    for case, reason in selected:
        case = copy.deepcopy(case)
        case["semantic_sampling_stratum"] = reason
        for branch in case["branches"]:
            branch["readout_request"] = separate_answer_fields(branch["readout_request"])
        output.append(case)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "cases.json", output)
    (args.output / "states.jsonl").write_text((args.prepared / "states.jsonl").read_text())
    write_json(args.output / "run.json", {**original, "status": "COMPLETED",
        "original_preparation": str(args.prepared.resolve()), "scores": str(args.scores.resolve()),
        "seed": args.seed, "selected_states": len(output),
        "comparison_states": len(output),
        "families": len({c["family"] for c in output}),
        "packets": sum(len(c["branches"]) for c in output),
        "sampling_counts": dict(Counter(reason for _, reason in selected)),
        "answer_format_version": "answer_separate_v1",
        "native_metric_field": "answer",
        "semantic_review_fields": ["answer", "explanation", "evidence"],
        "Host_calls": 0, "no_sha_validation": True,
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}})


if __name__ == "__main__":
    main()
