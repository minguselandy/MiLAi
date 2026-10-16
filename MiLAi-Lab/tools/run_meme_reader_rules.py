"""Paired Reader task wording on frozen, previously exposed MEME deliveries.

No Writer, retrieval, state repair, new source or evaluator answer enters this
experiment. Both fresh conditions use temperature zero and the same output limit.
"""

from __future__ import annotations

import argparse
import copy
import os
import time
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.impact_comparison import TimedBenchmarkRun


def messages_for(request: dict, addition: str | None) -> list[dict]:
    messages = copy.deepcopy(request["messages"])
    if addition:
        messages[0]["content"] += "\n" + addition
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    config = read_json(args.config)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "protocol.json", config)
    settings = read_json(Path(config["settings_source"]))
    settings.update(experiment_name=config["name"], config_version=config["name"])
    settings["model"].update(temperature=0.0, max_calls=2 * len(config["cases"]))
    run_state = {"status": "RUNNING", "pid": os.getpid(), "planned_calls": 2 * len(config["cases"]),
                 "completed_calls": 0, "new_writer_calls": 0, "new_retrieval_calls": 0,
                 "temperature": 0.0, "source_version": config["source_version"]}
    write_json(args.output / "run.json", run_state)
    started = time.perf_counter()
    run = TimedBenchmarkRun(settings, args.output, phase="predict")
    answers = []
    try:
        for index, case in enumerate(config["cases"]):
            request = read_json(Path(case["source_request"]))
            variants = ("baseline", "rule_application")
            if index % 2:
                variants = tuple(reversed(variants))
            for variant in variants:
                addition = config["instruction"] if variant == "rule_application" else None
                messages = messages_for(request, addition)
                key = f"questions/{variant}/{case['episode']}/{case['id']}"
                answer = {"episode": case["episode"], "id": case["id"], "phase": case["phase"],
                          "variant": variant, "source_request": case["source_request"]}
                try:
                    answer["hypothesis"] = run.call(key, messages, structured=False,
                                                   enable_thinking=run.stage_thinking("reader"))
                except ValueError as error:
                    failure = run._known_reader_failure(error, key)
                    if failure is None:
                        raise
                    answer.update(hypothesis=None, reader_failure=failure)
                answers.append(answer)
                write_json(args.output / "answers.json", answers)
                run_state["completed_calls"] += 1
                write_json(args.output / "run.json", run_state)
                print(f"{run_state['completed_calls']}/{run_state['planned_calls']} "
                      f"{case['episode']}/{case['id']} {variant}", flush=True)
        run_state["status"] = "COMPLETED"
    except BaseException as error:
        run_state.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        run.close()
        run_state["wall_seconds"] = time.perf_counter() - started
        write_json(args.output / "run.json", run_state)


if __name__ == "__main__":
    main()
