"""Freeze chronological raw-source Reader inputs before opening evaluation labels.

The source-only confirmation deliberately has no model-written semantic views.
It tests the frozen instruction on new stories, not a replication of the older
mixed-state delivery or a measurement of memory maintenance.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.edit_benchmarks import READER_PROMPT


def project_episode(episode: dict) -> tuple[list[dict], list[dict]]:
    cases, references = [], []
    before = episode["before_questions"]["questions"]
    for phase in ("before", "after"):
        group = episode[f"{phase}_questions"]
        sources = []
        for index, session in enumerate(episode["sessions"][:group["position_after_session"] + 1]):
            for turn, observation in enumerate(session["conversation"]):
                sources.append({"source": f"s{index}-t{turn}", "role": observation["role"],
                                "reported_at": session["timestamp"],
                                "text": observation["content"]})
        for index, question in enumerate(group["questions"]):
            identity = f"{phase}-{index}"
            payload = {"question": question["question"], "date": group["timestamp"],
                       "memory_view": "source_history", "memories": sources}
            cases.append({"id": identity, "phase": phase, "episode": episode["episode_id"],
                          "source_turns": len(sources), "messages": [
                              {"role": "system", "content": READER_PROMPT},
                              {"role": "user", "content": json.dumps(
                                  payload, ensure_ascii=False)}]})
            matches = [f"before-{i}" for i, row in enumerate(before)
                       if row["task_type"] == question["task_type"]
                       and row["entity"] == question["entity"]]
            gated = phase == "after" and question["task_type"] in {"Cas", "Abs", "Del"}
            if gated and len(matches) != 1:
                raise ValueError("A native dynamic question lacks its unique before counterpart")
            references.append({"episode": episode["episode_id"], "id": identity,
                               "phase": phase, **question,
                               "before_id": matches[0] if gated else None})
    return cases, references


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    start, cpu = time.perf_counter(), time.process_time()
    config = read_json(args.config)
    selection = read_json(Path(config["selection"]))
    args.output.mkdir(parents=True, exist_ok=False)
    episodes = {r["episode_id"]: r for r in read_json(Path(config["source"]))}
    cases, references = [], []
    for selected in selection["selected"]:
        inputs, refs = project_episode(episodes[selected["episode_id"]])
        references.extend(refs)
        for case in inputs:
            path = args.output / "inputs" / case["episode"] / f"{case['id']}.json"
            write_json(path, {"messages": case["messages"]})
            cases.append({k: v for k, v in case.items() if k != "messages"}
                         | {"source_request": str(path.resolve())})
    write_json(args.output / "references.json", references)
    write_json(args.output / "selection.json", selection)
    jobs = []
    for seed in config["seeds"]:
        for selected in selection["selected"]:
            episode = selected["episode_id"]
            job = {**config, "name": f"{config['name']}-{seed}-{episode}",
                   "cases": [r for r in cases if r["episode"] == episode],
                   "sampling": {**config["sampling"], "seed": seed}}
            path = args.output / "jobs" / str(seed) / f"{episode}.json"
            write_json(path, job)
            jobs.append({"seed": seed, "episode": episode, "config": str(path.resolve()),
                         "planned_calls": len(job["cases"]) * len(config["variants"])})
    write_json(args.output / "preparation.json", {
        "status": "PREPARED_NO_MODEL", "jobs": jobs, "source_cases": len(cases),
        "total_planned_calls": sum(j["planned_calls"] for j in jobs),
        "wall_seconds": time.perf_counter() - start, "cpu_seconds": time.process_time() - cpu,
        "scope": config["scope"], "new_model_calls": 0})


if __name__ == "__main__":
    main()
