"""Form genuine shared before states and capture the original next arrivals."""

from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.impact_comparison import TimedBenchmarkRun, state_reader_messages
from milai_lab.runners.method_architecture_factorial import _arrival, _seed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    protocol = read_json(args.source / "prepared.json")
    for case in protocol["cases"]:
        root = args.source / case["id"]
        state = _seed(protocol, case, root, TimedBenchmarkRun)
        _arrival(protocol, case, root)
        output = root / "before-probes"
        if (output / "complete.json").exists():
            continue
        settings = {**protocol["settings"], "experiment_name": f"{case['id']}-before-probes"}
        run = TimedBenchmarkRun(settings, output, phase="predict")
        answers = []
        try:
            for query in case["queries"]:
                key = f"questions/{query['id']}"
                answer = {"id": query["id"], "question": query["question"]}
                try:
                    answer["hypothesis"] = run.call(key, state_reader_messages(
                        state["actual_state"], query["question"],
                        case["observations"]["update"]["date"]),
                        structured=False, enable_thinking=run.stage_thinking("reader"))
                except ValueError as error:
                    failure = run._known_reader_failure(error, key)
                    if failure is None:
                        raise
                    answer.update(hypothesis=None, reader_failure=failure)
                answers.append(answer)
                write_json(output / "answers.json", answers)
        finally:
            run.close()
        write_json(output / "complete.json", {"status": "BEFORE_PROBES_CLOSED",
                                               "answers": len(answers)})
    write_json(args.source / "formation-terminal.json", {
        "status": "FORMATION_AND_ARRIVAL_CLOSED", "cases": len(protocol["cases"]),
        "semantic_correctness": "requires source review; before questions never enter Writer"})


if __name__ == "__main__":
    main()
